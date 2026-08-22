from flask import Flask, request, jsonify
from datetime import datetime, timezone, timedelta
import heapq

app = Flask(__name__)


# ============================================================
# INTERNAL STATE
# ============================================================

transactions = {}          # txId -> record
expiry_heap = []           # (timestamp, txId) min-heap

graph = {}                 # graph[from_user][tx_id] = to_user
reverse_graph = {}         # reverse_graph[to_user][tx_id] = from_user

return_nodes = {}          # to_user -> count of active "return" edges into it

device_index = {}          # deviceId -> set(txId)
ip_index = {}               # ipAddress -> set(txId)

LOOKBACK = timedelta(hours=24)


# ============================================================
# TIME HELPERS
# ============================================================

def parse_timestamp(timestamp):
    if not timestamp:
        return None
    try:
        value = timestamp
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def saturate(x, k=1.0):
    """
    Smooth 0 -> 1 saturating curve. x=0 -> 0, grows toward 1 as x -> inf.
    k controls how quickly it saturates (smaller k = faster).
    """
    if x <= 0:
        return 0.0
    return x / (x + k)


# ============================================================
# GRAPH HELPERS
# ============================================================

def incoming_edges(user):
    """Active transactions whose toUserId == user."""
    edges = reverse_graph.get(user)
    if not edges:
        return []
    return [transactions[tx_id]["tx"] for tx_id in edges if tx_id in transactions]


def outgoing_edges(user):
    """Active transactions whose fromUserId == user."""
    edges = graph.get(user)
    if not edges:
        return []
    return [transactions[tx_id]["tx"] for tx_id in edges if tx_id in transactions]


def can_reach(start, target):
    """Is there an active directed path start -> ... -> target?"""
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


def structurally_related(u1, u2):
    """True if either node can reach the other along active edges."""
    return can_reach(u1, u2) or can_reach(u2, u1)


def count_paths(start, target, max_paths=10):
    """Count distinct directed paths start -> target, capped."""
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
                dfs(neighbour, visited | {neighbour})

    dfs(start, {start})
    return path_count


def get_all_ancestors(user, limit=500):
    """All users that can reach `user` along active edges."""
    ancestors = set()
    stack = [user]
    while stack:
        current = stack.pop()
        for sender, edges in graph.items():
            if sender in ancestors:
                continue
            if current in edges.values():
                ancestors.add(sender)
                stack.append(sender)
                if len(ancestors) >= limit:
                    return ancestors
    return ancestors


def chain_depth_into(user, visited=None, depth=0, max_depth=12):
    """
    Longest active incoming chain ending at `user`.
    Cycle-safe (returns can create cycles in the graph).
    """
    if visited is None:
        visited = set()
    if user in visited or depth >= max_depth:
        return depth
    visited.add(user)
    incoming = incoming_edges(user)
    if not incoming:
        return depth
    return max(
        chain_depth_into(tx["fromUserId"], visited, depth + 1, max_depth)
        for tx in incoming
    )


def fan_in_info(to_user, from_user):
    """
    Distinct existing senders into to_user (excluding from_user), and
    whether any of them shares upstream ancestry with from_user
    (a merge of structurally related branches, vs. coincidental fan-in).
    """
    incoming = incoming_edges(to_user)
    senders = {tx["fromUserId"] for tx in incoming if tx["fromUserId"] != from_user}
    if not senders:
        return 0, False
    from_ancestors = get_all_ancestors(from_user) | {from_user}
    related = False
    for s in senders:
        if s in from_ancestors or from_user in (get_all_ancestors(s) | {s}):
            related = True
            break
    return len(senders), related


# ============================================================
# STRUCTURAL SCORING (continuous, not fixed buckets)
# ============================================================

