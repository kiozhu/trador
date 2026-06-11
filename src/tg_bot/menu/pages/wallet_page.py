"""Wallet page — exchange connection, API input, connection test."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class WalletPage(MenuPage):
    name = "wallet"

    def __init__(self, state_mgr=None):
        self._state_mgr = state_mgr

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get() if self._state_mgr else {}
        api_key = state.get("wallet_api_key", "")
        connected = state.get("wallet_connected", False)
        exchange = state.get("exchange", "binance")

        # Show connection status
        if api_key and connected:
            status_line = f"✅ {exchange.upper()} Connected\n{api_key[:12]}... | Tap 🧪 to verify"
        elif api_key:
            status_line = f"🔑 {exchange.upper()} Key Set\n{api_key[:12]}... | Tap 🧪 to connect"
        else:
            status_line = "❌ Not connected\nSelect exchange and input API key/secret"

        text = (
            "🔗 WALLET SETUP\n\n"
            f"{status_line}\n\n"

            "📋 Langkah Setup:\n"
            "1. Pilih exchange (Binance / Hyperliquid)\n"
            "2. Input API Key + Secret via keyboard\n"
            "3. 🧪 Test Connection -> Connected\n\n"

            "🔐 API Key Permissions:\n"
            "  Binance: enable Futures + Spot\n"
            "  Hyperliquid: sign with wallet\n\n"

            "🔏 Credential Type:\n"
            "  Ed25519 (recommended) atau HMAC-SHA256\n"
            "  Bot auto-detect format dari secret.\n\n"

            "⚠️ Keys disimpan lokal only.\n"
            "JANGAN share secret ke siapapun!"
        )

        keyboard = [
            [
                InlineKeyboardButton("🔴 Binance", callback_data="wallet:binance"),
                InlineKeyboardButton("⚡ Hyperliquid", callback_data="wallet:hyperliquid"),
            ],
            [
                InlineKeyboardButton("🔐 Input API Key", callback_data="wallet:input_key"),
                InlineKeyboardButton("🔏 Input API Secret", callback_data="wallet:input_secret"),
            ],
            [
                InlineKeyboardButton("🧪 Test Connection", callback_data="wallet:test"),
                InlineKeyboardButton("🔄 Reload Engine", callback_data="wallet:reload"),
            ],
            [InlineKeyboardButton("◀️ Back", callback_data="page:main")],
        ]
        return text, InlineKeyboardMarkup(keyboard)