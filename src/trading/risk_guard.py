"""RiskGuard — 10-layer pre-trade risk validation, circuit breakers, kill/resume."""
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum

from ..utils.logger import log


class TradingMode(Enum):
    KILL    = "kill"     # hard block all trades
    RESUME  = "resume"    # normal operation


@dataclass
class RiskLayerResult:
    """Result of a single risk layer check."""
    layer: str
    passed: bool
    reason: str
    severity: str = "info"  # info, warn, block


@dataclass
class RiskGuardConfig:
    """Configuration for all RiskGuard thresholds."""
    # ── Layer 1: Daily loss circuit breaker ───────────────────────────
    daily_loss_limit_pct:    float = 5.0   # block if daily loss > 5%
    daily_profit_limit_pct:  float = 15.0  # optional cap (set 0 to disable)

    # ── Layer 2: Trade count limits ──────────────────────────────────
    max_trades_per_day:       int = 20
    max_trades_per_hour:      int = 5

    # ── Layer 3: Position exposure ──────────────────────────────────
    max_open_positions:       int = 5
    max_position_size_pct:    float = 25.0  # max % of balance per trade
    max_total_exposure_pct:   float = 80.0  # total capital at risk

    # ── Layer 4: Symbol concentration ────────────────────────────────
    max_positions_per_symbol: int = 2

    # ── Layer 5: Consecutive losses (cooldown trigger) ──────────────
    max_consecutive_losses:    int = 4
    cooldown_minutes:         int = 15

    # ── Layer 6: Drawdown limits ────────────────────────────────────
    max_drawdown_pct:         float = 8.0   # block if equity drawdown > 8%

    # ── Layer 7: Volatility filter ─────────────────────────────────
    min_volatility_threshold: float = 0.3   # min ATR% to allow trades
    max_volatility_threshold: float = 8.0  # block if ATR% > 8%

    # ── Layer 4: Time-based filters (WIB) ─────────────────────────
    time_filter_enabled:       bool = False   # ON/OFF toggle
    no_trade_hours_wib:        list[int] = field(default_factory=lambda: [])  # WIB hours, e.g. [0,1,2,3,4,5] = 07-12 WIB
    no_trade_minutes_wib:      list[int] = field(default_factory=lambda: [])  # near hour close

    # ── Layer 5: Balance floor ──────────────────────────────────────
    min_balance_usd:          float = 5.0  # block if balance < $5
    emergency_balance_usd:     float = 5.0   # hard block everything below this

    # ── Layer 6: Regime alignment ─────────────────────────────────
    blocked_regimes:          list[str] = field(default_factory=lambda: ["sideway"])


