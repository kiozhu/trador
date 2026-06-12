"""Margin type page — switch ISOLATED / CROSSED per symbol."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class MarginTypePage(MenuPage):
    name = "margin_type"

    def __init__(self, state_mgr=None, engine=None):
        self._state_mgr = state_mgr
        self._engine = engine

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get() if self._state_mgr else {}
        positions = state.get("open_positions", [])

        text = "📍 MARGIN TYPE\n\nISOLATED — position frozen at entry margin\nCROSSED — entire balance used as margin\n\nCurrent positions:"

        keyboard = []
        if not positions:
            text += "\n  No open positions"
        else:
            for p in positions:
                sym = p["symbol"]
                margin = p.get("margin_type", "CROSSED")
                icon = "🔶" if margin == "ISOLATED" else "🔷"
                text += f"\n{icon} {sym}: {margin}"
                keyboard.append([
                    InlineKeyboardButton(
                        f"🔶 {sym} → ISOLATED",
                        callback_data=f"mt_isolated:{sym}"
                    ),
                    InlineKeyboardButton(
                        f"🔷 {sym} → CROSSED",
                        callback_data=f"mt_crossed:{sym}"
                    ),
                ])

        # Add symbol selector for setting margin type on non-position symbols
        text += "\n\nSet for symbol (no open position):"
        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "XAU/USDT"]
        row = []
        for sym in symbols:
            row.append(InlineKeyboardButton(sym.split("/")[0], callback_data=f"mt_set:{sym}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="nav:settings")])

        return text, InlineKeyboardMarkup(keyboard)