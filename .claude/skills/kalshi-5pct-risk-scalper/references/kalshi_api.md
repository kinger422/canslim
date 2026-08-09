# Kalshi API notes

## Auth
Kalshi's trading API uses an API key ID + RSA private key. Every request is signed:

```
message = timestamp_ms + method.upper() + path
signature = RSA-PSS-SHA256(private_key, message)  # base64
headers = {
  "KALSHI-ACCESS-KEY": key_id,
  "KALSHI-ACCESS-SIGNATURE": signature,
  "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
}
```

Credentials are read from environment variables:
- `KALSHI_API_KEY_ID`
- `KALSHI_PRIVATE_KEY` (PEM contents, or `KALSHI_PRIVATE_KEY_PATH` pointing at a PEM file)

## Base URLs
- Production: `https://api.elections.kalshi.com/trade-api/v2` (real money — orders here execute for real)
- Demo/paper: `https://demo-api.kalshi.co/trade-api/v2` (sandbox, fake balance, same API shape)

`kalshi_client.py` defaults to **production** per the account owner's preference, but always
accepts `--demo` to point at the sandbox for dry-runs. Given every order here risks real money,
prefer a `--demo` dry run first when testing a new market or a change to the sizing/stop/target logic.

## Endpoints used by this skill
- `GET /portfolio/balance` — available (free) cash balance, in cents
- `GET /markets/{ticker}` — current yes_bid/yes_ask/no_bid/no_ask, close_time
- `GET /markets/{ticker}/orderbook` — depth, used for slippage-aware sizing
- `POST /portfolio/orders` — place order (limit orders recommended over market to control fill price)
- `DELETE /portfolio/orders/{order_id}` — cancel
- `GET /portfolio/positions` — current open positions

## Contract mechanics that matter for a 15-min directional trade
- Kalshi contracts settle YES at $1.00 / NO at $0.00 (or vice versa) — price already reflects
  implied probability, so "stop distance" and "target distance" should be expressed in cents of
  contract price, not in the underlying's own price units.
- There's no leverage: max loss on a bought contract is the price paid. The 5% risk rule in this
  skill caps *how many contracts you buy*, not a stop that could lose more than the premium.
- A resting limit stop/target still needs an active process polling the market and firing a
  cancel + opposing order — Kalshi doesn't natively support conditional (stop/OCO) orders as of
  this writing. `run_trade.py` implements the polling loop.
