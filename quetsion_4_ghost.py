from flask import Flask, request, jsonify

app = Flask(__name__)


# ============================================================
# INTERNAL STATE
# ============================================================

transactions_seen = []
graph = {}
return_nodes = {}


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
    data = request.get_json()

    clear_transactions = data.get("clearTransactions", False)

    if clear_transactions:
        transactions_seen.clear()
        graph.clear()
        return_nodes.clear()

    return jsonify({
        "clearTransactions": clear_transactions
    })


# ============================================================
# GRAPH HELPERS
# ============================================================

def can_reach(start, target):
    """Check whether start can reach target."""

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


def get_all_ancestors(user):
    """Find every node that can reach user."""

    visited = set()

    def visit(current):
        for sender, recipients in graph.items():

            if current in recipients and sender not in visited:
                visited.add(sender)
                visit(sender)

    visit(user)

    return visited


def creates_return(from_user, to_user):
    """Check whether this transaction creates a cycle."""

    return can_reach(to_user, from_user)


def creates_convergence(from_user, to_user):
    """Check whether this transaction creates convergence."""

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


# ============================================================
# RISK CALCULATION
# ============================================================

def calculate_risk(tx):

    from_user = tx["fromUserId"]
    to_user = tx["toUserId"]

    # Multi-loop
    if creates_return(from_user, to_user):

        previous_returns = return_nodes.get(to_user, 0)

        if previous_returns >= 1:
            return 0.9

        # First return
        return 0.6

    # Convergence
    if creates_convergence(from_user, to_user):
        return 0.3

    # Extension
    if from_user in graph:
        return 0.1

    # Isolated
    return 0.0


# ============================================================
# TRANSACTION PROCESSING
# ============================================================

@app.route("/ghost-chains/transactions", methods=["POST"])
def process_transactions():

    data = request.get_json()

    transactions = data.get("transactions", [])

    results = []

    # Process transactions sequentially
    for tx in transactions:

        # Calculate risk BEFORE updating state
        risk_score = calculate_risk(tx)

        # Store transaction
        transactions_seen.append(tx)

        from_user = tx["fromUserId"]
        to_user = tx["toUserId"]

        # Remember return paths
        if creates_return(from_user, to_user):

            return_nodes[to_user] = (
                return_nodes.get(to_user, 0) + 1
            )

        # Update graph
        if from_user not in graph:
            graph[from_user] = []

        graph[from_user].append(to_user)

        # Build response
        results.append({
            "txId": tx["txId"],
            "riskScore": risk_score
        })

    return jsonify({
        "transactions": results
    })


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080
    )