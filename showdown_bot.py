from flask import Flask, jsonify, request


app = Flask(__name__)

GOAL_DELTA = 25
rule_memory = {}
seen_hands = set()
opponent_profile = {
    "aggressive": {"wins": 0, "losses": 0, "ties": 0},
    "passive": {"wins": 0, "losses": 0, "ties": 0},
}


def new_record():
    return {"wins": 0, "losses": 0, "ties": 0}


def add_result(record, result):
    if result > 0:
        record["wins"] += 1
    elif result < 0:
        record["losses"] += 1
    else:
        record["ties"] += 1


def record_value(record, smoothing=True):
    total = record["wins"] + record["losses"] + record["ties"]
    if total == 0:
        return 0.5, 0
    value = record["wins"] + 0.5 * record["ties"]
    if smoothing:
        value = (value + 1) / (total + 2)
    else:
        value /= total
    return value, total


def rule_data(table_rule):
    if table_rule not in rule_memory:
        rule_memory[table_rule] = {
            "exact": {},
            "overall": {},
            "ratings": {},
            "local_ratings": {},
            "games": {},
        }
    return rule_memory[table_rule]


def normalized_matchup(first, second):
    if first <= second:
        return first, second, 1
    return second, first, -1


def update_elo(memory, first, second, community, result):
    first_rating = memory["ratings"].get(first, 1000.0)
    second_rating = memory["ratings"].get(second, 1000.0)
    expected = 1 / (1 + 10 ** ((second_rating - first_rating) / 400))
    score = (result + 1) / 2
    change = 32 * (score - expected)
    memory["ratings"][first] = first_rating + change
    memory["ratings"][second] = second_rating - change

    first_key = community, first
    second_key = community, second
    first_local = memory["local_ratings"].get(first_key, first_rating)
    second_local = memory["local_ratings"].get(second_key, second_rating)
    expected_local = 1 / (1 + 10 ** ((second_local - first_local) / 400))
    local_change = 48 * (score - expected_local)
    memory["local_ratings"][first_key] = first_local + local_change
    memory["local_ratings"][second_key] = second_local - local_change

    memory["games"][first] = memory["games"].get(first, 0) + 1
    memory["games"][second] = memory["games"].get(second, 0) + 1


def learn_from_history(data, opponent_seat):
    memory = rule_data(data["table_rule"])
    your_seat = data["your_seat"]

    for hand in data.get("recent_hands", []):
        hand_id = (
            data.get("match_id"),
            data.get("leg_number"),
            hand.get("hand_number"),
        )
        if hand_id in seen_hands:
            continue

        shown = hand.get("shown_numbers", {})
        yours = shown.get(str(your_seat))
        theirs = shown.get(str(opponent_seat))
        if yours is None or theirs is None:
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
        community = hand.get("community_number")
        low, high, direction = normalized_matchup(yours, theirs)
        low_result = result * direction

        exact = memory["exact"].setdefault(
            (community, low, high), new_record()
        )
        overall = memory["overall"].setdefault((low, high), new_record())
        add_result(exact, low_result)
        add_result(overall, low_result)

        if yours != theirs:
            update_elo(memory, yours, theirs, community, result)

        opponent_was_aggressive = any(
            action.get("seat") == opponent_seat
            and action.get("action") in ("bet", "raise")
            for action in hand.get("actions", [])
        )
        profile = opponent_profile[
            "aggressive" if opponent_was_aggressive else "passive"
        ]
        add_result(profile, result)


def estimate_matchup(table_rule, yours, theirs, community):
    if yours == theirs:
        return 0.5, 1.0

    memory = rule_data(table_rule)
    low, high, direction = normalized_matchup(yours, theirs)
    evidence = []

    exact = memory["exact"].get((community, low, high))
    if exact:
        value, samples = record_value(exact, smoothing=False)
        evidence.append((value, samples * 16))

    overall = memory["overall"].get((low, high))
    if overall:
        value, samples = record_value(overall)
        evidence.append((value, samples * 2))

    low_rating = memory["ratings"].get(low, 1000.0)
    high_rating = memory["ratings"].get(high, 1000.0)
    low_local = memory["local_ratings"].get((community, low), low_rating)
    high_local = memory["local_ratings"].get((community, high), high_rating)
    low_blended = 0.65 * low_rating + 0.35 * low_local
    high_blended = 0.65 * high_rating + 0.35 * high_local
    elo_value = 1 / (1 + 10 ** ((high_blended - low_blended) / 400))
    games = memory["games"].get(low, 0) + memory["games"].get(high, 0)
    if games:
        evidence.append((elo_value, min(8, games * 0.6)))

    if not evidence:
        return 0.5, 0.0

    neutral_weight = 1.5
    total_weight = neutral_weight + sum(weight for _, weight in evidence)
    low_equity = (
        0.5 * neutral_weight
        + sum(value * weight for value, weight in evidence)
    ) / total_weight
    equity = low_equity if direction == 1 else 1 - low_equity
    confidence = 1 - neutral_weight / total_weight
    return equity, confidence


