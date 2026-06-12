"""KellySizer — Kelly Criterion position sizing with 8 adjustment factors."""
import math
from typing import Optional

from ..utils.logger import log


class KellySizer:
    """Calculate optimal position size using Kelly Criterion + 8 adjustment factors.

    The Kelly formula: f* = (bp - q) / b
    where:
      b = odds (profit / loss ratio)
      p = win probability
      q = 1 - p

    Applied with 8 adjustment factors to produce a final position size % of balance.
    """

    # ── Default adjustment factor weights ───────────────────────────────────
    DEFAULT_FACTORS = {
        "win_rate_adj":      1.0,   # multiplier based on rolling win rate
        "volatility_adj":   1.0,   # multiplier based on recent ATR/volatility
        "confidence_adj":   1.0,   # multiplier from signal confidence score
        "balance_adj":      1.0,   # scale based on absolute balance level
        "drawdown_adj":     1.0,   # reduce size when in drawdown
        "concentration_adj": 1.0,  # reduce when many open positions
        "regime_adj":       1.0,   # scale down in uncertain regimes
        "streak_adj":       1.0,   # adjust for winning/losing streaks
    }

    def __init__(
        self,
        base_kelly_pct: float = 25.0,  # base Kelly % (recommend 20-30%)
        max_kelly_pct: float = 50.0,   # absolute cap on Kelly %
        factors: Optional[dict[str, float]] = None,
    ):
        self.base_kelly_pct = base_kelly_pct
        self.max_kelly_pct = max_kelly_pct
        self.factors = {**self.DEFAULT_FACTORS, **(factors or {})}

        log.info("KellySizer initialised | base=%.1f%% | max=%.1f%%", base_kelly_pct, max_kelly_pct)

    # ── Main sizing entry point ──────────────────────────────────────────────

    def size(
        self,
        balance: float,
        trade: dict,
        win_rate: float = 0.55,
        avg_win_pct: float = 3.0,
        avg_loss_pct: float = -2.0,
        factors_override: Optional[dict[str, float]] = None,
    ) -> float:
        """Calculate final position size % of balance.

        Parameters
        ----------
        balance : float
            Current account balance in USD.
        trade : dict
            Trade signal dict (must contain symbol, side, score, atr_pct, etc.).
        win_rate : float
            Estimated win probability (0-1). Default 0.55.
        avg_win_pct : float
            Average win as % of position (e.g. 3.0 = 3% profit).
        avg_loss_pct : float
            Average loss as % of position (e.g. -2.0 = -2% loss).
        factors_override : dict, optional
            Override specific adjustment factors for this call.

        Returns
        -------
        float
            Position size as % of balance (0-100).
        """
        # ── 1. Raw Kelly calculation ──────────────────────────────────────
        raw_kelly = self._kelly(win_rate, avg_win_pct, avg_loss_pct)

        # ── 2. Gather adjustment factors ──────────────────────────────────
        factors = {**self.factors, **(factors_override or {})}
        adj = self._compute_factors(trade, balance, factors)

        # ── 3. Apply adjustments ──────────────────────────────────────────
        adjusted = raw_kelly * adj["combined"]

        # ── 4. Enforce caps ────────────────────────────────────────────────
        final = min(adjusted, self.max_kelly_pct)

        # Minimum threshold — tiny sizes not worth trading
        if final < 0.5:
            final = 0.0

        log.debug(
            "KellySizer | raw=%.2f%% | adj=%.3f | final=%.2f%% | bal=%.2f",
            raw_kelly, adj["combined"], final, balance,
        )

        return final

    # ── Kelly formula ────────────────────────────────────────────────────────

    def _kelly(self, win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
        """Compute raw Kelly % given win rate and reward/risk ratio.

        f* = (b·p - q) / b
        where b = avg_win_pct / |avg_loss_pct|, p = win_rate, q = 1-p
        """
        if avg_loss_pct == 0:
            return 0.0

        b = avg_win_pct / abs(avg_loss_pct)   # odds ratio (e.g. 3/2 = 1.5)
        p = max(0.0, min(1.0, win_rate))       # win probability
        q = 1.0 - p

        # Kelly value
        kelly_pct = (b * p - q) / b

        # Scale: Kelly is expressed as a % of bankroll
        kelly_pct *= 100

        # Safety: floor at 0
        return max(0.0, kelly_pct)

    # ── 8 adjustment factors ─────────────────────────────────────────────────

    def _compute_factors(
        self,
        trade: dict,
        balance: float,
        factors: dict[str, float],
    ) -> dict:
        """Compute all 8 adjustment factors and return combined multiplier."""

        # ── Factor 1: Win Rate Adjustment ────────────────────────────────
        win_rate_adj = self._factor_win_rate(
            trade.get("win_rate", 0.55),
            factors.get("win_rate_adj", 1.0),
        )

        # ── Factor 2: Volatility Adjustment ─────────────────────────────
        vol_adj = self._factor_volatility(
            trade.get("atr_pct", 0),
            trade.get("volatility", 0),
            factors.get("volatility_adj", 1.0),
        )

        # ── Factor 3: Signal Confidence Adjustment ───────────────────────
        conf_adj = self._factor_confidence(
            trade.get("score", 0),
            trade.get("min_score", 65),
            factors.get("confidence_adj", 1.0),
        )

        # ── Factor 4: Balance Level Adjustment ──────────────────────────
        bal_adj = self._factor_balance(
            balance,
            factors.get("balance_adj", 1.0),
        )

        # ── Factor 5: Drawdown Adjustment ───────────────────────────────
        dd_adj = self._factor_drawdown(
            trade.get("drawdown_pct", 0),
            factors.get("drawdown_adj", 1.0),
        )

        # ── Factor 6: Concentration Adjustment ──────────────────────────
        conc_adj = self._factor_concentration(
            trade.get("open_positions", 0),
            trade.get("max_positions", 5),
            factors.get("concentration_adj", 1.0),
        )

        # ── Factor 7: Market Regime Adjustment ───────────────────────────
        regime_adj = self._factor_regime(
            trade.get("market_regime", "sideway"),
            trade.get("market_trend", "neutral"),
            factors.get("regime_adj", 1.0),
        )

        # ── Factor 8: Streak Adjustment ─────────────────────────────────
        streak_adj = self._factor_streak(
            trade.get("consecutive_wins", 0),
            trade.get("consecutive_losses", 0),
            factors.get("streak_adj", 1.0),
        )

        # ── Combine (multiplicative) ─────────────────────────────────────
        combined = (
            win_rate_adj
            * vol_adj
            * conf_adj
            * bal_adj
            * dd_adj
            * conc_adj
            * regime_adj
            * streak_adj
        )

        # Ensure combined is within safe bounds
        combined = max(0.0, min(combined, 3.0))   # cap at 3× to prevent runaway sizing

        log.debug(
            "Kelly factors | win_rate=%.3f | vol=%.3f | conf=%.3f | bal=%.3f | "
            "dd=%.3f | conc=%.3f | regime=%.3f | streak=%.3f | combined=%.3f",
            win_rate_adj, vol_adj, conf_adj, bal_adj,
            dd_adj, conc_adj, regime_adj, streak_adj, combined,
        )

        return {
            "win_rate_adj": win_rate_adj,
            "vol_adj": vol_adj,
            "conf_adj": conf_adj,
            "bal_adj": bal_adj,
            "dd_adj": dd_adj,
            "conc_adj": conc_adj,
            "regime_adj": regime_adj,
            "streak_adj": streak_adj,
            "combined": combined,
        }

    # ── Individual factor methods ─────────────────────────────────────────────

    def _factor_win_rate(self, win_rate: float, weight: float) -> float:
        """Factor 1: Win rate adjustment.
        - win_rate > 60%: boost
        - win_rate < 45%: reduce significantly
        """
        if win_rate >= 0.60:
            return min(1.5, 0.5 + win_rate * weight)
        elif win_rate <= 0.40:
            return max(0.2, win_rate * weight)
        else:
            base = 0.5 + (win_rate - 0.40) / 0.20 * 0.5  # linear 40-60% → 0.5-1.0
            return base * weight

    def _factor_volatility(self, atr_pct: float, volatility: float, weight: float) -> float:
        """Factor 2: Volatility adjustment.
        High volatility = reduce size. Low volatility = slightly boost.
        Optimal ATR% is around 1-3%.
        """
        if atr_pct == 0 and volatility == 0:
            return weight  # no data, neutral

        val = atr_pct if atr_pct > 0 else volatility

        if val < 0.5:
            return min(1.3, 0.8 + val * weight)
        elif val > 5.0:
            return max(0.2, 1.5 - (val - 5.0) * 0.2) * weight
        else:
            # Sweet spot 0.5-5% — linear scaling
            factor = 1.0 - (val - 1.0) * 0.05
            return max(0.3, min(1.2, factor * weight))

    def _factor_confidence(self, score: float, min_score: float, weight: float) -> float:
        """Factor 3: Signal confidence adjustment.
        Score relative to minimum threshold determines confidence.
        """
        if score <= 0 or min_score <= 0:
            return weight

        ratio = score / min_score  # e.g. 80/65 = 1.23

        if ratio >= 1.5:
            return min(1.5, 0.8 + ratio * 0.3 * weight)
        elif ratio >= 1.2:
            return 0.9 + (ratio - 1.0) * 0.5 * weight
        elif ratio >= 1.0:
            return 0.8 + (ratio - 0.9) * weight
        else:
            return max(0.3, (ratio - 0.5) * weight)

    def _factor_balance(self, balance: float, weight: float) -> float:
        """Factor 4: Absolute balance level adjustment.
        Very small balances → reduce (fees eat profits).
        Very large balances → slight reduction (risk management).
        """
        if balance < 20:
            # Testing range ($6-$20): scale linearly 0→20, minimum 0.4
            return max(0.4, balance / 20 * weight)
        elif balance < 100:
            return max(0.2, balance / 500 * weight)
        elif balance > 100_000:
            return max(0.5, 1.0 - (balance - 100_000) / 500_000 * weight)
        else:
            # Normal range 100-100k — slight boost for mid-sized
            return weight

    def _factor_drawdown(self, drawdown_pct: float, weight: float) -> float:
        """Factor 5: Drawdown adjustment.
        In drawdown → reduce size to protect capital.
        Deep drawdown → significant reduction.
        """
        if drawdown_pct <= 0:
            return weight  # at peak, no reduction

        if drawdown_pct >= 10:
            return max(0.1, 0.3 * weight)
        elif drawdown_pct >= 5:
            return max(0.3, 0.6 * weight)
        elif drawdown_pct >= 2:
            return max(0.5, 0.8 * weight)
        else:
            return weight

    def _factor_concentration(
        self,
        open_positions: int,
        max_positions: int,
        weight: float,
    ) -> float:
        """Factor 6: Position concentration adjustment.
        More open positions → reduce size of new trades.
        """
        if open_positions <= 0:
            return weight
        if max_positions <= 0:
            max_positions = 5

        ratio = open_positions / max_positions

        if ratio >= 0.8:
            return max(0.2, 0.5 * weight)
        elif ratio >= 0.5:
            return max(0.4, 0.75 * weight)
        else:
            return weight

    def _factor_regime(
        self,
        regime: str,
        trend: str,
        weight: float,
    ) -> float:
        """Factor 7: Market regime adjustment.
        Trending markets → full size.
        Sideway/choppy → reduce.
        Unknown → reduce.
        """
        regime = (regime or "unknown").lower()
        trend = (trend or "neutral").lower()

        if regime in ("bullish", "strong_bull"):
            factor = 1.2 if trend in ("up", "bullish") else 1.0
        elif regime in ("bearish", "strong_bear"):
            factor = 1.1 if trend in ("down", "bearish") else 0.9
        elif regime in ("sideway", "choppy", "neutral"):
            factor = 0.6
        else:
            factor = 0.7  # unknown

        return factor * weight

    def _factor_streak(
        self,
        consecutive_wins: int,
        consecutive_losses: int,
        weight: float,
    ) -> float:
        """Factor 8: Streak adjustment.
        - Hot streak (3+ wins): slightly increase (momentum)
        - Cold streak (3+ losses): significantly reduce
        """
        if consecutive_losses >= 3:
            return max(0.2, 0.5 - consecutive_losses * 0.1) * weight
        elif consecutive_wins >= 4:
            return min(1.3, 1.0 + consecutive_wins * 0.05) * weight
        elif consecutive_wins >= 2:
            return 1.0 + consecutive_wins * 0.05 * weight
        else:
            return weight

    # ── Utility: recommended Kelly fraction (half-Kelly) ────────────────────

    def half_kelly(self, win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
        """Return half-Kelly size — recommended for real trading (less volatility)."""
        return self._kelly(win_rate, avg_win_pct, avg_loss_pct) / 2

    def kelly_fraction(self, win_rate: float, avg_win_pct: float, avg_loss_pct: float, fraction: float = 0.5) -> float:
        """Return Kelly size at a specific fraction (e.g. 0.25 = quarter-Kelly)."""
        return self._kelly(win_rate, avg_win_pct, avg_loss_pct) * fraction

    # ── Status ───────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return current KellySizer configuration snapshot."""
        return {
            "base_kelly_pct": self.base_kelly_pct,
            "max_kelly_pct": self.max_kelly_pct,
            "factors": self.factors,
        }