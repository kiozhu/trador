"""Order Flow Imbalance (OBI) analyzer — tick bar granularity."""
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from ..utils.logger import log


@dataclass
class TickBar:
    """Single tick bar snapshot."""
    timestamp: int # ms epoch
    open: float
    high: float
    low: float
    close: float
    volume: float
    bid_volume: float = 0.0
    ask_volume: float = 0.0
    trade_count: int = 0


@dataclass
class OBISnapshot:
    """Order Flow Imbalance reading at a point in time."""
    timestamp: int
    obi: float # raw imbalance: (bidVol - askVol) / (bidVol + askVol)
    obi_smoothed: float    # EMA-smoothed imbalance
    cumulative_obi: float # running cumulative OBI
    pressure: Literal["bid", "ask", "neutral"]
    intensity: Literal["weak", "moderate", "strong"]
    bar_count: int
    cumulative_volume: float


class OBIFilter:
    """Exponential moving average filter for OBI smoothing."""

    def __init__(self, alpha: float = 0.02):
        self.alpha = alpha
        self.value: float | None = None

    def update(self, raw: float) -> float:
        if self.value is None:
            self.value = raw
        else:
            self.value = self.alpha * raw + (1 - self.alpha) * self.value
        return self.value


class OBIAuthor:
    """Accumulates tick bars and computes OBI metrics."""

    def __init__(
        self,
        window: int = 20,
        smooth_alpha: float = 0.02,
        tick_thresh: int = 50,
    ):
        """
        Args:
            window: number of bars to keep in rolling window
            smooth_alpha:   EMA smoothing factor for OBI
            tick_thresh:    number of ticks that form one bar (0 = time-based)
        """
        self.window = window
        self.smooth_alpha = smooth_alpha
        self.tick_thresh = tick_thresh

        self._bars: deque[TickBar] = deque(maxlen=window)
        self._filter = OBIFilter(alpha=smooth_alpha)
        self._cumulative_obi: float = 0.0
        self._cumulative_volume: float = 0.0

        # Current bar being accumulated
        self._cur: TickBar | None = None
        self._cur_tick_count: int = 0

    # ── Public API ─────────────────────────────────────────────────────────────

    def ingest_tick(
        self,
        timestamp_ms: int,
        price: float,
        volume: float,
        side: Literal["bid", "ask", "buy", "sell"],
    ) -> OBISnapshot | None:
        """Ingest a tick and return a snapshot when a bar closes.

        Args:
            timestamp_ms: epoch milliseconds
            price:        last traded price
            volume:       trade volume
            side:         'bid'/'buy' = aggressive bid, 'ask'/'sell' = aggressive ask

        Returns:
            OBISnapshot if a bar just closed, None otherwise.
        """
        if self._cur is None:
            self._cur = TickBar(
                timestamp=timestamp_ms,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
            )
        else:
            self._cur.high = max(self._cur.high, price)
            self._cur.low = min(self._cur.low, price)
            self._cur.close = price
            self._cur.volume += volume

        # Classify side
        is_bid = side in ("bid", "buy")

        if is_bid:
            self._cur.bid_volume += volume
        else:
            self._cur.ask_volume += volume

        self._cur.trade_count += 1
        self._cur_tick_count += 1

        # Check bar close condition
        bar_closed = (
            (self.tick_thresh > 0 and self._cur_tick_count >= self.tick_thresh)
        )

        if bar_closed:
            snapshot = self._close_bar()
            return snapshot
        return None

    def ingest_ohlcv(
        self,
        timestamp_ms: int,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        bid_vol: float = 0.0,
        ask_vol: float = 0.0,
    ) -> OBISnapshot:
        """Ingest a completed OHLCV bar (e.g. from exchange) and compute OBI.

        Use this when you have bar-level data with volume on each side.
        """
        bar = TickBar(
            timestamp=timestamp_ms,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            bid_volume=bid_vol,
            ask_volume=ask_vol,
            trade_count=1,
        )
        self._bars.append(bar)
        self._cumulative_volume += volume
        return self._compute_snapshot(bar)

    def get_current_obi(self) -> OBISnapshot | None:
        """Return the latest snapshot without forcing a bar close."""
        if not self._bars:
            return None
        return self._compute_snapshot(self._bars[-1])

    def rolling_obi(self, n: int | None = None) -> float:
        """Rolling OBI over the last `n` bars (default: full window)."""
        n = n or self.window
        bars = list(self._bars)[-n:]
        if not bars:
            return 0.0
        total_bid = sum(b.bid_volume for b in bars)
        total_ask = sum(b.ask_volume for b in bars)
        total = total_bid + total_ask
        if total == 0:
            return 0.0
        return (total_bid - total_ask) / total

    # ── Internal ───────────────────────────────────────────────────────────────

    def _close_bar(self) -> OBISnapshot:
        bar = self._cur
        self._bars.append(bar)
        self._cumulative_volume += bar.volume
        self._cur = None
        self._cur_tick_count = 0
        return self._compute_snapshot(bar)

    def _compute_snapshot(self, bar: TickBar) -> OBISnapshot:
        total = bar.bid_volume + bar.ask_volume
        if total > 0:
            raw_obi = (bar.bid_volume - bar.ask_volume) / total
        else:
            raw_obi = 0.0

        smoothed = self._filter.update(raw_obi)
        self._cumulative_obi += raw_obi

        # Pressure
        if smoothed > 0.05:
            pressure: Literal["bid", "ask", "neutral"] = "bid"
        elif smoothed < -0.05:
            pressure = "ask"
        else:
            pressure = "neutral"

        # Intensity
        intensity: Literal["weak", "moderate", "strong"]
        abs_obi = abs(smoothed)
        if abs_obi < 0.15:
            intensity = "weak"
        elif abs_obi < 0.40:
            intensity = "moderate"
        else:
            intensity = "strong"

        return OBISnapshot(
            timestamp=bar.timestamp,
            obi=round(raw_obi, 6),
            obi_smoothed=round(smoothed, 6),
            cumulative_obi=round(self._cumulative_obi, 6),
            pressure=pressure,
            intensity=intensity,
            bar_count=len(self._bars),
            cumulative_volume=round(self._cumulative_volume, 4),
        )


