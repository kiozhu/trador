"""Telegram keyboards — reply and inline menus"""
from telegram import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup

# ── Reply Keyboard (persistent bottom menu) ─────────────────────────────────

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("⚡ Quick Actions"), KeyboardButton("📈 Positions")],
            [KeyboardButton("⚙️ Strategi"), KeyboardButton("📋 History")],
            [KeyboardButton("🚀 Start"), KeyboardButton("🛑 Stop")],
            [KeyboardButton("💰 Balance"), KeyboardButton("🧠 Smart Mode")],
            [KeyboardButton("📊 PnL Chart"), KeyboardButton("🔗 Wallet")],
            [KeyboardButton("🎮 Mode"), KeyboardButton("❓ Help")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def smart_mode_keyboard() -> ReplyKeyboardMarkup:
    """Smart mode control panel."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🤖 Auto Trading"), KeyboardButton("🔄 Force Scan")],
            [KeyboardButton("📊 Smart Stats"), KeyboardButton("🎯 Best Strategy")],
            [KeyboardButton("🧪 Simulate Next"), KeyboardButton("◀️ Back")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def quick_actions_keyboard() -> ReplyKeyboardMarkup:
    """Quick action panel — instant execution."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📋 View Orders"), KeyboardButton("❌ Cancel All")],
            [KeyboardButton("💸 Close All"), KeyboardButton("📈 Avg Entry")],
            [KeyboardButton("🔍 Scan Market"), KeyboardButton("📐 Direction")],
            [KeyboardButton("◀️ Back")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


# ── Inline: Strategy Selection ───────────────────────────────────────────────

def strategy_selection_keyboard(strategies: list[dict], active_id: str | None) -> InlineKeyboardMarkup:
    buttons = []
    for s in strategies:
        label = f"📈 {s['name']}" if s["id"] == active_id else s["name"]
        active_mark = " ✅" if s["id"] == active_id else ""
        buttons.append(
            InlineKeyboardButton(f"{label}{active_mark}", callback_data=f"strat_select:{s['id']}")
        )
    # 2 per row
    pairs = _pair_up(buttons)
    pairs.append([InlineKeyboardButton("📋 Lihat Config", callback_data="strat_view_config")])
    pairs.append([InlineKeyboardButton("🧠 Smart Select", callback_data="strat_smart")])
    return InlineKeyboardMarkup(pairs)


def _pair_up(buttons: list[InlineKeyboardButton]) -> list[tuple]:
    pairs = []
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            pairs.append((buttons[i], buttons[i+1]))
        else:
            pairs.append((buttons[i],))
    return pairs


# ── Inline: Strategy Detail / Toggle ────────────────────────────────────────

def strategy_detail_keyboard(strategy_id: str, is_active: bool) -> InlineKeyboardMarkup:
    activate_label = "⏸️ Deactivate" if is_active else "✅ Activate"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(activate_label, callback_data=f"strat_toggle:{strategy_id}")],
        [InlineKeyboardButton("✏️ Edit Params", callback_data=f"strat_edit:{strategy_id}"),
         InlineKeyboardButton("📄 View Full Config", callback_data=f"strat_full:{strategy_id}")],
        [InlineKeyboardButton("📊 Performa", callback_data=f"strat_perf:{strategy_id}"),
         InlineKeyboardButton("🗑️ Delete", callback_data=f"strat_delete:{strategy_id}")],
        [InlineKeyboardButton("◀️ Kembali", callback_data="strat_back")],
    ])


# ── Inline: Parameter Adjustment ─────────────────────────────────────────────

def strategy_param_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Risk %", callback_data="param:risk"),
         InlineKeyboardButton("📏 TP/SL", callback_data="param:tpsl")],
        [InlineKeyboardButton("🔢 Leverage", callback_data="param:leverage"),
         InlineKeyboardButton("⏱️ Max Hold", callback_data="param:maxhold")],
        [InlineKeyboardButton("📦 Position Size", callback_data="param:size"),
         InlineKeyboardButton("🔗 Trailing", callback_data="param:trailing")],
        [InlineKeyboardButton("📐 Grid Size", callback_data="param:grid"),
         InlineKeyboardButton("📍 Signal src", callback_data="param:signal")],
        [InlineKeyboardButton("◀️ Kembali", callback_data="menu_main")],
    ])


