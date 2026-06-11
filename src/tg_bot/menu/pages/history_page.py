"""History page — mode-aware with time range filter, delete trades."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class HistoryPage(MenuPage):
    name = "history"

    def __init__(self, trade_log):
        self._trade_log = trade_log

    def build(self, mode: str = "dry_run", time_range: str = "24h",
              show_delete: bool = False) -> tuple[str, InlineKeyboardMarkup]:
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        if time_range == "7d":
            cutoff = now - timedelta(days=7)
        elif time_range == "30d":
            cutoff = now - timedelta(days=30)
        elif time_range == "all":
            cutoff = None
        else:
            cutoff = now - timedelta(hours=24)

        all_trades = self._trade_log.all(mode=mode)

        if cutoff:
            cutoff_iso = cutoff.isoformat()
            trades = [t for t in all_trades if (t.get("close_timestamp") or t.get("timestamp", "")) >= cutoff_iso]
        else:
            trades = all_trades[-50:]

        total = len(trades)
        wins = sum(1 for t in trades if t.get("pnl_pct", 0) > 0)
        losses = total - wins
        wr = (wins / total * 100) if total > 0 else 0
        pnl_sum = sum(t.get("pnl_pct", 0) for t in trades)
        pnl_usr = sum(t.get("pnl", 0) for t in trades)
        pnl_str = f"+${pnl_usr:.2f}" if pnl_usr >= 0 else f"-${abs(pnl_usr):.2f}"
        wr_icon = "🟢" if wr >= 60 else "🟡" if wr >= 45 else "🔴"

        text = (
            f"📋 HISTORY — {mode.upper()}\n"
            f"Filter: {time_range.upper()}\n\n"
            f"📊 {total} trades | {wr_icon} WR: {wr:.1f}%\n"
            f"   Wins: {wins} | Losses: {losses}\n"
            f"   PnL: {pnl_str} ({pnl_sum:+.1f}%)\n\n"
        )

        if not trades:
            text += "No trades in this range."
        else:
            text += "Recent Trades:\n"
            text += "─────────────────────\n"
            for t in trades[-15:]:
                side_icon = "🟢" if t.get("side") == "LONG" else "🔴"
                ts = (t.get("close_timestamp") or t.get("timestamp", ""))[11:16]
                pnl_val = t.get("pnl_pct", 0)
                pnl_mark = f"+{pnl_val:.1f}%" if pnl_val >= 0 else f"{pnl_val:.1f}%"
                exit_r = t.get("exit_reason", "-").upper()
                sym = t.get("symbol", "?")
                lev = t.get("leverage", 1)
                pnl_amt = t.get("pnl", 0)
                pnl_amt_str = f"+${pnl_amt:.2f}" if pnl_amt >= 0 else f"-${abs(pnl_amt):.2f}"
                text += f"{ts} {side_icon} {sym} (x{lev})\n"
                text += f"   TP/SL: {pnl_mark} | {pnl_amt_str} | {exit_r}\n"

        ranges = ["24h", "7d", "30d", "all"]
        range_row = [InlineKeyboardButton(r.upper(), callback_data=f"hist:{mode}:{r}") for r in ranges]
        other_mode = "live" if mode == "dry_run" else "dry_run"
        mode_row = [
            InlineKeyboardButton(f"📂 {mode.upper()}", callback_data=f"hist:{mode}:{time_range}"),
            InlineKeyboardButton(f"📁 {other_mode.upper()}", callback_data=f"hist:{other_mode}:{time_range}"),
        ]

        if show_delete:
            delete_row = [
                InlineKeyboardButton("🗑 Delete 24h", callback_data=f"hist_del:{mode}:24h"),
                InlineKeyboardButton("🗑 Delete 7d", callback_data=f"hist_del:{mode}:7d"),
            ]
            delete_row2 = [
                InlineKeyboardButton("🗑 Delete 30d", callback_data=f"hist_del:{mode}:30d"),
                InlineKeyboardButton("🗑 Delete ALL", callback_data=f"hist_del:{mode}:all"),
            ]
            keyboard = [
                range_row,
                mode_row,
                delete_row,
                delete_row2,
                [InlineKeyboardButton("◀️ Back", callback_data="page:main")],
            ]
        else:
            keyboard = [
                range_row,
                mode_row,
                [InlineKeyboardButton("🗑 Delete", callback_data=f"hist_delete_menu:{mode}:{time_range}")],
                [InlineKeyboardButton("◀️ Back", callback_data="page:main")],
            ]
        return text, InlineKeyboardMarkup(keyboard)