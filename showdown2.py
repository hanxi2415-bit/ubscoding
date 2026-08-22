from flask import Flask, request, jsonify

app = Flask(__name__)

GOAL_DELTA = 25

rule_memory = {}
seen_hands = set()


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
            "exact": {},
            "matchups": {},
            "numbers": {}
        }
    return rule_memory[table_rule]


def update_rule_memory(data, opponent_seat):
    memory = get_rule_data(data["table_rule"])
    your_seat = data["your_seat"]
    match_id = data.get("match_id")
    leg_number = data.get("leg_number")

    for hand in data.get("recent_hands", []):
        hand_id = (match_id, leg_number, hand.get("hand_number"))
        if hand_id in seen_hands:
            continue

        shown = hand.get("shown_numbers", {})
        your_number = shown.get(str(your_seat))
        opponent_number = shown.get(str(opponent_seat))
        if your_number is None or opponent_number is None:
            continue

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
        community = hand["community_number"]
        low, high, direction = normalize_matchup(your_number, opponent_number)
        normalized_result = result * direction

        exact = memory["exact"].setdefault(
            (community, low, high), new_record()
        )
        matchup = memory["matchups"].setdefault((low, high), new_record())
        add_result(exact, normalized_result)
        add_result(matchup, normalized_result)

        your_record = memory["numbers"].setdefault(your_number, new_record())
        opponent_record = memory["numbers"].setdefault(opponent_number, new_record())
        add_result(your_record, result)
        add_result(opponent_record, -result)


def estimate_matchup(table_rule, your_number, opponent_number, community):
    if your_number == opponent_number:
        return 0.5, 1.0

    memory = get_rule_data(table_rule)
    low, high, direction = normalize_matchup(your_number, opponent_number)
    estimates = []

    exact = memory["exact"].get((community, low, high))
    if exact:
        equity, samples = record_equity(exact)
        estimates.append((equity, samples * 4))

    overall = memory["matchups"].get((low, high))
    if overall:
        equity, samples = record_equity(overall)
        estimates.append((equity, samples))

    low_record = memory["numbers"].get(low)
    high_record = memory["numbers"].get(high)
    if low_record or high_record:
        low_strength, low_samples = record_equity(low_record or new_record())
        high_strength, high_samples = record_equity(high_record or new_record())
        strength_equity = 0.5 + 0.5 * (low_strength - high_strength)
        strength_weight = (low_samples + high_samples) * 0.2
        estimates.append((strength_equity, strength_weight))

    if not estimates:
        return 0.5, 0.0

    total_weight = sum(weight for _, weight in estimates)
    low_equity = sum(equity * weight for equity, weight in estimates) / total_weight
    equity = low_equity if direction == 1 else 1 - low_equity
    confidence = min(1.0, total_weight / (total_weight + 6))
    return equity, confidence


def estimate_equity(table_rule, your_number, community):
    total_equity = 0
    total_confidence = 0

    for opponent_number in range(1, 14):
        equity, confidence = estimate_matchup(
            table_rule, your_number, opponent_number, community
        )
        total_equity += equity
        total_confidence += confidence

    return total_equity / 13, total_confidence / 13


def calculate_pot_odds(pot, to_call):
    if to_call == 0:
        return 0
    return to_call / (pot + to_call)


def raise_amount(pot, to_call, min_raise_to, max_raise_to, aggressive=False):
    multiplier = 1.0 if aggressive else 0.6
    target = int((pot + to_call) * multiplier)
    return max(min_raise_to, min(target, max_raise_to))


def decide_move(data):
    your_seat = data["your_seat"]
    opponent_seat = next(
        player["seat"] for player in data["players"]
        if player["seat"] != your_seat
    )
    update_rule_memory(data, opponent_seat)

    table_rule = data["table_rule"]
    your_number = data["your_number"]
    community = data["community_number"]
    pot = data["pot"]
    to_call = data["to_call"]
    legal_actions = data["legal_actions"]
    min_raise_to = data.get("min_raise_to")
    max_raise_to = data.get("max_raise_to")

    chip_delta = next(
        player["chip_delta"] for player in data["players"]
        if player["seat"] == your_seat
    )
    hand_number = data.get("hand_number", 1)
    total_hands = data.get("total_hands", 40)
    hands_left = max(0, total_hands - hand_number)

    equity, confidence = estimate_equity(table_rule, your_number, community)
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
            amount = raise_amount(
                pot, to_call, min_raise_to, max_raise_to,
                aggressive=equity >= 0.85
            )
            return {"action": "raise", "amount": amount}
        if "check" in legal_actions:
            return {"action": "check"}

    cheap_exploration = (
        confidence < 0.25
        and hands_left > 12
        and to_call <= max(2, pot * 0.15)
    )
    if cheap_exploration and "call" in legal_actions:
        return {"action": "call"}

    edge_required = 0.03
    if chip_delta < 0:
        edge_required = 0
    if hands_left <= 10 and chip_delta < GOAL_DELTA:
        edge_required -= 0.04

    if equity >= pot_odds + edge_required:
        should_raise = (
            confidence >= 0.4
            and equity >= 0.76
            and "raise" in legal_actions
        )
        if should_raise:
            amount = raise_amount(
                pot, to_call, min_raise_to, max_raise_to,
                aggressive=hands_left <= 10 or equity >= 0.88
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
    return jsonify(decision)