def risk_percent_keyboard() -> InlineKeyboardMarkup:
    options = ["0.5%", "1%", "2%", "3%", "5%", "10%"]
    buttons = [InlineKeyboardButton(o, callback_data=f"set:risk:{o}") for o in options]
    pairs = _pair_up(buttons)
    pairs.append([InlineKeyboardButton("Custom →", callback_data="param:risk_custom"),
                  InlineKeyboardButton("◀️ Kembali", callback_data="strat_params")])
    return InlineKeyboardMarkup(pairs)


def leverage_keyboard() -> InlineKeyboardMarkup:
    options = ["1x", "2x", "3x", "5x", "10x", "20x"]
    buttons = [InlineKeyboardButton(o, callback_data=f"set:leverage:{o}") for o in options]
    pairs = _pair_up(buttons)
    pairs.append([InlineKeyboardButton("◀️ Kembali", callback_data="strat_params")])
    return InlineKeyboardMarkup(pairs)


def maxhold_keyboard() -> InlineKeyboardMarkup:
    options = ["5m", "10m", "15m", "30m", "45m", "60m"]
    buttons = [InlineKeyboardButton(o, callback_data=f"set:maxhold:{o}") for o in options]
    pairs = _pair_up(buttons)
    pairs.append([InlineKeyboardButton("◀️ Kembali", callback_data="strat_params")])
    return InlineKeyboardMarkup(pairs)


def position_size_keyboard() -> InlineKeyboardMarkup:
    options = ["2%", "5%", "10%", "15%", "20%", "30%"]
    buttons = [InlineKeyboardButton(o, callback_data=f"set:size:{o}") for o in options]
    pairs = _pair_up(buttons)
    pairs.append([InlineKeyboardButton("◀️ Kembali", callback_data="strat_params")])
    return InlineKeyboardMarkup(pairs)


def trailing_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Off ❌", callback_data="set:trailing:off"),
         InlineKeyboardButton("Breakeven", callback_data="set:trailing:breakeven")],
        [InlineKeyboardButton("Secure 🔒", callback_data="set:trailing:secure"),
         InlineKeyboardButton("Trail 📈", callback_data="set:trailing:trail")],
        [InlineKeyboardButton("◀️ Kembali", callback_data="strat_params")],
    ])


