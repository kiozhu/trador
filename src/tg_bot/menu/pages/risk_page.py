"""Risk page — 6 active layers with inline manual controls."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from ..core import MenuPage, make_back_button

# Import COIN_LIST from settings for coins display
from .settings_page import COIN_LIST as _SETTINGS_COIN_LIST


class RiskPage(MenuPage):
    name = "risk"
    back_callback = "main"

    def __init__(self, state_mgr, auto_trader=None):
        self.state_mgr = state_mgr
        self._auto_trader = auto_trader

    def set_auto_trader(self, auto_trader):
        self._auto_trader = auto_trader

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        if not self._auto_trader or not self._auto_trader.risk_guard:
            return "Risk not ready", InlineKeyboardMarkup(make_back_button("main"))
        rg = self._auto_trader.risk_guard
        state = self.state_mgr.get()
        mode = state.get("mode", "dry_run")
        balance_key = "dry_run_balance" if mode == "dry_run" else "live_balance"
        return _build_page(rg, state, balance_key)


def _build_page(risk_guard, state, balance_key) -> tuple[str, InlineKeyboardMarkup]:
    cfg = risk_guard.config
    status = risk_guard.status()

    # ── Header ────────────────────────────────────────────────────
    mode_icon  = "🟢" if status["mode"] == "resume" else "🔴"
    mode_text = "AKTIF" if status["mode"] == "resume" else "MATI"
    regime    = state.get("market_regime", "unknown")
    regime_icon = {"up": "⬆️", "down": "⬇️", "sideway": "↔️", "unknown": "❓"}.get(regime, "❓")

    # ── Balance& PnL ─────────────────────────────────────────────
    balance = state.get(balance_key, 0.0)
    daily_pnl     = state.get("daily_pnl", 0.0)
    daily_pnl_pct = state.get("daily_pnl_pct", 0.0)

    # ── VaR from risk_guard (synced in auto_trader._sync_risk_state) ──
    var_1d  = state.get("var_1d", 0.0)
    cvar_1d = state.get("cvar_1d", 0.0)
    var_7d  = state.get("var_7d", 0.0)
    cvar_7d = state.get("cvar_7d", 0.0)

    # ── Config values (current runtime values from risk_guard) ─────
    # Position Size
    l04_val = f"{cfg.max_position_size_pct:.0f}%"

    # Symbol Concentration
    l05_val = f"Max {cfg.max_positions_per_symbol}/pair"

    # Balance Floor
    l10_val = f"Min ${cfg.min_balance_usd:.0f} | Emergency ${cfg.emergency_balance_usd:.0f}"

    # Regime Alignment (sideways)
    l11_val = "<< Sideway" if risk_guard._sideways_mode else "Up/Down All regimes"
    l11_icon = "🟢" if risk_guard._sideways_mode else "🔴"

    # ── Moved params from settings ────────────────────────────────
    cycle_interval    = state.get("cycle_interval", 15)
    daily_loss_limit  = state.get("daily_loss_limit", 50)
    max_orders        = state.get("max_orders_per_cycle", 2)
    max_pos           = state.get("max_concurrent_positions", 5)
    enabled_symbols  = set(state.get("enabled_symbols", "").split(",") if state.get("enabled_symbols") else _SETTINGS_COIN_LIST)
    enabled_count    = len(enabled_symbols) if enabled_symbols else 0

    text = (
        "🛡️ RISK ENGINE\n"
        f"Status : {mode_icon} {mode_text}\n"
        f"Regime : {regime_icon} {regime.capitalize()}\n"
        f"Balance: ${balance:.2f}\n\n"
        "── 💰 PnL Harian ──\n"
        f"  📈 ${daily_pnl:+.2f} ({daily_pnl_pct:+.2f}%)\n\n"
        "── 📊 Value at Risk ──\n"
        f"  VaR  1d: ${var_1d:.2f}   CVaR 1d: ${cvar_1d:.2f}\n"
        f"  VaR  7d: ${var_7d:.2f}   CVaR 7d: ${cvar_7d:.2f}\n\n"
        "── ⚙️ KONFIGURASI ──\n\n"
        f"⏱️ Cycle Interval     | {cycle_interval}s\n"
        f"📉 Daily Loss Limit  | ${daily_loss_limit:.0f}\n"
        f"📋 Max Orders/Cycle | {max_orders}\n"
        f"🔢 Max Positions     | {max_pos}\n"
        f"🪙 Coins Enabled     | {enabled_count}/{len(_SETTINGS_COIN_LIST)}\n\n"
        f"✅ Position Size     | {l04_val}\n"
        f"✅ Symbol Limit      | {l05_val}\n"
        f"✅ Balance Floor      | {l10_val}\n"
        f"{l11_icon} Regime Block      | {l11_val}\n"
    )

    # ── Buttons ────────────────────────────────────────────────────
    rows = []

    # ── Moved params from settings ──────────────────────────────────
    # Cycle Interval
    rows.append([
        InlineKeyboardButton("➖", callback_data="adj:ci_-5"),
        InlineKeyboardButton(f"⏱️ Cycle: {cycle_interval}s", callback_data="noop"),
        InlineKeyboardButton("➕", callback_data="adj:ci_+5"),
    ])

    # Daily Loss Limit
    rows.append([
        InlineKeyboardButton("➖", callback_data="adj:dll_-10"),
        InlineKeyboardButton(f"📉 Daily Loss: ${daily_loss_limit:.0f}", callback_data="noop"),
        InlineKeyboardButton("➕", callback_data="adj:dll_+10"),
    ])

    # Max Orders/Cycle
    rows.append([
        InlineKeyboardButton("➖", callback_data="adj:mo_-1"),
        InlineKeyboardButton(f"📋 Max Orders: {max_orders}", callback_data="noop"),
        InlineKeyboardButton("➕", callback_data="adj:mo_+1"),
    ])

    # Max Positions
    rows.append([
        InlineKeyboardButton("➖", callback_data="adj:mp_-1"),
        InlineKeyboardButton(f"🔢 Max Pos: {max_pos}", callback_data="noop"),
        InlineKeyboardButton("➕", callback_data="adj:mp_+1"),
    ])

    # Position Size
    rows.append([
        InlineKeyboardButton("➖", callback_data="adj:mpsp_-5"),
        InlineKeyboardButton(f"Position Size: {l04_val}", callback_data="noop"),
        InlineKeyboardButton("➕", callback_data="adj:mpsp_+5"),
    ])

    # Symbol Concentration
    rows.append([
        InlineKeyboardButton("➖", callback_data="adj:mpps_+1"),
        InlineKeyboardButton(f"Max Pair: {cfg.max_positions_per_symbol}x", callback_data="noop"),
        InlineKeyboardButton("➕", callback_data="adj:mpps_-1"),
    ])

    # Balance Floor
    rows.append([
        InlineKeyboardButton("➖", callback_data="adj:mbus_-20"),
        InlineKeyboardButton(f"Min Balance: ${cfg.min_balance_usd:.0f}", callback_data="noop"),
        InlineKeyboardButton("➕", callback_data="adj:mbus_+20"),
    ])

    # Regime toggle
    if risk_guard._sideways_mode:
        rows.append([
            InlineKeyboardButton("🔴 Sideways: BLOKIR", callback_data="set:sideways_off"),
        ])
    else:
        rows.append([
            InlineKeyboardButton("🟢 Sideways: DIIZINKAN", callback_data="set:sideways_on"),
        ])

    # Stress test
    rows.append([
        InlineKeyboardButton("💥 Stress Test", callback_data="page:stress"),
    ])

    # Coins
    rows.append([
        InlineKeyboardButton(f"🪙 Coins ({enabled_count})", callback_data="symbol_page"),
    ])

    # Back
    rows.append([
        InlineKeyboardButton("◀️ Back", callback_data="page:main"),
    ])

    keyboard = InlineKeyboardMarkup(rows)
    return text, keyboard
