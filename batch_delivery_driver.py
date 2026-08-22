from flask import Flask, jsonify, request
from bisect import bisect_right
import json
import heapq
from datetime import datetime, timedelta

app = Flask(__name__)


def solve_case(d):
    start = tuple(d["start_coordinate"])
    end = tuple(d["end_coordinate"])
    t0 = datetime.fromisoformat(d["start_time"].replace("Z", "+00:00"))
    fail = {"total_duration_sec": None, "arrival_time": None, "path": []}

    graph = {tuple(node): [] for node in d["nodes"]}
    if start not in graph or end not in graph:
        return fail

    for edge in d["edges"]:
        a, b = tuple(edge["node1"]), tuple(edge["node2"])
        item = edge["edge_id"], edge["base_duration_sec"]
        graph[a].append((b, *item))
        graph[b].append((a, *item))

    blocks = {}
    max_speeds = {}
    horizon = t0
    for ob in d["obstructions"]:
        edge = ob["edge"]
        key = ob["edge_id"], tuple(edge["from"]), tuple(edge["to"])
        interval = (
            datetime.fromisoformat(ob["start_time"].replace("Z", "+00:00")),
            datetime.fromisoformat(ob["end_time"].replace("Z", "+00:00")),
            ob["speed_factor"],
        )
        blocks.setdefault(key, []).append(interval)
        max_speeds[key] = max(max_speeds.get(key, 1), ob["speed_factor"])
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
                span = (begin - now).total_seconds()
                if left <= span:
                    return now + timedelta(seconds=left)
                left -= span
                now = begin
            span = (finish - now).total_seconds()
            if factor and left <= span * factor:
                return now + timedelta(seconds=left / factor)
            left -= span * factor
            now = finish

        return now + timedelta(seconds=left)

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

    # Base distances are exact after the final obstruction. Optimistic distances
    # remain valid lower bounds even when a speed_factor is greater than one.
    dist, follow = reverse_dist()
    lower, _ = reverse_dist(optimistic=True)

    if start not in dist:
        return fail

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
        now = t0 + timedelta(seconds=elapsed)

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
                    new = (arrival - t0).total_seconds()
                    bound = new + lower[near]
                    if best is None or bound < best[0]:
                        serial += 1
                        parents[serial] = label, edge_id
                        heapq.heappush(q, (bound, new, serial, near, serial))

    if best is None:
        return fail

    duration, path = best
    duration = round(duration, 9)
    duration = int(duration) if duration.is_integer() else duration
    arrival = (t0 + timedelta(seconds=duration)).isoformat().replace("+00:00", "Z")
    return {"total_duration_sec": duration, "arrival_time": arrival, "path": path}


def solve(data: str) -> str:
    batch = json.loads(data)
    return json.dumps({case_id: solve_case(case) for case_id, case in batch.items()})


@app.route("/kan-cheong-delivery-driver", methods=["POST"])
def solve_api():
    batch = request.get_json(force=True)
    return jsonify({case_id: solve_case(case) for case_id, case in batch.items()})
