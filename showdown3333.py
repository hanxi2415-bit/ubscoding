"""
Phase 3: six-seat, multiway tables. table_rule is still an opaque codename
whose showdown rules must be learned empirically (see phase 2), but now:

  - Up to 5 opponents can be live in a hand at once, not just 1. A bet has
    to get through everyone still in, and "beat the field" now means beat
    every live opponent, not one person.
  - Learning is richer, not poorer: a multiway showdown reveals several
    numbers at once. We can't rank two *losers* against each other (we
    only learn who won, not the full order), but every winner-vs-loser
    pair, and every winner-vs-winner tie, is a valid empirical (number A
    beat number B) observation at that community_number -- so we extract
    all of those from every showdown, not just ones we personally played.
    This means we learn from hands we folded out of too.
  - Multiway equity is approximated as (1v1 win probability against a
    single random opponent number) ** (number of live opponents),
    treating each comparison as independent. Numbers ARE dealt
    independently, so this is a reasonable approximation -- it's an
    upper bound in practice since players still live in a hand skew
    toward stronger holdings than a uniform random draw, which is why we
    still require a real edge before committing chips (see edge_required
    below), not just equity > pot_odds.
  - Clearing the leg is stricter than phase 2: chip_delta >= goal AND
    strictly the highest chip_delta at the table ("top the table" --
    ties don't count). Risk mode below accounts for this: we only ever
    go into "preserve" (minimize further variance) once we're both past
    the goal delta AND actually leading -- being up +50 while someone
    else is up +80 still means push, not coast.
  - The file auto-detects heads-up (2 seats, phase 2 rules: clear a flat
    delta) vs multiway (>2 seats, phase 3 rules: clear a delta AND lead)
    from len(data["players"]), so the same endpoint keeps working for
    both without being told which phase it's in.
"""

import json
import os
import threading

from flask import Flask, request, jsonify

app = Flask(__name__)

HEADS_UP_GOAL_DELTA = 25   # phase 2 per-leg target (no "lead" requirement)
MULTIWAY_GOAL_DELTA = 10   # phase 3 per-leg target (must also top the table)
STORE_PATH = "rule_store.json"
_store_lock = threading.Lock()

EXPLORATION_HAND_WINDOW = 8   # be willing to pay for info in a leg's first N hands
EXPLORATION_MIN_OBS = 20      # ...or until we've seen this many showdowns for the rule
CONFIDENCE_FULL_AT = 30       # showdowns at this community value for "fully confident"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_store():
    if os.path.exists(STORE_PATH):
        try:
            with open(STORE_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_store(store):
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f)
    os.replace(tmp, STORE_PATH)


RULE_STORE = _load_store()  # {codename: {community_number(str): {"lo_hi": {...}}}}

# In-memory, per-process leg tracking (reset when we detect a new leg).
_leg_state = {"table_rule": None, "leg_number": None, "seen_hand_numbers": set()}


# ---------------------------------------------------------------------------
# Learning from showdowns
# ---------------------------------------------------------------------------

def _pair_key(a, b):
    lo, hi = (a, b) if a <= b else (b, a)
    return f"{lo}_{hi}"


def _record_pair_outcome(codename, community_number, n_a, n_b, outcome):
    """outcome: 'a', 'b', or 'tie' -- which of the two revealed numbers won."""
    lo, hi = (n_a, n_b) if n_a <= n_b else (n_b, n_a)
    lo_won = (outcome == "a" and n_a == lo) or (outcome == "b" and n_b == lo)
    hi_won = (outcome == "a" and n_a == hi) or (outcome == "b" and n_b == hi)

    with _store_lock:
        comm = RULE_STORE.setdefault(codename, {}).setdefault(str(community_number), {})
        rec = comm.setdefault(_pair_key(lo, hi), {"low_wins": 0, "high_wins": 0, "ties": 0})
        if outcome == "tie":
            rec["ties"] += 1
        elif lo_won:
            rec["low_wins"] += 1
        elif hi_won:
            rec["high_wins"] += 1


def _record_multiway_showdown(codename, community_number, shown_numbers, winners):
    """shown_numbers: {seat_str: number} for everyone who showed at this
    hand's showdown. winners: list of seats (any int/str form) that won
    (>1 entry means a tie among winners).

    We can only extract valid pairwise observations for pairs where we
    know who won: winner-vs-loser (winner beat loser) and winner-vs-winner
    (tie). Loser-vs-loser carries no information -- we only see the best
    hand(s), not a full ranking -- so those pairs are skipped."""
    winner_set = {str(w) for w in winners}
    seats = list(shown_numbers.keys())
    for i in range(len(seats)):
        for j in range(i + 1, len(seats)):
            sa, sb = seats[i], seats[j]
            a_win, b_win = sa in winner_set, sb in winner_set
            if a_win and b_win:
                outcome = "tie"
            elif a_win:
                outcome = "a"
            elif b_win:
                outcome = "b"
            else:
                continue  # both losers -- no info about their relative order
            _record_pair_outcome(codename, community_number,
                                  shown_numbers[sa], shown_numbers[sb], outcome)


