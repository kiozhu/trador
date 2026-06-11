"""Main menu page — trojan-style inline keyboard."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class MainPage(MenuPage):
    name = "main"

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        text = (
            "*🚀 TRADOR — Trading Bot*\n\n"
            "Pilih menu di bawah:"
        )
        keyboard = [
            [
                InlineKeyboardButton("📊 Status", callback_data="page:status"),
                InlineKeyboardButton("📈 Positions", callback_data="page:positions"),
            ],
            [
                InlineKeyboardButton("⚙️ Strategi", callback_data="page:strategy"),
                InlineKeyboardButton("📋 History", callback_data="page:history"),
            ],
            [
                InlineKeyboardButton("💰 Balance", callback_data="page:balance"),
                InlineKeyboardButton("🔗 Wallet", callback_data="page:wallet"),
            ],
            [
                InlineKeyboardButton("🎮 Mode", callback_data="page:mode"),
                InlineKeyboardButton("📡 Monitor", callback_data="page:monitor"),
            ],
            [
                InlineKeyboardButton("🛠️ Settings", callback_data="page:settings"),
                InlineKeyboardButton("🛡️ Risk", callback_data="page:risk"),
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="page:help"),
            ],
            [
                InlineKeyboardButton("🚀 Start Trading", callback_data="action:start"),
            ],
            [
                InlineKeyboardButton("🛑 Stop Trading", callback_data="action:stop"),
            ],
        ]
        return text, InlineKeyboardMarkup(keyboard)