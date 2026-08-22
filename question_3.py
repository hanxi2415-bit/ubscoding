
'''
requirements:
explain: A betting game between bots. You write one HTTP endpoint; our server deals, 
runs the betting and calls you whenever it's your turn.

rules:
card game
If your number equals the community number you have a pair, and any pair beats any non-pair. That's the big one.
Otherwise the higher number wins.
Identical results split the pot.

my goal: 
One-on-one against one of our bots. 100 hands, one match per attempt. table_rule reads standard the whole way through.
i need to finish with a chip delta of +10 or better

'''

'''
input:

{
  "protocol_version": 2,
  "match_id": "phase1-seed7",
  "phase": 1,
  "table_rule": "standard",
  "small_blind": 1,
  "big_blind": 2,
  "starting_stack": 200,
  "your_stack": 185,
  "hand_number": 6,
  "total_hands": 100,
  "round": "post_reveal",
  "your_number": 3,
  "community_number": 5,
  "your_seat": 0,
  "button_seat": 1,
  "pot": 32,
  "to_call": 18,
  "min_raise_to": 36,
  "max_raise_to": 185,
  "legal_actions": ["fold", "call", "raise"],
  "players": [
    {
      "seat": 0,
      "name": "you",
      "folded": false,
      "chip_delta": -8,
      "bet_this_round": 0,
      "stack": 185,
      "all_in": false,
      "busted": false
    },
    {
      "seat": 1,
      "name": "Gaston",
      "folded": false,
      "chip_delta": 8,
      "bet_this_round": 18,
      "stack": 183,
      "all_in": false,
      "busted": false
    }
  ],
  "current_hand_actions": [
    { "round": "pre_reveal", "seat": 1, "action": "raise", "amount": 7 },
    { "round": "pre_reveal", "seat": 0, "action": "call", "amount": 7 },
    { "round": "post_reveal", "seat": 0, "action": "check" },
    { "round": "post_reveal", "seat": 1, "action": "bet", "amount": 18 }
  ],
  "recent_hands": [
    {
      "hand_number": 2,
      "community_number": 13,
      "winners": [1],
      "pot": 24,
      "shown_numbers": { "0": 9, "1": 11 },
      "actions": [
        { "round": "pre_reveal", "seat": 1, "action": "raise", "amount": 5 },
        { "round": "pre_reveal", "seat": 0, "action": "call", "amount": 5 },
        { "round": "post_reveal", "seat": 0, "action": "check" },
        { "round": "post_reveal", "seat": 1, "action": "bet", "amount": 7 },
        { "round": "post_reveal", "seat": 0, "action": "call", "amount": 7 }
      ]
    }
  ]
}

'''


'''

## my strategy:

### 1. Determine hand strength

If `your_number == community_number`:
    → PAIR
    → strongest possible hand
    → raise aggressively

Else:
    11 to 13 → very strong
    8 to 10  → medium-strong
    5 to 7   → weak
    1 to 4   → very weak


### 2. Consider pot odds

Calculate:

    pot_odds = to_call / (pot + to_call)

The larger `to_call` is relative to the pot, the more selective I should be
about calling.

- Small `to_call` relative to pot → more willing to call
- Large `to_call` relative to pot → require a stronger hand
- If `to_call` is 0 and `check` is legal → check rather than fold


### 3. Basic betting strategy

PAIR:
    → raise aggressively
    → willing to call large bets
    → avoid folding unless there is a very unusual situation

11 to 13:
    → strong enough to call most reasonable bets
    → raise when the opponent appears weak or the bet is small
    → avoid unnecessarily large raises when already safely above +10

8 to 10:
    → call when `to_call` is small relative to the pot
    → fold against large bets, especially from an opponent who rarely bluffs
    → raise selectively rather than automatically

5 to 7:
    → mostly check/fold
    → call only when `to_call` is very small relative to the pot
    → avoid large pots

1 to 4:
    → usually fold
    → only consider calling/bluffing if opponent behaviour suggests they are weak


### 4. Adjust based on current chip delta

Goal: finish with `chip_delta >= +10`.

If `chip_delta < 0`:
    → take reasonable positive-EV opportunities
    → do not become overly aggressive just because I am losing

If `0 <= chip_delta < +10`:
    → normal strategy
    → prioritize reaching +10 while avoiding unnecessary risk

If `chip_delta >= +10`:
    → switch to preservation mode
    → avoid high-risk calls/raises with medium or weak hands
    → continue betting strong hands and pairs


### 5. Track opponent behaviour

Use `recent_hands` to build an opponent profile.

Track:
    - how often the opponent raises
    - how often they bet
    - what numbers they previously had when they raised/bet
    - their typical bet size relative to the pot

If the opponent frequently raises with weak numbers:
    → their raises are less threatening
    → more willing to call/raise against them

If the opponent usually raises with strong numbers:
    → respect their aggression
    → fold medium/weak hands more often

Use `current_hand_actions` to consider how aggressive the opponent has
been during the current hand.


### 6. Always respect legal actions

Before returning a decision, check `legal_actions`.

Only return:
    - `fold` if legal
    - `check` if legal
    - `call` if legal
    - `raise` if legal

Never return an action that is not in `legal_actions`.


### Overall decision hierarchy

1. Pair → aggressively bet/raise
2. Strong number (11 to 13) → generally call/raise
3. Medium number (8 to 10) → use pot odds and opponent behaviour
4. Weak number (5 to 7) → mostly check/fold
5. Very weak number (1 to 4) → usually fold
6. Adjust risk according to current chip delta
7. Adjust decisions using opponent behaviour
8. Always obey `legal_actions`

'''