def tpsl_keyboard() -> InlineKeyboardMarkup:
    """TP/SL inline keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("SL: 1%", callback_data="set:sl:1"),
         InlineKeyboardButton("SL: 2%", callback_data="set:sl:2")],
        [InlineKeyboardButton("SL: 3%", callback_data="set:sl:3"),
         InlineKeyboardButton("SL: 5%", callback_data="set:sl:5")],
        [InlineKeyboardButton("TP: 3%", callback_data="set:tp:3"),
         InlineKeyboardButton("TP: 5%", callback_data="set:tp:5")],
        [InlineKeyboardButton("TP: 8%", callback_data="set:tp:8"),
         InlineKeyboardButton("TP: 10%", callback_data="set:tp:10")],
        [InlineKeyboardButton("◀️ Kembali", callback_data="strat_params")],
    ])


def grid_keyboard() -> InlineKeyboardMarkup:
    options = ["2", "3", "5", "7", "10", "15"]
    buttons = [InlineKeyboardButton(f"{o} grids", callback_data=f"set:grid:{o}") for o in options]
    pairs = _pair_up(buttons)
    pairs.append([InlineKeyboardButton("◀️ Kembali", callback_data="strat_params")])
    return InlineKeyboardMarkup(pairs)


def signal_source_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("EMA", callback_data="set:signal:ema"),
         InlineKeyboardButton("RSI", callback_data="set:signal:rsi")],
        [InlineKeyboardButton("MACD", callback_data="set:signal:macd"),
         InlineKeyboardButton("Bollinger", callback_data="set:signal:bollinger")],
        [InlineKeyboardButton("Volume", callback_data="set:signal:volume"),
         InlineKeyboardButton("ADX", callback_data="set:signal:adx")],
        [InlineKeyboardButton("◀️ Kembali", callback_data="strat_params")],
    ])


# ── Inline: Wallet Connect ────────────────────────────────────────────────────

def wallet_panel_keyboard(connected: bool, exchange: str | None, address: str | None) -> InlineKeyboardMarkup:
    if connected:
        addr_short = (address[:6] + "..." + address[-4:]) if address else "—"
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔗 {(exchange or '').upper()}: {addr_short}", callback_data="wallet_info")],
            [InlineKeyboardButton("🔄 Reconnect", callback_data="wallet_reconnect")],
            [InlineKeyboardButton("🔌 Disconnect", callback_data="wallet_disconnect")],
            [InlineKeyboardButton("◀️ Back", callback_data="menu_main")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟣 Binance Futures", callback_data="wallet:binance")],
        [InlineKeyboardButton("🔵 Bybit Unified", callback_data="wallet:bybit")],
        [InlineKeyboardButton("🟠 OKX", callback_data="wallet:okx")],
        [InlineKeyboardButton("◀️ Back", callback_data="menu_main")],
    ])


def wallet_connecting_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏳ Connecting...", callback_data="wallet_none")],
    ])


# ── Inline: Mode Selection ───────────────────────────────────────────────────

def mode_selection_keyboard(current: str) -> InlineKeyboardMarkup:
    live = "🔴 LIVE" if current == "live" else "LIVE"
    dry = "🟡 DRY RUN" if current == "dry_run" else "DRY RUN"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔴 {live}", callback_data="mode:live"),
         InlineKeyboardButton(f"🟡 {dry}", callback_data="mode:dry_run")],
        [InlineKeyboardButton("📊 View Mode Info", callback_data="mode:info")],
        [InlineKeyboardButton("◀️ Back", callback_data="menu_main")],
    ])


# ── Inline: Long/Short Direction ─────────────────────────────────────────────

def direction_keyboard(current: str | None) -> InlineKeyboardMarkup:
    long_mark = " ✅" if current == "long" else ""
    short_mark = " ✅" if current == "short" else ""
    both_mark = " ✅" if current == "both" else ""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📈 LONG{long_mark}", callback_data="dir:long"),
         InlineKeyboardButton(f"📉 SHORT{short_mark}", callback_data="dir:short")],
        [InlineKeyboardButton(f"🔄 BOTH{both_mark}", callback_data="dir:both")],
        [InlineKeyboardButton("◀️ Back", callback_data="menu_main")],
    ])


# ── Inline: Smart Mode ───────────────────────────────────────────────────────

def smart_mode_panel_keyboard(
    auto_trade: bool,
    current_strategy: str | None,
    hermes_active: bool,
) -> InlineKeyboardMarkup:
    auto_label = "🟢 Auto Trading ON" if auto_trade else "⚪ Auto Trading OFF"
    hermes_label = "🟡 Hermes: Passive" if hermes_active else "⚪ Hermes: Off"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(auto_label, callback_data="smart:toggle_auto")],
        [InlineKeyboardButton(hermes_label, callback_data="smart:toggle_hermes")],
        [InlineKeyboardButton("🎯 Best Strategy", callback_data="smart:best_strategy")],
        [InlineKeyboardButton("🔄 Force Market Scan", callback_data="smart:scan")],
        [InlineKeyboardButton("🧪 Simulate Signal", callback_data="smart:simulate")],
        [InlineKeyboardButton("📊 Performance", callback_data="smart:performance")],
        [InlineKeyboardButton("◀️ Back", callback_data="menu_main")],
    ])


# ── Inline: Quick Actions (instant, no confirm) ──────────────────────────────

def confirm_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Ya, Cancel All", callback_data="qa:cancel_all_confirm")],
        [InlineKeyboardButton("❌ Tidak", callback_data="qa:cancel_all_abort")],
    ])


def confirm_close_all_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Ya, Close All", callback_data="qa:close_all_confirm")],
        [InlineKeyboardButton("❌ Tidak", callback_data="qa:close_all_abort")],
    ])