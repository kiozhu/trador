"""Strategy selection page — multi-strategy toggle, all strategies listed."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class StrategyPage(MenuPage):
    name = "strategy"

    def __init__(self, loader):
        self._loader = loader

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        strategies = self._loader.list_all() if self._loader else []
        active_ids = set(self._loader.list_active_ids()) if self._loader else set()

        lines = [
            "*📈 STRATEGI — Multi-Strategy\n",
            f"Active: {len(active_ids)} | Total: {len(strategies)}\n",
            "_Tap untuk toggle aktif/nonaktif._\n",
        ]

        buttons = []
        for s in strategies:
            sid = s.get("id", "?")
            name = s.get("name", sid)
            if sid in active_ids:
                label = f"✅ {name}"
            else:
                label = f"⚪ {name}"
            buttons.append(InlineKeyboardButton(label, callback_data=f"strat:{sid}"))

        pairs = []
        for i in range(0, len(buttons), 2):
            if i + 1 < len(buttons):
                pairs.append([buttons[i], buttons[i+1]])
            else:
                pairs.append([buttons[i]])

        pairs.append([InlineKeyboardButton("◀️ Back", callback_data="page:main")])
        return "\n".join(lines), InlineKeyboardMarkup(pairs)