"""Adaptive stop-loss + take-profit logic for a 15-minute directional Kalshi trade.

All prices are contract prices in cents (1-99), on the side you bought (yes or no).
"favor" means "toward 100" (the contract you hold winning).

Three ideas combine here:

1. Volatility-based stop: distance = k * recent average absolute tick-to-tick move
   (an ATR analog, since there's no OHLC on a 15-min binary contract, just quote ticks).
   A choppy market gets a wider stop than a quiet one, so normal noise doesn't stop you out.
   The stop only ever tightens (ratchets up): a crash inflates measured volatility, and
   letting that widen the stop would mean an adverse move loosening its own stop — exactly
   the harmful direction — so the level is clamped monotonic.

2. Time-decay tightening: as the 15-minute window runs out, the volatility component of
   the stop distance shrinks. Early in the trade you can give it room; near expiry an
   adverse move matters more (less time to recover) so the stop should bite sooner.
   The min_stop_cents floor is applied AFTER decay, so the stop never gets tighter than
   the documented minimum even at the end of the window.

3. Adaptive target: the target starts at target_k * volatility past entry and keeps
   re-estimating until enough ticks exist for a real volatility read (locking it on the
   placeholder estimate would freeze a ~2c target against a ~3c stop — inverted R/R).
   If price moves in your favor fast (velocity over a fixed wall-clock lookback above a
   threshold — "capitulation" by the other side), the target extends outward AND a
   trailing stop arms immediately behind the best price, so gains already made are
   protected even if the extended target is never reached. The (extended) target itself
   still exits — capitulation moves the goalposts, it never abolishes them.
"""
from dataclasses import dataclass, field
from collections import deque


@dataclass
class StopTargetConfig:
    vol_window: int = 8          # number of recent ticks used for the volatility estimate
    stop_k: float = 1.5          # stop distance = stop_k * volatility
    min_stop_cents: int = 3      # never let the stop get tighter than this (avoid noise stop-outs)
    stop_floor_fraction: float = 0.4  # volatility component shrinks to this fraction by expiry
    target_k: float = 2.0        # initial target distance = target_k * volatility
    capitulation_velocity_cents_per_sec: float = 0.4  # favorable move rate that counts as capitulation
    velocity_lookback_seconds: float = 10.0  # wall-clock window the velocity is measured over
    min_velocity_span_seconds: float = 5.0   # below this span the sample is too small to trust
    target_extension_cents: int = 5   # how far past best price to push the target on capitulation
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
    target_locked: bool = False
    stop_price: float = None
    capitulation_triggered: bool = False

    def __post_init__(self):
        if self.best_price is None:
            self.best_price = self.entry_price

    def volatility(self):
        c = self.config
        recent = list(self.ticks)[-c.vol_window:]
        if len(recent) < 2:
            # placeholder sized so the interim stop is min_stop_cents, not narrower
            return c.min_stop_cents / c.stop_k
        diffs = [abs(recent[i][1] - recent[i - 1][1]) for i in range(1, len(recent))]
        return sum(diffs) / len(diffs)

    def time_remaining_fraction(self, now):
        elapsed = now - self.started_at
        return max(0.0, 1.0 - elapsed / self.window_seconds)

    def velocity(self, now):
        # measured over a fixed wall-clock lookback, not a fixed tick count: a tick-count
        # window makes the reading swing wildly with the poll interval (2 ticks = hair
        # trigger, 8 slow ticks = unreachable threshold)
        c = self.config
        recent = [(t, p) for t, p in self.ticks if t >= now - c.velocity_lookback_seconds]
        if len(recent) < 2:
            return 0.0
        (t0, p0), (t1, p1) = recent[0], recent[-1]
        span = t1 - t0
        if span < c.min_velocity_span_seconds:
            return 0.0
        return (p1 - p0) / span

    def _arm_trail(self):
        candidate = max(1.0, self.best_price - self.config.trail_distance_cents)
        if self.trailing_stop is None or candidate > self.trailing_stop:
            self.trailing_stop = candidate

    def update(self, now, price):
        """Feed a new quote tick. Returns an action dict: {'action': 'hold'|'exit', 'reason': str}."""
        c = self.config
        self.ticks.append((now, price))
        self.best_price = max(self.best_price, price)

        vol = self.volatility()
        time_frac = self.time_remaining_fraction(now)
        # decay shrinks only the volatility component; the floor is applied after,
        # so the stop never gets tighter than min_stop_cents
        decay = c.stop_floor_fraction + (1 - c.stop_floor_fraction) * time_frac
        stop_distance = max(c.min_stop_cents, c.stop_k * vol * decay)
        candidate_stop = max(1.0, self.entry_price - stop_distance)
        # monotonic: the hard stop only tightens; crash-inflated volatility never loosens it
        self.stop_price = candidate_stop if self.stop_price is None else max(self.stop_price, candidate_stop)

        # keep re-estimating the target until a real volatility read exists (then lock);
        # target distance is at least the stop distance so R/R never inverts
        if not self.target_locked:
            self.target_price = min(99.0, self.entry_price + max(c.target_k * vol, stop_distance))
            if len(self.ticks) >= c.vol_window:
                self.target_locked = True

        favorable_move = self.best_price - self.entry_price
        vel = self.velocity(now)

        # capitulation: fast favorable move -> extend target AND arm the trail immediately,
        # so the extra room granted to the trade is backed by locked-in protection
        if vel >= c.capitulation_velocity_cents_per_sec and favorable_move > 0:
            self.capitulation_triggered = True
            self.target_locked = True
            extended = min(99.0, self.best_price + c.target_extension_cents)
            if extended > self.target_price:
                self.target_price = extended
            self._arm_trail()

        if favorable_move >= c.trail_activation_cents:
            self._arm_trail()

        effective_stop = max(self.stop_price, self.trailing_stop) if self.trailing_stop else self.stop_price

        if price <= effective_stop:
            reason = "trailing_stop" if self.trailing_stop and effective_stop == self.trailing_stop else "stop_loss"
            return {"action": "exit", "reason": reason, "price": price, "stop": effective_stop}

        # the (possibly extended) target always exits — don't evaluate it before there's
        # any real data at all, but never suppress it after capitulation
        if len(self.ticks) >= 2 and price >= self.target_price:
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
