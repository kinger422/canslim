"""Orchestrates one 5%-risk, 15-minute directional Kalshi trade end to end:

  size -> enter (verify fill) -> poll market, adapt stop/target -> flatten (verify flat)

Usage:
  python run_trade.py TICKER SIDE [--demo] [--window-seconds 900] [--poll-seconds 3] [--dry-run]

  TICKER      Kalshi market ticker, e.g. "KXUSDJPY-25JUL26-T150"
  SIDE        "yes" or "no" -- the direction you believe wins

--dry-run prints every decision without placing real orders (recommended for a first pass
even against --demo, since it also verifies the sizing/stop/target math before any order fires).
"""
import argparse
import fcntl
import os
import sys
import time
import urllib.error
from datetime import datetime

from kalshi_client import KalshiClient
from position_sizer import size_trade
from stop_target import TradeState, StopTargetConfig

CLOSE_SAFETY_BUFFER_S = 15.0    # stop managing this long before the market's close_time
MIN_VIABLE_WINDOW_S = 60.0      # don't enter with less than this left to trade
ENTRY_FILL_TIMEOUT_S = 12.0     # how long the entry limit may rest before we cancel the remainder
EXIT_REPRICE_AFTER_S = 4.0      # how long an exit limit may rest before cancel + re-place lower
EXIT_MAX_ROUNDS = 8             # cancel/re-place rounds before giving up loudly
MAX_CONSECUTIVE_POLL_FAILURES = 10
LOCK_PATH = os.path.expanduser("~/.kalshi_5pct_trade.lock")


def valid_quote(v, lo=1, hi=99):
    return isinstance(v, (int, float)) and lo <= v <= hi


def parse_close_ts(market):
    raw = market.get("close_time")
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()


def side_bid(market, side):
    return market.get("yes_bid") if side == "yes" else market.get("no_bid")


def depth_cap(client, ticker, side, entry_price, band_cents=2):
    """Contracts available to take within [ask, ask+band]. Buying YES lifts resting NO
    bids at 100 - yes_price (and vice versa), so depth comes from the opposite book."""
    try:
        book = client.get_orderbook(ticker)
    except Exception as e:
        print(f"[warn] orderbook unavailable ({e}); skipping depth cap")
        return None
    opposite = book.get("no" if side == "yes" else "yes") or []
    total = 0
    for level in opposite:
        price, qty = level[0], level[1]
        implied_ask = 100 - price
        if entry_price <= implied_ask <= entry_price + band_cents:
            total += qty
    return total if total > 0 else None


def wait_for_fill(client, order_id, timeout_s, poll_s=1.0):
    """Poll an order until it stops resting or the timeout passes. Returns (filled, status)."""
    deadline = time.time() + timeout_s
    while True:
        order = client.get_order(order_id)
        filled = order.get("count", 0) - order.get("remaining_count", 0)
        status = order.get("status", "")
        if status in ("executed", "canceled") or order.get("remaining_count", 0) == 0:
            return filled, status
        if time.time() >= deadline:
            return filled, status
        time.sleep(poll_s)


