import base64
import json
import math
from flask import Flask, request, jsonify

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
        "HIGH": 3,
    }

    adapt_output = {
        "id": user["id"],
        "name": user["fullName"],
        "action": adapt_input["action"].lower(),
        "priority": priority_map[adapt_input["metadata"]["priority"]],
    }

    # =========================
    # SLO
    # =========================

    query = data["sloQuery"]
    service = query["service"]
    since = query["since"]

    relevant = [
        heartbeat
        for heartbeat in data["heartbeats"]
        if heartbeat["service"] == service and heartbeat["timestamp"] >= since
    ]

    # Availability
    total = len(relevant)
    successful = sum(1 for heartbeat in relevant if heartbeat["status"] == "OK")
    availability = successful / total if total > 0 else 0.0

    # Latencies
    latencies = sorted(heartbeat["latencyMs"] for heartbeat in relevant)

    # p95 using nearest-rank method: index = ceil(p * n) - 1, clamped.
    # (Truncating instead of ceiling gives the wrong answer on small n --
    # e.g. n=2 truncated gives index 0, nearest-rank gives index 1.)
    if latencies:
        n = len(latencies)
        index = math.ceil(0.95 * n) - 1
        index = max(0, min(index, n - 1))
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
            "p95LatencyMs": p95_latency,
        },
    }


@app.route("/solve", methods=["POST"])
def solve_endpoint():
    body = request.get_json()
    payload = body["payload"]
    result = solve(payload)
    return jsonify(result)


if __name__ == "__main__":
    app.run()

