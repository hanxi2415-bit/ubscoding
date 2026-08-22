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

EXAM_PASSAGES = [
    """Meridian Trench Research Station: habitat 6214m; storage annex 6050m; director Dr. Ansel Kovrith. Callsign Umbral Seven; backup Umbral Two. Residents 41; safety ceiling 52. Primary submersible Halcyon Drift; reserve Halberd Drift. Resupply every 19 days. Oxygen scrubber failure 2 Nov; annex flooding 9 Nov. Kesterline array recalibrated 14 Mar; Halberd sub-array maintained 12 Mar. Hydrophone gasket 12Nm; >0.5Nm deviation requires re-seat. Dive max 47min; first-month 35min. STOP_01 Sablefin Vent Field; STOP_02 Wraithmoor Escarpment; STOP_03 Corbel Slide; STOP_04 Pellucid Shelf.""",

    """Ashgrove Metropolitan Transit Authority: Director-General Dorian Fenwick. 68 certified drivers; minimum 50. Lines Amber, Cobalt, Russet, Willowmere, Foxglove. Cobalt Line 34.2km. Premium train Wrenfield-Class; Wrenwood prototype. Brake torque 9Nm; >0.5Nm deviation requires recheck. Daily fare cap £4.90. Russet relay fault 5 Jan; maintenance-vehicle near-miss 3 Jan. Driving limit 58min; first-month 40min. Callsign Fantail Nine; backup Fantail Two. STOP_05 Verity Observatory; STOP_06 Ashgrove Botanical Conservatory; STOP_07 Marrowgate Market; STOP_08 Halloway Aquatic Centre.""",

    """Velmara Phase II Trial: sponsor Thornquist Biotherapeutics; lead Dr. Reva Sandoval. Site 4 Bellhaven; Site 9 Corrimal Bay; Site 12 hub. Site 9 enrolled 37. Amended dosing began 3 Jun. Maintenance dose 240mg subcutaneous; pilot 180mg; proposed 210mg never used. Bloodwork every 21 days. Grade-3 hepatic event Site 9 on 11 Aug; injection-site reaction Site 4 on 4 Aug. ALT >260U/L stops dosing. Observation 90min; 60min after 3 uneventful visits. Code VLM-204-B; former VLM-204-A. STOP_09 Bellhaven Infusion Suite; STOP_10 Corrimal Bay Screening Annex; STOP_11 Thornquist Central Pharmacy; STOP_12 Velmara Sample Repository.""",

    """Hollowlight Engine: lead architect Perrin Ashwicke; 32 engineers; minimum 18. Duskcast Renderer uses Emberline deferred lighting, first Release 14; Release 13 forward lighting; Release 15 stability fixes. Texture ceilings console 512MB, desktop 768MB, mobile 256MB. Physics Ferrolight Solver; scripting Larkspur VM; audio Cindertide Audio; networking Tallowmere Netcode; assets Mossgate Pipeline; builds Ashfall Build System. Regression every 6h during milestones, otherwise 12h. Skeleton max 90 bones; environment 40000 triangles/cell. Console render budget 11ms; desktop 14ms. Streaming stall >9s; warning >3s. Stable tag Driftglass Nine; emergency Driftglass Two. STOP_13 Capture Stage; STOP_14 Determinism Test Rig; STOP_15 Asset Pipeline Farm; STOP_16 Audio Vault.""",

    """Thornmere Growers Cooperative: chair Cordelia Vance; 54 households; dissolution floor 30. Josiah Pell farms 42 acres at Cross Furlong; Josiah Pelling is different. Bellwether Drier for late-season root crops; Bellwether Two reserve. Potato harvester rotates every 11 days. Grain >18% moisture downgraded one grade. Unused cold-storage bay forfeited after 90 days. Compressor failure 6 Apr; door-seal failure 4 Apr. Drier rota adopted 21 May unanimously by 7 board members. Every crate leaving the packing shed is stamped Thornmere Nine; Thornmere Two only for consignments held for internal grading disputes, never released sale produce. STOP_17 Thornmere Grading Hall; STOP_18 Netherfield Cold Store; STOP_19 Cooperative Machinery Yard; STOP_20 Harrowbeck Weighbridge."""
]


@mcp.tool()
def get_exam_materials() -> list[str]:
    """
    Use this tool for exam questions about the assigned study materials.
    Return these factual passages to help answer questions accurately.
    """
    return EXAM_PASSAGES


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
    hops_left: int | None = None
) -> str:
    """ALWAYS use this tool for travel, routing, navigation, or any question
    asking how to get from one node/location to another when a map_id is
    provided.

    Example: "How can I get from HUB-Q to HUB-C? map_id: ..."
    -> call this tool with current="HUB-Q", destination="HUB-C".

    Return exactly ONE next adjacent node on the cheapest valid directed route.
    Call this tool repeatedly after each move until the destination is reached.

    Route cost = directed edge weight + toll of every node entered.
    Never revisit nodes listed in visited. If visited is omitted, treat it as
    empty. If hops_left is provided, the route must reach the destination
    within that many remaining edges, including the move being requested now.
    """
    graph = get_graph(map_id)
    adjacency = graph["adjacency"]
    tolls = graph.get("tolls", {})

    if current == destination:
        raise ValueError("Already at the destination")

    blocked = set(visited or [])
    blocked.discard(current)
    max_hops = hops_left
    if max_hops is None:
        max_hops = max(0, len(adjacency) - len(blocked))
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
        if hops_used == max_hops:
            continue

        for next_node, edge_weight in get_neighbours(adjacency, node):
            if next_node in blocked or next_node in path:
                continue

            next_hops = hops_used + 1
            next_cost = cost + edge_weight + tolls.get(next_node, 0)
            state = next_node, next_hops
            if next_cost < best.get(state, float("inf")):
                best[state] = next_cost
                heapq.heappush(
                    queue,
                    (next_cost, next_hops, next_node, path + [next_node])
                )

    raise ValueError("Destination is not reachable within the hop limit")

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