def determine_structure_score(from_user, to_user):
    """
    Returns (score, label). Score is graded within each structural
    category rather than a flat per-category constant, so scenarios
    of different severity within the same category (e.g. a 2-hop vs
    6-hop return) are distinguished.
    """
    if can_reach(to_user, from_user):
        paths = count_paths(to_user, from_user, max_paths=10)
        prior_returns = return_nodes.get(to_user, 0)
        base = 0.55 + 0.30 * saturate(max(paths - 1, 0), k=1.0)
        base += 0.10 * saturate(prior_returns, k=1.0)
        return min(base, 0.97), "return"

    fan_in, related = fan_in_info(to_user, from_user)
    if fan_in > 0:
        base = 0.25 + 0.20 * saturate(fan_in - 1, k=2.0)
        if related:
            base += 0.12
        return min(base, 0.65), "convergence"

    depth = chain_depth_into(from_user)
    if depth > 0:
        return 0.05 + 0.15 * saturate(depth - 1, k=3.0), "extension"

    return 0.0, "isolated"


# ============================================================
# IDENTITY SCORING (Phase 2)
# ============================================================

def collect_flow_identity(user, field, depth=0, visited=None, max_depth=8):
    """
    Walk backward along active incoming edges from `user`, collecting
    the set of values seen for `field` along the continuous incoming
    structure, plus whether any leg on that walk was missing the field.

    Returns (values_seen: set, any_missing: bool).
    An empty values_seen means there's no upstream identity evidence
    at all -- in that case we stay neutral (nothing to compare against).
    """
    if visited is None:
        visited = set()
    if user in visited or depth >= max_depth:
        return set(), False
    visited.add(user)

    values = set()
    missing = False

    for tx in incoming_edges(user):
        val = tx.get(field)
        if val:
            values.add(val)
        else:
            missing = True
        up_values, up_missing = collect_flow_identity(
            tx["fromUserId"], field, depth + 1, visited, max_depth
        )
        values |= up_values
        missing = missing or up_missing

    return values, missing


def disconnected_identity_score(tx, field, index, from_user, to_user):
    """
    Shared identity reused across structurally disconnected components.
    This is a distinct, weaker signal than in-flow consistency/shift --
    coincidence is possible, so it's weighted modestly and only counts
    occurrences that are genuinely not structurally related.
    """
    val = tx.get(field)
    if not val:
        return 0.0
    other_ids = index.get(val)
    if not other_ids:
        return 0.0

    disconnected_count = 0
    for other_id in other_ids:
        record = transactions.get(other_id)
        if record is None:
            continue
        o_tx = record["tx"]
        o_from, o_to = o_tx["fromUserId"], o_tx["toUserId"]
        related = any(
            structurally_related(a, b)
            for a in (from_user, to_user)
            for b in (o_from, o_to)
        )
        if not related:
            disconnected_count += 1

    if disconnected_count == 0:
        return 0.0
    return 0.06 * saturate(disconnected_count, k=2.0)


def identity_score(tx, from_user, to_user):
    """
    Combines identity evidence across deviceId and ipAddress as two
    independent dimensions (per Phase 2 spec), each contributing:
      - in-flow consistency / shift / drop signal (Examples 1-3)
      - cross-component reuse signal (Example 4)
    """
    total = 0.0

    for field, index in (("deviceId", device_index), ("ipAddress", ip_index)):
        val = tx.get(field)
        prior_values, _ = collect_flow_identity(from_user, field)

        if prior_values:
            if val:
                if prior_values == {val}:
                    pass  # fully consistent flow -- no anomaly (Example 1)
                elif val in prior_values:
                    total += 0.05  # upstream branch already mixed
                else:
                    total += 0.10  # identity shift / branch divergence (Examples 2 & 3)
            else:
                # identity dropped on a flow that was carrying one -- possible trail break
                total += 0.08 if len(prior_values) == 1 else 0.03

        total += disconnected_identity_score(tx, field, index, from_user, to_user)

    return min(total, 0.35)


def calculate_risk(tx):
    from_user = tx["fromUserId"]
    to_user = tx["toUserId"]

    structural, structure_label = determine_structure_score(from_user, to_user)
    identity = identity_score(tx, from_user, to_user)

    score = max(0.0, min(structural + identity, 1.0))
    return score, structure_label


# ============================================================
# EXPIRATION
# ============================================================