def update_from_recent_hands(codename, recent_hands):
    """Pull any not-yet-seen showdowns out of recent_hands and record them.
    Processes every shown pair in every hand -- including hands we folded
    out of -- since recent_hands includes the whole table's results, not
    just ours. Hands with fewer than 2 revealed numbers (everyone but one
    folded) teach us nothing, so we skip them but still mark them seen."""
    changed = False
    for hand in recent_hands or []:
        hn = hand.get("hand_number")
        if hn is None or hn in _leg_state["seen_hand_numbers"]:
            continue
        _leg_state["seen_hand_numbers"].add(hn)

        shown = hand.get("shown_numbers") or {}
        if len(shown) < 2:
            continue  # no showdown, or only one player left to show

        community = hand.get("community_number")
        winners = hand.get("winners", [])
        _record_multiway_showdown(codename, community, shown, winners)
        changed = True

    if changed:
        _save_store(RULE_STORE)


# ---------------------------------------------------------------------------
# Equity estimation: empirical (Copeland-style) ranking, no assumed rule shape
# ---------------------------------------------------------------------------

def _copeland_scores(codename, community_number):
    """score(n) = wins - losses across every number we've seen n face,
    at this exact (codename, community_number). Numbers never observed
    are simply absent from the dict."""
    comm = RULE_STORE.get(codename, {}).get(str(community_number), {})
    wins = {n: 0 for n in range(1, 14)}
    losses = {n: 0 for n in range(1, 14)}
    seen = set()
    n_obs = 0

    for key, rec in comm.items():
        lo, hi = (int(x) for x in key.split("_"))
        seen.add(lo)
        seen.add(hi)
        if rec["low_wins"]:
            wins[lo] += rec["low_wins"]
            losses[hi] += rec["low_wins"]
        if rec["high_wins"]:
            wins[hi] += rec["high_wins"]
            losses[lo] += rec["high_wins"]
        n_obs += rec["low_wins"] + rec["high_wins"] + rec["ties"]

    return {n: wins[n] - losses[n] for n in seen}, n_obs


def estimate_equity_1v1(codename, your_number, community_number):
    """Returns (equity, confidence) for beating ONE random opponent number.
    confidence in [0,1] reflects how much data backs the estimate; 0 means
    "we know nothing, treat as a coin flip and don't trust it for sizing."""
    scores, n_obs = _copeland_scores(codename, community_number)

    if your_number not in scores or n_obs == 0:
        return 0.5, 0.0

    my_score = scores[your_number]
    wins = 0.0
    knowns = 0
    for opp in range(1, 14):
        if opp not in scores:
            continue
        knowns += 1
        opp_score = scores[opp]
        if my_score > opp_score:
            wins += 1
        elif my_score == opp_score:
            wins += 0.5

    if knowns == 0:
        return 0.5, 0.0

    equity = wins / knowns
    confidence = min(1.0, n_obs / CONFIDENCE_FULL_AT)
    return equity, confidence


def estimate_equity_multiway(codename, your_number, community_number, num_live_opponents):
    """Probability of beating EVERY live opponent, approximated by raising
    the 1v1 win probability to the power of the opponent count (numbers are
    dealt independently, so treating each comparison as independent is a
    reasonable first-order approximation). This is an upper bound in
    practice -- opponents who are still in the hand skew toward stronger
    holdings than a uniform random draw -- so edge_required in decide_move
    still demands a real margin on top of this, rather than trusting it at
    face value."""
    equity_1v1, confidence = estimate_equity_1v1(codename, your_number, community_number)
    equity = equity_1v1 ** max(1, num_live_opponents)
    return equity, confidence


def _observations_at(codename, community_number):
    """Observation count for the exact (codename, community_number) bucket
    -- the same granularity estimate_equity_1v1's confidence is computed
    at, so explore/exploit and confidence are answering the same question."""
    comm = RULE_STORE.get(codename, {}).get(str(community_number), {})
    return sum(rec["low_wins"] + rec["high_wins"] + rec["ties"] for rec in comm.values())


def in_exploration_phase(codename, hand_number, community_number):
    return (hand_number <= EXPLORATION_HAND_WINDOW
            or _observations_at(codename, community_number) < EXPLORATION_MIN_OBS)


# ---------------------------------------------------------------------------
# Risk mode / sizing
# ---------------------------------------------------------------------------

def get_risk_mode(chip_delta, goal_delta, must_top, leading):
    """must_top=True (phase 3): only ease off once we've BOTH cleared the
    goal delta AND are strictly ahead of every other seat -- being up
    +50 while someone else is up +80 still means push, not preserve.
    must_top=False (heads-up phase 2): clearing the goal delta is enough."""
    if chip_delta >= goal_delta and (leading or not must_top):
        return "preserve"
    if chip_delta >= 0:
        return "normal"
    return "recover"