def estimate_equity(table_rule, your_number, community, aggressive=False):
    weighted_equity = 0
    weighted_confidence = 0
    total_weight = 0

    for opponent_number in range(1, 14):
        equity, confidence = estimate_matchup(
            table_rule, your_number, opponent_number, community
        )
        weight = 1.0
        weighted_equity += equity * weight
        weighted_confidence += confidence * weight
        total_weight += weight

    equity = weighted_equity / total_weight
    confidence = weighted_confidence / total_weight

    if aggressive:
        profile_equity, samples = record_value(opponent_profile["aggressive"])
        profile_weight = min(0.35, samples / (samples + 8))
        equity = equity * (1 - profile_weight) + profile_equity * profile_weight

    return equity, confidence


def current_opponent_aggression(data, opponent_seat):
    return any(
        action.get("seat") == opponent_seat
        and action.get("round") == data.get("round")
        and action.get("action") in ("bet", "raise")
        for action in data.get("current_hand_actions", [])
    )


def sized_action(data, aggressive=False):
    legal = data["legal_actions"]
    action = "bet" if "bet" in legal else "raise" if "raise" in legal else None
    if action is None:
        return None

    minimum = data.get("min_raise_to")
    maximum = data.get("max_raise_to")
    if minimum is None or maximum is None:
        return None

    pot_fraction = 0.85 if aggressive else 0.5
    target = int((data["pot"] + data["to_call"]) * pot_fraction)
    amount = max(minimum, min(target, maximum))
    return {"action": action, "amount": amount}


def decide_move(data):
    your_seat = data["your_seat"]
    opponent_seat = next(
        player["seat"]
        for player in data["players"]
        if player["seat"] != your_seat
    )
    learn_from_history(data, opponent_seat)

    your_player = next(
        player for player in data["players"]
        if player["seat"] == your_seat
    )
    chip_delta = your_player["chip_delta"]
    legal = data["legal_actions"]
    to_call = data["to_call"]
    pot = data["pot"]
    hands_left = max(0, data["total_hands"] - data["hand_number"])
    aggressive_opponent = current_opponent_aggression(data, opponent_seat)

    equity, confidence = estimate_equity(
        data["table_rule"],
        data["your_number"],
        data.get("community_number"),
        aggressive_opponent,
    )
    pot_odds = to_call / (pot + to_call) if to_call else 0

    if chip_delta >= GOAL_DELTA:
        if to_call == 0 and "check" in legal:
            return {"action": "check"}
        if confidence > 0.8 and equity > max(0.92, pot_odds + 0.18):
            if "call" in legal:
                return {"action": "call"}
        if "fold" in legal:
            return {"action": "fold"}

    if to_call == 0:
        if confidence >= 0.25 and equity >= 0.64:
            value_bet = sized_action(data, aggressive=equity >= 0.82)
            if value_bet:
                return value_bet
        if "check" in legal:
            return {"action": "check"}

    cheap_information = (
        confidence < 0.22
        and hands_left > 10
        and to_call <= max(2, pot * 0.18)
    )
    if cheap_information and "call" in legal:
        return {"action": "call"}

    required_edge = 0.025 + 0.11 * (1 - confidence)
    if aggressive_opponent and confidence < 0.65:
        required_edge += 0.045
    if chip_delta < 0:
        required_edge -= 0.025
    if hands_left <= 8 and chip_delta < GOAL_DELTA:
        required_edge -= 0.05

    if equity >= pot_odds + required_edge:
        if confidence >= 0.35 and equity >= 0.73:
            value_raise = sized_action(
                data,
                aggressive=equity >= 0.86 or hands_left <= 8,
            )
            if value_raise:
                return value_raise
        if "call" in legal:
            return {"action": "call"}

    if "check" in legal:
        return {"action": "check"}
    if "fold" in legal:
        return {"action": "fold"}
    if "call" in legal:
        return {"action": "call"}
    return {"action": legal[0]}


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/move")
def move():
    return jsonify(decide_move(request.get_json()))


@app.get("/debug")
def debug():
    summary = {}
    for name, memory in rule_memory.items():
        summary[name] = {
            "ratings": memory["ratings"],
            "exact_matchups": len(memory["exact"]),
            "overall_matchups": len(memory["overall"]),
        }
    return jsonify({"rules": summary, "opponent_profile": opponent_profile})
