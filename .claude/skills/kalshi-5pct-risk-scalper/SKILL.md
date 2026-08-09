---
name: kalshi-5pct-risk-scalper
description: Sizes, enters, and manages 15-minute directional Kalshi contract trades using a fixed 5%-of-free-balance risk rule, with a volatility-and-time-decay-adaptive stop-loss and a capitulation-triggered adaptive take-profit/trailing stop. Use this whenever the user wants to trade Kalshi short-duration directional markets (15-min windows, e.g. crypto/forex "up or down" contracts), asks about position sizing as a percent of their account, wants automated stop-loss or take-profit management on Kalshi, or wants a bot/script to place and monitor Kalshi orders with risk controls. Trigger even if they just say things like "size my next Kalshi trade" or "set a stop on this contract" without naming the skill.
---

# Kalshi 5%-Risk 15-Minute Directional Scalper

This skill runs one trade at a time on a short-duration (typically 15-minute) Kalshi directional
market: a fixed fraction of the account is put at risk, an entry is sized off the live free
balance, and a stop/target loop manages the exit automatically. It trades **real money against
Kalshi's production API by default** — treat every invocation as something that can lose cash,
and read `references/kalshi_api.md` once before the first live run so you understand what "stop"
and "target" mean for a binary contract (there's no leverage; max loss is the premium paid).

## Why the pieces are shaped this way

**5% risk, not 5% of account in general.** Kalshi contracts can't lose more than what you paid
for them (no margin calls, no leverage). So "risk 5% of free balance" is just "spend at most 5%
of free balance on contracts" — `scripts/position_sizer.py` divides the risk budget by the entry
price and floors it to a whole contract count. This is deliberately the simplest correct version
of position sizing; don't overcomplicate it with Kelly criterion or similar unless the user asks.

**The stop widens with volatility and tightens with time.** A fixed-cents stop either gets you
stopped out by normal noise in a choppy market, or exposes you to too much slippage in a quiet
one — so the stop distance in `scripts/stop_target.py` scales with a short rolling average of
tick-to-tick moves (an ATR analog for a quote series with no OHLC). Separately, the same stop
distance shrinks toward a floor as the 15-minute window runs out, because a given adverse move
matters more when there's less time left to recover from it.

**The target grows if the market capitulates in your favor, and a trailing stop locks in the
gain in case it doesn't grow enough.** A plain fixed take-profit leaves money on the table when
the other side is clearly folding fast; but chasing an ever-receding target with nothing behind
it risks giving the whole move back. So when favorable *velocity* (price change per second, not
just price change) crosses a threshold, the target steps outward — and a trailing stop arms
behind the running price at the same time, so the position is protected even if the extended
target is never reached.

## Workflow

1. **Confirm the setup before doing anything live.** Ask (or infer from context) the market
   ticker, direction (yes/no), and whether this is a dry run, a demo-sandbox test, or a live
   production trade. Kalshi credentials must already be in `KALSHI_API_KEY_ID` and
   `KALSHI_PRIVATE_KEY`/`KALSHI_PRIVATE_KEY_PATH` — if they're missing, say so rather than
   guessing at how to obtain them.

2. **Always dry-run a new market or a changed config first.** Run
   `python scripts/run_trade.py TICKER SIDE --dry-run --demo` before ever passing neither flag.
   This exercises the exact sizing/stop/target math against live quotes without moving money, and
   catches bad ticker names or misconfigured thresholds cheaply.

3. **Run the live trade** once the dry run looks right, by dropping `--dry-run` (and `--demo` if
   the user wants production, which is the default). `run_trade.py`:
   - Pulls free balance and the current ask, sizes the position at 5% risk
     (`position_sizer.size_trade`), and places the entry limit order.
   - Polls the market every `--poll-seconds` (default 3s) and feeds each quote into
     `stop_target.TradeState.update`, which returns `hold` (with the current stop/target levels)
     or `exit` (with a reason: `stop_loss`, `trailing_stop`, `target_hit`, or `window_expired`).
   - Places the opposing (sell) order the moment an `exit` fires.

4. **Report the outcome plainly**: entry price and size, exit reason, exit price, realized P&L in
   cents. If something looks off mid-trade (repeated `hold` near expiry with no clear stop/target
   engagement, API errors, unexpected balance), surface it immediately rather than letting the
   loop run unattended — this is real money on a short clock.

## Tuning knobs

All defaults live in `scripts/stop_target.py`'s `StopTargetConfig` and are reasonable starting
points, not tuned to any specific market — adjust them when the user gives feedback like "it got
stopped out on noise" (raise `stop_k` or `min_stop_cents`) or "it took profit too early during a
strong move" (raise `capitulation_velocity_cents_per_sec` threshold or `target_extension_cents`).
Explain which knob you're changing and why, in terms of what the user actually observed.

## Reference

- `references/kalshi_api.md` — auth scheme, endpoints, base URLs (prod vs demo), and why stop/
  target here means a polling loop rather than a native conditional order (Kalshi has none).
- `scripts/kalshi_client.py` — signed REST client (balance, market quotes, order placement).
- `scripts/position_sizer.py` — the 5%-of-free-balance sizing calculation.
- `scripts/stop_target.py` — the adaptive stop/target state machine described above.
- `scripts/run_trade.py` — ties the above together into one runnable trade.