def size_raise(pot, to_call, min_raise_to, max_raise_to, pot_multiple):
    target = int((pot + to_call) * pot_multiple)
    return max(min_raise_to, min(target, max_raise_to))


# ---------------------------------------------------------------------------
# Main decision
# ---------------------------------------------------------------------------

def decide_move(data):
    codename = data["table_rule"]
    hand_number = data["hand_number"]
    leg_number = data.get("leg_number")

    # New leg? -> table_rule changes, leg_number changes, or hand_number
    # restarts at 1. Reset our in-run "already processed" hand tracker so
    # we don't skip hand_number==1 of a new leg because we saw a
    # hand_number==1 earlier in a previous leg.
    if (_leg_state["table_rule"] != codename
            or _leg_state["leg_number"] != leg_number
            or hand_number == 1):
        _leg_state["table_rule"] = codename
        _leg_state["leg_number"] = leg_number
        _leg_state["seen_hand_numbers"] = set()

    update_from_recent_hands(codename, data.get("recent_hands", []))

    your_seat = data["your_seat"]
    players = data["players"]
    # Look up by the `seat` field rather than assuming list index == seat --
    # players is documented as "a list in seat order", not indexed by seat.
    your_player = next(p for p in players if p["seat"] == your_seat)
    chip_delta = your_player["chip_delta"]

    other_players = [p for p in players if p["seat"] != your_seat]
    other_deltas = [p["chip_delta"] for p in other_players]
    live_opponents = [p for p in other_players
                       if not p.get("folded", False) and not p.get("busted", False)]
    num_live_opponents = len(live_opponents)
    multiway_mode = len(players) > 2

    your_number = data["your_number"]
    community_number = data["community_number"]
    pot = data["pot"]
    to_call = data["to_call"]
    min_raise_to = data["min_raise_to"]
    max_raise_to = data["max_raise_to"]
    legal_actions = data["legal_actions"]

    if multiway_mode:
        equity, confidence = estimate_equity_multiway(
            codename, your_number, community_number, num_live_opponents)
    else:
        equity, confidence = estimate_equity_1v1(codename, your_number, community_number)

    pot_odds = (to_call / (pot + to_call)) if to_call else 0.0

    goal_delta = MULTIWAY_GOAL_DELTA if multiway_mode else HEADS_UP_GOAL_DELTA
    top_delta = max(other_deltas) if other_deltas else float("-inf")
    leading = chip_delta > top_delta
    risk_mode = get_risk_mode(chip_delta, goal_delta, multiway_mode, leading)

    exploring = in_exploration_phase(codename, hand_number, community_number)

    base_edge = {"preserve": 0.10, "normal": 0.03, "recover": 0.0}[risk_mode]
    uncertainty_penalty = (1 - confidence) * 0.10

    if exploring and risk_mode != "preserve":
        # Cheap information is worth paying for early -- willing to call
        # closer to break-even purely to see a showdown. Never applies once
        # a leg's goal is already banked; no reason to pay for data then.
        edge_required = max(0.0, base_edge - 0.08)
    else:
        edge_required = base_edge + uncertainty_penalty

    # Don't size up big on a read we don't trust yet, even if it looks great.
    # Scales smoothly with confidence rather than a hard cliff.
    max_pot_multiple = 0.4 + 0.85 * confidence

    def try_actions(*ordered):
        for action, amount in ordered:
            if action in legal_actions:
                return {"action": action} if amount is None else {"action": action, "amount": amount}
        return None

    decision = None

    if equity > pot_odds + edge_required:
        want_to_size_up = equity > 0.75 and confidence > 0.15 and risk_mode != "preserve"
        if to_call == 0:
            # Nothing to call means it's on us to open the betting (or
            # there's nothing left to do but check). "bet" is the legal
            # action here, not "raise" -- try both so this works whichever
            # the server sends, rather than defaulting to a free check and
            # giving up the edge entirely.
            bet_multiple = max_pot_multiple if want_to_size_up else 0.5
            bet_to = size_raise(pot, to_call, min_raise_to, max_raise_to, bet_multiple)
            decision = try_actions(("bet", bet_to), ("raise", bet_to), ("check", None))
        elif want_to_size_up:
            raise_to = size_raise(pot, to_call, min_raise_to, max_raise_to, max_pot_multiple)
            decision = try_actions(("raise", raise_to), ("bet", raise_to), ("call", None))
        else:
            decision = try_actions(("call", None))
    elif (exploring and risk_mode != "preserve"
            and to_call > 0 and (to_call / max(pot, 1)) < 0.35):
        # Marginal/unknown by our current model, but cheap enough that the
        # information is worth the price.
        decision = try_actions(("call", None))

    if decision is None:
        decision = try_actions(("check", None), ("fold", None), ("call", None))
    if decision is None:
        decision = {"action": legal_actions[0]}

    return decision


@app.route("/move", methods=["POST"])
def move():
    data = request.get_json()
    return jsonify(decide_move(data))


if __name__ == "__main__":
    app.run()