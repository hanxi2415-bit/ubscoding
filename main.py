import heapq
import itertools
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request


app = Flask(__name__)


def _parse_time(value):
    if not isinstance(value, str):
        raise ValueError("times must be ISO-8601 strings")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("times must include a UTC offset")
    return parsed


def _coordinate(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("coordinates must contain exactly two values")
    return tuple(value)


def _isoformat(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _travel_time(start, base_duration, intervals):
    """Calculate an edge arrival while its speed changes over time."""
    if base_duration == 0:
        return start

    remaining = float(base_duration)
    now = start
    for interval_start, interval_end, factor in intervals:
        if interval_end <= now:
            continue
        if now < interval_start:
            normal_window = (interval_start - now).total_seconds()
            if remaining <= normal_window:
                return now + timedelta(seconds=remaining)
            remaining -= normal_window
            now = interval_start

        obstructed_window = (interval_end - now).total_seconds()
        possible_progress = obstructed_window * factor
        if factor > 0 and remaining <= possible_progress:
            return now + timedelta(seconds=remaining / factor)
        remaining -= possible_progress
        now = interval_end

    return now + timedelta(seconds=remaining)


def calculate_route(payload):
    start = _coordinate(payload["start_coordinate"])
    destination = _coordinate(payload["end_coordinate"])
    departure = _parse_time(payload["start_time"])

    nodes = {_coordinate(node) for node in payload["nodes"]}
    if start not in nodes or destination not in nodes:
        return {"total_duration_sec": None, "arrival_time": None, "path": []}

    graph = defaultdict(list)
    edge_directions = set()
    for edge in payload["edges"]:
        node1 = _coordinate(edge["node1"])
        node2 = _coordinate(edge["node2"])
        edge_id = edge["edge_id"]
        duration = float(edge["base_duration_sec"])
        if node1 not in nodes or node2 not in nodes:
            raise ValueError("every edge endpoint must be present in nodes")
        if duration < 0:
            raise ValueError("base_duration_sec cannot be negative")
        graph[node1].append((node2, edge_id, duration))
        graph[node2].append((node1, edge_id, duration))
        edge_directions.update(((edge_id, node1, node2), (edge_id, node2, node1)))

    obstructions = defaultdict(list)
    for obstruction in payload.get("obstructions", []):
        edge = obstruction["edge"]
        key = (obstruction["edge_id"], _coordinate(edge["from"]), _coordinate(edge["to"]))
        if key not in edge_directions:
            raise ValueError("obstruction must refer to an existing directed edge")
        interval_start = _parse_time(obstruction["start_time"])
        interval_end = _parse_time(obstruction["end_time"])
        factor = float(obstruction["speed_factor"])
        if interval_end < interval_start:
            raise ValueError("obstruction end_time cannot precede start_time")
        if factor < 0:
            raise ValueError("speed_factor cannot be negative")
        if interval_end > interval_start:
            obstructions[key].append((interval_start, interval_end, factor))

    for intervals in obstructions.values():
        intervals.sort(key=lambda interval: interval[0])
        for previous_interval, current_interval in zip(intervals, intervals[1:]):
            if current_interval[0] < previous_interval[1]:
                raise ValueError("obstructions for one directed edge cannot overlap")

    # Edge traversal is FIFO, so a time-dependent Dijkstra finds the optimum.
    sequence = itertools.count()
    queue = [(departure, next(sequence), start)]
    earliest = {start: departure}
    previous = {}

    while queue:
        arrival, _, node = heapq.heappop(queue)
        if arrival != earliest[node]:
            continue
        if node == destination:
            break
        for neighbour, edge_id, duration in graph[node]:
            intervals = obstructions.get((edge_id, node, neighbour), ())
            candidate = _travel_time(arrival, duration, intervals)
            if candidate < earliest.get(neighbour, datetime.max.replace(tzinfo=timezone.utc)):
                earliest[neighbour] = candidate
                previous[neighbour] = (node, edge_id)
                heapq.heappush(queue, (candidate, next(sequence), neighbour))

    if destination not in earliest:
        return {"total_duration_sec": None, "arrival_time": None, "path": []}

    path = []
    cursor = destination
    while cursor != start:
        cursor, edge_id = previous[cursor]
        path.append(edge_id)
    path.reverse()

    duration = (earliest[destination] - departure).total_seconds()
    if duration.is_integer():
        duration = int(duration)
    return {
        "total_duration_sec": duration,
        "arrival_time": _isoformat(earliest[destination]),
        "path": path,
    }


def solve(data: str) -> str:
    return json.dumps(calculate_route(json.loads(data)))


@app.get("/")
def home():
    return "Server is running"


@app.post("/kan-cheong-delivery-driver")
def solve_api():
    try:
        return jsonify(calculate_route(request.get_json(force=True)))
    except (KeyError, TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400
