"""Positions page — mode-aware open positions with manual close."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class PositionsPage(MenuPage):
    name = "positions"

    def __init__(self, trade_log, state_mgr=None):
        self._trade_log = trade_log
        self._state_mgr = state_mgr

    def build(self, mode: str = "dry_run") -> tuple[str, InlineKeyboardMarkup]:
        """Build positions page for given mode."""
        positions = self._trade_log.get_active(mode=mode)
        total = len(positions)

        text = (
            f"📈 *Positions — {mode.upper()}\n\n"
            f"Open: {total}\n\n"
        )

        if not positions:
            text += "_No open positions._"
        else:
            for i, p in enumerate(positions):
                idx = i + 1
                side_emoji = "🟢" if p.get("side") == "LONG" else "🔴"
                entry = p.get("entry_price", 0)
                pnl_pct = p.get("pnl_pct", 0)
                pnl_mark = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"
                lev = p.get("leverage", 1)
                strat = p.get("strategy_id", "unknown")
                sym = p.get("symbol", "?")
                current_pnl = p.get("pnl", 0)
                pnl_amt_str = f"+${current_pnl:.2f}" if current_pnl >= 0 else f"-${abs(current_pnl):.2f}"
                text += f"{side_emoji} {idx}. {sym} {pnl_mark} (x{lev})\n"
                text += f"   Entry: *${entry:.4f} | {strat}\n"
                text += f"   PnL: {pnl_amt_str}\n"

        # Mode toggle
        other_mode = "live" if mode == "dry_run" else "dry_run"
        keyboard = [
            [
                InlineKeyboardButton(f"📂 {mode.upper()}", callback_data=f"pos:{mode}"),
                InlineKeyboardButton(f"📁 {other_mode.upper()}", callback_data=f"pos:{other_mode}"),
            ],
            [InlineKeyboardButton("◀️ Back", callback_data="page:main")],
        ]

        # Add close buttons for each open position
        if positions:
            keyboard.insert(0, [InlineKeyboardButton("─ Close All ─", callback_data=f"pos_close_all:{mode}")])
            for i, p in enumerate(positions):
                idx = i + 1
                sym = p.get("symbol", "?")
                keyboard.insert(idx, [
                    InlineKeyboardButton(f"🔴 Close {sym}", callback_data=f"pos_close:{mode}:{i}"),
                    InlineKeyboardButton(f"📊 Partial {sym}", callback_data=f"pos_partial:{mode}:{i}"),
                ])

        return text, InlineKeyboardMarkup(keyboard)