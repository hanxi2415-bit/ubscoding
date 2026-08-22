"""
Tests for mcp_server.get_next_node()

This test file matches the real function signature:

    get_next_node(
        map_id,
        current,
        destination,
        visited,
        hops_left=None
    )

It avoids calling the real Graph API by temporarily replacing
mcp_server.get_graph() with a local fake graph provider.
"""

import mcp_server


def check(name, actual, expected):
    if actual == expected:
        print(f"PASS  {name}: {actual}")
    else:
        raise AssertionError(
            f"FAIL  {name}: expected {expected}, got {actual}"
        )


def run_with_graph(graph, **kwargs):
    """
    Temporarily replace mcp_server.get_graph so get_next_node()
    uses our local test graph instead of making an HTTP request.
    """
    original_get_graph = mcp_server.get_graph

    try:
        mcp_server.get_graph = lambda map_id: graph
        return mcp_server.get_next_node(**kwargs)
    finally:
        mcp_server.get_graph = original_get_graph


# ============================================================
# TEST 1 — edge weight + entry toll
#
# A -> B -> D = 4 + 1 + 3 + 2 = 10
# A -> C -> D = 2 + 9 + 2 + 2 = 15
#
# Expected first move: B
# ============================================================

graph1 = {
    "adjacency": {
        "A": {"B": 4.0, "C": 2.0},
        "B": {"D": 3.0},
        "C": {"D": 2.0},
        "D": {}
    },
    "tolls": {
        "A": 5.0,
        "B": 1.0,
        "C": 9.0,
        "D": 2.0
    }
}

result = run_with_graph(
    graph1,
    map_id="test1",
    current="A",
    destination="D",
    visited=["A"],
    hops_left=None
)
check("edge + toll calculation", result, "B")


# ============================================================
# TEST 2 — continue from B
# ============================================================

result = run_with_graph(
    graph1,
    map_id="test2",
    current="B",
    destination="D",
    visited=["A", "B"],
    hops_left=None
)
check("continue to destination", result, "D")


# ============================================================
# TEST 3 — hop constraint
#
# Cheap route:
# S -> X -> Y -> Z -> D
# cost 4, but needs 4 hops
#
# More expensive:
# S -> B -> D
# cost 6, only 2 hops
#
# With 2 hops remaining, MUST choose B.
# ============================================================

graph2 = {
    "adjacency": {
        "S": {"X": 1.0, "B": 3.0},
        "X": {"Y": 1.0},
        "Y": {"Z": 1.0},
        "Z": {"D": 1.0},
        "B": {"D": 3.0},
        "D": {}
    },
    "tolls": {
        "S": 0.0,
        "X": 0.0,
        "Y": 0.0,
        "Z": 0.0,
        "B": 0.0,
        "D": 0.0
    }
}

result = run_with_graph(
    graph2,
    map_id="test3",
    current="S",
    destination="D",
    visited=["S"],
    hops_left=2
)
check("hop limit", result, "B")


# ============================================================
# TEST 4 — without hop limit, cheaper longer route wins
# Expected: X
# ============================================================

result = run_with_graph(
    graph2,
    map_id="test4",
    current="S",
    destination="D",
    visited=["S"],
    hops_left=None
)
check("no hop limit", result, "X")


# ============================================================
# TEST 5 — visited node must never be revisited
#
# From C, B is cheap but already visited.
# Only legal move toward D is D.
# ============================================================

graph3 = {
    "adjacency": {
        "A": {"B": 1.0},
        "B": {"C": 1.0},
        "C": {"B": 0.1, "D": 5.0},
        "D": {}
    },
    "tolls": {
        "A": 0.0,
        "B": 0.0,
        "C": 0.0,
        "D": 0.0
    }
}

result = run_with_graph(
    graph3,
    map_id="test5",
    current="C",
    destination="D",
    visited=["A", "B", "C"],
    hops_left=None
)
check("visited nodes excluded", result, "D")


# ============================================================
# TEST 6 — directed edges
#
# B -> A exists, but A -> B does not.
# From A, correct route starts with C.
# ============================================================

graph4 = {
    "adjacency": {
        "A": {"C": 2.0},
        "B": {"A": 0.1, "D": 0.1},
        "C": {"D": 2.0},
        "D": {}
    },
    "tolls": {
        "A": 0.0,
        "B": 0.0,
        "C": 0.0,
        "D": 0.0
    }
}

result = run_with_graph(
    graph4,
    map_id="test6",
    current="A",
    destination="D",
    visited=["A"],
    hops_left=None
)
check("directed edges respected", result, "C")


# ============================================================
# TEST 7 — one hop left
#
# P -> Q -> D is cheaper overall, but needs 2 hops.
# With one hop left, must go directly to D.
# ============================================================

graph5 = {
    "adjacency": {
        "P": {"Q": 0.1, "D": 5.0},
        "Q": {"D": 0.1},
        "D": {}
    },
    "tolls": {
        "P": 0.0,
        "Q": 0.0,
        "D": 0.0
    }
}

result = run_with_graph(
    graph5,
    map_id="test7",
    current="P",
    destination="D",
    visited=["P"],
    hops_left=1
)
check("one hop left", result, "D")


# ============================================================
# TEST 8 — no legal route within hop limit should fail
# ============================================================

try:
    run_with_graph(
        graph2,
        map_id="test8",
        current="S",
        destination="D",
        visited=["S", "B"],
        hops_left=2
    )
except ValueError:
    print("PASS  impossible within hop limit raises ValueError")
else:
    raise AssertionError(
        "FAIL  expected ValueError when no route fits remaining hops"
    )


print("\nAll Part 2 tests passed.")
