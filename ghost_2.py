from flask import Flask, request, jsonify
from datetime import datetime, timedelta, timezone
import heapq
import json

app = Flask(__name__)


# ============================================================
# INTERNAL STATE
# ============================================================

# txId -> stored transaction record
transactions = {}

# Min-heap of (createdAt timestamp, txId)
# Used to efficiently find expired transactions.
expiry_heap = []

# Directed graph:
#
# graph[from_user][tx_id] = to_user
#
# Keeping tx_id on each edge allows us to remove
# individual expired transactions.
graph = {}

# Number of return transactions that have occurred
# toward each destination while those transactions
# are still inside the active window.
return_nodes = {}

# Identity indexes.
#
# device_index[device_id] = set of txIds
# ip_index[ip_address] = set of txIds
device_index = {}
ip_index = {}


LOOKBACK = timedelta(hours=24)


# ============================================================
# TIME HELPERS
# ============================================================

def parse_timestamp(timestamp):
    """
    Convert ISO 8601 timestamp into a timezone-aware datetime.
    """

    if not timestamp:
        return None

    try:
        value = timestamp

        # Handle timestamps ending in Z
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        dt = datetime.fromisoformat(value)

        # Make naive timestamps UTC-aware if necessary
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


# ============================================================
# GRAPH HELPERS
# ============================================================

def can_reach(start, target):
    """
    Check whether there is an active directed path
    from start to target.
    """

    if start == target:
        return True

    visited = set()
    stack = [start]

    while stack:

        current = stack.pop()

        if current == target:
            return True

        if current in visited:
            continue

        visited.add(current)

        for neighbour in graph.get(current, {}).values():

            if neighbour not in visited:
                stack.append(neighbour)

    return False


def count_paths(start, target, max_paths=10):
    """
    Count distinct directed paths from start to target.

    This is capped to avoid excessive computation.
    """

    if start == target:
        return 1

    path_count = 0

    def dfs(current, visited):

        nonlocal path_count

        if path_count >= max_paths:
            return

        for neighbour in graph.get(current, {}).values():

            if neighbour == target:
                path_count += 1

                if path_count >= max_paths:
                    return

            elif neighbour not in visited:

                dfs(
                    neighbour,
                    visited | {neighbour}
                )

    dfs(start, {start})

    return path_count


def get_all_ancestors(user):
    """
    Find all users that can reach `user`.
    """

    ancestors = set()
    stack = [user]

    while stack:

        current = stack.pop()

        for sender, edges in graph.items():

            if current in edges.values() and sender not in ancestors:

                ancestors.add(sender)
                stack.append(sender)

    return ancestors


# ============================================================
# STRUCTURAL SIGNALS
# ============================================================

def creates_return(from_user, to_user):
    """
    A transaction creates a return if there is already
    an active path from the receiver back to the sender.

    Example:

        A -> B -> C
        C -> A

    C -> A is a return.
    """

    return can_reach(to_user, from_user)


def creates_convergence(from_user, to_user):
    """
    Detect whether the destination is already reachable
    from another structural path.

    This is a deliberately conservative convergence signal.
    """

    # Find existing senders into the destination.
    existing_senders = set()

    for sender, edges in graph.items():

        if to_user in edges.values():
            existing_senders.add(sender)

    if not existing_senders:
        return False

    # Find nodes upstream of the new sender.
    new_branch = get_all_ancestors(from_user)
    new_branch.add(from_user)

    for existing_sender in existing_senders:

        existing_branch = get_all_ancestors(existing_sender)
        existing_branch.add(existing_sender)

        # If the two branches have some upstream relationship,
        # they are structurally connected.
        if new_branch.intersection(existing_branch):
            return True

    return False


def determine_structure(from_user, to_user):
    """
    Determine the strongest structural signal for a new edge.
    """

    # A return is stronger than ordinary convergence.
    if creates_return(from_user, to_user):

        previous_returns = return_nodes.get(to_user, 0)

        if previous_returns >= 1:
            return "multi_loop"

        return "return"

    if creates_convergence(from_user, to_user):
        return "convergence"

    if from_user in graph and graph[from_user]:
        return "extension"

    return "isolated"


