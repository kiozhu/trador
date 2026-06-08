"""Volume profile scanner — Binance REST klines (no API key).

REST endpoint: https://api.binance.com/api/v3/klines
Computes POC (Point of Control), VAH (Value Area High), VAL (Value Area Low).
"""
from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Callable, Optional

import requests

log = logging.getLogger(__name__)

BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"


@dataclass
class VolumeProfileEvent:
    """Volume profile for a completed period."""
    symbol: str
    interval: str           # e.g. "1h", "15m"
    poc: float               # price with highest volume
    vah: float               # value area high (70% of volume)
    val: float               # value area low (70% of volume)
    total_volume: float
    profile_width_pct: float # (vah - val) / poc * 100
    timestamp: int           # kline close time (ms)
    local_time: datetime


class VolumeProfileScanner:
    """
    Fetches Binance klines via REST and computes volume profile metrics.
    POC  = price level with highest traded volume.
    VAH  = upper boundary of value area (70% of cumulative volume).
    VAL  = lower boundary of value area (70% of cumulative volume).
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        interval: str = "1h",
        lookback: int = 24,   # number of klines to fetch
        value_area_pct: float = 70.0,
    ):
        """
        symbols          : list of symbols to scan, None = defaults
        interval         : kline interval (e.g. "1m", "5m", "1h", "4h", "1d")
        lookback         : number of past klines to fetch
        value_area_pct   : percentage of total volume to define VAH/VAL range
        """
        self.symbols = symbols or [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
            "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
        ]
        self.interval = interval
        self.lookback = lookback
        self.value_area_pct = value_area_pct

        self._profiles: dict[str, VolumeProfileEvent] = {}
        self._running = False
        self._lock = Lock()

        # callbacks: (profile: VolumeProfileEvent) -> None
        self._callbacks: list[Callable[[VolumeProfileEvent], None]] = []

    # ── public ──────────────────────────────────────────────────────────────────

    def add_callback(self, cb: Callable[[VolumeProfileEvent], None]):
        self._callbacks.append(cb)

    def start(self):
        """Run a single scan (blocking). Use in a thread or loop."""
        self._running = True
        self._scan_all()
        self._running = False

    def stop(self):
        self._running = False

    def get_active(self) -> list[VolumeProfileEvent]:
        with self._lock:
            return list(self._profiles.values())

    def summary_text(self) -> str:
        profiles = self.get_active()
        if not profiles:
            return "VolumeProfileScanner: no data yet."

        lines = ["📈 *Volume Profile:*\n"]
        for p in sorted(profiles, key=lambda x: x.symbol):
            width = p.profile_width_pct
            lines.append(
                f"  {p.symbol} | POC {p.poc:.4f} | "
                f"VAH {p.vah:.4f} | VAL {p.val:.4f} | "
                f"w {width:.2f}% | vol {p.total_volume:,.0f}"
            )
        return "\n".join(lines)

    # ── internal ────────────────────────────────────────────────────────────────

    def _scan_all(self):
        for sym in self.symbols:
            if not self._running:
                break
            try:
                profile = self._fetch_profile(sym)
                if profile:
                    with self._lock:
                        self._profiles[sym] = profile
                    log.info(
                        "📊 VP %s: POC=%.4f VAH=%.4f VAL=%.4f w=%.2f%% vol=%.0f",
                        sym, profile.poc, profile.vah, profile.val,
                        profile.profile_width_pct, profile.total_volume
                    )
                    for cb in self._callbacks:
                        try:
                            cb(profile)
                        except Exception as e:
                            log.error("VolumeProfileScanner callback error: %s", e)
            except Exception as e:
                log.warning("VolumeProfileScanner error fetching %s: %s", sym, e)
            time.sleep(0.2)  # rate-limit to avoid Binance 4200 errors

    def _fetch_profile(self, symbol: str) -> Optional[VolumeProfileEvent]:
        params = {
            "symbol": symbol.upper(),
            "interval": self.interval,
            "limit": self.lookback,
        }
        try:
            resp = requests.get(BINANCE_KLINE_URL, params=params, timeout=10)
            if resp.status_code == 429:
                log.warning("VolumeProfileScanner: Binance rate limit, backing off")
                time.sleep(5)
                return None
            resp.raise_for_status()
            klines = resp.json()
        except Exception as e:
            log.warning("VolumeProfileScanner: failed to fetch klines for %s: %s", symbol, e)
            return None

        if not klines:
            return None

        return self._compute_profile(symbol, klines)

    def _compute_profile(self, symbol: str, klines: list) -> VolumeProfileEvent:
        """
        klines entry: [open_time, open, high, low, close, volume, close_time, ...]
        We bucket by close price to build a volume histogram.
        """
        # Build price-volume buckets
        buckets: dict[float, float] = defaultdict(float)  # price_bucket -> volume
        total_volume = 0.0

        for k in klines:
            try:
                close_price = float(k[4])   # close price
                volume = float(k[5])         # base asset volume
            except (IndexError, ValueError):
                continue

            # Bucket by rounding to a tick size (0.01 for most, 0.1 for others)
            tick = self._tick_size(close_price)
            bucket = round(close_price / tick) * tick
            buckets[bucket] += volume
            total_volume += volume

        if not buckets:
            return None

        # POC = bucket with highest volume
        poc_price = max(buckets.items(), key=lambda x: x[1])[0]
        poc_volume = buckets[poc_price]

        # Build cumulative volume from POC outward
        sorted_prices = sorted(buckets.keys())
        poc_idx = sorted_prices.index(poc_price)

        cumulative = poc_volume
        # Spread outward symmetrically
        left = list(sorted_prices[:poc_idx])
        right = list(sorted_prices[poc_idx + 1:])

        target_volume = total_volume * (self.value_area_pct / 100)

        vah_price = poc_price
        val_price = poc_price

        # Expand to the right (higher prices)
        for p in sorted(right):
            cumulative += buckets[p]
            vah_price = p
            if cumulative >= target_volume:
                break

        # Expand to the left (lower prices)
        for p in sorted(left, reverse=True):
            cumulative += buckets[p]
            val_price = p
            if cumulative >= target_volume:
                break

        profile_width_pct = ((vah_price - val_price) / poc_price * 100) if poc_price else 0

        last_kline = klines[-1]
        return VolumeProfileEvent(
            symbol=symbol.lower(),
            interval=self.interval,
            poc=poc_price,
            vah=vah_price,
            val=val_price,
            total_volume=total_volume,
            profile_width_pct=profile_width_pct,
            timestamp=int(last_kline[6]),   # close_time
            local_time=datetime.now(),
        )

    @staticmethod
    def _tick_size(price: float) -> float:
        """Return reasonable tick size based on price magnitude."""
        if price >= 10000:
            return 1.0
        elif price >= 1000:
            return 0.1
        elif price >= 100:
            return 0.01
        elif price >= 10:
            return 0.001
        else:
            return 0.0001