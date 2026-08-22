from flask import Flask, request, jsonify

app = Flask(__name__)

GOAL_DELTA = 25

rule_memory = {}
seen_hands = set()

def get_showdown_examples(recent_hands, your_seat, opponent_seat):

    examples = []

    for hand in recent_hands:

        shown = hand.get("shown_numbers", {})

        your_number = shown.get(str(your_seat))
        opponent_number = shown.get(str(opponent_seat))

        if your_number is None or opponent_number is None:
            continue

        community_number = hand.get("community_number")
        winners = hand.get("winners", [])
        hand_number = hand.get("hand_number")

        if your_seat in winners and opponent_seat in winners:
            result = 0

        elif your_seat in winners:
            result = 1

        elif opponent_seat in winners:
            result = -1

        else:
            continue

        examples.append({
            "hand_number": hand_number,
            "community_number": community_number,
            "your_number": your_number,
            "opponent_number": opponent_number,
            "result": result
        })

    return examples

def update_rule_memory(table_rule, examples, match_id,
    leg_number):

    if table_rule not in rule_memory:
        rule_memory[table_rule] = {}
    
    for example in examples:

        hand_number = example["hand_number"]

        hand_id = (
                match_id,
                leg_number,
                hand_number
            )

        if hand_id in seen_hands:
            continue

        seen_hands.add(hand_id)

        community = example["community_number"]
        your_number = example["your_number"]
        opponent_number = example["opponent_number"]
        result = example["result"]

        if community not in rule_memory[table_rule]:
            rule_memory[table_rule][community] = {}

        number_a, number_b, direction = normalize_matchup(
                your_number,
                opponent_number
         )

        matchup_key = (number_a, number_b)

        normalized_result = result * direction

        if matchup_key not in rule_memory[table_rule][community]:
            rule_memory[table_rule][community][matchup_key] = {
                "wins": 0,
                "losses": 0,
                "ties": 0
            }

        record = rule_memory[table_rule][community][matchup_key]

        if normalized_result == 1:
            record["wins"] += 1
        elif normalized_result == -1:
            record["losses"] += 1
        else:
            record["ties"] += 1

        # print(rule_memory)

def calculate_pot_odds(pot, to_call):

    if to_call == 0:
        return 0

    return to_call / (pot + to_call)

def estimate_known_matchup(
    table_rule,
    your_number,
    opponent_number,
    community_number
):

    if table_rule not in rule_memory:
        return None

    if community_number not in rule_memory[table_rule]:
        return None

    number_a, number_b, direction = normalize_matchup(
        your_number,
        opponent_number
    )

    matchup_key = (number_a, number_b)

    matchups = rule_memory[table_rule][community_number]

    if matchup_key not in matchups:
        return None

    record = matchups[matchup_key]

    wins = record["wins"]
    losses = record["losses"]
    ties = record["ties"]

    total = wins + losses + ties

    if total == 0:
        return None

    equity = (
        wins + 0.5 * ties + 1
    ) / (total + 2)

    if direction == 1:
        return equity

    return 1 - equity

def estimate_equity(
    table_rule,
    your_number,
    community_number
):

    total_equity = 0

    for opponent_number in range(1, 14):

        matchup_equity = estimate_known_matchup(
            table_rule,
            your_number,
            opponent_number,
            community_number
        )

        if matchup_equity is not None:
            total_equity += matchup_equity
            continue

        your_strength = estimate_number_strength(
            table_rule,
            your_number,
            community_number
        )

        opponent_strength = estimate_number_strength(
            table_rule,
            opponent_number,
            community_number
        )

        if (
            your_strength is not None
            and opponent_strength is not None
        ):
            difference = (
                your_strength
                - opponent_strength
            )

            estimated_matchup = (
                0.5 + 0.5 * difference
            )

            estimated_matchup = max(
                0,
                min(1, estimated_matchup)
            )

        else:
            estimated_matchup = 0.5

        total_equity += estimated_matchup

    return total_equity / 13

def normalize_matchup(number_a, number_b):

    if number_a <= number_b:
        return (number_a, number_b, 1)

    return (number_b, number_a, -1)

def estimate_number_strength(
    table_rule,
    number,
    community_number
    ):

    if table_rule not in rule_memory:
        return None

    if community_number not in rule_memory[table_rule]:
        return None

    matchups = rule_memory[table_rule][community_number]

    wins = 0
    losses = 0
    ties = 0

    for (number_a, number_b), record in matchups.items():

        if number == number_a:
            wins += record["wins"]
            losses += record["losses"]
            ties += record["ties"]

        elif number == number_b:
            wins += record["losses"]
            losses += record["wins"]
            ties += record["ties"]

    total = wins + losses + ties

    if total == 0:
        return None

    return (
        wins + 0.5 * ties + 1
    ) / (total + 2)

def decide_move(data):


    table_rule = data["table_rule"]

    your_number = data["your_number"]
    community_number = data["community_number"]

    your_seat = data["your_seat"]


    opponent_seat = None

    for player in data["players"]:
        if player["seat"] != your_seat:
            opponent_seat = player["seat"]
            break


    recent_hands = data.get("recent_hands", [])

    match_id = data.get("match_id")
    leg_number = data.get("leg_number")


    examples = get_showdown_examples(
        recent_hands,
        your_seat,
        opponent_seat
    )


    update_rule_memory(
        table_rule,
        examples,
        match_id,
        leg_number
    )

    pot = data["pot"]
    to_call = data["to_call"]


    equity = estimate_equity(
        table_rule,
        your_number,
        community_number
    )


    pot_odds = calculate_pot_odds(
        pot,
        to_call
    )

    chip_delta = 0

    for player in data["players"]:
        if player["seat"] == your_seat:
            chip_delta = player["chip_delta"]
            break

    legal_actions = data["legal_actions"]
    min_raise_to = data.get("min_raise_to")
    max_raise_to = data.get("max_raise_to")

    if chip_delta >= GOAL_DELTA:
        required_edge = 0.10
    elif chip_delta >= 10:
        required_edge = 0.05
    elif chip_delta >= 0:
        required_edge = 0.02
    else:
        required_edge = 0.00

    profitable = equity >= pot_odds + required_edge


    if to_call == 0:
        if equity >= 0.75 and "raise" in legal_actions:
            raise_to = min_raise_to

            if max_raise_to is not None:
                raise_to = min(
                    max_raise_to,
                    max(min_raise_to, int(pot * 0.75)
                    )
                )

            return {
                "action": "raise",
                "amount": raise_to
            }

        if "check" in legal_actions:
            return {
                "action": "check"
            }

    if profitable:
        if equity >= 0.80 and "raise" in legal_actions:
            raise_to = min_raise_to

            if max_raise_to is not None:
                raise_to = min(
                    max_raise_to,
                    max(
                        min_raise_to,
                        int((pot + to_call) * 0.75)
                    )
                )

            return {
                "action": "raise",
                "amount": raise_to
            }

        if "call" in legal_actions:
            return {
                "action": "call"
            }

    if "check" in legal_actions:
        return {
            "action": "check"
        }

    if "fold" in legal_actions:
        return {
            "action": "fold"
        }

    if "call" in legal_actions:
        return {
            "action": "call"
        }

    return {
        "action": legal_actions[0]
    }


@app.route("/move", methods=["POST"])
def move():
    data = request.get_json()

    decision = decide_move(data)

    return jsonify(decision)


if __name__ == "__main__":
    app.run()           

