"""
Phase 4 -- final table. Two structural changes from phase 1/2:

1. Multi-way, not heads-up: up to 7 bots per table. Every showdown at the
   table (even ones you're not in) is free data about the rule -- so
   rule-learning now walks every pair of players who revealed a number,
   not just "you vs the opponent." Equity is now "beat everyone still in
   the hand," not "beat one random opponent."

2. No chip-delta target: scoring is relative-rank survival (bottom third
   of the table gets cut). Risk posture is now driven by where you rank
   in current stacks among everyone still alive at the table, not by an
   absolute chip_delta threshold.

Also: no retries, so the endpoint must never throw or hang, and there's a
pre-bracket health check to answer.

The rule_memory_store.json file is unchanged in format from phase 1/2 --
if this deploy has been running continuously, whatever it already learned
about specific codenames carries straight into phase 4.
"""

import json
import os
import threading

from flask import Flask, request, jsonify

app = Flask(__name__)

STORE_PATH = "rule_memory_store.json"
_store_lock = threading.Lock()

rule_memory = {}
seen_hands = set()
decision_log = []


# ---------------------------------------------------------------------------
# Persistence (same schema as phase 1/2 -- deliberately compatible)
# ---------------------------------------------------------------------------

def _encode_key(key):
    if isinstance(key, tuple):
        return "|".join(str(k) for k in key)
    return str(key)


def _decode_key(raw, arity):
    parts = [int(p) for p in raw.split("|")]
    return parts[0] if arity == 1 else tuple(parts)


def _serialize_memory(memory):
    return {
        "exact": {_encode_key(k): v for k, v in memory["exact"].items()},
        "matchups": {_encode_key(k): v for k, v in memory["matchups"].items()},
        "numbers": {_encode_key(k): v for k, v in memory["numbers"].items()},
        "ratings": {_encode_key(k): v for k, v in memory["ratings"].items()},
        "local_ratings": {_encode_key(k): v for k, v in memory["local_ratings"].items()},
        "games": {_encode_key(k): v for k, v in memory["games"].items()},
        "action_stats": {_encode_key(k): v for k, v in memory["action_stats"].items()},
    }


def _deserialize_memory(raw):
    return {
        "exact": {_decode_key(k, 3): v for k, v in raw.get("exact", {}).items()},
        "matchups": {_decode_key(k, 2): v for k, v in raw.get("matchups", {}).items()},
        "numbers": {_decode_key(k, 1): v for k, v in raw.get("numbers", {}).items()},
        "ratings": {_decode_key(k, 1): v for k, v in raw.get("ratings", {}).items()},
        "local_ratings": {_decode_key(k, 2): v for k, v in raw.get("local_ratings", {}).items()},
        "games": {_decode_key(k, 1): v for k, v in raw.get("games", {}).items()},
        "action_stats": {_decode_key(k, 1): v for k, v in raw.get("action_stats", {}).items()},
    }


def _load_all():
    global rule_memory, seen_hands
    if not os.path.exists(STORE_PATH):
        return
    try:
        with open(STORE_PATH) as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    rule_memory = {tr: _deserialize_memory(m) for tr, m in raw.get("rule_memory", {}).items()}
    seen_hands = {tuple(item) for item in raw.get("seen_hands", [])}


def _save_all():
    with _store_lock:
        payload = {
            "rule_memory": {tr: _serialize_memory(m) for tr, m in rule_memory.items()},
            "seen_hands": [list(item) for item in seen_hands],
        }
        tmp = STORE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, STORE_PATH)


_load_all()


# ---------------------------------------------------------------------------
# Rule memory
# ---------------------------------------------------------------------------

def new_record():
    return {"wins": 0, "losses": 0, "ties": 0}


def add_result(record, result):
    if result > 0:
        record["wins"] += 1
    elif result < 0:
        record["losses"] += 1
    else:
        record["ties"] += 1


def record_equity(record):
    total = record["wins"] + record["losses"] + record["ties"]
    if total == 0:
        return 0.5, 0
    equity = (record["wins"] + 0.5 * record["ties"] + 1) / (total + 2)
    return equity, total


def normalize_matchup(first, second):
    if first <= second:
        return first, second, 1
    return second, first, -1


def get_rule_data(table_rule):
    if table_rule not in rule_memory:
        rule_memory[table_rule] = {
            "exact": {}, "matchups": {}, "numbers": {}, "ratings": {},
            "local_ratings": {}, "games": {}, "action_stats": {},
        }
    return rule_memory[table_rule]


