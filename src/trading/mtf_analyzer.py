"""MTF Analyzer — Multi-Timeframe (15m / 1h / 4h) trend & signal analysis.

Fetches candles for 15m, 1h and 4h timeframes, computes EMAs, RSI, ADX
on each, then produces a consolidated MTF verdict:
  - Confluence: all 3 timeframes agree on direction
  - Divergence: higher TF disagrees with lower TF
  - Trend quality score (0-100)

Public API
----------
MTFAnalyzer(engine, symbol)
    await run()              -> fetch all 3 TFs and compute indicators
    verdict()                -> dict with mtf_signal, confluence, trend_score
    summary_text()           -> Telegram-formatted string

Usage
-----
    mtf = MTFAnalyzer(engine, "BTC/USDT")
    await mtf.run()
    print(mtf.verdict())
    print(mtf.summary_text())
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .signals import compute_ema, compute_rsi, compute_adx
from ..utils.logger import log


# ── Timeframe definitions ──────────────────────────────────────────────────────

TF_15M = "15m"
TF_1H  = "1h"
TF_4H  = "4h"

DEFAULT_TFS = [TF_15M, TF_1H, TF_4H]

# How many candles to fetch per timeframe
TF_LIMITS: dict[str, int] = {
    TF_15M: 300,   # ~3 days of 15m
    TF_1H:  200,   # ~8 days of 1h
    TF_4H:  200,   # ~33 days of 4h
}


# ── Per-timeframe indicators ───────────────────────────────────────────────────

@dataclass
class TFIndicators:
    timeframe:    str
    closes:       list[float]    = field(default_factory=list)
    highs:        list[float]    = field(default_factory=list)
    lows:         list[float]    = field(default_factory=list)
    ema_fast:     float = 0.0
    ema_mid:      float = 0.0
    ema_slow:     float = 0.0
    ema_fast_prev: float = 0.0
    ema_mid_prev:  float = 0.0
    rsi:          float = 50.0
    adx:          float = 0.0
    atr:          float = 0.0
    ema_slope_pct: float = 0.0   # % change of slow EMA over last N bars
    trend:        str   = "sideway"   # "bullish" | "bearish" | "sideway"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe":      self.timeframe,
            "ema_fast":       round(self.ema_fast, 4),
            "ema_mid":        round(self.ema_mid, 4),
            "ema_slow":       round(self.ema_slow, 4),
            "rsi":            round(self.rsi, 1),
            "adx":            round(self.adx, 1),
            "atr":            round(self.atr, 4),
            "ema_slope_pct":  round(self.ema_slope_pct, 4),
            "trend":          self.trend,
        }


# ── MTF Verdict ────────────────────────────────────────────────────────────────

@dataclass
class MTFVerdict:
    mtf_signal:   str   = "neutral"    # "LONG" | "SHORT" | "neutral"
    confluence:   str   = "none"       # "high" | "medium" | "low" | "none"
    trend_score:  int   = 0            # 0-100
    quality:      str   = "low"        # "high" | "medium" | "low"
    reason:       str   = ""
    tf_15m:       dict  = field(default_factory=dict)
    tf_1h:        dict  = field(default_factory=dict)
    tf_4h:        dict  = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mtf_signal":  self.mtf_signal,
            "confluence":  self.confluence,
            "trend_score": self.trend_score,
            "quality":     self.quality,
            "reason":      self.reason,
            "15m":         self.tf_15m,
            "1h":          self.tf_1h,
            "4h":          self.tf_4h,
        }

    def is_bullish(self) -> bool:
        return self.mtf_signal == "LONG"

    def is_bearish(self) -> bool:
        return self.mtf_signal == "SHORT"

    def has_confluence(self) -> bool:
        return self.confluence in ("high", "medium")


# ── ATR helper ─────────────────────────────────────────────────────────────────

def compute_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        h_l = highs[i] - lows[i]
        h_c = abs(highs[i] - closes[i - 1])
        l_c = abs(lows[i]  - closes[i - 1])
        trs.append(max(h_l, h_c, l_c))
    if len(trs) < period:
        return 0.0
    return sum(trs[-period:]) / period


# ── MTFAnalyzer ─────────────────────────────────────────────────────────────────

class MTFAnalyzer:
    """Multi-timeframe trend analyser.

    Parameters
    ----------
    engine : TradingEngine
        The shared TradingEngine instance (provides fetch_ohlcv).
    symbol : str
        Trading symbol, e.g. "BTC/USDT".
    timeframes : list[str]
        Timeframes to analyse. Default [TF_15M, TF_1H, TF_4H].
    fetch_limit : int | None
        Override candle limits per timeframe. None = use TF_LIMITS defaults.
    """

    def __init__(
        self,
        engine: Any,            # TradingEngine (has fetch_ohlcv method)
        symbol: str,
        timeframes: list[str] | None = None,
        fetch_limit: int | None = None,
    ):
        self.engine  = engine
        self.symbol  = symbol
        self.tfs     = timeframes or DEFAULT_TFS
        self.limit   = fetch_limit

        # Results
        self.tf_data:   dict[str, TFIndicators] = {}
        self._verdict:  MTFVerdict | None = None
        self._ran       = False

        # EMA periods (fast/mid/slow)
        self._ema_fast = 9
        self._ema_mid  = 21
        self._ema_slow = 50

    # ── Public API ─────────────────────────────────────────────────────────────

    async def run(self) -> MTFVerdict:
        """Fetch all timeframes and compute indicators. Returns MTFVerdict."""
        self.tf_data = {}
        self._ran = False

        # Fetch all TFs concurrently
        async def fetch_tf(tf: str) -> tuple[str, list]:
            limit = self.limit or TF_LIMITS.get(tf, 200)
            try:
                candles = await self.engine.fetch_ohlcv(self.symbol, tf, limit=limit)
            except Exception as e:
                log.debug("MTF fetch_ohlcv %s %s failed: %s", self.symbol, tf, e)
                candles = []
            return tf, candles

        results = await asyncio.gather(*[fetch_tf(tf) for tf in self.tfs])

        for tf, candles in results:
            if candles and len(candles) >= 20:
                self.tf_data[tf] = self._compute_indicators(tf, candles)
            else:
                log.debug("MTF: insufficient candles for %s TF=%s (%d)",
                          self.symbol, tf, len(candles) if candles else 0)

        self._verdict = self._build_verdict()
        self._ran = True
        return self._verdict

    def verdict(self) -> MTFVerdict:
        """Return cached verdict. Raises RuntimeError if run() not called first."""
        if not self._ran:
            raise RuntimeError("MTFAnalyzer.run() must be called before verdict()")
        return self._verdict

    def summary_text(self) -> str:
        """Telegram-friendly multi-line MTF summary."""
        if not self._ran or self._verdict is None:
            return "⚠️ MTF not yet run."

        v = self._verdict
        lines = [
            f"📊 *MTF — {self.symbol}*",
            f"Signal: *{v.mtf_signal}*  |  Confluence: *{v.confluence}*  |  Score: *{v.trend_score}*",
            "",
        ]

        for label, tf_key in [("15m", TF_15M), ("1h", TF_1H), ("4h", TF_4H)]:
            ind = self.tf_data.get(tf_key)
            if ind is None:
                lines.append(f"{label}: — no data")
                continue
            trend_icon = "🟢" if ind.trend == "bullish" else "🔴" if ind.trend == "bearish" else "⚪"
            lines.append(
                f"{trend_icon} {label}: EMA{ind.ema_fast:.1f}/{ind.ema_mid:.1f}/{ind.ema_slow:.1f}  "
                f"RSI={ind.rsi:.0f}  ADX={ind.adx:.0f}"
            )

        if v.reason:
            lines.append("")
            lines.append(f"▸ {v.reason}")

        return "\n".join(lines)

    # ── Indicator computation ─────────────────────────────────────────────────

    def _compute_indicators(self, tf: str, candles: list[list]) -> TFIndicators:
        closes = [float(c[4]) for c in candles]
        highs  = [float(c[2]) for c in candles]
        lows   = [float(c[3]) for c in candles]

        ind = TFIndicators(timeframe=tf, closes=closes, highs=highs, lows=lows)

        # EMA
        ind.ema_fast      = compute_ema(closes, self._ema_fast)
        ind.ema_mid       = compute_ema(closes, self._ema_mid)
        ind.ema_slow      = compute_ema(closes, self._ema_slow)
        ind.ema_fast_prev = compute_ema(closes[:-3], self._ema_fast)
        ind.ema_mid_prev  = compute_ema(closes[:-3], self._ema_mid)

        # RSI & ADX
        ind.rsi = compute_rsi(closes, 14)
        ind.adx = compute_adx(highs, lows, closes, 14)

        # ATR
        ind.atr = compute_atr(highs, lows, closes, 14)

        # EMA slope (% change of slow EMA over last 10 bars)
        if len(closes) >= 20:
            prev_slow = compute_ema(closes[:-10], self._ema_slow)
            ind.ema_slope_pct = (ind.ema_slow - prev_slow) / prev_slow * 100 if prev_slow else 0
        elif ind.ema_slow and len(closes) >= 2:
            prev_slow = compute_ema(closes[:-1], self._ema_slow)
            ind.ema_slope_pct = (ind.ema_slow - prev_slow) / prev_slow * 100 if prev_slow else 0

        # Trend on this TF
        ind.trend = self._tf_trend(ind)

        return ind

    def _tf_trend(self, ind: TFIndicators) -> str:
        """Determine single-TF trend from EMA arrangement + slope."""
        bull = ind.ema_fast > ind.ema_mid > ind.ema_slow and ind.ema_slope_pct > 0.001
        bear = ind.ema_fast < ind.ema_mid < ind.ema_slow and ind.ema_slope_pct < -0.001
        if bull:
            return "bullish"
        if bear:
            return "bearish"
        return "sideway"

    # ── MTF verdict ────────────────────────────────────────────────────────────

    def _build_verdict(self) -> MTFVerdict:
        v = MTFVerdict()

        # Populate per-TF dicts
        for tf_key, label in [(TF_15M, "15m"), (TF_1H, "1h"), (TF_4H, "4h")]:
            ind = self.tf_data.get(tf_key)
            if ind:
                d = ind.to_dict()
                if label == "15m": v.tf_15m = d
                elif label == "1h": v.tf_1h = d
                else: v.tf_4h = d

        if not self.tf_data:
            v.reason = "No TF data available"
            return v

        # ── Step 1: Align trends across timeframes ───────────────────────────
        # Priority: 4h > 1h > 15m (higher TFs override lower)
        tf_4h = self.tf_data.get(TF_4H)
        tf_1h = self.tf_data.get(TF_1H)
        tf_15m = self.tf_data.get(TF_15M)

        trends = {
            TF_4H:  tf_4h.trend  if tf_4h  else "unknown",
            TF_1H:  tf_1h.trend  if tf_1h  else "unknown",
            TF_15M: tf_15m.trend if tf_15m else "unknown",
        }

        # ── Step 2: Count bullish / bearish TFs ──────────────────────────────
        bull_count = sum(1 for t in trends.values() if t == "bullish")
        bear_count = sum(1 for t in trends.values() if t == "bearish")

        # ── Step 3: Higher-TF alignment check ────────────────────────────────
        # Confluence = high: all 3 agree, medium: 2+ agree, low: 1 agrees
        if bull_count >= 2:
            v.mtf_signal = "LONG"
        elif bear_count >= 2:
            v.mtf_signal = "SHORT"
        else:
            v.mtf_signal = "neutral"

        # Confluence
        if bull_count == 3 or bear_count == 3:
            v.confluence = "high"
        elif bull_count == 2 or bear_count == 2:
            v.confluence = "medium"
        elif bull_count == 1 or bear_count == 1:
            v.confluence = "low"
        else:
            v.confluence = "none"

        # ── Step 4: Trend quality score (0-100) ──────────────────────────────
        score = self._calc_trend_score(trends)
        v.trend_score = score

        if   score >= 75: v.quality = "high"
        elif score >= 50: v.quality = "medium"
        else:             v.quality = "low"

        # ── Step 5: Build reason string ──────────────────────────────────────
        reasons = []
        for tf_key, label in [(TF_4H, "4h"), (TF_1H, "1h"), (TF_15M, "15m")]:
            ind = self.tf_data.get(tf_key)
            if ind:
                reasons.append(
                    f"{label}:{ind.trend[0].upper()}"
                    f"(RSI={ind.rsi:.0f},ADX={ind.adx:.0f})"
                )
        v.reason = " | ".join(reasons)

        return v

    def _calc_trend_score(self, trends: dict[str, str]) -> int:
        """Score 0-100: how strong is the multi-TF trend?"""
        # Higher TF trends carry more weight
        weights = {TF_4H: 50, TF_1H: 30, TF_15M: 20}
        score = 0

        for tf, trend in trends.items():
            w = weights.get(tf, 10)
            if trend == "bullish":
                score += w
            elif trend == "bearish":
                score += w   # same absolute value; sign handled by direction

        # Convert to 0-100 (max possible = 4h+1h+15m = 50+30+20 = 100)
        return min(100, max(0, score))

    # ── Convenience class methods ───────────────────────────────────────────────

    @staticmethod
    def filter_by_regime(
        verdict: MTFVerdict,
        regime: str,
    ) -> bool:
        """Return True if the MTF signal is compatible with the given regime."""
        if regime == "sideway":
            return verdict.confluence == "high"   # only trade high-confluence in sideway
        if regime == "bullish" and verdict.mtf_signal == "SHORT":
            return False
        if regime == "bearish" and verdict.mtf_signal == "LONG":
            return False
        return True

    @staticmethod
    def direction_multiplier(verdict: MTFVerdict) -> float:
        """Return a position-size multiplier (0.0-1.0) based on MTF quality."""
        if verdict.quality == "high":
            return 1.0
        if verdict.quality == "medium":
            return 0.75
        return 0.5