from flask import Flask, request
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
        horizon = max(horizon, interval[1])

    for intervals in blocks.values():
        intervals.sort()

    def arrive(edge_id, a, b, duration, now):
        if duration == 0:
            return now
        left = duration

        for begin, finish, factor in blocks.get((edge_id, a, b), []):
            if finish <= now:
                continue
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

    dist = {end: 0}
    follow = {}
    q = [(0, end)]
    while q:
        cost, node = heapq.heappop(q)
        if cost != dist[node]:
            continue
        for near, edge_id, duration in graph[node]:
            new = cost + duration
            if new < dist.get(near, float("inf")):
                dist[near] = new
                follow[near] = node, edge_id
                heapq.heappush(q, (new, near))

    if start not in dist:
        return fail

    def tail(node):
        path = []
        while node != end:
            node, edge_id = follow[node]
            path.append(edge_id)
        return path

    best = None
    q = [(0, start, [])]
    seen = set()

    while q:
        elapsed, node, path = heapq.heappop(q)
        state = node, round(elapsed, 9)
        if state in seen or best and elapsed >= best[0]:
            continue
        seen.add(state)
        now = t0 + timedelta(seconds=elapsed)

        if node == end:
            best = elapsed, path
        elif now >= horizon:
            best = elapsed + dist[node], path + tail(node)
        else:
            for near, edge_id, duration in graph[node]:
                arrival = arrive(edge_id, node, near, duration, now)
                if arrival is not None and near in dist:
                    new = (arrival - t0).total_seconds()
                    heapq.heappush(q, (new, near, path + [edge_id]))

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
    return solve(request.get_data(as_text=True))


