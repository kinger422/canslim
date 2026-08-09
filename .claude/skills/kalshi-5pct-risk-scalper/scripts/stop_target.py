"""Adaptive stop-loss + take-profit logic for a 15-minute directional Kalshi trade.

All prices are contract prices in cents (1-99), on the side you bought (yes or no).
"favor" means "toward 100" (the contract you hold winning).

Three ideas combine here:

1. Volatility-based stop: distance = k * recent average absolute tick-to-tick move
   (an ATR analog, since there's no OHLC on a 15-min binary contract, just quote ticks).
   A choppy market gets a wider stop than a quiet one, so normal noise doesn't stop you out.

2. Time-decay tightening: as the 15-minute window runs out, the stop distance shrinks
   toward a floor. Early in the trade you can give it room; near expiry, an adverse move
   matters more (less time to recover) so the stop should bite sooner.

3. Adaptive target: start with a fixed initial target (k_target * volatility past entry).
   If price moves in your favor fast (velocity above a threshold — "capitulation" by the
   other side), extend the target by a further step rather than taking early profit, and
   also start trailing a stop behind the running price so gains already made are protected
   even if the target extension turns out to be too greedy.
"""
from dataclasses import dataclass, field
from collections import deque


@dataclass
class StopTargetConfig:
    vol_window: int = 8          # number of recent ticks used for the volatility estimate
    stop_k: float = 1.5          # stop distance = stop_k * volatility
    min_stop_cents: int = 3      # never let the stop get tighter than this (avoid noise stop-outs)
    stop_floor_fraction: float = 0.4  # stop distance shrinks to this fraction of itself by expiry
    target_k: float = 2.0        # initial target distance = target_k * volatility
    capitulation_velocity_cents_per_sec: float = 0.8  # favorable move rate that counts as capitulation
    target_extension_cents: int = 5   # how far to push the target out on a capitulation trigger
    trail_activation_cents: int = 4   # favorable move needed before trailing stop engages
    trail_distance_cents: float = 2.0  # trailing stop stays this far behind the best price


@dataclass
class TradeState:
    side: str                    # "yes" or "no" -- direction you bought
    entry_price: float
    window_seconds: float        # total trade duration, e.g. 900 for 15 min
    started_at: float            # unix timestamp of entry
    config: StopTargetConfig = field(default_factory=StopTargetConfig)
    ticks: deque = field(default_factory=lambda: deque(maxlen=50))  # (timestamp, price)
    best_price: float = None
    trailing_stop: float = None
    target_price: float = None
    stop_price: float = None
    capitulation_triggered: bool = False

    def __post_init__(self):
        if self.best_price is None:
            self.best_price = self.entry_price

    def _favor_sign(self):
        # both "yes" and "no" contracts win by moving toward 100c; "favor" is always +1 in
        # contract-price terms once you've bought a side, since price = P(your side wins).
        return 1

    def volatility(self):
        c = self.config
        recent = list(self.ticks)[-c.vol_window:]
        if len(recent) < 2:
            return 1.0  # default assumption before enough data
        diffs = [abs(recent[i][1] - recent[i - 1][1]) for i in range(1, len(recent))]
        return sum(diffs) / len(diffs)

    def time_remaining_fraction(self, now):
        elapsed = now - self.started_at
        return max(0.0, 1.0 - elapsed / self.window_seconds)

    def velocity(self):
        c = self.config
        recent = list(self.ticks)[-c.vol_window:]
        if len(recent) < 2:
            return 0.0
        (t0, p0), (t1, p1) = recent[0], recent[-1]
        dt = t1 - t0
        if dt <= 0:
            return 0.0
        return (p1 - p0) / dt  # favor-signed already, since price up = favor for the side you hold

    def update(self, now, price):
        """Feed a new quote tick. Returns an action dict: {'action': 'hold'|'exit', 'reason': str}."""
        c = self.config
        self.ticks.append((now, price))
        self.best_price = max(self.best_price, price)

        vol = self.volatility()
        time_frac = self.time_remaining_fraction(now)
        # stop distance shrinks linearly from full size (time_frac=1) to stop_floor_fraction (time_frac=0)
        decay = c.stop_floor_fraction + (1 - c.stop_floor_fraction) * time_frac
        base_stop_distance = max(c.min_stop_cents, c.stop_k * vol) * decay
        self.stop_price = self.entry_price - base_stop_distance

        if self.target_price is None:
            self.target_price = self.entry_price + c.target_k * vol

        favorable_move = self.best_price - self.entry_price
        vel = self.velocity()

        # capitulation: fast favorable move -> extend target, arm trailing stop
        if vel >= c.capitulation_velocity_cents_per_sec and favorable_move > 0:
            self.capitulation_triggered = True
            extended = self.best_price + c.target_extension_cents
            if extended > self.target_price:
                self.target_price = extended

        if favorable_move >= c.trail_activation_cents:
            candidate_trail = self.best_price - c.trail_distance_cents
            if self.trailing_stop is None or candidate_trail > self.trailing_stop:
                self.trailing_stop = candidate_trail

        effective_stop = max(self.stop_price, self.trailing_stop) if self.trailing_stop else self.stop_price

        if price <= effective_stop:
            reason = "trailing_stop" if self.trailing_stop and effective_stop == self.trailing_stop else "stop_loss"
            return {"action": "exit", "reason": reason, "price": price, "stop": effective_stop}

        if price >= self.target_price and not self.capitulation_triggered:
            return {"action": "exit", "reason": "target_hit", "price": price, "target": self.target_price}

        if time_frac <= 0:
            return {"action": "exit", "reason": "window_expired", "price": price}

        return {
            "action": "hold",
            "stop": effective_stop,
            "target": self.target_price,
            "time_remaining_frac": round(time_frac, 3),
            "capitulation": self.capitulation_triggered,
        }
