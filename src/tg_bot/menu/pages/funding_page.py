"""Funding rates page — show current funding rates per symbol."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class FundingPage(MenuPage):
    name = "funding"

    def __init__(self, state_mgr=None, engine=None):
        self._state_mgr = state_mgr
        self._engine = engine

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get() if self._state_mgr else {}
        funding_rates = state.get("funding_rates", {})

        text = "💰 FUNDING RATES\n"
        text += "Binance settles every 8 hours (00:00, 08:00, 16:00 UTC)\n\n"
        text += "Rate > 0.05%: traders pay funding (shorts pay longs)\n"
        text += "Rate < -0.05%: longs pay shorts\n\n"
        text += "Current rates:\n"

        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT",
                   "DOGE/USDT", "ADA/USDT", "LINK/USDT", "AVAX/USDT",
                   "XAU/USDT", "XAG/USDT"]

        keyboard = []
        if not funding_rates:
            text += "⏳ Loading... Use '🔄 Refresh' to update"
        else:
            for sym in symbols:
                rate = funding_rates.get(sym, 0.0)
                if rate == 0.0 and sym not in funding_rates:
                    continue  # skip if not in cache
                icon = "🔴" if rate > 0.05 else ("🟢" if rate < -0.05 else "⚪")
                text += f"{icon} {sym}: {rate*100:.4f}%\n"

        text += "\n💡 High funding = expensive to hold position"
        keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="funding_refresh")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="nav:monitor")])

        return text, InlineKeyboardMarkup(keyboard)