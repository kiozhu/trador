"""Countdown page — emergency auto-cancel timer (Binance countdownCancelAll API)."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class CountdownPage(MenuPage):
    name = "countdown"

    def __init__(self, state_mgr=None, engine=None):
        self._state_mgr = state_mgr
        self._engine = engine

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get() if self._state_mgr else {}
        countdown_sec = state.get("countdown_timer_sec", 0)
        countdown_active = state.get("countdown_active", False)

        text = "⏱️ EMERGENCY COUNTDOWN\n\n"
        text += "Set a timer — ALL orders auto-cancelled after N seconds.\n"
        text += "Safety feature: prevents runaway orders if bot misbehaves.\n\n"

        if countdown_active:
            text += f"⏳ ACTIVE: {countdown_sec}s remaining\n"
            text += "All open orders will be cancelled when timer expires.\n"
        else:
            text += "Timer not active.\n"

        text += "\nSet countdown (seconds):"

        keyboard = []
        # Timer options: 10, 30, 60, 120, 300, 600 seconds
        row = []
        for t in [10, 30, 60, 120, 300]:
            label = f"{t}s" if t < 60 else f"{t//60}m"
            row.append(InlineKeyboardButton(label, callback_data=f"cd_set:{t}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        if countdown_active:
            keyboard.append([
                InlineKeyboardButton("🛑 STOP TIMER", callback_data="cd_stop"),
                InlineKeyboardButton("❌ CANCEL ALL NOW", callback_data="ocancel_all"),
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("🛑 STOP TIMER", callback_data="cd_stop"),
            ])

        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="nav:settings")])

        return text, InlineKeyboardMarkup(keyboard)