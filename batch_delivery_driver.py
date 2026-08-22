from bisect import bisect_right
from datetime import datetime, timedelta, timezone
import heapq
import json
from flask import Flask, request, jsonify

app = Flask(__name__)


def solve_case(data):
    start = tuple(data["start_coordinate"])
    end = tuple(data["end_coordinate"])
    start_time = datetime.fromisoformat(data["start_time"].replace("Z", "+00:00"))

    unreachable = {"total_duration_sec": None, "arrival_time": None, "path": []}

    graph = {tuple(node): [] for node in data["nodes"]}
    if start not in graph or end not in graph:
        return unreachable

    for edge in data["edges"]:
        node1 = tuple(edge["node1"])
        node2 = tuple(edge["node2"])
        info = edge["edge_id"], edge["base_duration_sec"]
        graph[node1].append((node2, *info))
        graph[node2].append((node1, *info))

    blocks = {}
    max_speeds = {}
    horizon = 0.0
    for obstruction in data["obstructions"]:
        edge = obstruction["edge"]
        key = obstruction["edge_id"], tuple(edge["from"]), tuple(edge["to"])
        interval = (
            (
                datetime.fromisoformat(obstruction["start_time"].replace("Z", "+00:00"))
                - start_time
            ).total_seconds(),
            (
                datetime.fromisoformat(obstruction["end_time"].replace("Z", "+00:00"))
                - start_time
            ).total_seconds(),
            obstruction["speed_factor"],
        )
        blocks.setdefault(key, []).append(interval)
        max_speeds[key] = max(max_speeds.get(key, 1), obstruction["speed_factor"])
        horizon = max(horizon, interval[1])

    for intervals in blocks.values():
        intervals.sort()
    block_ends = {
        key: [finish for _, finish, _ in intervals]
        for key, intervals in blocks.items()
    }

    def arrive(edge_id, a, b, duration, now):
        if duration == 0:
            return now
        left = duration

        key = edge_id, a, b
        intervals = blocks.get(key, ())
        first = bisect_right(block_ends.get(key, ()), now)
        for index in range(first, len(intervals)):
            begin, finish, factor = intervals[index]
            if begin <= now < finish and factor == 0:
                return None
            if now < begin:
                span = begin - now
                if left <= span:
                    return now + left
                left -= span
                now = begin
            span = finish - now
            if factor and left <= span * factor:
                return now + left / factor
            left -= span * factor
            now = finish

        return now + left

    def reverse_dist(optimistic=False):
        result = {end: 0}
        next_step = {}
        queue = [(0, end)]
        while queue:
            cost, node = heapq.heappop(queue)
            if cost != result[node]:
                continue
            for near, edge_id, duration in graph[node]:
                weight = duration
                if optimistic:
                    weight /= max_speeds.get((edge_id, near, node), 1)
                new = cost + weight
                if new < result.get(near, float("inf")):
                    result[near] = new
                    next_step[near] = node, edge_id
                    heapq.heappush(queue, (new, near))
        return result, next_step

    dist, follow = reverse_dist()
    lower, _ = reverse_dist(optimistic=True)

    if start not in dist:
        return unreachable

    def tail(node):
        path = []
        while node != end:
            node, edge_id = follow[node]
            path.append(edge_id)
        return path

    def prefix(label):
        path = []
        while label:
            label, edge_id = parents[label]
            path.append(edge_id)
        path.reverse()
        return path

    best = None
    serial = 0
    parents = {0: None}
    q = [(lower[start], 0, serial, start, 0)]
    seen = set()

    while q:
        estimate, elapsed, _, node, label = heapq.heappop(q)
        state = node, round(elapsed, 9)
        if state in seen or best and estimate >= best[0]:
            continue
        seen.add(state)
        now = elapsed

        if node == end:
            best = elapsed, prefix(label)
        elif now >= horizon:
            candidate = elapsed + dist[node]
            if best is None or candidate < best[0]:
                best = candidate, prefix(label) + tail(node)
        else:
            for near, edge_id, duration in graph[node]:
                arrival = arrive(edge_id, node, near, duration, now)
                if arrival is not None and near in dist:
                    new = arrival
                    bound = new + lower[near]
                    if best is None or bound < best[0]:
                        serial += 1
                        parents[serial] = label, edge_id
                        heapq.heappush(q, (bound, new, serial, near, serial))

    if best is None:
        return unreachable

    duration, path = best
    duration = round(duration, 9)
    duration = int(duration) if duration.is_integer() else duration
    arrival = (
        start_time + timedelta(seconds=duration)
    ).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "total_duration_sec": duration,
        "arrival_time": arrival,
        "path": path
    }


def solve(data: str) -> str:
    batch = json.loads(data)
    return json.dumps({case_id: solve_case(case) for case_id, case in batch.items()})


@app.route("/kan-cheong-delivery-driver", methods=["POST"])
def solve_endpoint():
    body = request.get_json()
    result = {case_id: solve_case(case) for case_id, case in body.items()}

    return jsonify(result)
