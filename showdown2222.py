"""
Phase 2: table_rule is an opaque codename whose showdown rules are unknown
and must be learned from observed showdowns during play.

Key design points (see accompanying explanation):
  - We never assume a rule *shape*. We build a purely empirical strength
    ranking over numbers 1-13, per (codename, community_number), from
    actual showdown outcomes.
  - Observations are persisted to disk, keyed by codename, because the
    guide states the same codename always means the same rule, in every
    match/attempt/phase, and retries replay the same leg order and rules.
    ASSUMPTION TO VERIFY: this only helps if the server process (or at
    least the disk) survives between attempts. If each attempt runs in a
    fresh container, this degrades gracefully to "learn within the attempt
    only" -- still correct, just less powerful.
  - Betting has an explicit explore phase (pay small amounts to see
    showdowns while the rule is still unknown) and an exploit phase (bet
    on the learned ranking once there's enough data).
  - Per-leg preservation: chip_delta resets to 0 every leg, and only
    reaching +25 matters (100 pts flat, no bonus beyond) -- so once a leg
    is at +25, minimize further risk for the rest of that leg.
"""

import json
import os
import threading

from flask import Flask, request, jsonify

app = Flask(__name__)

GOAL_DELTA = 25          # phase 2 per-leg target
STORE_PATH = "rule_store.json"
_store_lock = threading.Lock()

EXPLORATION_HAND_WINDOW = 8   # be willing to pay for info in a leg's first N hands
EXPLORATION_MIN_OBS = 20      # ...or until we've seen this many showdowns for the rule
CONFIDENCE_FULL_AT = 30        # showdowns at this community value for "fully confident"


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


def _record_showdown(codename, community_number, n_a, n_b, outcome):
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


def update_from_recent_hands(codename, recent_hands, your_seat, opponent_seat):
    """Pull any not-yet-seen showdowns out of recent_hands and record them.
    Hands that ended without a reveal (someone folded) teach us nothing
    about the rule, so we skip them but still mark them seen."""
    changed = False
    for hand in recent_hands or []:
        hn = hand.get("hand_number")
        if hn is None or hn in _leg_state["seen_hand_numbers"]:
            continue
        _leg_state["seen_hand_numbers"].add(hn)

        shown = hand.get("shown_numbers") or {}
        my_shown = shown.get(str(your_seat))
        opp_shown = shown.get(str(opponent_seat))
        if my_shown is None or opp_shown is None:
            continue  # no showdown this hand

        community = hand.get("community_number")
        winners = hand.get("winners", [])
        if len(winners) >= 2:
            outcome = "tie"
        elif winners == [your_seat]:
            outcome = "a"
        elif winners == [opponent_seat]:
            outcome = "b"
        else:
            outcome = "tie"

        _record_showdown(codename, community, my_shown, opp_shown, outcome)
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


def estimate_equity(codename, your_number, community_number):
    """Returns (equity, confidence). confidence in [0,1] reflects how much
    data backs the estimate; 0 means "we know nothing, treat as a coin
    flip and don't trust it for sizing decisions."""
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


def _total_observations(codename):
    return sum(
        sum(rec["low_wins"] + rec["high_wins"] + rec["ties"] for rec in comm.values())
        for comm in RULE_STORE.get(codename, {}).values()
    )


def _observations_at(codename, community_number):
    """Observation count for the exact (codename, community_number) bucket
    -- the same granularity estimate_equity's confidence is computed at.
    Using the codename-wide total here (as before) made this function
    declare "done exploring" while confidence for the specific number
    we're about to act on was still ~0, which flipped edge_required from
    lenient to strict at the worst possible time."""
    comm = RULE_STORE.get(codename, {}).get(str(community_number), {})
    return sum(rec["low_wins"] + rec["high_wins"] + rec["ties"] for rec in comm.values())


def in_exploration_phase(codename, hand_number, community_number):
    return (hand_number <= EXPLORATION_HAND_WINDOW
            or _observations_at(codename, community_number) < EXPLORATION_MIN_OBS)


# ---------------------------------------------------------------------------
# Risk mode / sizing (per-leg preservation at GOAL_DELTA)
# ---------------------------------------------------------------------------

def get_risk_mode(chip_delta):
    if chip_delta >= GOAL_DELTA:
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

    your_seat = data["your_seat"]
    opponent_seat = next(p["seat"] for p in data["players"] if p["seat"] != your_seat)

    update_from_recent_hands(codename, data.get("recent_hands", []), your_seat, opponent_seat)

    your_number = data["your_number"]
    community_number = data["community_number"]
    pot = data["pot"]
    to_call = data["to_call"]
    min_raise_to = data["min_raise_to"]
    max_raise_to = data["max_raise_to"]
    legal_actions = data["legal_actions"]
    your_player = next(p for p in data["players"] if p["seat"] == your_seat)
    chip_delta = your_player["chip_delta"]

    equity, confidence = estimate_equity(codename, your_number, community_number)
    pot_odds = (to_call / (pot + to_call)) if to_call else 0.0

    risk_mode = get_risk_mode(chip_delta)
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
    # Scale smoothly with confidence rather than a hard cliff -- with only
    # 40 hands split across up to 13 community_number buckets, confidence
    # rarely climbs high in a single leg, so a steep cutoff meant we almost
    # never sized up even with a near-certain winner.
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
            # the server sends. Still size smaller when we're not in
            # full value-betting territory, rather than defaulting to a
            # free check and giving up the edge entirely.
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