def update_elo(memory, first, second, community, result):
    first_rating = memory["ratings"].get(first, 1000.0)
    second_rating = memory["ratings"].get(second, 1000.0)
    expected = 1 / (1 + 10 ** ((second_rating - first_rating) / 400))
    score = (result + 1) / 2
    change = 32 * (score - expected)
    memory["ratings"][first] = first_rating + change
    memory["ratings"][second] = second_rating - change

    first_key, second_key = (community, first), (community, second)
    first_local = memory["local_ratings"].get(first_key, first_rating)
    second_local = memory["local_ratings"].get(second_key, second_rating)
    local_expected = 1 / (1 + 10 ** ((second_local - first_local) / 400))
    local_change = 40 * (score - local_expected)
    memory["local_ratings"][first_key] = first_local + local_change
    memory["local_ratings"][second_key] = second_local - local_change

    memory["games"][first] = memory["games"].get(first, 0) + 1
    memory["games"][second] = memory["games"].get(second, 0) + 1


def record_pairwise(memory, community, num_a, num_b, result_a):
    """result_a: 1 if num_a's side won, -1 if num_b's side won, 0 tie."""
    low, high, direction = normalize_matchup(num_a, num_b)
    normalized_result = result_a * direction

    exact = memory["exact"].setdefault((community, low, high), new_record())
    matchup = memory["matchups"].setdefault((low, high), new_record())
    add_result(exact, normalized_result)
    add_result(matchup, normalized_result)

    if num_a != num_b:
        a_record = memory["numbers"].setdefault(num_a, new_record())
        b_record = memory["numbers"].setdefault(num_b, new_record())
        add_result(a_record, result_a)
        add_result(b_record, -result_a)
        update_elo(memory, num_a, num_b, community, result_a)


def update_rule_memory(data):
    """Walks every pair of players who reached showdown in each new hand --
    not just you and one opponent -- since a multi-way pot can reveal
    several numbers at once, including in hands you weren't part of."""
    memory = get_rule_data(data["table_rule"])
    match_id = data.get("match_id")
    leg_number = data.get("leg_number")

    changed = False
    for hand in data.get("recent_hands", []):
        hand_id = (match_id, leg_number, hand.get("hand_number"))
        if hand_id in seen_hands:
            continue
        seen_hands.add(hand_id)

        shown = hand.get("shown_numbers") or {}
        if len(shown) < 2:
            continue
        changed = True

        community = hand["community_number"]
        winners = set(hand.get("winners", []))
        seats = list(shown.keys())

        for i in range(len(seats)):
            for j in range(i + 1, len(seats)):
                seat_a, seat_b = seats[i], seats[j]
                num_a, num_b = shown[seat_a], shown[seat_b]
                a_won = int(seat_a) in winners
                b_won = int(seat_b) in winners
                if a_won and b_won:
                    result_a = 0
                elif a_won:
                    result_a = 1
                elif b_won:
                    result_a = -1
                else:
                    continue  # both lost this pot -- relative order unknown
                record_pairwise(memory, community, num_a, num_b, result_a)

        # Aggression tendencies pooled across every bot at this table --
        # seats are anonymised and reshuffle each round, so we can't build
        # per-bot identity profiles; this is number-keyed, not seat-keyed.
        for seat_key, number in shown.items():
            was_aggressive = any(
                a.get("seat") == int(seat_key) and a.get("action") in ("bet", "raise")
                for a in hand.get("actions", [])
            )
            action_record = memory["action_stats"].setdefault(number, {"aggressive": 0, "passive": 0})
            action_record["aggressive" if was_aggressive else "passive"] += 1

    if changed:
        _save_all()


