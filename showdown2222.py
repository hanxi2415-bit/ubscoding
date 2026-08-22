"""
Phase 2 bot -- merges the blended rule-learning engine (exact-community +
cross-community + Elo ratings, confidence-weighted) with disk persistence
so what we learn about a codename survives process restarts between
attempts. The guide states the same codename always means the same rule,
across every match/attempt/phase, and retries replay the same leg order
and rules -- so carrying the learned model forward is worth doing.

ASSUMPTION TO VERIFY: persistence only helps if the disk (or process)
survives between attempts. If each attempt runs in a fresh container with
no shared volume, this degrades gracefully to "learn within the attempt
only" -- still correct, just without the cross-attempt benefit.

Fix vs. the uploaded version: exact-community matchup equity was computed
as a raw unsmoothed ratio (wins/samples), so a single observed showdown
gave equity exactly 0.0 or 1.0 at 12x weight -- one hand could swing the
whole read. It now goes through the same Laplace-smoothed record_equity()
used for cross-community matchups.
"""

import json
import os
import threading

from flask import Flask, request, jsonify

app = Flask(__name__)

GOAL_DELTA = 25
STORE_PATH = "rule_memory_store.json"
_store_lock = threading.Lock()

rule_memory = {}
seen_hands = set()
decision_log = []


# ---------------------------------------------------------------------------
# Persistence -- rule_memory has tuple dict keys, which JSON can't hold
# directly, so we encode/decode them around a plain-string-keyed form.
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

    rule_memory = {
        table_rule: _deserialize_memory(mem)
        for table_rule, mem in raw.get("rule_memory", {}).items()
    }
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
# Rule memory helpers
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
    """Laplace-smoothed (Beta(1,1) prior) equity estimate: starts at 0.5
    with zero data, shrinks toward the observed rate as samples grow."""
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
            "exact": {},
            "matchups": {},
            "numbers": {},
            "ratings": {},
            "local_ratings": {},
            "games": {},
            "action_stats": {},
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

    first_key = (community, first)
    second_key = (community, second)
    first_local = memory["local_ratings"].get(first_key, first_rating)
    second_local = memory["local_ratings"].get(second_key, second_rating)
    local_expected = 1 / (1 + 10 ** ((second_local - first_local) / 400))
    local_change = 40 * (score - local_expected)
    memory["local_ratings"][first_key] = first_local + local_change
    memory["local_ratings"][second_key] = second_local - local_change

    memory["games"][first] = memory["games"].get(first, 0) + 1
    memory["games"][second] = memory["games"].get(second, 0) + 1


def update_rule_memory(data, opponent_seat):
    memory = get_rule_data(data["table_rule"])
    your_seat = data["your_seat"]
    match_id = data.get("match_id")
    leg_number = data.get("leg_number")

    changed = False
    for hand in data.get("recent_hands", []):
        hand_id = (match_id, leg_number, hand.get("hand_number"))
        if hand_id in seen_hands:
            continue

        shown = hand.get("shown_numbers", {})
        your_number = shown.get(str(your_seat))
        opponent_number = shown.get(str(opponent_seat))
        if your_number is None or opponent_number is None:
            continue  # no showdown this hand

        winners = hand.get("winners", [])
        if your_seat in winners and opponent_seat in winners:
            result = 0
        elif your_seat in winners:
            result = 1
        elif opponent_seat in winners:
            result = -1
        else:
            continue

        seen_hands.add(hand_id)
        changed = True
        community = hand["community_number"]
        low, high, direction = normalize_matchup(your_number, opponent_number)
        normalized_result = result * direction

        exact = memory["exact"].setdefault((community, low, high), new_record())
        matchup = memory["matchups"].setdefault((low, high), new_record())
        add_result(exact, normalized_result)
        add_result(matchup, normalized_result)

        if your_number != opponent_number:
            your_record = memory["numbers"].setdefault(your_number, new_record())
            opponent_record = memory["numbers"].setdefault(opponent_number, new_record())
            add_result(your_record, result)
            add_result(opponent_record, -result)
            update_elo(memory, your_number, opponent_number, community, result)

        opponent_actions = [
            action for action in hand.get("actions", [])
            if action.get("seat") == opponent_seat
        ]
        was_aggressive = any(
            action.get("action") in ("bet", "raise") for action in opponent_actions
        )
        action_record = memory["action_stats"].setdefault(
            opponent_number, {"aggressive": 0, "passive": 0}
        )
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
        # FIX: use the same Laplace-smoothed estimator as the cross-community
        # case. A raw ratio here meant a single showdown gave equity of
        # exactly 0.0 or 1.0 at 12x weight -- one hand could swing the read.
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

    total_weight = sum(weight for _, weight in estimates)
    low_equity = sum(equity * weight for equity, weight in estimates) / total_weight
    equity = low_equity if direction == 1 else 1 - low_equity
    confidence = min(1.0, total_weight / (total_weight + 6))
    return equity, confidence


