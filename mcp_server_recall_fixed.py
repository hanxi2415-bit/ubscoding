import os
from fastmcp import FastMCP
import base64
import cv2
import heapq
import json
import numpy as np
from urllib.parse import urlencode
from urllib.request import urlopen

mcp = FastMCP("UBS Stage 2")

GRAPH_API_URL = os.environ.get(
    "GRAPH_API_URL",
    "https://tool-box-2591eaa24fa3.herokuapp.com/graph"
)
graph_cache = {}

import json
from urllib.request import urlopen

STUDY_URLS = [
    "https://tool-box-2591eaa24fa3.herokuapp.com/study-materials/1",
    "https://tool-box-2591eaa24fa3.herokuapp.com/study-materials/2",
    "https://tool-box-2591eaa24fa3.herokuapp.com/study-materials/3",
    "https://tool-box-2591eaa24fa3.herokuapp.com/study-materials/4",
    "https://tool-box-2591eaa24fa3.herokuapp.com/study-materials/5",
]

study_cache = None


def load_study_materials():
    global study_cache

    if study_cache:
        return study_cache

    materials = []

    for url in STUDY_URLS:
        try:
            with urlopen(url, timeout=8) as response:
                raw = response.read().decode("utf-8")

            try:
                data = json.loads(raw)

                if isinstance(data, str):
                    text = data
                elif isinstance(data, dict):
                    text = (
                        data.get("content")
                        or data.get("text")
                        or data.get("body")
                        or data.get("document")
                        or raw
                    )
                else:
                    text = raw
            except json.JSONDecodeError:
                text = raw

            if text and text.strip():
                materials.append(text.strip())

        except Exception as e:
            print("Study material error:", url, str(e))

    study_cache = materials
    return materials


@mcp.tool()
def retrieve(query: str) -> str:
    materials = load_study_materials()

    if not materials:
        return "Unable to load study materials."

    words = [
        word.lower().strip(".,?!:;()[]{}'\"")
        for word in query.split()
        if len(word) > 2
    ]

    scored = []

    for text in materials:
        lower = text.lower()
        score = sum(lower.count(word) for word in words)
        scored.append((score, text))

    scored.sort(key=lambda x: x[0], reverse=True)

    result = ""

    for score, text in scored:
        sentences = text.replace("\n", " ").split(".")

        relevant = []

        for sentence in sentences:
            sentence_lower = sentence.lower()

            if any(word in sentence_lower for word in words):
                relevant.append(sentence.strip())

        for sentence in relevant:
            if not sentence:
                continue

            addition = sentence + ". "

            if len(result) + len(addition) > 900:
                return result.strip()[:900]

            result += addition

        if len(result) >= 700:
            break

    if not result:
        return scored[0][1][:900]

    return result.strip()[:900]

def get_graph(map_id: str) -> dict:
    if map_id not in graph_cache:
        url = f"{GRAPH_API_URL}?{urlencode({'map_id': map_id})}"
        with urlopen(url, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
            if "adjacency" not in data and isinstance(data.get("graph"), dict):
                data = data["graph"]
            graph_cache[map_id] = data
    return graph_cache[map_id]


def get_neighbours(adjacency, node):
    neighbours = adjacency.get(node, {})

    if isinstance(neighbours, dict):
        return list(neighbours.items())

    result = []
    for edge in neighbours:
        if isinstance(edge, dict):
            next_node = edge.get("to", edge.get("node"))
            weight = edge.get("weight", edge.get("cost"))
        else:
            next_node, weight = edge
        result.append((next_node, weight))
    return result


@mcp.tool()
def get_next_node(
    map_id: str,
    current: str,
    destination: str,
    visited: list[str] | None = None,
    hops_left: int | None = None,
    hops_remaining: int | None = None
) -> str:
    """
    ALWAYS use this tool for travel, routing, navigation, or any question
    asking how to get from one node/location to another when a map_id is provided.

    Example:
    "How can I get from HUB-Q to HUB-C? map_id: ..."
    -> call this tool with current="HUB-Q", destination="HUB-C".

    Return exactly ONE next adjacent node on the cheapest valid directed route.
    Call this tool repeatedly after each move until the destination is reached.

    Route cost = directed edge weight + toll of every node entered.
    Never revisit nodes listed in visited.

    A remaining-hop limit may be supplied as either hops_left or
    hops_remaining.
    """

    if hops_left is None and hops_remaining is not None:
        hops_left = hops_remaining

    graph = get_graph(map_id)
    adjacency = graph["adjacency"]
    tolls = graph.get("tolls", {})

    if current == destination:
        raise ValueError("Already at the destination")

    blocked = set(visited or [])
    blocked.discard(current)

    if hops_left is None:
        max_hops = max(0, len(adjacency) - len(blocked))
    else:
        max_hops = hops_left

    if max_hops <= 0:
        raise ValueError("No hops left")

    queue = [(0, 0, current, [current])]
    best = {(current, 0): 0}

    while queue:
        cost, hops_used, node, path = heapq.heappop(queue)

        if cost != best.get((node, hops_used)):
            continue

        if node == destination:
            return path[1]

        if hops_used >= max_hops:
            continue

        for next_node, edge_weight in get_neighbours(adjacency, node):
            if next_node in blocked or next_node in path:
                continue

            next_hops = hops_used + 1
            next_cost = cost + edge_weight + tolls.get(next_node, 0)
            state = (next_node, next_hops)

            if next_cost < best.get(state, float("inf")):
                best[state] = next_cost
                heapq.heappush(
                    queue,
                    (
                        next_cost,
                        next_hops,
                        next_node,
                        path + [next_node]
                    )
                )

    raise ValueError(
        "Destination is not reachable within the remaining hop limit"
    )

@mcp.tool()
def get_name() -> str:
    """Return the agent's name."""
    return "BabyBot"

@mcp.tool()
def calculate(expression: str) -> float:
    """Evaluate an arithmetic expression using +, -, *, / with standard operator precedence."""

    allowed = "0123456789+-*/.() "

    if not all(ch in allowed for ch in expression):
        raise ValueError("Invalid expression")

    return float(eval(expression))

@mcp.tool()
def identify_shape(image_base64: str) -> str:
    """Identify whether a base64-encoded PNG contains a triangle, rectangle, or circle."""

    image_bytes = base64.b64decode(image_base64)
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_GRAYSCALE)

    if image is None:
        raise ValueError("Invalid PNG image")

    _, threshold = cv2.threshold(
        image,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    contours, _ = cv2.findContours(
        threshold,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        raise ValueError("No shape found")


    contour = max(contours, key=cv2.contourArea)

    perimeter = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)

    vertices = len(approx)

    if vertices == 3:
        return "triangle"
    elif vertices == 4:
        return "rectangle"
    else:
        return "circle"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))

    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=port,
        path="/mcp"
    )