'''
def calculate_equity(your_number, community_number):
    wins = 0
    ties = 0

    for opponent_number in range(1, 14):

        # You have a pair
        if your_number == community_number:
            your_pair = True
        else:
            your_pair = False

        # Opponent has a pair
        if opponent_number == community_number:
            opponent_pair = True
        else:
            opponent_pair = False

        # Compare hands
        if your_pair and not opponent_pair:
            wins += 1

        elif not your_pair and opponent_pair:
            continue

        elif your_pair and opponent_pair:
            ties += 1

        elif your_number > opponent_number:
            wins += 1

        elif your_number == opponent_number:
            ties += 1

    return (wins + 0.5 * ties) / 13



def decide_move(data):
    your_number = data["your_number"]
    community_number = data["community_number"]

    pot = data["pot"]
    to_call = data["to_call"]

    min_raise_to = data["min_raise_to"]
    max_raise_to = data["max_raise_to"]

    legal_actions = data["legal_actions"]

    chip_delta = data["players"][data["your_seat"]]["chip_delta"]

    # -------------------------
    # 1. Calculate equity
    # -------------------------

    equity = calculate_equity(
        your_number,
        community_number
    )

    # -------------------------
    # 2. Calculate pot odds
    # -------------------------

    if to_call == 0:
        pot_odds = 0
    else:
        pot_odds = to_call / (pot + to_call)

    # -------------------------
    # 3. Determine hand strength
    # -------------------------

    if your_number == community_number:
        strength = "pair"
    elif your_number >= 11:
        strength = "very_strong"
    elif your_number >= 8:
        strength = "medium"
    elif your_number >= 5:
        strength = "weak"
    else:
        strength = "very_weak"

    # -------------------------
    # 4. Decide how aggressively
    # -------------------------

    # PAIR
    if strength == "pair":

        if "raise" in legal_actions:
            return {
                "action": "raise",
                "amount": max_raise_to
            }

        elif "call" in legal_actions:
            return {"action": "call"}

    # VERY STRONG
    elif strength == "very_strong":

        # Strong equity + cheap to continue → raise
        if "raise" in legal_actions and equity > 0.75:
            return {
                "action": "raise",
                "amount": min(min_raise_to * 2, max_raise_to)
            }

        # If calling is profitable → call
        elif "call" in legal_actions and equity > pot_odds:
            return {"action": "call"}

    # MEDIUM
    elif strength == "medium":

        # Only continue if equity justifies the price
        if "call" in legal_actions and equity > pot_odds:
            return {"action": "call"}

    # WEAK
    elif strength == "weak":

        # Only call if the price is very attractive
        if "call" in legal_actions and equity > pot_odds:
            return {"action": "call"}

    # VERY WEAK
    else:

        # Usually don't invest more money
        pass

    # -------------------------
    # 5. Check if possible
    # -------------------------

    if "check" in legal_actions:
        return {"action": "check"}

    # -------------------------
    # 6. Otherwise fold
    # -------------------------

    if "fold" in legal_actions:
        return {"action": "fold"}

    # Fallback
    if "call" in legal_actions:
        return {"action": "call"}

    return {"action": "fold"}


from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/move", methods=["POST"])
def move():
    data = request.get_json()

    decision = decide_move(data)

    return jsonify(decision)


if __name__ == "__main__":
    app.run()
'''

