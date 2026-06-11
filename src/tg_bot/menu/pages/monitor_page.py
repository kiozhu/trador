"""Monitor page — real-time AutoTrader activity, synced with actual state."""
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class MonitorPage(MenuPage):
    name = "monitor"
    back_callback = "main"

    def __init__(self, state_mgr, trade_log, perf, loader=None):
        self.state_mgr = state_mgr
        self.trade_log = trade_log
        self.perf = perf
        self._loader = loader

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        state = self.state_mgr.get()
        trading = state.get("trading_enabled", False)
        mode = state.get("mode", "dry_run")

        # ── Active strategies from StrategyLoader (source of truth) ─────────
        active_strats = []
        if self._loader:
            active_ids = self._loader.list_active_ids()
            active_strats = [s.get("name", sid) for sid, s in
                             ((sid, self._loader.get(sid)) for sid in active_ids) if s]
        strat_display = ", ".join(active_strats) if active_strats else "none"

        # ── Balance ───────────────────────────────────────────────────────
        if mode == "dry_run":
            balance = state.get("dry_run_balance", 100)
            init_bal = state.get("dry_run_initial_balance", 100)
        else:
            balance = state.get("live_balance", 0)
            init_bal = state.get("live_initial_balance", 0)
        pnl_amt = balance - init_bal
        pnl_str = f"+{pnl_amt:.2f}" if pnl_amt >= 0 else f"{pnl_amt:.2f}"
        pnl_pct = (pnl_amt / init_bal * 100) if init_bal > 0 else 0

        # ── Active positions from TradeLog ───────────────────────────────
        active_pos = self.trade_log.get_active(mode=mode) if self.trade_log else []
        open_count = len(active_pos)

        # ── Scanner states ───────────────────────────────────────────────
        scanners = state.get("scanner_states", {})
        scanner_summary = []
        for name, sc_state in scanners.items():
            active_signals = sc_state.get("active_signals", 0) if isinstance(sc_state, dict) else 0
            if active_signals > 0:
                scanner_summary.append(f"  • {name}: {active_signals} signal(s)")
        if not scanner_summary:
            scanner_summary = ["  • Semua scanner aktif — no signals"]
        scanner_text = "\n".join(scanner_summary)

        # ── Trade size settings ───────────────────────────────────────────
        size_pct = state.get("balance_per_trade_pct", 10)
        max_orders = state.get("max_orders_per_cycle", 2)
        max_pos = state.get("max_concurrent_positions", 5)
        daily_loss = state.get("daily_loss_limit", 50)

        # ── Status icons ─────────────────────────────────────────────────
        status_icon = "🟢" if trading else "🔴"
        mode_icon = "🔴 LIVE" if mode == "live" else "🟡 DRY"
        pool_size = state.get("symbol_pool_size", 20)
        cycle_interval = state.get("cycle_interval", 15)

        # ── Recent closed trades (last 5) ─────────────────────────────────
        recent = self.trade_log.recent(5, mode=mode) if self.trade_log else []

        text = (
            f"📡 TRADOR MONITOR\n\n"
            f"{status_icon} Status: {'AKTIF' if trading else 'STOPPED'} | {mode_icon}\n"
            f"Balance: *${balance:,.2f} | PnL: {pnl_str} ({pnl_pct:+.2f}%)\n\n"

            f"⚙️ SETTINGS SYNC\n"
            f"  Strategy: {strat_display}\n"
            f"  Size/trade: {size_pct}%\n"
            f"  Max orders/cycle: {max_orders}\n"
            f"  Max positions: {max_pos}\n"
            f"  Daily loss limit: *$ {daily_loss:.0f}\n"
            f"  Pool size: {pool_size} symbols\n"
            f"  Cycle interval: {cycle_interval}s\n\n"

            f"📊 POSITIONS\n"
            f"  Open: {open_count} | Max: {max_pos}\n"
        )

        # Open positions detail
        if active_pos:
            text += "  ─── Open Positions ───\n"
            for p in active_pos[:5]:
                side = p.get("side", "?").upper()
                sym = p.get("symbol", "?")
                pnl_val = p.get("pnl_pct", 0)
                pnl_str2 = f"+{pnl_val:.1f}%" if pnl_val >= 0 else f"{pnl_val:.1f}%"
                lev = p.get("leverage", 1)
                text += f"  {side} {sym} (x{lev}) {pnl_str2}\n"

        text += f"\n*🔍 SCANNERS\n{scanner_text}\n"

        # Recent trades with full details
        if recent:
            text += "\n*🕐 RECENT CLOSED\n"
            for t in reversed(recent):
                pnl_val = t.get("pnl_pct", 0)
                icon = "✅" if pnl_val >= 0 else "❌"
                side = t.get("side", "?").upper()
                sym = t.get("symbol", "?")
                lev = t.get("leverage", 1)
                entry = t.get("entry_price", 0)
                exit_p = t.get("exit_price", 0)
                fee = t.get("exit_fee", 0)
                pnl_amt = t.get("pnl", 0)
                exit_r = t.get("exit_reason", "?").upper()
                ts_str = "--:--"
                ts = t.get("close_timestamp") or t.get("timestamp", "")
                if ts:
                    try:
                        if isinstance(ts, (int, float)):
                            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                        else:
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        ts_str = dt.strftime("%H:%M:%S")
                    except (ValueError, TypeError):
                        pass
                pnl_amt_str = f"+${pnl_amt:.2f}" if pnl_amt >= 0 else f"-${abs(pnl_amt):.2f}"
                text += f"{icon} {ts_str} {side} {sym} (x{lev})\n"
                text += f"   Entry: ${entry:.4f} → Exit: ${exit_p:.4f}\n"
                text += f"   Fee: *${fee:.4f} | PnL: {pnl_amt_str} ({pnl_val:+.2f}%) [{exit_r}]\n"
        else:
            text += "\n*🕐 RECENT CLOSED\n  Belum ada closed trade.\n"

        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="page:monitor")],
            [InlineKeyboardButton("◀️ Back to Menu", callback_data="page:main")],
        ]
        return text, InlineKeyboardMarkup(keyboard)