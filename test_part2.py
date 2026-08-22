"""
Part 2 local tests

How to use:
1. Put this file in the same folder as your MCP server file.
2. Change the import line below if your server file is not named main.py.
3. Your server should expose a pure helper with this signature:

   find_next_node(
       graph,
       tolls,
       current,
       destination,
       visited,
       hops_left
   ) -> str

   Convention used by these tests:
   - hops_left = 0 means "no hop limit".
   - Cost of moving u -> v is edge_weight(u,v) + toll[v].
   - A returned node must be an outgoing neighbor of current.
   - Already visited nodes must not be revisited.
"""

# CHANGE ONLY THIS LINE if your server file has a different name.
from mcp_server import get_next_node


def check(name, actual, expected):
    if actual == expected:
        print(f"PASS  {name}: {actual}")
    else:
        print(f"FAIL  {name}: expected {expected}, got {actual}")
        raise AssertionError(name)


# ------------------------------------------------------------
# TEST 1: Official-style example
#
# A -> B -> D = 4 + toll(B=1) + 3 + toll(D=2) = 10
# A -> C -> D = 2 + toll(C=9) + 2 + toll(D=2) = 15
# Correct first move: B
# ------------------------------------------------------------

graph1 = {
    "A": {"B": 4.0, "C": 2.0},
    "B": {"D": 3.0},
    "C": {"D": 2.0},
    "D": {}
}

tolls1 = {
    "A": 5.0,
    "B": 1.0,
    "C": 9.0,
    "D": 2.0
}

result = get_next_node(
    graph=graph1,
    tolls=tolls1,
    current="A",
    destination="D",
    visited=["A"],
    hops_left=0
)
check("edge + toll calculation", result, "B")


# ------------------------------------------------------------
# TEST 2: Continue from B
# Correct next node must be D.
# ------------------------------------------------------------

result = get_next_node(
    graph=graph1,
    tolls=tolls1,
    current="B",
    destination="D",
    visited=["A", "B"],
    hops_left=0
)
check("continue to destination", result, "D")


# ------------------------------------------------------------
# TEST 3: Hop constraint
#
# Cheap route:
# S -> X -> Y -> Z -> D = 4 hops, total cost 4
#
# More expensive route:
# S -> B -> D = 2 hops, total cost 6
#
# With only 2 hops left, it MUST choose B.
# ------------------------------------------------------------

graph2 = {
    "S": {"X": 1.0, "B": 3.0},
    "X": {"Y": 1.0},
    "Y": {"Z": 1.0},
    "Z": {"D": 1.0},
    "B": {"D": 3.0},
    "D": {}
}

tolls2 = {node: 0.0 for node in graph2}

result = get_next_node(
    graph=graph2,
    tolls=tolls2,
    current="S",
    destination="D",
    visited=["S"],
    hops_left=2
)
check("hop limit", result, "B")


# ------------------------------------------------------------
# TEST 4: Without a hop limit, choose the cheaper longer route.
# Correct first node: X.
# ------------------------------------------------------------

result = get_next_node(
    graph=graph2,
    tolls=tolls2,
    current="S",
    destination="D",
    visited=["S"],
    hops_left=0
)
check("no hop limit", result, "X")


# ------------------------------------------------------------
# TEST 5: Do not revisit an already visited node.
#
# From C, B would be cheapest but B has already been visited.
# C -> D is therefore the only legal choice.
# ------------------------------------------------------------

graph3 = {
    "A": {"B": 1.0},
    "B": {"C": 1.0},
    "C": {"B": 0.1, "D": 5.0},
    "D": {}
}

tolls3 = {
    "A": 0.0,
    "B": 0.0,
    "C": 0.0,
    "D": 0.0
}

result = get_next_node(
    graph=graph3,
    tolls=tolls3,
    current="C",
    destination="D",
    visited=["A", "B", "C"],
    hops_left=0
)
check("visited nodes excluded", result, "D")


# ------------------------------------------------------------
# TEST 6: Directed graph
#
# B -> A exists, but A -> B does NOT.
# From A, the only valid route to D starts with C.
# ------------------------------------------------------------

graph4 = {
    "A": {"C": 2.0},
    "B": {"A": 0.1, "D": 0.1},
    "C": {"D": 2.0},
    "D": {}
}

tolls4 = {
    "A": 0.0,
    "B": 0.0,
    "C": 0.0,
    "D": 0.0
}

result = get_next_node(
    graph=graph4,
    tolls=tolls4,
    current="A",
    destination="D",
    visited=["A"],
    hops_left=0
)
check("directed edges respected", result, "C")


# ------------------------------------------------------------
# TEST 7: One hop left means destination must be selected now.
# ------------------------------------------------------------

graph5 = {
    "P": {"Q": 0.1, "D": 5.0},
    "Q": {"D": 0.1},
    "D": {}
}

tolls5 = {
    "P": 0.0,
    "Q": 0.0,
    "D": 0.0
}

result = get_next_node(
    graph=graph5,
    tolls=tolls5,
    current="P",
    destination="D",
    visited=["P"],
    hops_left=1
)
check("one hop left", result, "D")


print("\nAll Part 2 tests passed.")
