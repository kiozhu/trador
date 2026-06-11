"""Direction page (Long/Short/Both)."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class DirectionPage(MenuPage):
    name = "direction"

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        text = "📐 Direction\n\nPilih arah trading."
        keyboard = [
            [InlineKeyboardButton("📈 Long — Buy only", callback_data="action:dir_long")],
            [InlineKeyboardButton("📉 Short — Sell only", callback_data="action:dir_short")],
            [InlineKeyboardButton("🔄 Both — Auto", callback_data="action:dir_both")],
            [InlineKeyboardButton("◀️ Back", callback_data="page:main")],
        ]
        return text, InlineKeyboardMarkup(keyboard)