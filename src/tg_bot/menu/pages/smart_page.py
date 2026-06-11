"""Smart Mode page — jelaskan rule-based vs LLM vs fixed sizing."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class SmartPage(MenuPage):
    name = "smart"

    def __init__(self, state_mgr, loader):
        self._state_mgr = state_mgr
        self._loader = loader

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get()
        smart_on = state.get("smart_mode", False)
        llm_on = state.get("llm_enabled", False)
        sizing_mode = state.get("position_sizing_mode", "fixed")
        active_strats = self._loader.list_active_ids() if self._loader else []
        strategy_count = len(active_strats)

        smart_icon = "✅" if smart_on else "❌"
        llm_icon = "🔮" if llm_on else "📐"

        text = (
            "*🧠 SMART MODE — Position Sizing\n\n"
            f"{smart_icon} Smart Mode: {'ON' if smart_on else 'OFF'}\n"
            f"{llm_icon} LLM Smart: {'ON' if llm_on else 'OFF'}\n"
            f"Active strategies: {strategy_count}\n\n"
            "*3 Mode yang tersedia:\n\n"
            "📐 *Fixed Percent\n"
            "  Trade size = % dari balance\n"
            "  Tidak ada AI/LLM\n"
            "  Simple, predictable, no brain\n\n"
            "🧠 *Smart Mode (Rule-Based)\n"
            "  Evaluasi semua strategi aktif\n"
            "  Pilih symbol terbaik dari 20 pool\n"
            "  Scanner: whale, liq, VP, funding, SMC\n"
            "  Tidak pakai LLM — pure code logic\n\n"
            "🔮 *LLM Smart (Hermes)\n"
            "  Hermes baca trade reports\n"
            "  Analisa market regime + risk\n"
            "  Kasih saran position size via JSON\n"
            "  Hermes pasif — hanya kasih saran\n\n"
            "*Kombinasi:\n"
            "  Smart Mode + LLM = rule-based scoring\n"
            "  + Hermes position advice\n"
            "  Smart Mode only = auto trading tanpa AI\n"
            "  Fixed only = trading manual (LLM off)"
        )

        smart_btn = "❌ Disable Smart Mode" if smart_on else "✅ Enable Smart Mode"
        smart_data = "action:smart_off" if smart_on else "action:smart_on"

        llm_btn = "📐 Fixed Percent Only" if llm_on else "🔮 Enable LLM Smart"
        llm_data = "set:sizing_fixed" if llm_on else "set:sizing_llm"

        keyboard = [
            [InlineKeyboardButton(smart_btn, callback_data=smart_data)],
            [InlineKeyboardButton(llm_btn, callback_data=llm_data)],
            [InlineKeyboardButton("📈 Strategi", callback_data="page:strategy")],
            [InlineKeyboardButton("◀️ Back", callback_data="page:main")],
        ]
        return text, InlineKeyboardMarkup(keyboard)