def remove_transaction(tx_id):
    record = transactions.pop(tx_id, None)
    if record is None:
        return

    tx = record["tx"]
    from_user = tx["fromUserId"]
    to_user = tx["toUserId"]

    if from_user in graph:
        graph[from_user].pop(tx_id, None)
        if not graph[from_user]:
            del graph[from_user]

    if to_user in reverse_graph:
        reverse_graph[to_user].pop(tx_id, None)
        if not reverse_graph[to_user]:
            del reverse_graph[to_user]

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

    if record.get("structure") == "return" and to_user in return_nodes:
        return_nodes[to_user] -= 1
        if return_nodes[to_user] <= 0:
            del return_nodes[to_user]


def expire_transactions(current_time):
    """
    Active condition: current_time - 24h < createdAt <= current_time.
    A transaction exactly 24h old is expired.
    """
    cutoff = (current_time - LOOKBACK).timestamp()

    while expiry_heap:
        timestamp_value, tx_id = expiry_heap[0]
        if timestamp_value > cutoff:
            break
        heapq.heappop(expiry_heap)

        record = transactions.get(tx_id)
        if record is None:
            continue
        if record["timestamp_value"] == timestamp_value:
            remove_transaction(tx_id)


# ============================================================
# ADD TRANSACTION TO STATE
# ============================================================

def add_transaction(tx, risk_score, structure, timestamp):
    tx_id = tx["txId"]
    from_user = tx["fromUserId"]
    to_user = tx["toUserId"]

    transactions[tx_id] = {
        "tx": tx,
        "riskScore": risk_score,
        "structure": structure,
        "timestamp_value": timestamp.timestamp(),
    }

    heapq.heappush(expiry_heap, (timestamp.timestamp(), tx_id))

    graph.setdefault(from_user, {})[tx_id] = to_user
    reverse_graph.setdefault(to_user, {})[tx_id] = from_user

    device_id = tx.get("deviceId")
    if device_id:
        device_index.setdefault(device_id, set()).add(tx_id)

    ip_address = tx.get("ipAddress")
    if ip_address:
        ip_index.setdefault(ip_address, set()).add(tx_id)

    if structure == "return":
        return_nodes[to_user] = return_nodes.get(to_user, 0) + 1


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/ghost-chains/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ============================================================
# STATE RESET
# ============================================================

@app.route("/ghost-chains/reset", methods=["POST"])
def reset():
    data = request.get_json(silent=True) or {}
    clear_transactions = data.get("clearTransactions", False)

    if clear_transactions:
        transactions.clear()
        expiry_heap.clear()
        graph.clear()
        reverse_graph.clear()
        return_nodes.clear()
        device_index.clear()
        ip_index.clear()

    return jsonify({"clearTransactions": clear_transactions})


# ============================================================
# TRANSACTION PROCESSING
# ============================================================

REQUIRED_FIELDS = ["txId", "fromUserId", "toUserId", "amount", "createdAt"]


@app.route("/ghost-chains/transactions", methods=["POST"])
def process_transactions():
    data = request.get_json(silent=True) or {}
    input_transactions = data.get("transactions", [])

    results = []

    # Process sequentially -- a bad/edge-case transaction anywhere in the
    # batch must NOT prevent the rest of the batch from being scored, since
    # the response must preserve input ordering and every valid transaction
    # still needs a score.
    for tx in input_transactions:
        tx_id = tx.get("txId")

        if any(field not in tx or tx[field] is None for field in REQUIRED_FIELDS):
            results.append({"txId": tx_id, "riskScore": 0.0})
            continue

        # Idempotency: txId is the authoritative identity. A repeat
        # submission -- identical or not -- returns the original score
        # and makes no state changes.
        if tx_id in transactions:
            previous = transactions[tx_id]
            results.append({"txId": tx_id, "riskScore": previous["riskScore"]})
            continue

        timestamp = parse_timestamp(tx.get("createdAt"))
        if timestamp is None:
            results.append({"txId": tx_id, "riskScore": 0.0})
            continue

        expire_transactions(timestamp)

        # Score using only state active *before* this transaction is added,
        # so a transaction never influences its own score.
        risk_score, structure = calculate_risk(tx)

        add_transaction(tx, risk_score, structure, timestamp)

        results.append({"txId": tx_id, "riskScore": risk_score})

    return jsonify({"transactions": results})


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)