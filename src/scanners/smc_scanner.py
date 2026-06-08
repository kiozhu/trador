"""Smart Money Concepts scanner — Binance REST klines (no API key).

Detects:
  • Order Blocks     — institutional candle zones (body + wick)
  • Fair Value Gaps  — 3-candle imbalance (FVG)
  • Liquidity Sweeps — stop-hunt above/below recent swing levels
  • Market Structure — swing highs/lows + Break-of-Structure (BOS)
  • BTC Master Filter — block signals against BTC trend

Public API:
 SMCScanner.add_callback(cb)        — register cb(event)
  await SMCScanner.start() — begin polling
  await SMCScanner.stop()            — stop polling
  get_active_ob()                    — list[OrderBlock]
  get_active_fvg()                   — list[FairValueGap]
  get_active_sweeps()                — list[LiquiditySweep]
  get_active_structure()             — list[MarketStructure]
  get_btc_trend()                    — "bullish" | "bearish" | "neutral"
  summary_text()                     — Telegram-formatted string
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from threading import Lock
from typing import Callable, Optional

import httpx

from ..utils.logger import log

# ── Binance REST ──────────────────────────────────────────────────────────────
_BINANCE_KLINE = "https://api.binance.com/api/v3/klines"
_BINANCE_SPOT  = "https://api.binance.com/api/v3/klines"
_BTC_SYMBOL = "BTCUSDT"


# ── Event Dataclasses ──────────────────────────────────────────────────────────

class OBType(Enum):
    BULLISH = "bullish_ob"
    BEARISH = "bearish_ob"


class FVGDirection(Enum):
    BULLISH = "bullish_fvg"   # gap to the upside
    BEARISH = "bearish_fvg"   # gap to the downside


class SweepDirection(Enum):
    BULLISH = "bullish_sweep"   # sweep of low → reversal up
    BEARISH = "bearish_sweep"   # sweep of high → reversal down


class StructureDirection(Enum):
    BULLISH = "bullish_structure"   # higher highs, higher lows
    BEARISH = "bearish_structure" # lower highs, lower lows


@dataclass
class OrderBlock:
    symbol: str
    timeframe: str
    ob_type: OBType
    zone_high: float   # top of the OB zone
    zone_low: float    # bottom of the OB zone
    strength: float    # 0-1 (body/wick ratio heuristic)
    candles: int       # how many qualifying candles formed this OB
    created_at: datetime
    triggered_at: Optional[datetime] = None


@dataclass
class FairValueGap:
    symbol: str
    timeframe: str
    direction: FVGDirection
    gap_top: float
    gap_bottom: float
    mid: float
    created_at: datetime
    filled: bool = False
    filled_at: Optional[datetime] = None


@dataclass
class LiquiditySweep:
    symbol: str
    timeframe: str
    direction: SweepDirection
    sweep_price: float
    level_type: str          # "swing_high" | "swing_low"
    reversal_candle_ts: int  # timestamp of reversal candle
    created_at: datetime


@dataclass
class MarketStructure:
    symbol: str
    timeframe: str
    direction: StructureDirection
    bos_type: str            # "bullish_bos" | "bearish_bos" | "chocolate"
    break_price: float
    prev_swing_high: float
    prev_swing_low: float
    created_at: datetime


@dataclass
class BTCTrend:
    trend: str               # "bullish" | "bearish" | "neutral"
    price: float
    timeframe: str
    updated_at: datetime


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_klines(raw: list) -> list[dict]:
    """Convert raw Binance kline list to dicts."""
    parsed = []
    for k in raw:
        parsed.append({
            "open_time":     int(k[0]),
            "open":          float(k[1]),
            "high":          float(k[2]),
            "low":           float(k[3]),
            "close":         float(k[4]),
            "volume":        float(k[5]),
            "close_time":    int(k[6]),
            "quote_volume":  float(k[7]),
            "trades":        int(k[8]),
            "is_bullish":    float(k[4]) > float(k[1]),
        })
    return parsed


async def fetch_klines(
    symbol: str,
    interval: str = "1h",
    limit: int = 200,
    retries: int = 3,
) -> list[dict]:
    """Fetch klines from Binance public REST API."""
    params = {
        "symbol":   symbol.upper(),
        "interval": interval,
        "limit":    limit,
    }
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(_BINANCE_KLINE, params=params)
                resp.raise_for_status()
                return _parse_klines(resp.json())
        except Exception as e:
            log.warning("fetch_klines %s %s attempt %d failed: %s", symbol, interval, attempt + 1, e)
            await asyncio.sleep(2 ** attempt)
    return []


# ── SMC Engine ────────────────────────────────────────────────────────────────

class SMCEngine:
    """Pure-Python SMC detection on a single symbol's kline list."""

    def __init__(self, symbol: str, timeframe: str, lookback: int = 100):
        self.symbol = symbol
        self.timeframe = timeframe
        self.lookback = lookback
        self._klines: list[dict] = []

    # ── kline management ──────────────────────────────────────────────────────

    def update(self, klines: list[dict]):
        self._klines = klines[-self.lookback:]

    @property
    def closes(self) -> list[float]:
        return [k["close"] for k in self._klines]

    @property
    def highs(self) -> list[float]:
        return [k["high"] for k in self._klines]

    @property
    def lows(self) -> list[float]:
        return [k["low"] for k in self._klines]

    # ── Order Blocks ──────────────────────────────────────────────────────────

    def detect_order_blocks(self, min_candles: int = 2) -> list[OrderBlock]:
        """Detect bullish and bearish order blocks.

        Bullish OB  = last N candles are bearish with a low wick
 (body below midpoint, wick extends below)
        Bearish OB  = last N candles are bullish with a high wick
                      (body above midpoint, wick extends above)
        """
        obs: list[OrderBlock] = []
        klines = self._klines
        if len(klines) < min_candles + 1:
            return obs

        now = datetime.now()

        for i in range(len(klines) - min_candles, len(klines)):
            block_candles = klines[i - min_candles + 1 : i + 1]
            if len(block_candles) < min_candles:
                continue

            # ── Bullish OB ──────────────────────────────────────────────────
            if all(not c["is_bullish"] for c in block_candles):
                bodies = [max(c["open"], c["close"]) for c in block_candles]
                wicks = [c["low"] for c in block_candles]
                body_top = max(bodies)
                wick_bottom = min(wicks)
                # valid if wick extends meaningfully below body
                if wick_bottom < body_top * 0.999:
                    zone_high = body_top
                    zone_low  = wick_bottom
                    strength = 1 - (zone_high - zone_low) / zone_high
                    obs.append(OrderBlock(
                        symbol=self.symbol,
                        timeframe=self.timeframe,
                        ob_type=OBType.BULLISH,
                        zone_high=zone_high,
                        zone_low=zone_low,
                        strength=max(0, min(1, strength)),
                        candles=len(block_candles),
                        created_at=now,
                    ))

            # ── Bearish OB ─────────────────────────────────────────────────
            if all(c["is_bullish"] for c in block_candles):
                bodies = [min(c["open"], c["close"]) for c in block_candles]
                wicks  = [c["high"] for c in block_candles]
                body_bottom = min(bodies)
                wick_top    = max(wicks)
                if wick_top > body_bottom * 1.001:
                    zone_high = wick_top
                    zone_low  = body_bottom
                    strength  = 1 - (zone_high - zone_low) / zone_high
                    obs.append(OrderBlock(
                        symbol=self.symbol,
                        timeframe=self.timeframe,
                        ob_type=OBType.BEARISH,
                        zone_high=zone_high,
                        zone_low=zone_low,
                        strength=max(0, min(1, strength)),
                        candles=len(block_candles),
                        created_at=now,
                    ))

        return obs

    # ── Fair Value Gaps ───────────────────────────────────────────────────────

    def detect_fvg(self) -> list[FairValueGap]:
        """Detect 3-candle Fair Value Gaps (imbalance gaps).

        Bullish FVG = middle candle gaps below: high_1 > low_3 and close_2< open_2
        Bearish FVG = middle candle gaps above: low_1  < high_3 and close_2 > open_2
        """
        fvgs: list[FairValueGap] = []
        klines = self._klines
        if len(klines) < 3:
            return fvgs

        now = datetime.now()

        for i in range(1, len(klines) - 1):
            c1, c2, c3 = klines[i - 1], klines[i], klines[i + 1]

            # Bullish FVG: middle candle is bearish, gaps below
            if (c2["high"] < c1["low"] * 0.999) and (c2["close"] < c2["open"]):
                gap_top = c1["low"]
                gap_bottom = c2["high"]
                fvgs.append(FairValueGap(
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    direction=FVGDirection.BULLISH,
                    gap_top=gap_top,
                    gap_bottom=gap_bottom,
                    mid=(gap_top + gap_bottom) / 2,
                    created_at=now,
                ))

            # Bearish FVG: middle candle is bullish, gaps above
            elif (c3["high"] > c2["low"] * 1.001) and (c2["close"] > c2["open"]):
                gap_top    = c2["low"]
                gap_bottom = c3["high"]
                fvgs.append(FairValueGap(
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    direction=FVGDirection.BEARISH,
                    gap_top=gap_top,
                    gap_bottom=gap_bottom,
                    mid=(gap_top + gap_bottom) / 2,
                    created_at=now,
                ))

        return fvgs

    # ── Liquidity Sweeps ──────────────────────────────────────────────────────

    def detect_liquidity_sweeps(
        self,
        lookback: int = 20,
        sweep_threshold: float = 0.003,
    ) -> list[LiquiditySweep]:
        """Detect stop-hunts: price closes beyond recent swing high/low.

        A sweep is confirmed when price spikes beyond the level but closes
        back inside, and the next candle reverses.
        """
        sweeps: list[LiquiditySweep] = []
        klines = self._klines
        if len(klines) < lookback + 2:
            return sweeps

        now = datetime.now()

        for i in range(lookback, len(klines)):
            window = klines[i - lookback : i]
            recent = klines[i]

            swing_high = max(c["high"] for c in window)
            swing_low  = min(c["low"]  for c in window)

            # Bullish sweep: price spikes below swing low, then reverses up
            if recent["low"] < swing_low * (1 - sweep_threshold):
                if recent["close"] > recent["open"]:
                    sweeps.append(LiquiditySweep(
                        symbol=self.symbol,
                        timeframe=self.timeframe,
                        direction=SweepDirection.BULLISH,
                        sweep_price=recent["low"],
                        level_type="swing_low",
                        reversal_candle_ts=recent["close_time"],
                        created_at=now,
                    ))

            # Bearish sweep: price spikes above swing high, then reverses down
            elif recent["high"] > swing_high * (1 + sweep_threshold):
                if recent["close"] < recent["open"]:
                    sweeps.append(LiquiditySweep(
                        symbol=self.symbol,
                        timeframe=self.timeframe,
                        direction=SweepDirection.BEARISH,
                        sweep_price=recent["high"],
                        level_type="swing_high",
                        reversal_candle_ts=recent["close_time"],
                        created_at=now,
                    ))

        return sweeps

    # ── Market Structure ───────────────────────────────────────────────────────

    def detect_market_structure(
        self,
        swing_window: int = 5,
    ) -> list[MarketStructure]:
        """Detect swing highs/lows and Break-of-Structure (BOS).

        A swing high is the highest high in a local window.
        A swing low is the lowest low  in a local window.
        BOS = price breaks above last swing high (bullish) or below last swing low (bearish).
        """
        structures: list[MarketStructure] = []
        klines = self._klines
        if len(klines) < swing_window * 2 + 1:
            return structures

        now = datetime.now()

        # Find swing points
        swing_highs: list[tuple[int, float]] = []   # (index, price)
        swing_lows:  list[tuple[int, float]] = []

        for i in range(swing_window, len(klines) - swing_window):
            window = klines[i - swing_window : i + swing_window + 1]
            center = klines[i]
            if center["high"] == max(c["high"] for c in window):
                swing_highs.append((i, center["high"]))
            if center["low"] == min(c["low"] for c in window):
                swing_lows.append((i, center["low"]))

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return structures

        # Determine trend via sequential HH/HL or LH/LL
        last_hh = swing_highs[-1]
        prev_hh = swing_highs[-2]
        last_hl = swing_lows[-1]
        prev_hl = swing_lows[-2]

        # Bullish BOS: price breaks above last swing high
        if klines[-1]["close"] > last_hh[1] and prev_hh[1] > last_hh[1]:
            structures.append(MarketStructure(
                symbol=self.symbol,
                timeframe=self.timeframe,
                direction=StructureDirection.BULLISH,
                bos_type="bullish_bos",
                break_price=klines[-1]["close"],
                prev_swing_high=last_hh[1],
                prev_swing_low=last_hl[1],
                created_at=now,
            ))

        # Bearish BOS: price breaks below last swing low
        elif klines[-1]["close"] < last_hl[1] and prev_hl[1] < last_hl[1]:
            structures.append(MarketStructure(
                symbol=self.symbol,
                timeframe=self.timeframe,
                direction=StructureDirection.BEARISH,
                bos_type="bearish_bos",
                break_price=klines[-1]["close"],
                prev_swing_high=last_hh[1],
                prev_swing_low=last_hl[1],
                created_at=now,
            ))

        return structures