# ============================================================
# IDENTITY SIGNALS
# ============================================================

def has_shared_device(tx):
    """
    Check whether this device has appeared previously
    in the active transaction state.
    """

    device_id = tx.get("deviceId")

    if not device_id:
        return False

    return (
        device_id in device_index
        and len(device_index[device_id]) > 0
    )


def has_shared_ip(tx):
    """
    Check whether this IP address has appeared previously
    in the active transaction state.
    """

    ip_address = tx.get("ipAddress")

    if not ip_address:
        return False

    return (
        ip_address in ip_index
        and len(ip_index[ip_address]) > 0
    )


def device_changes_in_flow(tx):
    """
    Detect whether the same structural flow has previously
    used another device.

    This is a lightweight identity-shift signal.
    """

    device_id = tx.get("deviceId")

    if not device_id:
        return False

    from_user = tx["fromUserId"]

    previous_devices = set()

    for old_tx in transactions.values():

        if old_tx["toUserId"] == from_user:

            old_device = old_tx.get("deviceId")

            if old_device:
                previous_devices.add(old_device)

    if not previous_devices:
        return False

    return device_id not in previous_devices


# ============================================================
# EXPIRATION
# ============================================================

def remove_transaction(tx_id):
    """
    Remove one transaction from every active state structure.
    """

    record = transactions.pop(tx_id, None)

    if record is None:
        return

    tx = record["tx"]

    from_user = tx["fromUserId"]

    # Remove from graph
    if from_user in graph:

        graph[from_user].pop(tx_id, None)

        if not graph[from_user]:
            del graph[from_user]

    # Remove identity indexes
    device_id = tx.get("deviceId")

    if device_id and device_id in device_index:

        device_index[device_id].discard(tx_id)

        if not device_index[device_id]:
            del device_index[device_id]

    ip_address = tx.get("ipAddress")

    if ip_address and ip_address in ip_index:

        ip_index[ip_address].discard(tx_id)

        if not ip_index[ip_address]:
            del ip_index[ip_address]

    # Remove return count
    if record.get("structure") in ("return", "multi_loop"):

        to_user = tx["toUserId"]

        if to_user in return_nodes:

            return_nodes[to_user] -= 1

            if return_nodes[to_user] <= 0:
                del return_nodes[to_user]


def expire_transactions(current_time):
    """
    Remove all transactions outside the active 24-hour window.

    Active condition:

        current_time - 24 hours < createdAt <= current_time

    Therefore a transaction exactly 24 hours old is expired.
    """

    cutoff = current_time - LOOKBACK

    while expiry_heap:

        timestamp_value, tx_id = expiry_heap[0]

        if timestamp_value > cutoff:
            break

        heapq.heappop(expiry_heap)

        # It may already have been removed.
        record = transactions.get(tx_id)

        if record is None:
            continue

        # Only remove if the heap entry still corresponds
        # to the current transaction.
        if record["timestamp_value"] == timestamp_value:
            remove_transaction(tx_id)


# ============================================================
# RISK CALCULATION
# ============================================================

STRUCTURAL_SCORES = {
    "isolated": 0.00,
    "extension": 0.10,
    "convergence": 0.30,
    "return": 0.60,
    "multi_loop": 0.80,
}


def calculate_risk(tx):
    """
    Calculate relative suspiciousness using only the
    currently active state.
    """

    from_user = tx["fromUserId"]
    to_user = tx["toUserId"]

    # --------------------------------------------------------
    # 1. Structural signal
    # --------------------------------------------------------

    structure = determine_structure(
        from_user,
        to_user
    )

    score = STRUCTURAL_SCORES[structure]

    # --------------------------------------------------------
    # 2. Identity signals
    # --------------------------------------------------------

    # Shared identity can provide additional evidence,
    # but should not dominate strong structural signals.
    if has_shared_device(tx):
        score += 0.03

    if has_shared_ip(tx):
        score += 0.05

    # Device shift inside a structurally continuous flow.
    if device_changes_in_flow(tx):
        score += 0.05

    # --------------------------------------------------------
    # 3. Clamp
    # --------------------------------------------------------

    score = max(0.0, min(score, 1.0))

    return score, structure


