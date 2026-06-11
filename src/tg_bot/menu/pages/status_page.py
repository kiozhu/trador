"""Status page — shows bot overview, both dry_run and live performance."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage, make_back_button


class StatusPage(MenuPage):
    name = "status"
    back_callback = "main"

    def __init__(self, state_mgr, perf, trade_log, loader=None):
        self.state_mgr = state_mgr
        self.perf = perf
        self.trade_log = trade_log
        self._loader = loader

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        state = self.state_mgr.get()
        current_mode = state.get("mode", "dry_run")

        mode_emoji = "🔴 LIVE" if current_mode == "live" else "🟡 DRY RUN"
        direction = state.get("direction", "both")
        wallet_connected = state.get("wallet_connected", False)
        # Active strategies from StrategyLoader (source of truth)
        active_strats = []
        strat_count = 0
        if self._loader:
            active_ids = self._loader.list_active_ids()
            strat_count = len(active_ids)
            all_strats = self._loader.list_all()
            active_strats = [s.get("name", s.get("id", "")) for s in all_strats if s.get("id") in active_ids]
        strategy_display = ", ".join(active_strats) if active_strats else "none"
        strategy_label = f"{strat_count} strategi" if strat_count else "none"
        trading = "🟢 Active" if state.get("trading_enabled") else "🔴 Stopped"

        # ── Risk state (synced from AutoTrader) ───────────────────────────
        risk_enabled = state.get("risk_trading_enabled", True)
        risk_regime = state.get("risk_volatility_regime", "—")
        risk_kelly = state.get("risk_kelly_pct", 0.0)
        risk_var_1d = state.get("risk_var_1d_usd", 0.0)
        risk_daily_pnl = state.get("risk_daily_pnl_usd", 0.0)
        risk_open_pos = state.get("risk_open_positions", 0)

        regime_map = {"bullish": "📈", "bearish": "📉", "sideway": "↔️"}
        regime_icon = regime_map.get(risk_regime, "❓")

        risk_status = "🟢 ON" if risk_enabled else "🔴 KILL"
        risk_kelly_str = f"{risk_kelly:.1f}%" if risk_kelly else "—"
        risk_var_str = f"${risk_var_1d:,.2f}" if risk_var_1d else "$—"
        risk_pnl_str = f"+${risk_daily_pnl:,.2f}" if risk_daily_pnl >= 0 else f"${risk_daily_pnl:,.2f}"
        risk_pnl_icon = "📈" if risk_daily_pnl >= 0 else "📉"

        # ── DRY RUN ────────────────────────────────────────────────────────
        dr_trades = self.trade_log.all(mode="dry_run") if self.trade_log else []
        dr_init = state.get("dry_run_initial_balance", 100)
        dr_bal = sum(t.get("close_balance", dr_init) for t in dr_trades) if dr_trades else dr_init
        dr_pnl = dr_bal - dr_init
        dr_pnl_str = f"+{dr_pnl:,.2f}" if dr_pnl >= 0 else f"{dr_pnl:,.2f}"
        dr_pnl_emoji = "📈" if dr_pnl >= 0 else "📉"
        dr_open = len(self.trade_log.get_active(mode="dry_run")) if self.trade_log else 0
        # ── WR from trade_log (source of truth — no perf.update() needed) ──
        def calc_wr(trades: list) -> float:
            if not trades:
                return 0.0
            wins = sum(1 for t in trades if t.get("pnl_pct", 0) > 0)
            return round(wins / len(trades) * 100, 1)

        dr_wr = calc_wr(dr_trades)

        # ── LIVE ──────────────────────────────────────────────────────────
        lv_trades = self.trade_log.all(mode="live") if self.trade_log else []
        lv_init = state.get("live_initial_balance", 0)
        lv_bal = sum(t.get("close_balance", lv_init) for t in lv_trades) if lv_trades else lv_init
        lv_pnl = lv_bal - lv_init
        lv_pnl_str = f"+{lv_pnl:,.2f}" if lv_pnl >= 0 else f"{lv_pnl:,.2f}"
        lv_pnl_emoji = "📈" if lv_pnl >= 0 else "📉"
        lv_open = len(self.trade_log.get_active(mode="live")) if self.trade_log else 0
        lv_wr = calc_wr(lv_trades)
        lv_wr_emoji = "🟢" if lv_wr >= 60 else "🟡" if lv_wr >= 45 else "🔴"
        dr_wr_emoji = "🟢" if dr_wr >= 60 else "🟡" if dr_wr >= 45 else "🔴"

        # Active mode indicator
        active_dr = " ◀️ ACTIVE" if current_mode == "dry_run" else ""
        active_lv = " ◀️ ACTIVE" if current_mode == "live" else ""

        text = (
            f"*📊 TRADOR STATUS*\n\n"
            f"*Mode:* {mode_emoji}\n"
            f"*Direction:* {direction.upper()}\n"
            f"*Wallet:* {'✅ Connected' if wallet_connected else '❌ Not connected'}\n"
            f"*Strategy:* `{strategy_label}` | `{strategy_display}`\n"
            f"*Trading:* {trading}\n\n"
            f"*🛡️ Risk:* {risk_status} | {regime_icon} {risk_regime} | Kelly {risk_kelly_str} | VaR 1d {risk_var_str}\n"
            f"*📈 Daily PnL:* {risk_pnl_icon} {risk_pnl_str} | Open: {risk_open_pos} pos\n\n"
            f"*🟡 DRY RUN{active_dr}*\n"
            f"  Balance: `${dr_bal:,.2f}` | PnL: {dr_pnl_emoji} `{dr_pnl_str}`\n"
            f"  Open: {dr_open} | 24h WR: {dr_wr_emoji} {dr_wr:.1f}%\n\n"
            f"*🔴 LIVE{active_lv}*\n"
            f"  Balance: `${lv_bal:,.2f}` | PnL: {lv_pnl_emoji} `{lv_pnl_str}`\n"
            f"  Open: {lv_open} | 24h WR: {lv_wr_emoji} {lv_wr:.1f}%"
        )

        keyboard = make_back_button("main")
        return text, InlineKeyboardMarkup(keyboard)