"""
Betting bot for a 1-on-1, 100-hand match.

Rules recap:
  - your_number == community_number -> you have a pair, which beats any non-pair.
  - Otherwise, higher number wins.
  - Ties split the pot.

Goal: finish the match with chip_delta >= GOAL_DELTA. That's a modest target,
not "maximize EV" -- so once we're safely ahead, we deliberately reduce
variance rather than keep taking large all-in swings.
"""

from flask import Flask, request, jsonify

app = Flask(__name__)

GOAL_DELTA = 10


# ---------------------------------------------------------------------------
# Equity
# ---------------------------------------------------------------------------

def calculate_equity(your_number, community_number):
    """
    Win probability assuming the opponent's number is uniform over 1-13,
    WITH replacement (i.e. your number and the community number don't
    reduce what the opponent could be holding).

    ASSUMPTION TO VERIFY: if the game actually deals from a single 13-card
    deck without replacement, the opponent can't hold your_number or
    community_number (unless they're the same value), so the true sample
    space is 11 or 12 numbers, not 13. That shift matters most in close
    spots (e.g. your_number == 7). If you can confirm the deck rules,
    swap in calculate_equity_no_replacement below.
    """
    wins = 0
    ties = 0
    your_pair = your_number == community_number

    for opponent_number in range(1, 14):
        opponent_pair = opponent_number == community_number

        if your_pair and opponent_pair:
            ties += 1
        elif your_pair:
            wins += 1
        elif opponent_pair:
            continue  # opponent's pair beats our non-pair
        elif your_number > opponent_number:
            wins += 1
        elif your_number == opponent_number:
            ties += 1

    return (wins + 0.5 * ties) / 13


def calculate_equity_no_replacement(your_number, community_number):
    """Same as above, but removes your_number/community_number from the
    opponent's possible range first. Use this if the deck has one card per
    value and no duplicates."""
    possible = [n for n in range(1, 14)]
    possible.remove(community_number)
    if your_number in possible:
        possible.remove(your_number)
    if not possible:
        return 0.5  # degenerate case, shouldn't happen in practice

    wins = 0
    ties = 0
    your_pair = your_number == community_number

    for opponent_number in possible:
        opponent_pair = opponent_number == community_number
        if your_pair and opponent_pair:
            ties += 1
        elif your_pair:
            wins += 1
        elif opponent_pair:
            continue
        elif your_number > opponent_number:
            wins += 1
        elif your_number == opponent_number:
            ties += 1

    return (wins + 0.5 * ties) / len(possible)


# ---------------------------------------------------------------------------
# Opponent profiling
# ---------------------------------------------------------------------------

def build_opponent_profile(recent_hands, opponent_seat, min_sample=5):
    """
    Cheap frequency-based read on the opponent from hand history:
    how often they bet/raise, and what they tended to show down with
    when aggressive vs. passive.

    Small samples are common early in the match, so callers should treat
    a profile with n_hands < min_sample as unreliable / neutral.
    """
    aggressive_shown = []
    passive_shown = []

    for hand in recent_hands or []:
        shown = hand.get("shown_numbers", {})
        opp_shown = shown.get(str(opponent_seat))
        if opp_shown is None:
            continue  # no showdown this hand (e.g. they folded)

        was_aggressive = any(
            a.get("seat") == opponent_seat and a.get("action") in ("bet", "raise")
            for a in hand.get("actions", [])
        )
        (aggressive_shown if was_aggressive else passive_shown).append(opp_shown)

    n_hands = len(aggressive_shown) + len(passive_shown)
    reliable = n_hands >= min_sample

    return {
        "n_hands": n_hands,
        "reliable": reliable,
        "aggression_freq": (len(aggressive_shown) / n_hands) if n_hands else None,
        "avg_shown_when_aggressive": (
            sum(aggressive_shown) / len(aggressive_shown) if aggressive_shown else None
        ),
    }