# ============================================================
# ADD TRANSACTION TO STATE
# ============================================================

def add_transaction(tx, risk_score, structure, timestamp):
    """
    Add a newly scored transaction to active state.
    """

    tx_id = tx["txId"]
    from_user = tx["fromUserId"]

    # Store transaction
    transactions[tx_id] = {
        "tx": tx,
        "riskScore": risk_score,
        "structure": structure,
        "timestamp_value": timestamp.timestamp()
    }

    # Add to expiration heap
    heapq.heappush(
        expiry_heap,
        (
            timestamp.timestamp(),
            tx_id
        )
    )

    # Add graph edge
    if from_user not in graph:
        graph[from_user] = {}

    graph[from_user][tx_id] = tx["toUserId"]

    # Add device index
    device_id = tx.get("deviceId")

    if device_id:

        if device_id not in device_index:
            device_index[device_id] = set()

        device_index[device_id].add(tx_id)

    # Add IP index
    ip_address = tx.get("ipAddress")

    if ip_address:

        if ip_address not in ip_index:
            ip_index[ip_address] = set()

        ip_index[ip_address].add(tx_id)

    # Update return count
    if structure in ("return", "multi_loop"):

        to_user = tx["toUserId"]

        return_nodes[to_user] = (
            return_nodes.get(to_user, 0) + 1
        )


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

    data = request.get_json(silent=True) or {}

    clear_transactions = data.get(
        "clearTransactions",
        False
    )

    if clear_transactions:

        transactions.clear()
        expiry_heap.clear()
        graph.clear()
        return_nodes.clear()
        device_index.clear()
        ip_index.clear()

    return jsonify({
        "clearTransactions": clear_transactions
    })


# ============================================================
# TRANSACTION PROCESSING
# ============================================================

@app.route("/ghost-chains/transactions", methods=["POST"])
def process_transactions():

    data = request.get_json(silent=True) or {}

    input_transactions = data.get(
        "transactions",
        []
    )

    results = []

    # --------------------------------------------------------
    # Process sequentially.
    #
    # This is important because transactions earlier in
    # the same request must influence later transactions.
    # --------------------------------------------------------

    for tx in input_transactions:

        tx_id = tx.get("txId")

        # Basic required-field validation
        required_fields = [
            "txId",
            "fromUserId",
            "toUserId",
            "amount",
            "createdAt"
        ]

        if any(field not in tx for field in required_fields):

            return jsonify({
                "error": "Transaction missing required field"
            }), 400

        # ----------------------------------------------------
        # Idempotency
        # ----------------------------------------------------

        if tx_id in transactions:

            previous = transactions[tx_id]

            # Identical transaction:
            # return original score and DO NOT change state.
            if previous["tx"] == tx:

                results.append({
                    "txId": tx_id,
                    "riskScore": previous["riskScore"]
                })

                continue

            # Same ID but different payload.
            return jsonify({
                "error": f"Conflicting payload for txId {tx_id}"
            }), 400

        # ----------------------------------------------------
        # Parse timestamp
        # ----------------------------------------------------

        timestamp = parse_timestamp(
            tx.get("createdAt")
        )

        if timestamp is None:

            return jsonify({
                "error": f"Invalid createdAt for txId {tx_id}"
            }), 400

        # ----------------------------------------------------
        # Expire old state BEFORE scoring this transaction.
        # ----------------------------------------------------

        expire_transactions(timestamp)

        # ----------------------------------------------------
        # Calculate score BEFORE adding the transaction.
        #
        # Therefore the transaction cannot influence
        # its own risk score.
        # ----------------------------------------------------

        risk_score, structure = calculate_risk(tx)

        # ----------------------------------------------------
        # Add transaction to active state.
        # ----------------------------------------------------

        add_transaction(
            tx,
            risk_score,
            structure,
            timestamp
        )

        # ----------------------------------------------------
        # Response
        # ----------------------------------------------------

        results.append({
            "txId": tx_id,
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