def estimate_equity(table_rule, your_number, community, opponent_aggressive=False):
    memory = get_rule_data(table_rule)
    total_equity = 0
    total_confidence = 0
    total_weight = 0

    for opponent_number in range(1, 14):
        equity, confidence = estimate_matchup(table_rule, your_number, opponent_number, community)
        weight = 1.0
        if opponent_aggressive:
            action_record = memory["action_stats"].get(opponent_number)
            if action_record:
                aggressive = action_record["aggressive"]
                passive = action_record["passive"]
                weight = (aggressive + 1) / (aggressive + passive + 2)
            else:
                weight = 0.5

        total_equity += equity * weight
        total_confidence += confidence * weight
        total_weight += weight

    return total_equity / total_weight, total_confidence / total_weight


# ---------------------------------------------------------------------------
# Betting math
# ---------------------------------------------------------------------------

def calculate_pot_odds(pot, to_call):
    if to_call == 0:
        return 0
    return to_call / (pot + to_call)


def raise_amount(pot, to_call, min_raise_to, max_raise_to, aggressive=False):
    multiplier = 1.0 if aggressive else 0.6
    target = int((pot + to_call) * multiplier)
    return max(min_raise_to, min(target, max_raise_to))


# ---------------------------------------------------------------------------
# Main decision
# ---------------------------------------------------------------------------

def decide_move(data):
    your_seat = data["your_seat"]
    opponent_seat = next(p["seat"] for p in data["players"] if p["seat"] != your_seat)
    update_rule_memory(data, opponent_seat)

    table_rule = data["table_rule"]
    your_number = data["your_number"]
    community = data["community_number"]
    pot = data["pot"]
    to_call = data["to_call"]
    legal_actions = data["legal_actions"]
    min_raise_to = data.get("min_raise_to")
    max_raise_to = data.get("max_raise_to")

    chip_delta = next(p["chip_delta"] for p in data["players"] if p["seat"] == your_seat)
    hand_number = data.get("hand_number", 1)
    total_hands = data.get("total_hands", 40)
    hands_left = max(0, total_hands - hand_number)

    opponent_aggressive = any(
        action.get("seat") == opponent_seat
        and action.get("action") in ("bet", "raise")
        and action.get("round") == data.get("round")
        for action in data.get("current_hand_actions", [])
    )
    equity, confidence = estimate_equity(table_rule, your_number, community, opponent_aggressive)
    pot_odds = calculate_pot_odds(pot, to_call)

    if chip_delta >= GOAL_DELTA:
        if to_call == 0 and "check" in legal_actions:
            return {"action": "check"}
        if confidence >= 0.7 and equity >= max(0.9, pot_odds + 0.15):
            if "call" in legal_actions:
                return {"action": "call"}
        if "fold" in legal_actions:
            return {"action": "fold"}

    if to_call == 0:
        if confidence >= 0.35 and equity >= 0.72 and "raise" in legal_actions:
            amount = raise_amount(pot, to_call, min_raise_to, max_raise_to, aggressive=equity >= 0.85)
            return {"action": "raise", "amount": amount}
        if "check" in legal_actions:
            return {"action": "check"}

    cheap_exploration = confidence < 0.25 and hands_left > 12 and to_call <= max(2, pot * 0.15)
    if cheap_exploration and "call" in legal_actions:
        return {"action": "call"}

    edge_required = 0.03 + 0.10 * (1 - confidence)
    if chip_delta < 0:
        edge_required -= 0.03
    if hands_left <= 10 and chip_delta < GOAL_DELTA:
        edge_required -= 0.04
    if opponent_aggressive and confidence < 0.6:
        edge_required += 0.05

    if equity >= pot_odds + edge_required:
        should_raise = confidence >= 0.4 and equity >= 0.76 and "raise" in legal_actions
        if should_raise:
            amount = raise_amount(
                pot, to_call, min_raise_to, max_raise_to,
                aggressive=hands_left <= 10 or equity >= 0.88,
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


@app.route("/move", methods=["POST"])
def move():
    data = request.get_json()
    decision = decide_move(data)

    your_seat = data["your_seat"]
    chip_delta = next(p["chip_delta"] for p in data["players"] if p["seat"] == your_seat)
    decision_log.append({
        "match_id": data.get("match_id"),
        "leg_number": data.get("leg_number"),
        "hand_number": data.get("hand_number"),
        "round": data.get("round"),
        "table_rule": data["table_rule"],
        "your_number": data["your_number"],
        "community_number": data["community_number"],
        "chip_delta": chip_delta,
        "pot": data["pot"],
        "to_call": data["to_call"],
        "current_hand_actions": data.get("current_hand_actions", []),
        "decision": decision,
    })
    if len(decision_log) > 500:
        del decision_log[:-500]

    return jsonify(decision)


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