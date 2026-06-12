"""Leverage page — set leverage per symbol (1x–125x)."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class LeveragePage(MenuPage):
    name = "leverage"

    def __init__(self, state_mgr=None, engine=None):
        self._state_mgr = state_mgr
        self._engine = engine

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get() if self._state_mgr else {}
        positions = state.get("open_positions", [])
        symbols_with_pos = [p["symbol"] for p in positions]

        # Common futures symbols
        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT",
                   "DOGE/USDT", "ADA/USDT", "LINK/USDT", "AVAX/USDT",
                   "XAU/USDT", "XAG/USDT"]

        text_lines = ["⚙️ LEVERAGE SETUP\n", "Current leverage per symbol:\n"]

        keyboard = []
        row = []
        for sym in symbols:
            lev = self._get_current_leverage(sym, state)
            label = f"{sym.split('/')[0]}: {lev}x"
            row.append(InlineKeyboardButton(label, callback_data=f"lev_set:{sym}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        # Show positions leverage
        if symbols_with_pos:
            text_lines.append("\n📌 Position Leverage:")
            for p in positions:
                sym = p["symbol"]
                lev = p.get("leverage", 1)
                text_lines.append(f"  {sym}: {lev}x")

        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="nav:settings")])

        return "\n".join(text_lines), InlineKeyboardMarkup(keyboard)

    def _get_current_leverage(self, symbol: str, state: dict) -> int:
        # Check open positions first
        for p in state.get("open_positions", []):
            if p.get("symbol") == symbol:
                return p.get("leverage", 3)
        # Default from config
        return state.get("default_leverage", 3)


class LeverageSetPage(MenuPage):
    """Sub-page for setting leverage of a specific symbol."""
    name = "leverage_set"

    def __init__(self, state_mgr=None, engine=None):
        self._state_mgr = state_mgr
        self._engine = engine

    def build(self, symbol: str = "BTC/USDT") -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get() if self._state_mgr else {}
        current = 3
        for p in state.get("open_positions", []):
            if p.get("symbol") == symbol:
                current = p.get("leverage", 3)
                break

        text = f"📊 {symbol}\nCurrent leverage: {current}x\n\nSelect new leverage:"

        keyboard = []
        # Leverage tiers: 1, 2, 3, 5, 10, 20, 50, 100, 125
        levels = [1, 2, 3, 5, 10, 20, 50, 100, 125]
        row = []
        for lv in levels:
            row.append(InlineKeyboardButton(
                f"{lv}x {'✅' if lv == current else ''}",
                callback_data=f"lev_apply:{symbol}:{lv}"
            ))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="nav:leverage")])

        return text, InlineKeyboardMarkup(keyboard)