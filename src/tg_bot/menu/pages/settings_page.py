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

# Provider presets — base_url can be overridden by user
LLM_PROVIDERS = {
    "minimax": {
        "name": "MiniMax",
        "base_url": "https://api.minimax.io/v1",
        "model_default": "MiniMax-M3",
        "auth_type": "Bearer",
    },
    "xiaomi": {
        "name": "Xiaomi MiMo",
        "base_url": "https://platform.xiaomimimo.com/v1",
        "model_default": "MiniMax-2.5-Pro",
        "auth_type": "X-Api-Key",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model_default": "gpt-4o-mini",
        "auth_type": "Bearer",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model_default": "deepseek-chat",
        "auth_type": "Bearer",
    },
    "custom": {
        "name": "Custom URL",
        "base_url": "",
        "model_default": "",
        "auth_type": "Bearer",
    },
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
            "⚙️ SETTINGS\n\n"
            f"Mode: {mode.upper()} | Trading: {'ON' if trading else 'OFF'}\n\n"
            "─── 🤖 LLM Smart ───\n"
            f"  Status: {'✅ ON' if llm_on else '❌ OFF'}\n"
            f"  API Key: {'✅ Set' if llm_api_key else '⛔ Not Set'}\n"
            f"  Provider: {llm_base_url or 'Not configured'}\n"
        )

        keyboard = [
            [InlineKeyboardButton("🤖 LLM Smart", callback_data="set:llm_page")],
            [InlineKeyboardButton("◀️ Back", callback_data="page:main")],
        ]
        return text, InlineKeyboardMarkup(keyboard)

    def _build_llm_page(self, llm_on, api_key, base_url, model) -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get()
        provider_key = state.get("llm_provider", "minimax")
        active_provider = LLM_PROVIDERS.get(provider_key, LLM_PROVIDERS["minimax"])

        # Show current values — use custom if base_url was manually set
        if provider_key == "custom":
            display_url = base_url or "(not set)"
            display_model = model or "(not set)"
        else:
            display_url = base_url if base_url else active_provider["base_url"]
            display_model = model if model else active_provider["model_default"]

        has_key = bool(api_key)

        text = (
            "🤖 LLM Smart Settings\n\n"
            f"Status: {'✅ ON' if llm_on else '❌ OFF'}\n"
            f"API Key: {'✅ Set' if has_key else '⛔ Not Set'}\n\n"
            f"Provider: {active_provider['name']}\n"
            f"Base URL: {display_url}\n"
            f"Model: {display_model}\n\n"
            "─── Change Provider ───"
        )

        # Provider selection rows — 2 per row
        rows = []
        providers = [(k, v) for k, v in LLM_PROVIDERS.items() if k != "custom"]
        for i in range(0, len(providers), 2):
            row = []
            for k, v in providers[i:i+2]:
                label = f"✅ {v['name']}" if k == provider_key else v["name"]
                row.append(InlineKeyboardButton(label, callback_data=f"set:llm_provider:{k}"))
            rows.append(row)

        rows.append([InlineKeyboardButton("✏️ Edit Base URL", callback_data="set:llm_base_url")])
        rows.append([InlineKeyboardButton("✏️ Edit Model", callback_data="set:llm_model")])
        rows.append([InlineKeyboardButton("🔑 Set API Key", callback_data="set:llm_key")])
        rows.append([InlineKeyboardButton("🧪 Test Connection", callback_data="set:llm_test")])
        rows.append([InlineKeyboardButton(
            f"{'🔴 Disable' if llm_on else '🟢 Enable'} LLM Smart",
            callback_data="set:llm_toggle"
        )])
        rows.append([InlineKeyboardButton("◀️ Back", callback_data="page:settings")])
        return text, InlineKeyboardMarkup(rows)

    def _build_symbol_page(self, enabled: set, filter_letter: str = None) -> tuple[str, InlineKeyboardMarkup]:
        # Filter coins by letter prefix (A-Z)
        if filter_letter:
            filtered = [c for c in COIN_LIST if c.upper().startswith(filter_letter.upper())]
        else:
            filtered = COIN_LIST

        text = (
            "🪙 Symbol Pool — tap to toggle\n\n"
            "✅ = enabled | ❌ = disabled\n"
            f"Total: {len(COIN_LIST)} coins (Binance Futures)\n\n"
            "Tap letter to filter, tap coin to toggle."
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
        rows.append([InlineKeyboardButton("◀️ Back", callback_data="page:risk")])
        return text, InlineKeyboardMarkup(rows)

    def _build_cycle_page(self, current: int) -> tuple[str, InlineKeyboardMarkup]:
        options = [5, 10, 15, 30, 60, 120]
        text = (
            "⏱️ Cycle Interval\n\n"
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