def flatten(client, ticker, side, count, base_order_id, dry_run, aggressive):
    """Sell `count` contracts and don't stop until the position is verifiably flat
    (or rounds are exhausted, in which case scream). A stop-loss that fires one resting
    limit order and walks away is not a stop-loss."""
    remaining = count
    for attempt in range(EXIT_MAX_ROUNDS):
        market = client.get_market(ticker)
        bid = side_bid(market, side)
        if not valid_quote(bid):
            print(f"[warn] no valid bid (got {bid!r}); retrying")
            time.sleep(1.0)
            continue
        # on stop exits, price below the bid so the order crosses even if the book moves;
        # Kalshi fills at the best available price, not the limit
        discount = (2 + attempt) if aggressive else attempt
        price = max(1, int(bid) - discount)
        if dry_run:
            print(f"[dry-run] would SELL {remaining} {side} @ {price}c (bid {bid}c, attempt {attempt + 1})")
            return True
        resp = client.place_order(ticker, side, "sell", remaining, price, f"{base_order_id}-x{attempt}")
        order_id = resp["order"]["order_id"]
        filled, status = wait_for_fill(client, order_id, EXIT_REPRICE_AFTER_S)
        if filled < remaining and status not in ("executed",):
            try:
                client.cancel_order(order_id)
            except Exception as e:
                print(f"[warn] cancel failed ({e}); re-checking position")
        held = client.position_count(ticker)
        print(f"[exit] attempt {attempt + 1}: sold so far, position now {held}")
        if held == 0:
            return True
        remaining = held
    print(
        f"[ERROR] could not flatten {remaining} {side} contracts on {ticker} after "
        f"{EXIT_MAX_ROUNDS} attempts — MANUAL INTERVENTION NEEDED"
    )
    return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ticker")
    p.add_argument("side", choices=["yes", "no"])
    p.add_argument("--demo", action="store_true", help="use Kalshi's sandbox instead of production")
    p.add_argument("--window-seconds", type=float, default=900.0)
    p.add_argument("--poll-seconds", type=float, default=3.0)
    p.add_argument("--dry-run", action="store_true", help="compute and log decisions, place no orders")
    p.add_argument("--risk-fraction", type=float, default=0.05)
    p.add_argument("--allow-risk-above-5pct", action="store_true")
    args = p.parse_args()

    if not (0 < args.risk_fraction <= 1.0):
        sys.exit("--risk-fraction must be in (0, 1] (0.05 = 5%)")
    if args.risk_fraction > 0.05 and not args.allow_risk_above_5pct:
        sys.exit(
            f"--risk-fraction {args.risk_fraction} exceeds the 5% rule; "
            "pass --allow-risk-above-5pct if you really mean it"
        )

    # one trade at a time: the 5% rule is per-account, and two concurrent runs would each
    # take 5% of the same balance. flock (not file existence) so a crash can't leave a stale lock.
    lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("Another trade is already running (lock held). One trade at a time.")

    client = KalshiClient(demo=args.demo)

    if client.position_count(args.ticker) > 0 and not args.dry_run:
        sys.exit(f"Already holding a position in {args.ticker}; refusing to stack risk.")

    balance = client.balance_cents()
    market = client.get_market(args.ticker)

    if market.get("status") not in (None, "active", "open"):
        sys.exit(f"Market status is {market.get('status')!r}; not tradeable.")

    close_ts = parse_close_ts(market)
    now = time.time()
    if close_ts is not None:
        remaining = close_ts - now - CLOSE_SAFETY_BUFFER_S
        if remaining < MIN_VIABLE_WINDOW_S:
            sys.exit(f"Only {remaining:.0f}s of tradeable time left; not entering.")
        window = min(args.window_seconds, remaining)
    else:
        print("[warn] market has no close_time; falling back to --window-seconds")
        window = args.window_seconds

    entry_price = market.get("yes_ask") if args.side == "yes" else market.get("no_ask")
    if not valid_quote(entry_price):
        sys.exit(f"No real ask on this book (got {entry_price!r}); refusing entry.")

    sizing = size_trade(balance, entry_price, args.risk_fraction)
    print(f"[size] balance={balance}c risk_fraction={args.risk_fraction} -> {sizing}")
    if sizing["contracts"] <= 0:
        sys.exit("Free balance too small for even 1 contract at this risk fraction.")

    cap = depth_cap(client, args.ticker, args.side, entry_price)
    count = sizing["contracts"]
    if cap is not None and cap < count:
        print(f"[size] capping {count} -> {cap} contracts (book depth near the ask)")
        count = cap

    base_order_id = f"5pct-{args.ticker}-{int(time.time())}"
    if args.dry_run:
        print(f"[dry-run] would BUY {count} {args.side} @ {entry_price}c on {args.ticker}")
        held = count
    else:
        resp = client.place_order(args.ticker, args.side, "buy", count, entry_price, base_order_id)
        order_id = resp["order"]["order_id"]
        filled, status = wait_for_fill(client, order_id, ENTRY_FILL_TIMEOUT_S)
        if filled < count and status not in ("executed", "canceled"):
            print(f"[entry] {filled}/{count} filled after {ENTRY_FILL_TIMEOUT_S}s; canceling remainder")
            try:
                client.cancel_order(order_id)
            except Exception as e:
                print(f"[warn] cancel failed ({e})")
        held = client.position_count(args.ticker)
        if held == 0:
            sys.exit("Entry never filled; nothing to manage. Done.")
        print(f"[entry] holding {held} {args.side} @ ~{entry_price}c")

    state = TradeState(
        side=args.side,
        entry_price=entry_price,
        window_seconds=window,
        started_at=time.time(),
        config=StopTargetConfig(),
    )

    print(f"[monitor] polling every {args.poll_seconds}s for up to {window:.0f}s...")
    failures = 0
    result = None
    while True:
        time.sleep(args.poll_seconds)
        try:
            market = client.get_market(args.ticker)
            price = side_bid(market, args.side)
            failures = 0
        except (RuntimeError, urllib.error.URLError, OSError, ValueError, KeyError) as e:
            failures += 1
            print(f"[warn] poll failed ({failures}/{MAX_CONSECUTIVE_POLL_FAILURES}): {e}")
            if failures < MAX_CONSECUTIVE_POLL_FAILURES:
                time.sleep(min(2 ** failures, 30))
                continue
            print("[error] persistent poll failures; forcing emergency exit")
            result = {"action": "exit", "reason": "poll_failure_bailout"}
            break
        if not valid_quote(price):
            print(f"[tick] no valid bid (got {price!r}); skipping tick")
            continue
        # belt and suspenders: never manage past the market's actual close
        if close_ts is not None and time.time() >= close_ts - CLOSE_SAFETY_BUFFER_S:
            result = {"action": "exit", "reason": "market_closing"}
            break
        result = state.update(time.time(), price)
        print(f"[tick] price={price}c -> {result}")
        if result["action"] == "exit":
            break

    reason = result["reason"]
    aggressive = reason in ("stop_loss", "trailing_stop", "window_expired", "market_closing", "poll_failure_bailout")
    print(f"[exit] reason={reason}; flattening {held} contracts")
    flat = flatten(client, args.ticker, args.side, held, base_order_id, args.dry_run, aggressive)
    if flat and not args.dry_run:
        final_balance = client.balance_cents()
        print(f"[done] flat. balance {balance}c -> {final_balance}c (net {final_balance - balance:+d}c incl. fees)")


if __name__ == "__main__":
    main()
