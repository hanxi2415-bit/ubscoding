import base64
import json
from flask import Flask, request,jsonify

app = Flask(__name__)


def solve(payload: str):
    decoded = base64.b64decode(payload).decode("utf-8")
    data = json.loads(decoded)


    priority_map = {
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3
    }

    priority = priority_map[data["adaptInput"]["metadata"]["priority"]]

    output = {
        "adaptOutput": {
            "id": data["adaptInput"]["user"]["id"],
            "name": data["adaptInput"]["user"]["fullName"],
            "action": data["adaptInput"]["action"].lower(),
            "priority": priority
        }
    }

    return output

@app.route("/solve", methods=["POST"])
def solve_endpoint():
    body = request.get_json()
    payload = body["payload"]

    result = solve(payload)

    return jsonify(result)