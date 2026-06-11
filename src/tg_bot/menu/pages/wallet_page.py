"""Wallet page — exchange connection, API input, connection test."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class WalletPage(MenuPage):
    name = "wallet"

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        text = (
            "*🔗 WALLET SETUP\n\n"
            "Hubungkan exchange untuk live trading.\n"
            "Supported: Binance Futures & Hyperliquid.\n\n"

            "*📋 Langkah Setup:\n"
            "1. Pilih exchange (Binance / Hyperliquid)\n"
            "2. Input API Key + Secret via keyboard\n"
            "3. Test connection → ✅ Connected\n\n"

            "*🔐 API Key Permissions:\n"
            "• Binance: enable Futures trading\n"
            "• Hyperliquid: sign with wallet\n\n"

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
                InlineKeyboardButton("📋 Show .env example", callback_data="wallet:show_env"),
            ],
            [InlineKeyboardButton("◀️ Back", callback_data="page:main")],
        ]
        return text, InlineKeyboardMarkup(keyboard)