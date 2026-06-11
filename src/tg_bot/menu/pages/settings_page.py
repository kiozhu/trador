"""Settings page — general bot config with coin pool grid."""
import asyncio
import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage

# Top 30 coins by volume (USDT pairs) — static fallback
_FALLBACK_COINS = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK",
    "MATIC", "LTC", "UNI", "ATOM", "ETC", "XLM", "ALGO", "VET", "ICP", "FIL",
    "APT", "ARB", "NEAR", "AAVE", "GRT", "OP", "INJ", "SUI", "SEI", "FTM",
]

# COIN_LIST — loaded dynamically from Binance, falls back to static
COIN_LIST: list[str] = _FALLBACK_COINS.copy()


def load_coin_list() -> list[str]:
    """Fetch top USDT-mapped symbols from Binance Futures 24hr ticker (sync)."""
    try:
        import json
        import urllib.request
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        # Filter USDT pairs with volume > 0
        pairs = [
            (t["symbol"], float(t.get("quoteVolume", 0) or 0))
            for t in data
            if t["symbol"].endswith("USDT") and float(t.get("quoteVolume", 0) or 0) > 0
        ]
        pairs.sort(key=lambda x: x[1], reverse=True)
        # Convert BTCUSDT → BTC, dedupe
        coins = []
        for sym, vol in pairs[:50]:
            base = sym.replace("USDT", "")
            if base and base not in coins:
                coins.append(base)
        return coins if len(coins) >= 10 else _FALLBACK_COINS
    except Exception:
        return _FALLBACK_COINS


# Load on import
COIN_LIST = load_coin_list()

# Provider presets
LLM_PROVIDERS = {
    "minimax": {"name": "MiniMax M3/M2", "base_url": "https://api.minimax.io", "model_default": "MiniMax-Text-01"},
    "openai": {"name": "OpenAI (GPT-4)", "base_url": "https://api.openai.com/v1", "model_default": "gpt-4o-mini"},
    "xiaomi_mimo": {"name": "Xiaomi MiMo", "base_url": "https://api.mimo.ai/v1", "model_default": "mimo-72b"},
}


