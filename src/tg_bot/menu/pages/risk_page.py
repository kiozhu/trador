"""Risk page — shows risk engine state, kill/resume, stress test."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class RiskPage(MenuPage):
    name = "risk"
    back_callback = "main"

    def __init__(self, state_mgr, rolling_buffer=None, kelly_sizer=None):
        self._state_mgr = state_mgr
        self._rolling_buffer = rolling_buffer
        self._kelly_sizer = kelly_sizer

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get()

        # ── Risk state from state_mgr (synced from AutoTrader._sync_risk_state) ──
        trading_enabled = state.get("risk_trading_enabled", True)
        regime = state.get("risk_volatility_regime", "sideway")
        kelly_pct = state.get("risk_kelly_pct", 0.0)
        var_1d = state.get("risk_var_1d_usd", 0.0)
        cvar_1d = state.get("risk_cvar_1d_usd", 0.0)
        var_7d = state.get("risk_var_7d_usd", 0.0)
        cvar_7d = state.get("risk_cvar_7d_usd", 0.0)
        daily_pnl = state.get("risk_daily_pnl_usd", 0.0)
        daily_pnl_pct = state.get("risk_daily_pnl_pct", 0.0)
        open_pos = state.get("risk_open_positions", 0)
        consec_loss = state.get("risk_consecutive_losses", 0)
        kill_reason = state.get("risk_killswitch_reason", "")

        # ── Regime ───────────────────────────────────────────────────────
        regime_map = {
            "bullish": "📈 Bullish",
            "bearish": "📉 Bearish",
            "sideway": "↔️ Sideway",
        }
        regime_label = regime_map.get(regime, f"❓ {regime}")

        # ── Trading status ───────────────────────────────────────────────
        if trading_enabled:
            status_icon = "🟢 AKTIF"
            status_text = "Risk engine normal — trading aktif"
        else:
            status_icon = "🔴 MATI"
            status_text = f"Trading dihentikan — {kill_reason or 'killswitch aktif'}"

        # ── VaR display ──────────────────────────────────────────────────
        var_1d_str = f"${var_1d:,.2f}" if var_1d else "$—"
        cvar_1d_str = f"${cvar_1d:,.2f}" if cvar_1d else "$—"
        var_7d_str = f"${var_7d:,.2f}" if var_7d else "$—"
        cvar_7d_str = f"${cvar_7d:,.2f}" if cvar_7d else "$—"

        # ── Daily PnL ───────────────────────────────────────────────────
        pnl_icon = "📈" if daily_pnl >= 0 else "📉"
        pnl_str = f"+${daily_pnl:,.2f}" if daily_pnl >= 0 else f"${daily_pnl:,.2f}"
        pnl_pct_str = f"+{daily_pnl_pct:.2f}%" if daily_pnl_pct >= 0 else f"{daily_pnl_pct:.2f}%"

        # ── Build clean text (NO markdown — plain text only) ─────────────
        lines = [
            "🛡️ RISK ENGINE",
            "",
            f"Status    : {status_icon}",
            f"          {status_text}",
            "",
            f"Regime    : {regime_label}",
            f"Kelly     : {kelly_pct:.1f}%",
            f"Open Pos  : {open_pos}",
            "",
            "── 📊 Value at Risk ──",
            f"  VaR 1d  : {var_1d_str}",
            f"  CVaR 1d : {cvar_1d_str}",
            f"  VaR 7d  : {var_7d_str}",
            f"  CVaR 7d : {cvar_7d_str}",
            "",
            "── 💰 Daily PnL ──",
            f"  {pnl_icon} {pnl_str} ({pnl_pct_str})",
            f"  Consecutive losses: {consec_loss}",
        ]

        text = "\n".join(lines)

        keyboard = []

        # Kill / Resume button
        if trading_enabled:
            keyboard.append([
                InlineKeyboardButton("🔴 KILL — Stop Trading", callback_data="set:risk_kill")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("🟢 RESUME — Enable Trading", callback_data="set:risk_resume")
            ])

        # Stress test buttons
        keyboard.append([
            InlineKeyboardButton("💥 Black Swan", callback_data="set:stress_black_swan")
        ])
        keyboard.append([
            InlineKeyboardButton("💥 Liquidation Cascade", callback_data="set:stress_liquidation_cascade")
        ])
        keyboard.append([
            InlineKeyboardButton("💥 Market Maker Withdrawal", callback_data="set:stress_market_maker_withdrawal")
        ])
        keyboard.append([
            InlineKeyboardButton("💥 Correlation Breakdown", callback_data="set:stress_correlation_breakdown")
        ])
        keyboard.append([
            InlineKeyboardButton("💥 Funding Spike", callback_data="set:stress_sudden_funding_spike")
        ])

        keyboard.append([
            InlineKeyboardButton("◀️ Back", callback_data="page:main")
        ])

        return text, InlineKeyboardMarkup(keyboard)