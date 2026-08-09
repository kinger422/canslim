"""Minimal signed HTTP client for the Kalshi trading API.

Credentials come from env vars:
  KALSHI_API_KEY_ID
  KALSHI_PRIVATE_KEY       (PEM text)  or  KALSHI_PRIVATE_KEY_PATH (path to PEM file)

Defaults to production (real money). Pass demo=True to hit the sandbox instead.
"""
import base64
import os
import time
import urllib.request
import urllib.error
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

PROD_BASE = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"


def _load_private_key():
    pem = os.environ.get("KALSHI_PRIVATE_KEY")
    if not pem:
        path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
        if not path:
            raise RuntimeError(
                "Set KALSHI_PRIVATE_KEY or KALSHI_PRIVATE_KEY_PATH to your Kalshi RSA private key."
            )
        with open(path, "rb") as f:
            pem = f.read()
    else:
        pem = pem.encode()
    return serialization.load_pem_private_key(pem, password=None)


class KalshiClient:
    def __init__(self, demo=False):
        self.base = DEMO_BASE if demo else PROD_BASE
        self.key_id = os.environ.get("KALSHI_API_KEY_ID")
        if not self.key_id:
            raise RuntimeError("Set KALSHI_API_KEY_ID.")
        self.private_key = _load_private_key()

    def _sign(self, method, path):
        ts = str(int(time.time() * 1000))
        message = (ts + method.upper() + path).encode()
        signature = self.private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }

    def request(self, method, path, body=None):
        url = self.base + path
        headers = self._sign(method, path)
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()}")

    def balance_cents(self):
        return self.request("GET", "/portfolio/balance")["balance"]

    def get_market(self, ticker):
        return self.request("GET", f"/markets/{ticker}")["market"]

    def get_orderbook(self, ticker):
        return self.request("GET", f"/markets/{ticker}/orderbook")["orderbook"]

    def place_order(self, ticker, side, action, count, price_cents, client_order_id):
        body = {
            "ticker": ticker,
            "side": side,       # "yes" or "no"
            "action": action,   # "buy" or "sell"
            "count": count,
            "type": "limit",
            "yes_price" if side == "yes" else "no_price": price_cents,
            "client_order_id": client_order_id,
        }
        return self.request("POST", "/portfolio/orders", body)

    def cancel_order(self, order_id):
        return self.request("DELETE", f"/portfolio/orders/{order_id}")

    def get_positions(self):
        return self.request("GET", "/portfolio/positions")["market_positions"]
