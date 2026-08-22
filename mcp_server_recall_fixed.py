import os
from fastmcp import FastMCP
import base64
import cv2
import heapq
import json
import numpy as np
import re
import tiktoken
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from urllib.request import urlopen

mcp = FastMCP("UBS Stage 2")

GRAPH_API_URL = os.environ.get(
    "GRAPH_API_URL",
    "https://tool-box-2591eaa24fa3.herokuapp.com/graph"
)
graph_cache = {}

STUDY_URLS = [
    "https://tool-box-2591eaa24fa3.herokuapp.com/study-materials/1",
    "https://tool-box-2591eaa24fa3.herokuapp.com/study-materials/2",
    "https://tool-box-2591eaa24fa3.herokuapp.com/study-materials/3",
    "https://tool-box-2591eaa24fa3.herokuapp.com/study-materials/4",
    "https://tool-box-2591eaa24fa3.herokuapp.com/study-materials/5",
]

study_cache = None


def fetch_study_material(url):
    try:
        with urlopen(url, timeout=6) as response:
            raw = response.read().decode("utf-8")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip()

        if isinstance(data, str):
            return data.strip()
        if isinstance(data, dict):
            text = (
                data.get("content")
                or data.get("text")
                or data.get("body")
                or data.get("document")
            )
            return text.strip() if isinstance(text, str) else ""
    except Exception:
        return ""

    return ""


def load_study_materials():
    global study_cache

    if study_cache is not None:
        return study_cache

    with ThreadPoolExecutor(max_workers=len(STUDY_URLS)) as pool:
        downloaded = list(pool.map(fetch_study_material, STUDY_URLS))

    study_cache = [text for text in downloaded if text]
    return study_cache


@mcp.tool()
def retrieve(query: str) -> list[str]:
    """Return relevant passages within the exact o200k_base 900-token budget."""
    encoding = tiktoken.get_encoding("o200k_base")
    max_output_tokens = 900

    def normalized_words(value):
        result = set()
        for word in re.findall(r"[a-z0-9]+", value.lower()):
            if len(word) <= 2:
                continue
            for suffix in ("ing", "ed", "es", "s"):
                if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                    word = word[:-len(suffix)]
                    break
            result.add(word)
        return result

    words = normalized_words(query)
    words -= {
        "the", "and", "for", "was", "were", "what", "when", "where",
        "which", "who", "how", "from", "with", "about", "into", "exact"
    }
    original_words = set(words)

    synonym_groups = [
        {"motorman", "motormen", "driver", "operator"},
        {"licensed", "certified", "qualified", "accredited"},
        {"network", "transit", "transport", "rail", "service"},
        {"many", "count", "total", "number", "headcount", "population", "enrolled"},
        {"day", "date", "when"},
        {"resolved", "fixed", "patched", "repaired"},
        {"glitch", "fault", "issue", "bug", "regression", "failure"},
        {"movement", "transition", "animation", "blending", "motion"},
        {"lead", "leader", "director", "head", "chair"},
        {"limit", "ceiling", "maximum", "max", "cap", "threshold"},
    ]
    normalized_groups = [
        set().union(*(normalized_words(word) for word in group))
        for group in synonym_groups
    ]
    active_groups = [group for group in normalized_groups if words & group]
    for group in active_groups:
        words |= group

    def split_sections(text, limit=3200):
        sections = re.split(r"(?=^#{1,3}\s+)", text, flags=re.MULTILINE)
        sections = [section.strip() for section in sections if section.strip()]
        if not sections:
            sections = [text.strip()]

        chunks = []
        for section in sections:
            match = re.match(r"^#{1,3}\s+([^\n]+)", section)
            heading = match.group(1).strip() if match else ""
            if len(section) <= limit:
                chunks.append((section, heading))
                continue

            sentences = re.split(r"(?<=[.!?])\s+|\n+", section)
            start = 0
            while start < len(sentences):
                size = 0
                end = start
                while end < len(sentences):
                    added = len(sentences[end]) + 1
                    if end > start and size + added > limit:
                        break
                    size += added
                    end += 1
                chunk = " ".join(sentences[start:end]).strip()
                if start and heading:
                    chunk = f"Section: {heading}\n{chunk}"
                if chunk:
                    chunks.append((chunk, heading))
                if end == len(sentences):
                    break
                start = max(start + 1, end - 2)
        return chunks

    candidates = []
    documents = [split_sections(text) for text in load_study_materials()]
    for document_index, chunks in enumerate(documents):
        for chunk_index, (chunk, heading) in enumerate(chunks):
            chunk_words = normalized_words(chunk)
            matches = words & chunk_words
            if not matches:
                continue
            original_matches = original_words & chunk_words
            synonym_matches = matches - original_words
            heading_matches = original_words & normalized_words(heading)
            semantic_groups = sum(bool(group & chunk_words) for group in active_groups)
            score = (
                len(original_matches) * 20
                + len(synonym_matches) * 6
                + len(heading_matches) * 50
                + semantic_groups * 12
            )
            candidates.append((score, document_index, chunk_index, chunk))

    candidates.sort(key=lambda item: (item[0], len(item[3])), reverse=True)
    results = []
    total_tokens = 0

    def add_passage(passage):
        nonlocal total_tokens
        if not passage or passage in results or total_tokens >= max_output_tokens:
            return

        remaining = max_output_tokens - total_tokens
        passage_tokens = encoding.encode(passage)
        if len(passage_tokens) > remaining:
            passage = encoding.decode(passage_tokens[:remaining]).strip()
            passage_tokens = encoding.encode(passage)

        if passage:
            results.append(passage)
            total_tokens += len(passage_tokens)

    if candidates:
        _, best_document, best_chunk, best_passage = candidates[0]
        add_passage(best_passage)

        distance = 1
        chunks = documents[best_document]
        while total_tokens < max_output_tokens and (
            best_chunk - distance >= 0 or best_chunk + distance < len(chunks)
        ):
            if best_chunk - distance >= 0:
                add_passage(chunks[best_chunk - distance][0])
            if total_tokens < max_output_tokens and best_chunk + distance < len(chunks):
                add_passage(chunks[best_chunk + distance][0])
            distance += 1

        for _, _, _, passage in candidates[1:]:
            if total_tokens >= max_output_tokens:
                break
            add_passage(passage)
    else:
        for chunks in documents:
            for passage, _ in chunks:
                if total_tokens >= max_output_tokens:
                    break
                add_passage(passage)

    return results

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
