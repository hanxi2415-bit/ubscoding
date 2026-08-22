import base64
import json
from flask import Flask, request,jsonify


app = Flask(__name__)


def solve(payload):

    decoded = base64.b64decode(payload).decode("utf-8")
    data = json.loads(decoded)

    # =========================
    # ADAPT
    # =========================

    adapt_input = data["adaptInput"]

    user = adapt_input["user"]

    priority_map = {
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3
    }

    adapt_output = {
        "id": user["id"],
        "name": user["fullName"],
        "action": adapt_input["action"].lower(),
        "priority": priority_map[
            adapt_input["metadata"]["priority"]
        ]
    }


    # =========================
    # SLO
    # =========================

    query = data["sloQuery"]

    service = query["service"]
    since = query["since"]

    # Filter heartbeats
    relevant = [
        heartbeat
        for heartbeat in data["heartbeats"]
        if heartbeat["service"] == service
        and heartbeat["timestamp"] >= since
    ]

    # Availability
    total = len(relevant)

    successful = sum(
        1
        for heartbeat in relevant
        if heartbeat["status"] == "OK"
    )

    availability = successful / total if total > 0 else 0.0

    # Latencies
    latencies = sorted(
        heartbeat["latencyMs"]
        for heartbeat in relevant
    )

    # p95
    if latencies:
        index = int(0.95 * len(latencies)) - 1
        index = max(0, min(index, len(latencies) - 1))
        p95_latency = latencies[index]
    else:
        p95_latency = 0


    # =========================
    # OUTPUT
    # =========================

    return {
        "adaptOutput": adapt_output,
        "sloOutput": {
            "availability": availability,
            "p95LatencyMs": p95_latency
        }
    }

@app.route("/solve", methods=["POST"])
def solve_endpoint():
    body = request.get_json()
    payload = body["payload"]

    result = solve(payload)

    return jsonify(result)



