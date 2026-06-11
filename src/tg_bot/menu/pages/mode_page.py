"""Mode page — Live/Dry Run switching with wallet prerequisites."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class ModePage(MenuPage):
    name = "mode"
    back_callback = "main"

    def __init__(self, state_mgr=None):
        self._state_mgr = state_mgr

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get() if self._state_mgr else {}
        current_mode = state.get("mode", "dry_run")
        wallet_connected = state.get("wallet_connected", False)
        balance_per_trade = state.get("balance_per_trade_pct", 10)

        # Status indicators
        wallet_status = "✅" if wallet_connected else "❌"
        size_status = "✅" if balance_per_trade > 0 else "❌"

        live_prereq = wallet_connected and balance_per_trade > 0

        text = (
            f"🎮 TRADING MODE\n\n"
            f"Current:* {'🔴 LIVE' if current_mode == 'live' else '🟡 DRY RUN'}\n\n"
            f"LIVE mode prerequisites:\n"
            f"  {wallet_status} Wallet connected\n"
            f"  {size_status} Size per trade set ({balance_per_trade}%)\n\n"
        )

        if current_mode == "live":
            text += "🔴 LIVE mode active — real money at risk.\n\n"
            text += "⚠️ To switch back to Dry Run, use Stop Trading first."
        else:
            if live_prereq:
                text += "🟡 Dry Run — testing mode, no real money.\n"
                text += "✅ LIVE prerequisites met — ready to switch."
            else:
                missing = []
                if not wallet_connected:
                    missing.append("connect wallet")
                if balance_per_trade <= 0:
                    missing.append("set trade size")
                text += f"❌ Cannot switch to LIVE — need to: {', '.join(missing)}"

        # Buttons
        keyboard = []
        if current_mode == "dry_run" and live_prereq:
            keyboard.append(
                [InlineKeyboardButton("🔴 Switch to LIVE", callback_data="action:mode_live")]
            )
        if current_mode == "live":
            keyboard.append(
                [InlineKeyboardButton("🟡 Switch to DRY RUN", callback_data="action:mode_dry")]
            )
        keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="page:main")])

        return text, InlineKeyboardMarkup(keyboard)