# ── Convenience helpers ────────────────────────────────────────────────────────

def obi_from_ohlcv_series(
    ohlcv_list: list[list],
    window: int = 20,
    smooth_alpha: float = 0.02,
) -> list[OBISnapshot]:
    """Compute OBI snapshots from a series of OHLCV candles.

    Args:
        ohlcv_list: list of [timestamp, open, high, low, close, volume]
        window:     rolling window size
        smooth_alpha: EMA smoothing factor

    Returns:
        list of OBISnapshot (one per input bar)
    """
    author = OBIAuthor(window=window, smooth_alpha=smooth_alpha)
    snapshots = []
    for bar in ohlcv_list:
        ts = int(bar[0])
        o, h, l, c, v = float(bar[1]), float(bar[2]), float(bar[3]), float(bar[4]), float(bar[5])
        snap = author.ingest_ohlcv(ts, o, h, l, c, v)
        snapshots.append(snap)
    return snapshots


def latest_obi_signal(snapshots: list[OBISnapshot]) -> dict:
    """Summarise the latest OBI snapshot into a trade-ready signal dict."""
    if not snapshots:
        return {"signal": "neutral", "obi": 0.0, "pressure": "neutral", "intensity": "weak"}

    latest = snapshots[-1]
    signal: Literal["long", "short", "neutral"]
    if latest.pressure == "bid" and latest.intensity in ("moderate", "strong"):
        signal = "long"
    elif latest.pressure == "ask" and latest.intensity in ("moderate", "strong"):
        signal = "short"
    else:
        signal = "neutral"

    return {
        "signal": signal,
        "obi": latest.obi_smoothed,
        "pressure": latest.pressure,
        "intensity": latest.intensity,
        "cumulative_obi": latest.cumulative_obi,
        "bar_count": latest.bar_count,
        "timestamp": datetime.fromtimestamp(latest.timestamp / 1000, tz=timezone.utc).isoformat(),
    }