def opponent_bluff_adjustment(profile):
    """
    Returns a small adjustment to subtract from our required equity edge.
    Positive value = opponent looks bluff-heavy -> we can call lighter.
    Negative value = opponent looks value-heavy -> we should call tighter.
    Zero if we don't have enough data to say anything.
    """
    if not profile["reliable"] or profile["avg_shown_when_aggressive"] is None:
        return 0.0

    avg = profile["avg_shown_when_aggressive"]
    if avg <= 6:
        return 0.06   # they bet/raise with weak numbers -> respect them less
    if avg >= 10:
        return -0.06  # they bet/raise mostly with real hands -> respect them more
    return 0.0


# ---------------------------------------------------------------------------
# Risk mode from chip delta
# ---------------------------------------------------------------------------

def get_risk_mode(chip_delta):
    if chip_delta >= GOAL_DELTA:
        return "preserve"   # already at goal: protect it, cut variance
    if chip_delta >= 0:
        return "normal"
    return "recover"        # behind: take standard +EV lines, no need to force it


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------

def size_raise(pot, to_call, min_raise_to, max_raise_to, pot_multiple):
    """Pot-relative raise, clipped to the legal range."""
    target = int((pot + to_call) * pot_multiple)
    return max(min_raise_to, min(target, max_raise_to))


# ---------------------------------------------------------------------------
# Main decision
# ---------------------------------------------------------------------------

def decide_move(data):
    your_number = data["your_number"]
    community_number = data["community_number"]
    pot = data["pot"]
    to_call = data["to_call"]
    min_raise_to = data["min_raise_to"]
    max_raise_to = data["max_raise_to"]
    legal_actions = data["legal_actions"]

    your_seat = data["your_seat"]
    opponent_seat = next(p["seat"] for p in data["players"] if p["seat"] != your_seat)
    chip_delta = data["players"][your_seat]["chip_delta"]

    equity = calculate_equity(your_number, community_number)
    pot_odds = (to_call / (pot + to_call)) if to_call else 0.0

    profile = build_opponent_profile(data.get("recent_hands", []), opponent_seat)
    bluff_adj = opponent_bluff_adjustment(profile)

    risk_mode = get_risk_mode(chip_delta)
    is_pair = your_number == community_number

    # Required edge above break-even to continue with a non-pair hand.
    # Bigger in preserve mode (we don't need marginal spots once we've hit
    # the goal); smaller if the opponent looks bluff-heavy.
    edge_required = {"preserve": 0.08, "normal": 0.02, "recover": 0.0}[risk_mode]
    edge_required = max(0.0, edge_required - bluff_adj)

    def try_actions(*ordered_actions_with_amounts):
        for action, amount in ordered_actions_with_amounts:
            if action in legal_actions:
                return {"action": action} if amount is None else {"action": action, "amount": amount}
        return None

    decision = None

    if is_pair:
        # Always the best possible hand, but size down once we've already
        # reached the goal or when there's no need to shove for value.
        if risk_mode == "preserve":
            raise_to = size_raise(pot, to_call, min_raise_to, max_raise_to, pot_multiple=0.75)
        elif risk_mode == "recover":
            raise_to = max_raise_to  # need to make up ground, apply max pressure
        else:
            raise_to = size_raise(pot, to_call, min_raise_to, max_raise_to, pot_multiple=1.25)

        decision = try_actions(("raise", raise_to), ("call", None))

    elif equity > pot_odds + edge_required:
        # Profitable enough to continue. Raise when the hand is genuinely
        # strong or the opponent looks weak; otherwise just call.
        want_to_raise = equity > 0.75 or (equity > 0.6 and bluff_adj > 0)
        if want_to_raise:
            raise_to = size_raise(pot, to_call, min_raise_to, max_raise_to, pot_multiple=1.0)
            decision = try_actions(("raise", raise_to), ("call", None))
        else:
            decision = try_actions(("call", None))

    # Fallback: check if free, otherwise fold, otherwise whatever's legal.
    if decision is None:
        decision = try_actions(("check", None), ("fold", None), ("call", None))

    if decision is None:
        # Nothing matched (shouldn't happen) -- pick anything legal so we
        # never send an illegal action.
        decision = {"action": legal_actions[0]}

    return decision


@app.route("/move", methods=["POST"])
def move():
    data = request.get_json()
    return jsonify(decide_move(data))


if __name__ == "__main__":
    app.run()