class RiskGuard:
    """6-layer pre-trade risk validation + kill/resume + circuit breaker."""

    def __init__(
        self,
        config: Optional[RiskGuardConfig] = None,
        state_mgr=None,
    ):
        self.config = config or RiskGuardConfig()
        self.state_mgr = state_mgr

        # ── Internal state ──────────────────────────────────────────
        self._mode: TradingMode = TradingMode.RESUME
        self._killswitch_reason: str = ""
        self._killswitch_timestamp: float = 0.0
        self._sideways_mode: bool = True  # True = block sideways trades (Layer 11)

        # ── Session stats (reset on new day) ────────────────────────
        self._session_start: datetime = datetime.now(timezone.utc)
        self._daily_trades: list[datetime] = []
        self._hourly_trades: list[datetime] = []
        self._consecutive_losses: int = 0
        self._cooldown_until: datetime | None = None

        # ── History for drawdown tracking ──────────────────────────
        self._peak_balance: float = 0.0
        self._nadir_balance: float = float("inf")

        log.info("RiskGuard initialised | daily_loss=%.1f%% | max_pos=%d | cooldown=%dm",
                 self.config.daily_loss_limit_pct, self.config.max_open_positions,
                 self.config.cooldown_minutes)

    # ── Kill / Resume ────────────────────────────────────────────────────────

    def kill(self, reason: str) -> None:
        """Hard block all trades immediately."""
        self._mode = TradingMode.KILL
        self._killswitch_reason = reason
        self._killswitch_timestamp = datetime.now(timezone.utc).timestamp()
        log.warning("🛑 RISKGUARD KILL — reason: %s", reason)

    def resume(self) -> None:
        """Resume normal trading after a kill."""
        self._mode = TradingMode.RESUME

    def set_sideways_mode(self, enabled: bool) -> None:
        """Enable/disable sideways market blocking (Layer 11)."""
        self._sideways_mode = enabled
        log.info("RiskGuard sideways mode: %s", "ON" if enabled else "OFF")

    def sync_sideways_mode(self, state: dict) -> None:
        """Sync sideways_mode from state dict (called each AutoTrader cycle)."""
        self._sideways_mode = state.get("sideways_mode", True)

    def set_config(self, **kwargs) -> None:
        """Update RiskGuardConfig params at runtime. E.g. set_config(max_position_size_pct=30.0)."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                old = getattr(self.config, key)
                setattr(self.config, key, value)
                log.info("RiskGuard config updated: %s = %s (was %s)", key, value, old)
            else:
                log.warning("RiskGuard config: unknown param '%s'", key)

    def is_killed(self) -> bool:
        """Return True if RiskGuard is in kill mode."""
        return self._mode == TradingMode.KILL

    def killswitch_reason(self) -> str:
        """Return the reason for current kill, or empty string."""
        return self._killswitch_reason

    def killswitch_age_seconds(self) -> float:
        """Seconds since last killswitch activation."""
        if self._killswitch_timestamp == 0:
            return 0.0
        return datetime.now(timezone.utc).timestamp() - self._killswitch_timestamp

    # ── Pre-trade validation ────────────────────────────────────────────────

    def validate_trade(self, trade: dict, balance: float) -> list[RiskLayerResult]:
        """Run all 10 validation layers. Returns list of results; any block layer = reject."""
        results: list[RiskLayerResult] = []

        for layer_fn in [
            self._layer04_time_filter,
            self._layer05_balance_floor,
            self._layer06_regime_alignment,
        ]:
            result = layer_fn(trade, balance)
            results.append(result)

        # Log all results
        for r in results:
            if not r.passed:
                log.warning("  ❌ RiskLayer '%s' FAILED — %s", r.layer, r.reason)

        return results

    def can_trade(self, trade: dict, balance: float) -> tuple[bool, list[RiskLayerResult]]:
        """Shorthand: returns (allowed, list_of_results)."""
        results = self.validate_trade(trade, balance)
        blocked = any(not r.passed for r in results)
        return not blocked, results

    # ── Session helpers ───────────────────────────────────────────────────────

    def record_trade_result(self, pnl_pct: float) -> None:
        """Call after each trade closes to update session stats."""
        now = datetime.now(timezone.utc)
        self._daily_trades.append(now)
        self._hourly_trades.append(now)

        if pnl_pct < 0:
            self._consecutive_losses += 1
            log.warning("  ⚠️ Consecutive losses: %d / %d", self._consecutive_losses,
                        self.config.max_consecutive_losses)
        else:
            self._consecutive_losses = 0

        # Auto-kill on too many consecutive losses
        if self._consecutive_losses >= self.config.max_consecutive_losses:
            self.kill(f"Consecutive losses limit hit ({self._consecutive_losses})")
            self._cooldown_until = now + timedelta(minutes=self.config.cooldown_minutes)

    def update_balance(self, balance: float) -> None:
        """Track peak/nadir for drawdown calculation."""
        if balance > self._peak_balance:
            self._peak_balance = balance
        if balance < self._nadir_balance:
            self._nadir_balance = balance

    def reset_daily(self) -> None:
        """Reset daily counters — call at UTC midnight."""
        self._daily_trades.clear()
        self._consecutive_losses = 0
        log.info("RiskGuard daily reset")

    def reset_hourly(self) -> None:
        """Reset hourly counters — call every hour."""
        self._hourly_trades.clear()

    # ── 10 Validation Layers ────────────────────────────────────────────────

    def _layer01_killswitch(self, trade: dict, balance: float) -> RiskLayerResult:
        """Layer 1: Hard killswitch — no trades allowed."""
        if self._mode == TradingMode.KILL:
            age = self.killswitch_age_seconds()
            return RiskLayerResult(
                layer="L01_KILLSWITCH",
                passed=False,
                reason=f"Killswitch active ({self._killswitch_reason}), active for {age:.0f}s",
                severity="block",
            )
        return RiskLayerResult(layer="L01_KILLSWITCH", passed=True, reason="OK", severity="info")

    def _layer02_daily_loss_breaker(self, trade: dict, balance: float) -> RiskLayerResult:
        """Layer 2: Daily loss circuit breaker — block if daily loss > limit."""
        cfg = self.config
        state = self.state_mgr.get() if self.state_mgr else {}

        # Get session start balance
        session_balance = state.get("session_start_balance", balance)
        if session_balance <= 0:
            session_balance = balance

        daily_pnl_pct = (balance - session_balance) / session_balance * 100

        if daily_pnl_pct <= -cfg.daily_loss_limit_pct:
            self.kill(f"Daily loss breaker triggered: {daily_pnl_pct:.2f}%")
            return RiskLayerResult(
                layer="L02_DAILY_LOSS",
                passed=False,
                reason=f"Daily loss {daily_pnl_pct:.2f}% > limit {cfg.daily_loss_limit_pct}%",
                severity="block",
            )

        if cfg.daily_profit_limit_pct > 0 and daily_pnl_pct >= cfg.daily_profit_limit_pct:
            return RiskLayerResult(
                layer="L02_DAILY_PROFIT_CAP",
                passed=False,
                reason=f"Daily profit {daily_pnl_pct:.2f}% > cap {cfg.daily_profit_limit_pct}% — take profit",
                severity="block",
            )

        return RiskLayerResult(
            layer="L02_DAILY_LOSS",
            passed=True,
            reason=f"Daily PnL {daily_pnl_pct:+.2f}% within limits",
            severity="info",
        )

    def _layer03_trade_count_limits(self, trade: dict, balance: float) -> RiskLayerResult:
        """Layer 3: Rate limit — max trades per day and per hour."""
        cfg = self.config
        now = datetime.now(timezone.utc)
        cutoff_day = now - timedelta(hours=24)
        cutoff_hour = now - timedelta(hours=1)

        daily_count = sum(1 for t in self._daily_trades if t > cutoff_day)
        hourly_count = sum(1 for t in self._hourly_trades if t > cutoff_hour)

        if daily_count >= cfg.max_trades_per_day:
            return RiskLayerResult(
                layer="L03_TRADE_COUNT",
                passed=False,
                reason=f"Daily trade count {daily_count} >= limit {cfg.max_trades_per_day}",
                severity="block",
            )

        if hourly_count >= cfg.max_trades_per_hour:
            return RiskLayerResult(
                layer="L03_TRADE_COUNT",
                passed=False,
                reason=f"Hourly trade count {hourly_count} >= limit {cfg.max_trades_per_hour}",
                severity="block",
            )

        return RiskLayerResult(
            layer="L03_TRADE_COUNT",
            passed=True,
            reason=f"Trade count OK (daily={daily_count}, hourly={hourly_count})",
            severity="info",
        )

    def _layer04_position_exposure(self, trade: dict, balance: float) -> RiskLayerResult:
        """Layer 4: Per-trade size and total exposure limits."""
        cfg = self.config
        size_pct = trade.get("size_value", 0) or trade.get("size_pct", 0)
        open_count = trade.get("open_positions", 0)

        if size_pct > cfg.max_position_size_pct:
            return RiskLayerResult(
                layer="L04_POSITION_SIZE",
                passed=False,
                reason=f"Trade size {size_pct:.1f}% > max {cfg.max_position_size_pct}%",
                severity="block",
            )

        total_exposed = sum(
            (trade.get("size_value", 0) or 0) for _ in range(open_count)
        )
        if total_exposed > cfg.max_total_exposure_pct:
            return RiskLayerResult(
                layer="L04_TOTAL_EXPOSURE",
                passed=False,
                reason=f"Total exposure {total_exposed:.1f}% > limit {cfg.max_total_exposure_pct}%",
                severity="block",
            )

        return RiskLayerResult(
            layer="L04_POSITION_EXPOSURE",
            passed=True,
            reason=f"Size={size_pct:.1f}%, exposure OK",
            severity="info",
        )

    def _layer05_symbol_concentration(self, trade: dict, balance: float) -> RiskLayerResult:
        """Layer 5: Max positions per symbol (avoid over-concentration)."""
        cfg = self.config
        symbol = trade.get("symbol", "")
        open_pos = trade.get("open_positions", [])
        same_symbol = sum(1 for p in open_pos if p.get("symbol") == symbol)

        if same_symbol >= cfg.max_positions_per_symbol:
            return RiskLayerResult(
                layer="L05_SYMBOL_CONCENTRATION",
                passed=False,
                reason=f"Symbol {symbol} has {same_symbol} open positions, max={cfg.max_positions_per_symbol}",
                severity="block",
            )

        return RiskLayerResult(
            layer="L05_SYMBOL_CONCENTRATION",
            passed=True,
            reason=f"Symbol concentration OK ({same_symbol} current)",
            severity="info",
        )

    def _layer06_consecutive_loss_cooldown(self, trade: dict, balance: float) -> RiskLayerResult:
        """Layer 6: Cooldown after consecutive losses."""
        cfg = self.config
        now = datetime.now(timezone.utc)

        if self._cooldown_until and now < self._cooldown_until:
            remaining = (self._cooldown_until - now).total_seconds() / 60
            return RiskLayerResult(
                layer="L06_CONSECUTIVE_LOSS",
                passed=False,
                reason=f"Cooldown active, {remaining:.0f}min remaining",
                severity="block",
            )

        if self._consecutive_losses >= cfg.max_consecutive_losses:
            return RiskLayerResult(
                layer="L06_CONSECUTIVE_LOSS",
                passed=False,
                reason=f"Consecutive losses {self._consecutive_losses} >= limit {cfg.max_consecutive_losses}",
                severity="block",
            )

        return RiskLayerResult(
            layer="L06_CONSECUTIVE_LOSS",
            passed=True,
            reason=f"No active cooldown ({self._consecutive_losses} consecutive losses)",
            severity="info",
        )

    def _layer07_drawdown_limit(self, trade: dict, balance: float) -> RiskLayerResult:
        """Layer 7: Equity drawdown limit — block if drawdown > threshold."""
        cfg = self.config

        if self._peak_balance <= 0:
            return RiskLayerResult(
                layer="L07_DRAWDOWN",
                passed=True,
                reason="No peak tracked yet",
                severity="info",
            )

        drawdown_pct = (self._peak_balance - balance) / self._peak_balance * 100

        if drawdown_pct > cfg.max_drawdown_pct:
            self.kill(f"Drawdown limit hit: {drawdown_pct:.2f}%")
            return RiskLayerResult(
                layer="L07_DRAWDOWN",
                passed=False,
                reason=f"Drawdown {drawdown_pct:.2f}% > limit {cfg.max_drawdown_pct}%",
                severity="block",
            )

        return RiskLayerResult(
            layer="L07_DRAWDOWN",
            passed=True,
            reason=f"Drawdown {drawdown_pct:.2f}% within limit",
            severity="info",
        )

    def _layer08_volatility_filter(self, trade: dict, balance: float) -> RiskLayerResult:
        """Layer 8: Skip trades in extreme volatility (chop or extreme moves)."""
        cfg = self.config
        atr_pct = trade.get("atr_pct", 0)

        if atr_pct == 0:
            return RiskLayerResult(
                layer="L08_VOLATILITY",
                passed=True,
                reason="No ATR data — allowing trade",
                severity="info",
            )

        if atr_pct < cfg.min_volatility_threshold:
            return RiskLayerResult(
                layer="L08_VOLATILITY",
                passed=False,
                reason=f"ATR {atr_pct:.2f}% < min {cfg.min_volatility_threshold}% (too choppy)",
                severity="warn",
            )

        if atr_pct > cfg.max_volatility_threshold:
            return RiskLayerResult(
                layer="L08_VOLATILITY",
                passed=False,
                reason=f"ATR {atr_pct:.2f}% > max {cfg.max_volatility_threshold}% (too volatile)",
                severity="block",
            )

        return RiskLayerResult(
            layer="L08_VOLATILITY",
            passed=True,
            reason=f"ATR {atr_pct:.2f}% within volatility range",
            severity="info",
        )

    def _layer04_time_filter(self, trade: dict, balance: float) -> RiskLayerResult:
        """Layer 4: Time-based filter (WIB) — block during specified hours if enabled."""
        cfg = self.config

        if not cfg.time_filter_enabled:
            return RiskLayerResult(
                layer="L04_TIME_FILTER",
                passed=True,
                reason="Time filter OFF",
                severity="info",
            )

        # WIB = UTC + 7
        now_wib = datetime.now(timezone.utc) + timedelta(hours=7)
        hour_wib = now_wib.hour
        minute_wib = now_wib.minute

        if hour_wib in cfg.no_trade_hours_wib:
            return RiskLayerResult(
                layer="L04_TIME_FILTER",
                passed=False,
                reason=f"Jam {hour_wib:02d} WIB diblokir",
                severity="block",
            )

        if minute_wib in cfg.no_trade_minutes_wib:
            return RiskLayerResult(
                layer="L04_TIME_FILTER",
                passed=False,
                reason=f"Menit {minute_wib} WIB diblokir (dekat jam selesai)",
                severity="block",
            )

        return RiskLayerResult(
            layer="L04_TIME_FILTER",
            passed=True,
            reason=f"Jam {hour_wib:02d}:{minute_wib:02d} WIB — diizinkan",
            severity="info",
        )

    def _layer05_balance_floor(self, trade: dict, balance: float) -> RiskLayerResult:
        """Layer 5: Balance floor — block if balance too low."""
        cfg = self.config

        if balance < cfg.emergency_balance_usd:
            self.kill(f"Emergency balance floor hit: ${balance:.2f}")
            return RiskLayerResult(
                layer="L05_BALANCE_FLOOR",
                passed=False,
                reason=f"Balance ${balance:.2f} < emergency floor ${cfg.emergency_balance_usd}",
                severity="block",
            )

        if balance < cfg.min_balance_usd:
            return RiskLayerResult(
                layer="L05_BALANCE_FLOOR",
                passed=False,
                reason=f"Balance ${balance:.2f} < min required ${cfg.min_balance_usd}",
                severity="block",
            )

        return RiskLayerResult(
            layer="L05_BALANCE_FLOOR",
            passed=True,
            reason=f"Balance ${balance:.2f} OK",
            severity="info",
        )

    def _layer06_regime_alignment(self, trade: dict, balance: float) -> RiskLayerResult:
        """Layer 6: Block trades in disallowed regimes — controlled by sideways_mode."""
        cfg = self.config
        regime = trade.get("market_regime", "unknown")

        # Respect the toggle — if sideways_mode is False, allow all regimes
        if not self._sideways_mode:
            return RiskLayerResult(
                layer="L06_REGIME",
                passed=True,
                reason=f"Regime '{regime}' allowed (sideways_mode=OFF)",
                severity="info",
            )

        if regime in cfg.blocked_regimes:
            return RiskLayerResult(
                layer="L06_REGIME",
                passed=False,
                reason=f"Regime '{regime}' is blocked",
                severity="warn",
            )

        return RiskLayerResult(
            layer="L06_REGIME",
            passed=True,
            reason=f"Regime '{regime}' allowed",
            severity="info",
        )

    # ── Status ─────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return current RiskGuard status snapshot."""
        now = datetime.now(timezone.utc)
        return {
            "mode": self._mode.value,
            "killswitch_reason": self._killswitch_reason,
            "killswitch_age_seconds": self.killswitch_age_seconds(),
            "consecutive_losses": self._consecutive_losses,
            "daily_trades": len(self._daily_trades),
            "cooldown_until": self._cooldown_until.isoformat() if self._cooldown_until else None,
            "peak_balance": self._peak_balance,
            "nadir_balance": self._nadir_balance if self._nadir_balance != float("inf") else 0,
        }