class SettingsPage(MenuPage):
    name = "settings"

    def __init__(self, state_mgr):
        self._state_mgr = state_mgr

    def build(self, sub_page: str = None) -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get()
        mode = state.get("mode", "dry_run")
        llm_on = state.get("llm_enabled", False)
        trading = state.get("trading_enabled", False)
        cycle_interval = state.get("cycle_interval", 15)
        daily_loss_limit = state.get("daily_loss_limit", 50)
        max_orders = state.get("max_orders_per_cycle", 2)
        max_pos = state.get("max_concurrent_positions", 5)
        llm_api_key = state.get("llm_api_key", "")
        llm_base_url = state.get("llm_base_url") or ""
        llm_model = state.get("llm_model") or ""
        enabled_symbols = set(state.get("enabled_symbols", "").split(",") if state.get("enabled_symbols") else COIN_LIST)

        # Sub-pages
        if sub_page == "llm":
            return self._build_llm_page(llm_on, llm_api_key, llm_base_url, llm_model)
        if sub_page == "symbols":
            filter_letter = state.get("symbol_filter_letter", None)
            return self._build_symbol_page(enabled_symbols, filter_letter)
        if sub_page == "cycle":
            return self._build_cycle_page(cycle_interval)

        # ── Main settings page ───────────────────────────────────────────
        enabled_count = len(enabled_symbols) if enabled_symbols else 0

        text = (
            "*⚙️ SETTINGS\n\n"
            f"Mode: {mode.upper()} | Trading: {'ON' if trading else 'OFF'}\n\n"
            "─── 🤖 LLM Smart ───\n"
            f"  Status: {'✅ ON' if llm_on else '❌ OFF'}\n"
            f"  API Key: {'✅ Set' if llm_api_key else '⛔ Not Set'}\n"
            f"  Provider: {llm_base_url or 'Not configured'}\n\n"
            "─── ⚡ Trading Params ───\n"
            f"  ⏱️ Cycle Interval: {cycle_interval}s\n"
            f"     → scan tiap {cycle_interval} detik\n"
            f"  📋 Max Orders/Cycle: {max_orders}\n"
            f"  🔢 Max Positions: {max_pos}\n"
            f"  📉 Daily Loss Limit: *$ {daily_loss_limit:.0f}\n\n"
            f"─── 🪙 Symbol Pool ───\n"
            f"  Enabled: {enabled_count}/{len(COIN_LIST)} coins\n"
        )

        keyboard = [
            [InlineKeyboardButton("🤖 LLM Smart", callback_data="set:llm_page")],
            [InlineKeyboardButton(f"⏱️ Cycle: {cycle_interval}s →", callback_data="set:cycle_page")],
            [InlineKeyboardButton(f"📉 Daily Loss: ${daily_loss_limit:.0f}", callback_data="set:daily_loss")],
            [InlineKeyboardButton(f"📋 Max Orders: {max_orders}", callback_data="set:max_orders_cycle")],
            [InlineKeyboardButton(f"🔢 Max Positions: {max_pos}", callback_data="set:max_positions")],
            [InlineKeyboardButton(f"🪙 Coins ({enabled_count}/{len(COIN_LIST)})", callback_data="set:symbol_page")],
            [InlineKeyboardButton("◀️ Back", callback_data="page:main")],
        ]
        return text, InlineKeyboardMarkup(keyboard)

    def _build_llm_page(self, llm_on, api_key, base_url, model) -> tuple[str, InlineKeyboardMarkup]:
        text = (
            "*🤖 LLM Smart Settings\n\n"
            "LLM Smart = Hermes kasih saran position size\n"
            "berdasarkan analisis market regime.\n\n"
            f"Status: {'✅ ON' if llm_on else '❌ OFF'}\n"
            f"API Key: {'✅ Set' if api_key else '⛔ Not Set'}\n\n"
            "─── Provider ───"
        )
        buttons = []
        for key, info in LLM_PROVIDERS.items():
            label = f"✅ {info['name']}" if base_url == info["base_url"] else info["name"]
            buttons.append(InlineKeyboardButton(label, callback_data=f"set:llm_provider:{key}"))

        rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        rows.append([InlineKeyboardButton("🔑 Set API Key", callback_data="set:llm_key")])
        rows.append([InlineKeyboardButton("🧪 Test Connection", callback_data="set:llm_test")])
        rows.append([InlineKeyboardButton(f"{'🔴 Disable' if llm_on else '🟢 Enable'} LLM Smart",
                                          callback_data="set:llm_toggle")])
        rows.append([InlineKeyboardButton("◀️ Back", callback_data="page:settings")])
        return text, InlineKeyboardMarkup(rows)

    def _build_symbol_page(self, enabled: set, filter_letter: str = None) -> tuple[str, InlineKeyboardMarkup]:
        # Filter coins by letter prefix (A-Z)
        if filter_letter:
            filtered = [c for c in COIN_LIST if c.upper().startswith(filter_letter.upper())]
        else:
            filtered = COIN_LIST

        text = (
            "*🪙 Symbol Pool — tap to toggle\n\n"
            "✅ = enabled | ❌ = disabled\n"
            f"Total: {len(COIN_LIST)} coins (Binance Futures)\n\n"
            "_Tap letter to filter, tap coin to toggle._"
        )

        # Letter filter rows — split into groups of 7 to stay within Telegram button-row limits
        import string
        letters = list(string.ascii_uppercase)
        # Build letter groups of 7: A-G, H-N, O-U, V-Z (+ numbers)
        letter_groups = []
        for i in range(0, len(letters), 7):
            group = letters[i:i+7]
            row = []
            for letter in group:
                count = sum(1 for c in COIN_LIST if c.upper().startswith(letter))
                if count == 0:
                    row.append(InlineKeyboardButton("·", callback_data="set:_noop"))
                else:
                    label = f"🔘{letter}" if letter == filter_letter else letter
                    row.append(InlineKeyboardButton(label, callback_data=f"set:symbol_filter:{letter}"))
            letter_groups.append(row)

        rows = letter_groups

        # Show count of filtered coins
        if filter_letter:
            rows.append([InlineKeyboardButton(f"🔍 {filter_letter} ({len(filtered)} coins) — tap ALL", callback_data="set:symbol_filter:")])

        # Coin grid (filtered)
        for i in range(0, len(filtered), 3):
            row = []
            for coin in filtered[i:i+3]:
                label = f"✅{coin}" if coin in enabled else f"❌{coin}"
                row.append(InlineKeyboardButton(label, callback_data=f"set:symbol_toggle:{coin}"))
            rows.append(row)

        # Back
        rows.append([InlineKeyboardButton("◀️ Back", callback_data="page:settings")])
        return text, InlineKeyboardMarkup(rows)

    def _build_cycle_page(self, current: int) -> tuple[str, InlineKeyboardMarkup]:
        options = [5, 10, 15, 30, 60, 120]
        text = (
            "*⏱️ Cycle Interval\n\n"
            "berapa detik antar scan cycle.\n"
            "Semakin kecil = lebih responsif tapi\n"
            "lebih banyak API calls.\n\n"
            f"Current: {current}s\n\n"
            "Pilih interval:"
        )
        rows = []
        row = []
        for opt in options:
            label = f"✅{opt}s" if opt == current else f"{opt}s"
            row.append(InlineKeyboardButton(label, callback_data=f"set:cycle_set:{opt}"))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton("◀️ Back", callback_data="page:settings")])
        return text, InlineKeyboardMarkup(rows)