# ── BTC Trend ──────────────────────────────────────────────────────────────────

async def fetch_btc_trend(
    interval: str = "1h",
    lookback: int = 50,
) -> BTCTrend:
    """Determine BTC trend from its own klines."""
    klines = await fetch_klines(_BTC_SYMBOL, interval=interval, limit=lookback)
    if not klines:
        return BTCTrend(trend="neutral", price=0, timeframe=interval, updated_at=datetime.now())

    closes = [k["close"] for k in klines]
    highs = [k["high"]  for k in klines]
    lows   = [k["low"]   for k in klines]

    # Simple trend: compare latest close to20-period SMA
    period = min(20, len(closes) - 1)
    sma = sum(closes[-period:]) / period
    latest_close = closes[-1]
    price = klines[-1]["close"]

    if latest_close > sma * 1.005:
        trend = "bullish"
    elif latest_close < sma * 0.995:
        trend = "bearish"
    else:
        trend = "neutral"

    return BTCTrend(
        trend=trend,
        price=price,
        timeframe=interval,
        updated_at=datetime.now(),
    )


# ── SMC Scanner ───────────────────────────────────────────────────────────────

class SMCScanner:
    """Smart Money Concepts scanner using Binance REST klines (no API key).

    Polls Binance public kline API every `poll_interval` seconds.
    Detects SMC events and fires callbacks. Thread-safe state access.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        timeframe: str = "1h",
        poll_interval: int = 60,
        lookback: int = 200,
        btc_filter: bool = True,
    ):
        """
        symbols : list of symbols to scan (None = default list)
        timeframe : kline interval (1m, 5m, 15m, 1h, 4h, 1d…)
        poll_interval  : seconds between polls
        lookback       : number of klines to fetch per request
        btc_filter     : if True, ignore bearish events when BTC is bullish
        """
        self.symbols = symbols or [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
            "XRPUDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
        ]
        self.timeframe = timeframe
        self.poll_interval = poll_interval
        self.lookback     = lookback
        self.btc_filter   = btc_filter

        # Per-symbol engines
        self._engines: dict[str, SMCEngine] = {
            s: SMCEngine(s, timeframe, lookback) for s in self.symbols
        }

        # Active events (thread-safe via _lock)
        self._ob:       list[OrderBlock]       = []
        self._fvg:       list[FairValueGap]     = []
        self._sweeps:    list[LiquiditySweep] = []
        self._structure: list[MarketStructure] = []
        self._btc_trend: BTCTrend = BTCTrend(
            trend="neutral", price=0, timeframe=timeframe, updated_at=datetime.now()
        )
        self._lock = Lock()

        # Async state
        self._task: Optional[asyncio.Task] = None
        self._running = False

        # Callbacks: (event) -> None
        self._callbacks: list[Callable] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def add_callback(self, cb: Callable):
        """Register a callback invoked on every new SMC event."""
        self._callbacks.append(cb)

    async def start(self):
        """Start the polling loop."""
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("SMCScanner: started (%d symbols, %s)", len(self.symbols), self.timeframe)

    async def stop(self):
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("SMCScanner: stopped")

    def get_active_ob(self) -> list[OrderBlock]:
        with self._lock:
            return list(self._ob)

    def get_active_fvg(self) -> list[FairValueGap]:
        with self._lock:
            return list(self._fvg)

    def get_active_sweeps(self) -> list[LiquiditySweep]:
        with self._lock:
            return list(self._sweeps)

    def get_active_structure(self) -> list[MarketStructure]:
        with self._lock:
            return list(self._structure)

    def get_btc_trend(self) -> BTCTrend:
        with self._lock:
            return self._btc_trend

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _run(self):
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_all()
            except Exception as e:
                log.warning("SMCScanner._poll_all error: %s", e)
            await asyncio.sleep(self.poll_interval)

    async def _poll_all(self):
        """Poll all symbols and update state."""
        # Update BTC trend first (master filter)
        if self.btc_filter:
            self._btc_trend = await fetch_btc_trend(
                interval=self.timeframe, lookback=50
            )

        # Poll all symbols concurrently
        async def poll_one(symbol: str) -> tuple[str, list[dict]]:
            klines = await fetch_klines(symbol, interval=self.timeframe, limit=self.lookback)
            return symbol, klines

        results = await asyncio.gather(
            *[poll_one(s) for s in self.symbols],
            return_exceptions=True,
        )

        now = datetime.now()
        new_ob: list[OrderBlock]       = []
        new_fvg:      list[FairValueGap]     = []
        new_sweeps:   list[LiquiditySweep]   = []
        new_struct:   list[MarketStructure]  = []

        for result in results:
            if isinstance(result, Exception):
                log.warning("SMCScanner poll error: %s", result)
                continue
            symbol, klines = result
            if not klines:
                continue

            engine = self._engines.get(symbol)
            if engine is None:
                continue
            engine.update(klines)

            # Detect events
            obs = engine.detect_order_blocks(min_candles=2)
            fvgs    = engine.detect_fvg()
            sweeps = engine.detect_liquidity_sweeps(lookback=20, sweep_threshold=0.003)
            structs = engine.detect_market_structure(swing_window=5)

            new_ob.extend(obs)
            new_fvg.extend(fvgs)
            new_sweeps.extend(sweeps)
            new_struct.extend(structs)

        # Apply BTC master filter
        if self.btc_filter:
            new_ob    = self._filter_ob(new_ob)
            new_fvg   = self._filter_fvg(new_fvg)
            new_sweeps = self._filter_sweeps(new_sweeps)
            new_struct = self._filter_struct(new_struct)

        # Update state under lock
        with self._lock:
            self._ob       = new_ob
            self._fvg      = new_fvg
            self._sweeps   = new_sweeps
            self._structure = new_struct

        # Fire callbacks
        for cb in self._callbacks:
            try:
                cb(new_ob, new_fvg, new_sweeps, new_struct)
            except Exception as e:
                log.error("SMCScanner callback error: %s", e)

    # ── BTC Filter ────────────────────────────────────────────────────────────

    def _filter_ob(self, obs: list[OrderBlock]) -> list[OrderBlock]:
        if self._btc_trend.trend == "bearish":
            return [ob for ob in obs if ob.ob_type == OBType.BULLISH]
        if self._btc_trend.trend == "bullish":
            return [ob for ob in obs if ob.ob_type == OBType.BEARISH]
        return obs

    def _filter_fvg(self, fvgs: list[FairValueGap]) -> list[FairValueGap]:
        if self._btc_trend.trend == "bearish":
            return [f for f in fvgs if f.direction == FVGDirection.BULLISH]
        if self._btc_trend.trend == "bullish":
            return [f for f in fvgs if f.direction == FVGDirection.BEARISH]
        return fvgs

    def _filter_sweeps(self, sweeps: list[LiquiditySweep]) -> list[LiquiditySweep]:
        if self._btc_trend.trend == "bearish":
            return [s for s in sweeps if s.direction == SweepDirection.BULLISH]
        if self._btc_trend.trend == "bullish":
            return [s for s in sweeps if s.direction == SweepDirection.BEARISH]
        return sweeps

    def _filter_struct(self, structs: list[MarketStructure]) -> list[MarketStructure]:
        if self._btc_trend.trend == "bearish":
            return [s for s in structs if s.direction == StructureDirection.BULLISH]
        if self._btc_trend.trend == "bullish":
            return [s for s in structs if s.direction == StructureDirection.BEARISH]
        return structs

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary_text(self) -> str:
        """Telegram-formatted summary of all active SMC events."""
        with self._lock:
            obs = list(self._ob)
            fvgs     = list(self._fvg)
            sweeps   = list(self._sweeps)
            structs  = list(self._structure)
            btc_trend = self._btc_trend

        lines = ["📊 *SMC Scan*"]

        # BTC header
        btc_emoji = "🟢" if btc_trend.trend == "bullish" else ("🔴" if btc_trend.trend == "bearish" else "⚪")
        lines.append(f"{btc_emoji} BTC: {btc_trend.trend.upper()} | ${btc_trend.price:,.0f}")
        lines.append("")

        if not any([obs, fvgs, sweeps, structs]):
            lines.append("No active SMC signals.")
            return "\n".join(lines)

        # Order Blocks
        if obs:
            lines.append("📦 *Order Blocks:*")
            for ob in obs[:5]:
                emoji = "🟢" if ob.ob_type == OBType.BULLISH else "🔴"
                lines.append(
                    f"{emoji} {ob.symbol} {ob.timeframe} | "
                    f"Zone: {ob.zone_low:.4f}–{ob.zone_high:.4f} | "
                    f"Str: {ob.strength:.0%}"
                )
            lines.append("")

        # Fair Value Gaps
        if fvgs:
            lines.append("🌊 *Fair Value Gaps:*")
            for f in fvgs[:5]:
                emoji = "🟢" if f.direction == FVGDirection.BULLISH else "🔴"
                lines.append(
                    f"{emoji} {f.symbol} {f.timeframe} | "
                    f"Gap: {f.gap_bottom:.4f}–{f.gap_top:.4f}"
                )
            lines.append("")

        # Liquidity Sweeps
        if sweeps:
            lines.append("💧 *Liquidity Sweeps:*")
            for s in sweeps[:5]:
                emoji = "🟢" if s.direction == SweepDirection.BULLISH else "🔴"
                lines.append(
                    f"{emoji} {s.symbol} {s.timeframe} | "
                    f"{s.level_type} @ {s.sweep_price:.4f}"
                )
            lines.append("")

        # Market Structure
        if structs:
            lines.append("🏛 *Market Structure:*")
            for s in structs[:5]:
                emoji = "🟢" if s.direction == StructureDirection.BULLISH else "🔴"
                lines.append(
                    f"{emoji} {s.symbol} {s.timeframe} | "
                    f"{s.bos_type} @ {s.break_price:.4f}"
                )
            lines.append("")

        return "\n".join(lines).rstrip()
