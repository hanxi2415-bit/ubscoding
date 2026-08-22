from flask import Flask, request, jsonify

app = Flask(__name__)

PRESENT_YEAR = 2037


def solve_case(case):
    energy = case["energy"]
    capital = case["capital"]
    timeline = case["timeline"]

    # Farthest year reachable: round trip to year Y costs 2*(2037-Y), and a
    # single ascending sweep visits every year in between for free.
    max_depth = energy // 2
    min_year = PRESENT_YEAR - max_depth

    # stock -> list of (year, price, qty), restricted to reachable years
    by_stock = {}
    for year_str, stocks in timeline.items():
        year = int(year_str)
        if year < min_year or year > PRESENT_YEAR:
            continue
        for stock, info in stocks.items():
            by_stock.setdefault(stock, []).append((year, info["price"], info["qty"]))

    # Build candidate trades: for each (stock, year) with stock available,
    # find the best price this stock reaches at any later reachable year.
    candidates = []
    for stock, entries in by_stock.items():
        entries.sort(key=lambda e: e[0])
        n = len(entries)
        best_price_after = [None] * n
        best_year_after = [None] * n
        running_price, running_year = None, None
        for i in range(n - 1, -1, -1):
            best_price_after[i] = running_price
            best_year_after[i] = running_year
            year_i, price_i, _ = entries[i]
            if running_price is None or price_i > running_price:
                running_price, running_year = price_i, year_i

        for i, (year, price, qty) in enumerate(entries):
            sell_price = best_price_after[i]
            sell_year = best_year_after[i]
            if qty <= 0 or sell_price is None or sell_price <= price:
                continue
            candidates.append({
                "stock": stock,
                "buy_year": year,
                "sell_year": sell_year,
                "price": price,
                "qty": qty,
                "ratio": (sell_price - price) / price,
            })

    # Greedy fractional knapsack: best profit-per-dollar first, until
    # capital runs out. Optimal for the shared, fungible capital pool.
    candidates.sort(key=lambda c: c["ratio"], reverse=True)

    remaining = capital
    buys_by_year = {}
    sells_by_year = {}
    for c in candidates:
        if remaining <= 0:
            break
        affordable = remaining // c["price"]
        take = min(c["qty"], affordable)
        if take <= 0:
            continue
        remaining -= take * c["price"]
        buys_by_year.setdefault(c["buy_year"], {}).setdefault(c["stock"], 0)
        buys_by_year[c["buy_year"]][c["stock"]] += take
        sells_by_year.setdefault(c["sell_year"], {}).setdefault(c["stock"], 0)
        sells_by_year[c["sell_year"]][c["stock"]] += take

    # Replay chronologically: sells before buys at each stop, in case a
    # sell's proceeds are needed to afford a buy at the same year.
    used_years = sorted(set(buys_by_year) | set(sells_by_year))
    intermediate_years = [y for y in used_years if y != PRESENT_YEAR]

    actions = []
    current = PRESENT_YEAR
    for y in intermediate_years:
        actions.append(f"j-{current}-{y}")
        for stock, qty in sells_by_year.get(y, {}).items():
            actions.append(f"s-{stock}-{qty}")
        for stock, qty in buys_by_year.get(y, {}).items():
            actions.append(f"b-{stock}-{qty}")
        current = y

    if current != PRESENT_YEAR:
        actions.append(f"j-{current}-{PRESENT_YEAR}")
        current = PRESENT_YEAR

    for stock, qty in sells_by_year.get(PRESENT_YEAR, {}).items():
        actions.append(f"s-{stock}-{qty}")

    return actions


@app.route("/stonks", methods=["POST"])
def stonks():
    cases = request.get_json()
    return jsonify([solve_case(case) for case in cases])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)