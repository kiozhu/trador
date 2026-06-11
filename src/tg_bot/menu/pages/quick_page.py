"""Quick Actions page — cancel all + close all only."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class QuickPage(MenuPage):
    name = "quick"

    def __init__(self, state_mgr=None, loader=None):
        self._state_mgr = state_mgr

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        text = (
            "⚡ QUICK ACTIONS\n\n"
            "🛑 Cancel All — Batalkan semua open order\n"
            "🔴 Close All — Tutup semua posisi (dengan konfirmasi)\n\n"
            "⚠️ Close All akan menutup seluruh posisi yang terbuka.\n"
            "Pastikan sebelum melakukan ini.\n"
        )
        keyboard = [
            [
                InlineKeyboardButton("🛑 Cancel All Orders", callback_data="qa:cancel_all"),
            ],
            [
                InlineKeyboardButton("🔴 Close All Positions", callback_data="qa:close_all"),
            ],
            [InlineKeyboardButton("◀️ Back", callback_data="page:main")],
        ]
        return text, InlineKeyboardMarkup(keyboard)