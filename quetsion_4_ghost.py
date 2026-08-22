from flask import Flask, request, jsonify

app = Flask(__name__)


# ============================================================
# INTERNAL STATE
# ============================================================

# Stores transactions that have already been processed.
# We will use this later to build the transaction graph.
transactions_seen = []

# Graph structure we will use later for detecting:
# - extensions
# - convergence
# - returns
# - multi-loops
graph = {}


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/ghost-chains/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok"
    })


# ============================================================
# STATE RESET
# ============================================================

@app.route("/ghost-chains/reset", methods=["POST"])
def reset():
    global transactions_seen, graph

    data = request.get_json()

    clear_transactions = data.get("clearTransactions", False)

    if clear_transactions:
        # Clear all previously stored transactions
        transactions_seen.clear()

        # Clear the transaction graph
        graph.clear()

    return jsonify({
        "clearTransactions": clear_transactions
    })


# ============================================================
# RISK CALCULATION
# ============================================================
def get_all_ancestors(user):
    """
    Find every node that can reach `user`.
    """

    visited = set()

    def visit(current):

        for sender, recipients in graph.items():

            if current in recipients and sender not in visited:
                visited.add(sender)
                visit(sender)

    visit(user)

    return visited


def creates_convergence(from_user, to_user):
    """
    Check whether adding from_user -> to_user
    creates convergence.
    """

    existing_senders = set()

    for sender, recipients in graph.items():

        if to_user in recipients:
            existing_senders.add(sender)

    if not existing_senders:
        return False

    new_sender_ancestors = get_all_ancestors(from_user)
    new_sender_ancestors.add(from_user)

    for existing_sender in existing_senders:

        existing_sender_ancestors = get_all_ancestors(
            existing_sender
        )
        existing_sender_ancestors.add(existing_sender)

        if new_sender_ancestors.intersection(
            existing_sender_ancestors
        ):
            return True

    return False


def can_reach(start, target):
    """
    Check whether `start` can reach `target`
    through the existing transaction graph.
    """

    visited = set()
    stack = [start]

    while stack:

        current = stack.pop()

        if current == target:
            return True

        if current in visited:
            continue

        visited.add(current)

        for neighbour in graph.get(current, []):
            if neighbour not in visited:
                stack.append(neighbour)

    return False

def creates_return(from_user, to_user):
    """
    Check whether adding from_user -> to_user
    creates a return/cycle.
    """

    return can_reach(to_user, from_user)


def count_paths(start, target, max_paths=10):
    """
    Count the number of distinct paths from start to target
    in the existing graph.

    max_paths prevents excessive searching in a large graph.
    """

    path_count = 0

    def dfs(current, visited):

        nonlocal path_count

        if path_count >= max_paths:
            return

        if current == target:
            path_count += 1
            return

        for neighbour in graph.get(current, []):

            if neighbour not in visited:

                dfs(
                    neighbour,
                    visited | {neighbour}
                )

    dfs(start, {start})

    return path_count

return_nodes = {}

def calculate_risk(tx):

    from_user = tx["fromUserId"]
    to_user = tx["toUserId"]

    # --------------------------------
    # 1. Is this a return?
    # --------------------------------

    if creates_return(from_user, to_user):

        # How many return paths have
        # already reached this destination?
        previous_returns = return_nodes.get(to_user, 0)

        if previous_returns >= 1:
            # This is another return to the
            # same node -> multi-loop
            return 0.9

        return 0.6

    # --------------------------------
    # 2. Convergence
    # --------------------------------

    if creates_convergence(from_user, to_user):
        return 0.3

    # --------------------------------
    # 3. Extension
    # --------------------------------

    if from_user in graph:
        return 0.1

    # --------------------------------
    # 4. Isolated
    # --------------------------------

    return 0.0


# ============================================================
# TRANSACTION PROCESSING
# ============================================================

@app.route("/ghost-chains/transactions", methods=["POST"])
def process_transactions():

    data = request.get_json()

    transactions = data.get("transactions", [])

    results = []

    # IMPORTANT:
    # Transactions must be processed sequentially.
    for tx in transactions:

        # Required fields
        tx_id = tx["txId"]
        from_user = tx["fromUserId"]
        to_user = tx["toUserId"]
        amount = tx["amount"]
        created_at = tx["createdAt"]

        # Optional fields
        ip_address = tx.get("ipAddress")
        device_id = tx.get("deviceId")

        risk_score = calculate_risk(tx)

        transactions_seen.append(tx)

        # If this transaction creates a return,
        # remember that the destination has received
        # a return path.
        if creates_return(
            tx["fromUserId"],
            tx["toUserId"]
        ):
            to_user = tx["toUserId"]

            return_nodes[to_user] = (
                return_nodes.get(to_user, 0) + 1
            )

        # Update graph
        from_user = tx["fromUserId"]
        to_user = tx["toUserId"]

        if from_user not in graph:
            graph[from_user] = []

        graph[from_user].append(to_user)

        # ----------------------------------------
        # Add result
        # ----------------------------------------

        results.append({
            "txId": tx_id,
            "riskScore": risk_score
        })

    # Preserve input ordering
    return jsonify({
        "transactions": results
    })


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":
    app.run()