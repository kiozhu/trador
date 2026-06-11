"""StrategyScorer — aggregate scoring and selection across multiple strategies.

Given a list of active strategy configs and a shared market context (candles,
regime, scanner signals), StrategyScorer produces a unified ranked list of
trade candidates and handles the multi-strategy selection logic used in
Smart Mode.

Public API
----------
StrategyScorer(candles, regime, scanner_context)
    .score_all(strategies, symbol)   -> list[dict]  ranked trade signals
    .top_n(n)                        -> list[dict]  top N candidates
    .regime_weight(regime)           -> float        0.0-1.0 multiplier
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .signals import generate_signal, compute_ema, compute_rsi, check_ema_crossover, compute_adx
from ..utils.logger import log


# ── Score breakdown weights ─────────────────────────────────────────────────────

@dataclass
class ScoreWeights:
    """Normalisation weights for signal components. Tune via strategy config."""
    base_momentum:   int = 20   # EMA crossover / alignment
    rsi_edge:        int = 10   # RSI oversold / overbought reversion
    adx_filter:      int = 15   # trending market confirmation
    scanner_bonus:   int = 25   # scanner signals (whale / liq / SMC …)
    regime_fit:      int = 20   # regime alignment (bull/bear/side)
    score_threshold: int = 65   # minimum composite score to fire

    @classmethod
    def from_strategy(cls, strat: dict) -> "ScoreWeights":
        w = strat.get("scoring_weights", {})
        return cls(
            base_momentum  =w.get("base_momentum",  20),
            rsi_edge       =w.get("rsi_edge",       10),
            adx_filter     =w.get("adx_filter",     15),
            scanner_bonus  =w.get("scanner_bonus",  25),
            regime_fit     =w.get("regime_fit",     20),
            score_threshold=strat.get("min_score",  65),
        )


# ── Composite signal ────────────────────────────────────────────────────────────

@dataclass
class ScoredSignal:
    """A trade signal with its full scoring breakdown."""
    symbol:        str
    side:          str          # "LONG" | "SHORT"
    entry_price:   float
    sl_pct:        float
    tp_pct:        float
    leverage:      int
    score:         int
    min_score:     int
    breakdown:     dict[str, int]  # component → points awarded
    scanner_signals: list[str]
    strategy_id:   str
    regime:        str
    reason:        str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol":          self.symbol,
            "side":            self.side,
            "entry_price":     self.entry_price,
            "sl_pct":          self.sl_pct,
            "tp_pct":          self.tp_pct,
            "leverage":        self.leverage,
            "score":           self.score,
            "min_score":       self.min_score,
            "breakdown":       self.breakdown,
            "scanner_signals": self.scanner_signals,
            "strategy_id":     self.strategy_id,
            "regime":          self.regime,
            "reason":          self.reason,
        }


# ── StrategyScorer ─────────────────────────────────────────────────────────────

class StrategyScorer:
    """Aggregate scorer for multi-strategy (Smart Mode) environments.

    Parameters
    ----------
    candles : list[list]
        OHLCV list in ccxt format [ts, open, high, low, close, vol].
    regime : str
        Market regime: "bullish" | "bearish" | "sideway".
    scanner_context : dict
        Scanner data collected by AutoTrader, e.g.:
        {
            "whale_clusters":   [...WhaleCluster],
            "liq_clusters":    [...Cluster],
            "smc_ob":          [...OrderBlock],
            "smc_fvg":         [...FairValueGap],
            "smc_sweeps":      [...LiquiditySweep],
            "smc_structure":   [...MarketStructure],
            "funding_rates":   [...FundingRateEvent],
            "vp_profiles":     {symbol: VolumeProfile},
        }
    """

    def __init__(
        self,
        candles: list[list],
        regime: str,
        scanner_context: dict | None = None,
    ):
        self.candles = candles
        self.closes  = [c[4] for c in candles]
        self.highs   = [c[2] for c in candles]
        self.lows    = [c[3] for c in candles]
        self.regime  = regime
        self.scanner = scanner_context or {}

        self._signals: list[ScoredSignal] = []

    # ── High-level API ─────────────────────────────────────────────────────────

    def score_all(
        self,
        strategies: list[dict[str, Any]],
        symbol: str,
    ) -> list[dict[str, Any]]:
        """Score all strategies against the same candles, return ranked list.

        Returns
        -------
        list[dict]
            Sorted descending by composite score. Each dict is a trade signal
            suitable for passing to AutoTrader._execute_trade.
        """
        self._signals = []

        if not self.candles or len(self.candles) < 20:
            log.debug("score_all: insufficient candles for %s", symbol)
            return []

        for strat in strategies:
            sig = self._score_one(strat, symbol)
            if sig is not None:
                self._signals.append(sig)

        # Sort descending by score
        self._signals.sort(key=lambda s: s.score, reverse=True)

        return [s.to_dict() for s in self._signals]

    def top_n(self, n: int = 2) -> list[dict[str, Any]]:
        """Return the top N trade signals (newest scored run)."""
        return [s.to_dict() for s in self._signals[:n]]

    # ── Per-strategy scoring ────────────────────────────────────────────────────

    def _score_one(self, strat: dict, symbol: str) -> ScoredSignal | None:
        """Score a single strategy for this symbol."""
        ind   = strat.get("indicators", {})
        risk  = strat.get("risk", {})
        pos   = strat.get("position", {})
        w     = ScoreWeights.from_strategy(strat)

        # ── 1. Direction filter ─────────────────────────────────────────────
        direction = strat.get("direction", "both")
        regime_signal = self._check_regime_fit(direction)
        if regime_signal is None:
            return None

        # ── 2. Technical entry check ────────────────────────────────────────
        entry_signal = self._check_technical_entry(ind, w)
        if entry_signal is None:
            return None

        side, reason = entry_signal   # side: "LONG" | "SHORT"

        # ── 3. Scanner reinforcement ────────────────────────────────────────
        breakdown: dict[str, int] = {}
        scanner_signals: list[str] = []

        s_score = self._score_scanners(symbol, side, breakdown, scanner_signals)

        # ── 4. Build composite score ────────────────────────────────────────
        momentum_pts   = breakdown.get("momentum", 0)
        rsi_pts       = breakdown.get("rsi", 0)
        adx_pts       = breakdown.get("adx", 0)
        regime_pts    = breakdown.get("regime", 0)
        scanner_pts   = s_score

        raw = momentum_pts + rsi_pts + adx_pts + regime_pts + scanner_pts
        composite = min(100, max(0, raw))

        min_score = strat.get("min_score", w.score_threshold)
        if composite < min_score:
            return None

        # ── 5. Risk parameters ───────────────────────────────────────────────
        sl_pct     = abs(risk.get("sl_percent", 2) or 2)
        tp_pct     = risk.get("tp_percent", 4) or 4
        leverage   = pos.get("leverage", 3)

        return ScoredSignal(
            symbol=symbol,
            side=side,
            entry_price=self.closes[-1],
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            leverage=leverage,
            score=composite,
            min_score=min_score,
            breakdown={
                "momentum": momentum_pts,
                "rsi":       rsi_pts,
                "adx":       adx_pts,
                "regime":    regime_pts,
                "scanner":   scanner_pts,
            },
            scanner_signals=scanner_signals,
            strategy_id=strat.get("id", "unknown"),
            regime=self.regime,
            reason=reason,
        )

    def _check_regime_fit(self, direction: str) -> str | None:
        """Return the tradeable side given current regime, or None to skip."""
        if self.regime == "sideway":
            return None
        if direction == "long" and self.regime in ("bearish", "sideway"):
            return None
        if direction == "short" and self.regime in ("bullish", "sideway"):
            return None
        if self.regime == "bullish":
            return "LONG"
        if self.regime == "bearish":
            return "SHORT"
        return None   # sideway already filtered above

    def _check_technical_entry(
        self,
        ind: dict,
        w: ScoreWeights,
    ) -> tuple[str, str] | None:
        """Run EMA crossover + RSI + ADX checks.

        Returns (side, reason) on a valid signal, None on no signal.
        """
        ema_fast = ind.get("ema_fast", 9)
        ema_mid  = ind.get("ema_mid", 21)
        ema_slow = ind.get("ema_slow", 50)
        adx_per  = ind.get("adx_period", 14)
        adx_thr  = ind.get("adx_threshold", 25)
        rsi_per  = ind.get("rsi_period", 14)
        rsi_ob   = ind.get("rsi_overbought", 70)
        rsi_os   = ind.get("rsi_oversold", 30)

        adx = compute_adx(self.highs, self.lows, self.closes, adx_per)
        rsi = compute_rsi(self.closes, rsi_per)
        crossover = check_ema_crossover(self.closes, ema_fast, ema_mid)

        # ── Trend confirmation via ADX ───────────────────────────────────
        strong_trend = adx >= adx_thr

        # EMA alignment
        ef = compute_ema(self.closes, ema_fast)
        em = compute_ema(self.closes, ema_mid)
        es = compute_ema(self.closes, ema_slow)
        bull_align = ef > em > es
        bear_align = ef < em < es

        # Crossover (faster cross on top of slow)
        bull_cross = crossover == "bullish"
        bear_cross = crossover == "bearish"

        # Long conditions
        long_ok = (
            (bull_cross and strong_trend) or
            (bull_align and rsi < rsi_ob) or
            (rsi < rsi_os and strong_trend)
        )
        # Short conditions
        short_ok = (
            (bear_cross and strong_trend) or
            (bear_align and rsi > rsi_os) or
            (rsi > rsi_ob and strong_trend)
        )

        if long_ok:
            reason = (
                f"EMA{ema_fast}/{ema_mid} bullish cross"
                if bull_cross else
                f"EMA align + RSI={rsi:.0f}" if bull_align else
                f"RSI oversold {rsi:.0f}"
            )
            return "LONG", reason

        if short_ok:
            reason = (
                f"EMA{ema_fast}/{ema_mid} bearish cross"
                if bear_cross else
                f"EMA align + RSI={rsi:.0f}" if bear_align else
                f"RSI overbought {rsi:.0f}"
            )
            return "SHORT", reason

        return None

    def _score_scanners(
        self,
        symbol: str,
        side: str,
        breakdown: dict[str, int],
        scanner_signals: list[str],
    ) -> int:
        """Score scanner context and populate breakdown + scanner_signals."""
        sym_key = symbol.lower().replace("/", "")
        score   = 0
        w       = ScoreWeights()

        # ── Whale clusters ────────────────────────────────────────────────
        whale_score = self._score_whale(sym_key, side)
        if whale_score:
            score += whale_score
            scanner_signals.append(f"whale+{whale_score}")

        # ── Liquidation clusters ──────────────────────────────────────────
        liq_score = self._score_liquidation(sym_key, side)
        if liq_score:
            score += liq_score
            scanner_signals.append(f"liq+{liq_score}")

        # ── SMC signals ───────────────────────────────────────────────────
        smc_score = self._score_smc(sym_key, side)
        if smc_score:
            score += smc_score
            scanner_signals.append(f"smc+{smc_score}")

        # ── Funding rate ──────────────────────────────────────────────────
        funding_score = self._score_funding(sym_key, side)
        if funding_score:
            score += funding_score
            scanner_signals.append(f"funding{funding_score:+d}")

        # ── Volume profile ────────────────────────────────────────────────
        vp_score = self._score_volume_profile(sym_key)
        if vp_score:
            score += vp_score
            scanner_signals.append(f"vp+{vp_score}")

        return score

    def _score_whale(self, sym_key: str, side: str) -> int:
        clusters = self.scanner.get("whale_clusters", [])
        matched  = [c for c in clusters if getattr(c, "symbol", "") == sym_key]
        if not matched:
            return 0
        same_side = [c for c in matched if getattr(c, "side", "") == side]
        if not same_side:
            return -10   # counter-trend whale
        total = sum(getattr(c, "total_quote_qty", 0) for c in same_side)
        if   total > 500_000: return 20
        elif total > 200_000: return 15
        elif total > 50_000:  return 10
        return 0

    def _score_liquidation(self, sym_key: str, side: str) -> int:
        clusters = self.scanner.get("liq_clusters", [])
        matched  = [c for c in clusters if getattr(c, "symbol", "") == sym_key]
        if not matched:
            return 0
        counter = "SELL" if side == "LONG" else "BUY"
        counter_clusters = [c for c in matched if getattr(c, "side", "") == counter]
        if not counter_clusters:
            return 0
        total = sum(getattr(c, "total_qty", 0) for c in counter_clusters)
        if   total > 100_000: return 15
        elif total > 50_000:  return 10
        return 0

    def _score_smc(self, sym_key: str, side: str) -> int:
        score = 0
        # Order blocks
        for ob in self.scanner.get("smc_ob", []):
            if getattr(ob, "symbol", "") != sym_key:
                continue
            ob_type = getattr(ob, "ob_type", None)
            if ob_type and hasattr(ob_type, "value"):
                if ob_type.value == "bullish_ob" and side == "LONG":
                    score += 15
                elif ob_type.value == "bearish_ob" and side == "SHORT":
                    score += 15
        # FVGs
        for fvg in self.scanner.get("smc_fvg", []):
            if getattr(fvg, "symbol", "") != sym_key:
                continue
            d = getattr(fvg, "direction", None)
            if d and hasattr(d, "value"):
                if d.value == "bullish_fvg" and side == "LONG":
                    score += 10
                elif d.value == "bearish_fvg" and side == "SHORT":
                    score += 10
        # Sweeps
        for sw in self.scanner.get("smc_sweeps", []):
            if getattr(sw, "symbol", "") != sym_key:
                continue
            d = getattr(sw, "direction", None)
            if d and hasattr(d, "value"):
                if d.value == "bullish_sweep" and side == "LONG":
                    score += 10
                elif d.value == "bearish_sweep" and side == "SHORT":
                    score += 10
        # Structure
        for ms in self.scanner.get("smc_structure", []):
            if getattr(ms, "symbol", "") != sym_key:
                continue
            d = getattr(ms, "direction", None)
            if d and hasattr(d, "value"):
                if d.value == "bullish_structure" and side == "LONG":
                    score += 10
                elif d.value == "bearish_structure" and side == "SHORT":
                    score += 10
        return min(score, 40)   # cap scanner contribution

    def _score_funding(self, sym_key: str, side: str) -> int:
        for ev in self.scanner.get("funding_rates", []):
            if getattr(ev, "symbol", "") != sym_key:
                continue
            rate = getattr(ev, "rate", 0)
            if rate > 0.0003:
                return 15 if side == "SHORT" else -5
            elif rate < -0.0003:
                return 15 if side == "LONG" else -5
        return 0

    def _score_volume_profile(self, sym_key: str) -> int:
        profiles = self.scanner.get("vp_profiles", {})
        profile = profiles.get(sym_key)
        if profile is None:
            return 0
        poc = getattr(profile, "poc", 0)
        if not poc or not self.closes:
            return 0
        deviation = abs(self.closes[-1] - poc) / poc
        if   deviation <= 0.005: return 10
        elif deviation <= 0.010:  return 5
        return 0

    # ── Regime weighting ───────────────────────────────────────────────────────

    @staticmethod
    def regime_weight(regime: str) -> float:
        """Return a 0.0-1.0 weight multiplier for a given regime.

        This can be used by position-sizing code to scale exposure.
        """
        weights = {
            "bullish": 1.0,
            "bearish": 0.7,
            "sideway": 0.3,
        }
        return weights.get(regime, 0.3)