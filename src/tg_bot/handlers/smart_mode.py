"""Smart Mode — Hermes-driven auto trading + manual quick scan"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, CallbackContext, ContextTypes

from ..keyboards import smart_mode_panel_keyboard, main_menu_keyboard
from ...memory import PerformanceTracker, StateManager
from ...strategy import StrategyLoader
from ...utils.logger import log


# ── Entry: Smart Mode panel ──────────────────────────────────────────────────

async def cmd_smart_mode(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        state_mgr: StateManager, loader: StrategyLoader, perf: PerformanceTracker):
    state = state_mgr.get()
    auto_trade = state.get("auto_trade_enabled", False)
    current = loader.active_id or "none"

    text = (
        f"*SMART MODE*\n\n"
        f"Auto Trading: {'ON' if auto_trade else 'OFF'}\n"
        f"Strategy: `{current}`\n\n"
        f"Pilih aksi atau toggle mode di bawah:"
    )
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=smart_mode_panel_keyboard(auto_trade, current),
    )


# ── Toggle Auto Trading ───────────────────────────────────────────────────────

async def toggle_auto_trading(update: Update, context: CallbackContext,
                             state_mgr: StateManager, loader: StrategyLoader, perf: PerformanceTracker):
    query = update.callback_query
    await query.answer()
    state = state_mgr.get()
    current = not state.get("auto_trade_enabled", False)
    state_mgr.set("auto_trade_enabled", current)
    current_strat = loader.active_id or "none"

    label = "Auto Trading ON" if current else "Auto Trading OFF"
    text = (
        f"*SMART MODE*\n\n"
        f"Auto Trading: {label}\n"
        f"Strategy: `{current_strat}`"
    )
    await query.message.edit_text(
        text, parse_mode="Markdown",
        reply_markup=smart_mode_panel_keyboard(current, current_strat),
    )


# ── Best Strategy (smart pick) ────────────────────────────────────────────────

async def best_strategy(update: Update, context: CallbackContext,
                      loader: StrategyLoader, perf: PerformanceTracker):
    query = update.callback_query
    await query.answer("Analysing...", show_alert=False)
    metrics = perf.get()
    strategies = loader.list_all()

    scored = []
    for s in strategies:
        sid = s["id"]
        strat_metrics = metrics.get("strategies", {}).get(sid, {})
        wins = strat_metrics.get("wins", 0)
        total = strat_metrics.get("total", 0)
        pnl = strat_metrics.get("pnl_pct", 0)
        wr = (wins / total * 100) if total > 0 else 0
        # Score: weighted combo of win rate and PnL
        score = wr * 0.5 + pnl * 5
        scored.append((sid, s["name"], round(wr, 1), round(pnl, 2), total, round(score, 2)))

    if not scored:
        await query.message.edit_text(
            "📭 Belum ada data performa. Need minimal 1 trade dulu.",
            parse_mode="Markdown",
        )
        return

    scored.sort(key=lambda x: x[5], reverse=True)
    best = scored[0]

    lines = ["*🎯 BEST STRATEGY RECOMMENDATION*\n"]
    for rank, (sid, name, wr, pnl, total, score) in enumerate(scored[:5], 1):
        marker = "👉 " if rank == 1 else f"#{rank} "
        lines.append(f"{marker}`{name}` — WR {wr}% | PnL {pnl:+.2f}% | {total} trades | score {score}")

    lines.append(f"\n👑 *TOP PICK:* `{best[1]}`")
    lines.append(f"Win Rate: {best[2]}% | Net PnL: {best[3]:+.2f}% | Trades: {best[4]}")

    # Auto-activate best button
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Activate {best[1]}", callback_data=f"strat_select:{best[0]}")],
        [InlineKeyboardButton("◀️ Back to Smart Mode", callback_data="smart:back")],
    ])
    await query.message.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ── Force Market Scan ─────────────────────────────────────────────────────────

async def force_market_scan(update: Update, context: CallbackContext,
                           state_mgr: StateManager, perf: PerformanceTracker):
    query = update.callback_query
    await query.answer("🔍 Scanning market signals...", show_alert=False)
    # In real impl, this triggers exchange.scan_signals()
    # For now just acknowledge
    metrics = perf.get()
    last_scan = state_mgr.get().get("last_scan_ts", "never")
    await query.message.edit_text(
        f"*🔍 Market Scan*\n\n"
        f"Last scan: {last_scan}\n"
        f"Scan triggered — results in next status.\n\n"
        f"_Full market scan would evaluate all symbols here._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Back", callback_data="smart:back")],
        ]),
    )


# ── Simulate Signal ───────────────────────────────────────────────────────────

async def simulate_signal(update: Update, context: CallbackContext,
                        loader: StrategyLoader, perf: PerformanceTracker):
    query = update.callback_query
    await query.answer("Simulating...", show_alert=False)
    strategy = loader.active()
    if not strategy:
        await query.message.edit_text(
            "⚠️ No active strategy. Pilih strategi dulu.",
            parse_mode="Markdown",
        )
        return

    # In real impl: call exchange.get_signal(strategy)
    # Simulate: generate mock signal
    import random
    sides = ["LONG", "SHORT"]
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    side = random.choice(sides)
    sym = random.choice(symbols)
    confidence = round(random.uniform(0.55, 0.92), 2)

    text = (
        f"*🧪 SIMULATED SIGNAL*\n\n"
        f"Strategy: `{strategy['name']}`\n"
        f"Symbol: {sym}\n"
        f"Direction: {'🟢 ' + side if side == 'LONG' else '🔴 ' + side}\n"
        f"Confidence: {confidence:.0%}\n"
        f"_This is a simulation — not a real signal._"
    )
    await query.message.edit_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Accept Signal", callback_data=f"smart:accept_signal:{sym}:{side}")],
            [InlineKeyboardButton("❌ Reject", callback_data="smart:back")],
        ]),
    )


# ── Accept Simulated Signal ───────────────────────────────────────────────────

async def accept_signal(update: Update, context: CallbackContext,
                      state_mgr: StateManager):
    query = update.callback_query
    raw = query.data.replace("smart:accept_signal:", "")
    parts = raw.split(":")
    if len(parts) >= 2:
        sym, side = parts[0], parts[1]
        await query.answer(f"✅ Signal queued: {side} {sym}", show_alert=True)
        state_mgr.set("pending_signal", {"symbol": sym, "side": side})
    await query.message.edit_text(
        "*✅ Signal Accepted*\n\nSignal queued for next execution cycle.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Back", callback_data="smart:back")],
        ]),
    )


# ── Smart Performance ─────────────────────────────────────────────────────────

async def smart_performance(update: Update, context: CallbackContext,
                          perf: PerformanceTracker):
    query = update.callback_query
    await query.answer()
    metrics = perf.get()
    d = metrics.get("24h", {})

    text = (
        f"*📊 SMART PERFORMANCE (24h)*\n\n"
        f"Total Trades: {d.get('trades', 0)}\n"
        f"Win Rate: {d.get('win_rate', 0):.1f}%\n"
        f"Net PnL: ${d.get('pnl_usd', 0):+.2f}\n"
        f"Profit Factor: {d.get('profit_factor', 0):.2f}\n"
        f"Max Drawdown: {d.get('max_drawdown', 0):+.2f}%\n"
        f"Sharpe Ratio: {d.get('sharpe_ratio', 0):.2f}\n\n"
        f"*7d*\n"
        f"Trades: {metrics.get('7d', {}).get('trades', 0)} | "
        f"WR: {metrics.get('7d', {}).get('win_rate', 0):.1f}%\n\n"
        f"*30d*\n"
        f"Trades: {metrics.get('30d', {}).get('trades', 0)} | "
        f"WR: {metrics.get('30d', {}).get('win_rate', 0):.1f}%"
    )
    await query.message.edit_text(text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Back", callback_data="smart:back")],
        ]),
    )


# ── Back ──────────────────────────────────────────────────────────────────────

async def smart_back(update: Update, context: CallbackContext,
                   state_mgr: StateManager, loader: StrategyLoader, perf: PerformanceTracker):
    query = update.callback_query
    await query.answer()
    state = state_mgr.get()
    auto_trade = state.get("auto_trade_enabled", False)
    current = loader.active_id or "none"
    text = (
        f"*SMART MODE*\n\n"
        f"Auto Trading: {'ON' if auto_trade else 'OFF'}\n"
        f"Strategy: `{current}`"
    )
    await query.message.edit_text(
        text, parse_mode="Markdown",
        reply_markup=smart_mode_panel_keyboard(auto_trade, current),
    )


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_smart_handlers(app, state_mgr: StateManager, loader: StrategyLoader, perf: PerformanceTracker):
    app.add_handler(CallbackQueryHandler(
        lambda u, c: cmd_smart_mode(u, c, state_mgr, loader, perf),
        pattern="^smart:panel$",
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: toggle_auto_trading(u, c, state_mgr, loader, perf),
        pattern="^smart:toggle_auto$",
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: best_strategy(u, c, loader, perf),
        pattern="^smart:best_strategy$",
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: force_market_scan(u, c, state_mgr, perf),
        pattern="^smart:scan$",
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: simulate_signal(u, c, loader, perf),
        pattern="^smart:simulate$",
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: accept_signal(u, c, state_mgr),
        pattern="^smart:accept_signal:",
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: smart_performance(u, c, perf),
        pattern="^smart:performance$",
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: smart_back(u, c, state_mgr, loader, perf),
        pattern="^smart:back$",
    ))