def estimate_matchup(table_rule, your_number, opponent_number, community):
    if your_number == opponent_number:
        return 0.5, 1.0

    memory = get_rule_data(table_rule)
    low, high, direction = normalize_matchup(your_number, opponent_number)
    estimates = []

    exact = memory["exact"].get((community, low, high))
    if exact:
        equity, samples = record_equity(exact)
        estimates.append((equity, samples * 12))

    overall = memory["matchups"].get((low, high))
    if overall:
        equity, samples = record_equity(overall)
        estimates.append((equity, samples))

    low_rating = memory["ratings"].get(low, 1000.0)
    high_rating = memory["ratings"].get(high, 1000.0)
    low_local = memory["local_ratings"].get((community, low), low_rating)
    high_local = memory["local_ratings"].get((community, high), high_rating)
    low_blended = 0.7 * low_rating + 0.3 * low_local
    high_blended = 0.7 * high_rating + 0.3 * high_local
    rating_equity = 1 / (1 + 10 ** ((high_blended - low_blended) / 400))
    rating_games = memory["games"].get(low, 0) + memory["games"].get(high, 0)
    if rating_games:
        estimates.append((rating_equity, min(6, rating_games * 0.5)))

    if not estimates:
        return 0.5, 0.0

    total_weight = sum(w for _, w in estimates)
    low_equity = sum(e * w for e, w in estimates) / total_weight
    equity = low_equity if direction == 1 else 1 - low_equity
    confidence = min(1.0, total_weight / (total_weight + 6))
    return equity, confidence


def estimate_equity(table_rule, your_number, community, opponent_aggressive=False):
    """Equity against a single uniformly-random opponent number. Combined
    with active-opponent count in multiway_equity() below for the actual
    decision-time win probability."""
    memory = get_rule_data(table_rule)
    total_equity = total_confidence = total_weight = 0

    for opponent_number in range(1, 14):
        equity, confidence = estimate_matchup(table_rule, your_number, opponent_number, community)
        weight = 1.0
        if opponent_aggressive:
            action_record = memory["action_stats"].get(opponent_number)
            if action_record:
                aggressive, passive = action_record["aggressive"], action_record["passive"]
                weight = (aggressive + 1) / (aggressive + passive + 2)
            else:
                weight = 0.5
        total_equity += equity * weight
        total_confidence += confidence * weight
        total_weight += weight

    return total_equity / total_weight, total_confidence / total_weight


def active_opponent_count(data):
    your_seat = data["your_seat"]
    return sum(
        1 for p in data["players"]
        if p["seat"] != your_seat and not p.get("folded", False) and not p.get("busted", False)
    )


def multiway_equity(single_equity, num_opponents):
    """Approximation: treats each live opponent's number as an independent
    draw, so probability of beating all of them is single_equity^K. This
    undercounts multi-way ties (splitting three ways isn't quite the same
    as winning twice), but is directionally correct and standard for
    decision-making without a full joint-equity calculator."""
    return single_equity ** max(1, num_opponents)


