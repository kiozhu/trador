"""Telegram keyboards — reply and inline"""
from telegram import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup

# ── Reply Keyboard (persistent menu) ──────────────────────────────────────

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📊 Status"), KeyboardButton("📈 Positions")],
            [KeyboardButton("⚙️ Strategi"), KeyboardButton("📋 History")],
            [KeyboardButton("🚀 Start"), KeyboardButton("🛑 Stop")],
            [KeyboardButton("💰 Balance"), KeyboardButton("❓ Help")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


# ── Inline Keyboard — Strategy Selection ─────────────────────────────────────

def strategy_selection_keyboard(strategies: list[dict], active_id: str | None) -> InlineKeyboardMarkup:
    buttons = []
    for s in strategies:
        label = f"📈 {s['name']}" if s["id"] == active_id else s["name"]
        buttons.append(
            InlineKeyboardButton(label, callback_data=f"strat_select:{s['id']}")
        )
    # 2 per row
    pairs = [(buttons[i], buttons[i+1]) if i+1 < len(buttons) else (buttons[i],)
             for i in range(0, len(buttons), 2)]
    pairs.append([InlineKeyboardButton("📋 Lihat Config", callback_data="strat_view_config")])
    return InlineKeyboardMarkup(pairs)


def strategy_param_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Risk %", callback_data="param:risk"),
         InlineKeyboardButton("📏 TP/SL", callback_data="param:tpsl")],
        [InlineKeyboardButton("🔢 Leverage", callback_data="param:leverage"),
         InlineKeyboardButton("⏱️ Max Hold", callback_data="param:maxhold")],
        [InlineKeyboardButton("📦 Position Size", callback_data="param:size"),
         InlineKeyboardButton("◀️ Kembali", callback_data="menu_main")],
    ])


def risk_percent_keyboard() -> InlineKeyboardMarkup:
    options = ["1%", "2%", "3%", "5%", "10%"]
    buttons = [InlineKeyboardButton(o, callback_data=f"set:risk:{o}") for o in options]
    pairs = [(buttons[i], buttons[i+1]) if i+1 < len(buttons) else (buttons[i],)
             for i in range(0, len(buttons), 2)]
    pairs.append([InlineKeyboardButton("◀️ Kembali", callback_data="strat_params")])
    return InlineKeyboardMarkup(pairs)


def leverage_keyboard() -> InlineKeyboardMarkup:
    options = ["1x", "2x", "3x", "5x", "10x"]
    buttons = [InlineKeyboardButton(o, callback_data=f"set:leverage:{o}") for o in options]
    pairs = [(buttons[i], buttons[i+1]) if i+1 < len(buttons) else (buttons[i],)
             for i in range(0, len(buttons), 2)]
    pairs.append([InlineKeyboardButton("◀️ Kembali", callback_data="strat_params")])
    return InlineKeyboardMarkup(pairs)


def trailing_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Off", callback_data="set:trailing:off"),
         InlineKeyboardButton("Breakeven", callback_data="set:trailing:breakeven"),
         InlineKeyboardButton("Secure", callback_data="set:trailing:secure")],
        [InlineKeyboardButton("Trail", callback_data="set:trailing:trail"),
         InlineKeyboardButton("◀️ Kembali", callback_data="strat_params")],
    ])