def compute_survival_state(data):
    """Relative-rank read: where do you sit among everyone still alive at
    the table right now? Phase 4 has no absolute chip target -- the bottom
    third gets cut at the end of the round, so risk posture should track
    rank, not a fixed number."""
    your_seat = data["your_seat"]
    alive = [p for p in data["players"] if not p.get("busted", False)]
    total = len(alive)
    if total <= 1:
        return "safe", 1, max(total, 1)

    ranked = sorted(alive, key=lambda p: p["stack"], reverse=True)
    rank = next(i for i, p in enumerate(ranked) if p["seat"] == your_seat) + 1  # 1 = chip leader

    top_third = max(1, total // 3)
    bottom_third_start = total - top_third + 1

    if rank <= top_third:
        return "safe", rank, total
    if rank >= bottom_third_start:
        return "danger", rank, total
    return "neutral", rank, total


# ---------------------------------------------------------------------------
# Betting math
# ---------------------------------------------------------------------------

def calculate_pot_odds(pot, to_call):
    return (to_call / (pot + to_call)) if to_call else 0


def raise_amount(pot, to_call, min_raise_to, max_raise_to, aggressive=False):
    multiplier = 1.0 if aggressive else 0.6
    target = int((pot + to_call) * multiplier)
    return max(min_raise_to, min(target, max_raise_to))


# ---------------------------------------------------------------------------
# Main decision
# ---------------------------------------------------------------------------

def decide_move(data):
    your_seat = data["your_seat"]
    update_rule_memory(data)

    table_rule = data["table_rule"]
    your_number = data["your_number"]
    community = data["community_number"]
    pot = data["pot"]
    to_call = data["to_call"]
    legal_actions = data["legal_actions"]
    min_raise_to = data.get("min_raise_to")
    max_raise_to = data.get("max_raise_to")

    hand_number = data.get("hand_number", 1)
    total_hands = data.get("total_hands", 200)
    hands_left = max(0, total_hands - hand_number)

    num_opponents = active_opponent_count(data)
    opponent_aggressive = any(
        action.get("seat") != your_seat
        and action.get("action") in ("bet", "raise")
        and action.get("round") == data.get("round")
        for action in data.get("current_hand_actions", [])
    )

    single_equity, confidence = estimate_equity(table_rule, your_number, community, opponent_aggressive)
    equity = multiway_equity(single_equity, num_opponents)
    pot_odds = calculate_pot_odds(pot, to_call)

    survival_state, rank, table_size = compute_survival_state(data)

    if survival_state == "safe":
        if to_call == 0 and "check" in legal_actions:
            return {"action": "check"}
        base_edge = 0.07
    elif survival_state == "danger":
        base_edge = -0.05  # need chips to climb out of the cut zone
    else:
        base_edge = 0.03

    if to_call == 0:
        raise_bar = 0.8 if survival_state == "safe" else 0.72
        if confidence >= 0.35 and single_equity >= raise_bar and "raise" in legal_actions:
            amount = raise_amount(pot, to_call, min_raise_to, max_raise_to, aggressive=single_equity >= 0.85)
            return {"action": "raise", "amount": amount}
        if "check" in legal_actions:
            return {"action": "check"}

    cheap_exploration = (
        confidence < 0.25 and hands_left > 12
        and to_call <= max(2, pot * 0.15)
        and survival_state != "safe"
    )
    if cheap_exploration and "call" in legal_actions:
        return {"action": "call"}

    edge_required = base_edge + 0.10 * (1 - confidence)
    if hands_left <= 15 and survival_state == "danger":
        edge_required -= 0.05
    if opponent_aggressive and confidence < 0.6:
        edge_required += 0.05
    edge_required += 0.02 * max(0, num_opponents - 1)

    if equity >= pot_odds + edge_required:
        should_raise = confidence >= 0.4 and single_equity >= 0.76 and "raise" in legal_actions
        if should_raise:
            amount = raise_amount(
                pot, to_call, min_raise_to, max_raise_to,
                aggressive=(hands_left <= 15 and survival_state == "danger") or single_equity >= 0.88,
            )
            return {"action": "raise", "amount": amount}
        if "call" in legal_actions:
            return {"action": "call"}

    if "check" in legal_actions:
        return {"action": "check"}
    if "fold" in legal_actions:
        return {"action": "fold"}
    if "call" in legal_actions:
        return {"action": "call"}
    return {"action": legal_actions[0]}


def _safe_fallback(data):
    """Used only if decide_move throws. No retries in phase 4, so an
    unhandled exception must never become a dropped/malformed response."""
    legal_actions = (data or {}).get("legal_actions") or ["fold"]
    for action in ("check", "fold", "call"):
        if action in legal_actions:
            return {"action": action}
    return {"action": legal_actions[0]}


@app.route("/move", methods=["POST"])
def move():
    data = request.get_json(silent=True) or {}
    try:
        decision = decide_move(data)
    except Exception:
        app.logger.exception("decide_move failed, using safe fallback")
        decision = _safe_fallback(data)

    try:
        your_seat = data.get("your_seat")
        chip_delta = next(
            (p.get("chip_delta") for p in data.get("players", []) if p.get("seat") == your_seat),
            None,
        )
        decision_log.append({
            "match_id": data.get("match_id"),
            "hand_number": data.get("hand_number"),
            "round": data.get("round"),
            "table_rule": data.get("table_rule"),
            "your_number": data.get("your_number"),
            "community_number": data.get("community_number"),
            "chip_delta": chip_delta,
            "pot": data.get("pot"),
            "to_call": data.get("to_call"),
            "decision": decision,
        })
        if len(decision_log) > 500:
            del decision_log[:-500]
    except Exception:
        pass  # logging must never take down the actual response

    return jsonify(decision)


@app.route("/", methods=["GET"])
def root():
    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/debug", methods=["GET"])
def debug():
    learned_rules = {}
    for table_rule, memory in rule_memory.items():
        learned_rules[table_rule] = {
            "ratings": memory["ratings"],
            "action_stats": memory["action_stats"],
            "exact_matchups": len(memory["exact"]),
            "cross_community_matchups": len(memory["matchups"]),
        }
    return jsonify({
        "store_path": os.path.abspath(STORE_PATH),
        "rules": learned_rules,
        "decisions": decision_log,
    })


if __name__ == "__main__":
    app.run()