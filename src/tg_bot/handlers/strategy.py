"""Strategy handlers — full CRUD + inline param adjustment + Hermes smart select"""
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, CallbackContext, ContextTypes

from ..keyboards import (
    main_menu_keyboard,
    strategy_selection_keyboard,
    strategy_detail_keyboard,
    strategy_param_keyboard,
    risk_percent_keyboard,
    leverage_keyboard,
    maxhold_keyboard,
    position_size_keyboard,
    trailing_keyboard,
    tpsl_keyboard,
    grid_keyboard,
    signal_source_keyboard,
)
from ...strategy import StrategyLoader
from ...strategy.validator import validate_strategy, apply_hard_limits
from ...memory import PerformanceTracker
from ...utils.helpers import atomic_write_json
from ...utils.logger import log


# ── Entry Points ─────────────────────────────────────────────────────────────

async def cmd_strategi(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      loader: StrategyLoader):
    strategies = loader.list_all()
    active = loader.active_id
    text = f"*⚙️ STRATEGI ({len(strategies)} loaded)*\n\nPilih strategi untuk melihat detail atau ubah:"
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=strategy_selection_keyboard(strategies, active),
    )


async def view_config(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     loader: StrategyLoader):
    query = update.callback_query
    await query.answer()
    active = loader.active()
    if not active:
        await query.answer("No active strategy", show_alert=True)
        return
    cfg = json.dumps(active, indent=2)
    if len(cfg) > 4000:
        await query.message.reply_text(
            f"*📋 CONFIG — {active['name']}*\n\n`{cfg[:4000]}`",
            parse_mode="Markdown",
        )
        await query.message.reply_text(f"`{cfg[4000:]}`", parse_mode="Markdown")
    else:
        await query.message.reply_text(
            f"*📋 CONFIG — {active['name']}*\n\n`{cfg}`",
            parse_mode="Markdown",
        )


async def view_full_config(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          loader: StrategyLoader):
    query = update.callback_query
    strategy_id = query.data.replace("strat_full:", "")
    await query.answer()
    strategy = loader.get(strategy_id)
    if not strategy:
        await query.answer("Strategy not found", show_alert=True)
        return
    cfg = json.dumps(strategy, indent=2)
    await query.message.reply_text(f"*📄 {strategy['name']}*\n\n`{cfg}`", parse_mode="Markdown")


# ── Strategy Selection + Detail ──────────────────────────────────────────────

async def select_strategy(update: Update, context: CallbackContext,
                         loader: StrategyLoader):
    query = update.callback_query
    strategy_id = query.data.replace("strat_select:", "")
    await query.answer()
    strategy = loader.get(strategy_id)
    if not strategy:
        await query.answer("Strategy not found", show_alert=True)
        return
    is_active = strategy["id"] == loader.active_id
    text = (
        f"*📈 {strategy['name']}*\n\n"
        f"ID: `{strategy['id']}`\n"
        f"Status: {'🟢 Active' if is_active else '⚪ Inactive'}\n\n"
        f"*Risk:* SL {strategy['risk']['sl_percent']}% | TP {strategy['risk']['tp_percent']}%\n"
        f"*Position:* {strategy['position']['size_value']}% | {strategy['position']['leverage']}x\n"
        f"*Indicators:* {strategy['indicators']}"
    )
    await query.message.edit_text(
        text, parse_mode="Markdown",
        reply_markup=strategy_detail_keyboard(strategy_id, is_active),
    )


async def smart_select(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      loader: StrategyLoader, perf: PerformanceTracker):
    """Hermes-style smart strategy selection — picks best by win rate + PnL."""
    query = update.callback_query
    await query.answer("🧠 Analysing performance...", show_alert=False)
    metrics = perf.get()
    strategies = loader.list_all()
    active_id = loader.active_id

    scored = []
    for s in strategies:
        sid = s["id"]
        strat_m = metrics.get("strategies", {}).get(sid, {})
        wins = strat_m.get("wins", 0)
        total = strat_m.get("total", 0)
        pnl = strat_m.get("pnl_pct", 0)
        wr = (wins / total * 100) if total > 0 else 0
        score = wr * 0.4 + pnl * 10
        scored.append((sid, s["name"], round(wr, 1), round(pnl, 2), total, score))

    if not scored:
        await query.message.edit_text(
            "📭 Belum ada data performa. Pilih strategi manual dulu.",
            parse_mode="Markdown",
            reply_markup=strategy_selection_keyboard(strategies, active_id),
        )
        return

    scored.sort(key=lambda x: x[5], reverse=True)
    best = scored[0]

    lines = ["*🧠 SMART STRATEGY PICK*\n", "Rank by win rate + PnL:"]
    for rank, (sid, name, wr, pnl, total, score) in enumerate(scored, 1):
        label = "👉 BEST" if rank == 1 else f"#{rank}"
        lines.append(f"{label} `{name}` — WR {wr}% | PnL {pnl}% | {total} trades")

    lines.append(f"\n👉 *Recommendation:* `{best[1]}`")
    lines.append(f"Win rate {best[2]}% | PnL {best[3]}% | {best[4]} trades")

    await query.message.edit_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Activate {best[1]}", callback_data=f"strat_select:{best[0]}")],
            [InlineKeyboardButton("📊 View All", callback_data="strat_view_all")],
            [InlineKeyboardButton("◀️ Kembali", callback_data="strat_back")],
        ]),
    )


# ── Toggle / Activate ────────────────────────────────────────────────────────

async def toggle_strategy(update: Update, context: CallbackContext,
                         loader: StrategyLoader):
    query = update.callback_query
    strategy_id = query.data.replace("strat_toggle:", "")
    await query.answer()
    if loader.set_active(strategy_id):
        await query.answer(f"Activated: {strategy_id}")
        await query.message.edit_reply_markup(
            reply_markup=strategy_detail_keyboard(strategy_id, True),
        )
    else:
        await query.answer("Failed to activate", show_alert=True)


# ── Back Navigation ───────────────────────────────────────────────────────────

async def strat_back(update: Update, context: ContextTypes.DEFAULT_TYPE,
                    loader: StrategyLoader):
    query = update.callback_query
    await query.answer()
    strategies = loader.list_all()
    active = loader.active_id
    await query.message.edit_text(
        "*⚙️ STRATEGI*\n\nPilih strategi:",
        parse_mode="Markdown",
        reply_markup=strategy_selection_keyboard(strategies, active),
    )


# ── Strategy Delete ──────────────────────────────────────────────────────────

async def delete_strategy(update: Update, context: CallbackContext,
                         loader: StrategyLoader, strategies_dir):
    query = update.callback_query
    strategy_id = query.data.replace("strat_delete:", "")
    await query.answer()
    strategy = loader.get(strategy_id)
    if not strategy:
        await query.answer("Not found", show_alert=True)
        return
    if strategy_id == loader.active_id:
        await query.answer("Cannot delete active strategy", show_alert=True)
        return
    file = strategies_dir / f"{strategy_id}.json"
    if file.exists():
        os.remove(file)
    loader.reload_all()
    await query.answer(f"Deleted: {strategy_id}")
    strategies = loader.list_all()
    active = loader.active_id
    await query.message.edit_text(
        f"✅ Deleted `{strategy_id}`. Pilih strategi lain:",
        parse_mode="Markdown",
        reply_markup=strategy_selection_keyboard(strategies, active),
    )


# ── Strategy Performance ─────────────────────────────────────────────────────

async def view_strategy_perf(update: Update, context: CallbackContext,
                            loader: StrategyLoader, perf: PerformanceTracker):
    query = update.callback_query
    strategy_id = query.data.replace("strat_perf:", "")
    await query.answer()
    metrics = perf.get()
    strat_data = metrics.get("strategies", {}).get(strategy_id, {})
    wins = strat_data.get("wins", 0)
    total = strat_data.get("total", 0)
    pnl = strat_data.get("pnl_pct", 0)
    avg_win = strat_data.get("avg_win_pct", 0)
    avg_loss = strat_data.get("avg_loss_pct", 0)
    wr = round(wins / total * 100, 1) if total > 0 else 0
    strategy = loader.get(strategy_id)
    name = strategy["name"] if strategy else strategy_id
    text = (
        f"*📊 Performa — {name}*\n\n"
        f"Total Trades: {total}\n"
        f"Win Rate: {wr}%\n"
        f"Net PnL: {pnl:+.2f}%\n"
        f"Avg Win: {avg_win:+.2f}% | Avg Loss: {avg_loss:+.2f}%"
    )
    await query.message.reply_text(text, parse_mode="Markdown")


# ── Parameter Adjustment ─────────────────────────────────────────────────────

async def show_params(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     loader: StrategyLoader):
    await update.callback_query.answer()
    strategy = loader.active()
    name = strategy["name"] if strategy else "None"
    await update.callback_query.message.reply_text(
        f"*✏️ UBAH PARAMETER — {name}*\n\nPilih parameter:",
        parse_mode="Markdown",
        reply_markup=strategy_param_keyboard(),
    )


async def param_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    param = query.data.replace("param:", "")
    await query.answer()
    keyboard_map = {
        "risk": risk_percent_keyboard,
        "leverage": leverage_keyboard,
        "maxhold": maxhold_keyboard,
        "size": position_size_keyboard,
        "trailing": trailing_keyboard,
        "tpsl": tpsl_keyboard,
        "grid": grid_keyboard,
        "signal": signal_source_keyboard,
    }
    labels = {
        "risk": "📊 Risk %", "leverage": "🔢 Leverage", "maxhold": "⏱️ Max Hold",
        "size": "📦 Position Size", "trailing": "🔗 Trailing Stop",
        "tpsl": "📏 TP/SL", "grid": "📐 Grid Size", "signal": "📍 Signal Source",
    }
    fn = keyboard_map.get(param)
    if fn:
        await query.message.reply_text(
            f"*{labels.get(param, param)}*\n\nPilih nilai:",
            parse_mode="Markdown",
            reply_markup=fn(),
        )


async def set_param(update: Update, context: CallbackContext,
                   loader: StrategyLoader, strategies_dir):
    query = update.callback_query
    raw = query.data.replace("set:", "")
    parts = raw.split(":")
    if len(parts) < 2:
        return
    param_type, value = parts[0], parts[1]
    await query.answer()

    active = loader.active()
    if not active:
        await query.answer("No active strategy", show_alert=True)
        return

    changed = False
    if param_type == "risk":
        active["position"]["size_value"] = float(value.replace("%", ""))
        changed = True
    elif param_type == "leverage":
        active["position"]["leverage"] = int(value.replace("x", ""))
        changed = True
    elif param_type == "maxhold":
        active["risk"]["max_hold_minutes"] = int(value.replace("m", ""))
        changed = True
    elif param_type == "size":
        active["position"]["size_value"] = float(value.replace("%", ""))
        changed = True
    elif param_type == "trailing":
        mode_map = {"off": False, "breakeven": "breakeven", "secure": "secure", "trail": True}
        active["risk"]["trailing"] = mode_map.get(value, True)
        changed = True
    elif param_type == "sl":
        active["risk"]["sl_percent"] = -float(value)
        changed = True
    elif param_type == "tp":
        active["risk"]["tp_percent"] = float(value)
        changed = True
    elif param_type == "grid":
        active["indicators"]["grid_levels"] = int(value)
        changed = True
    elif param_type == "signal":
        active["indicators"]["signal_type"] = value
        changed = True

    if changed:
        active = apply_hard_limits(active)
        valid, err = validate_strategy(active)
        if not valid:
            await query.answer(f"Invalid: {err}", show_alert=True)
            return
        file = strategies_dir / f"{active['id']}.json"
        atomic_write_json(file, active)
        loader.reload(active["id"])
        await query.answer(f"✅ {param_type} → {value}")
        await query.message.reply_text(
            f"Updated! *{param_type} = {value}*\n\nPilih parameter lain:",
            parse_mode="Markdown",
            reply_markup=strategy_param_keyboard(),
        )


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_strategy_handlers(app, loader: StrategyLoader, strategies_dir, perf: PerformanceTracker):
    app.add_handler(CallbackQueryHandler(
        lambda u, c: select_strategy(u, c, loader), pattern="^strat_select:"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: smart_select(u, c, loader, perf), pattern="^strat_smart$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: view_config(u, c, loader), pattern="^strat_view_config$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: view_full_config(u, c, loader), pattern="^strat_full:"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: toggle_strategy(u, c, loader), pattern="^strat_toggle:"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: delete_strategy(u, c, loader, strategies_dir), pattern="^strat_delete:"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: view_strategy_perf(u, c, loader, perf), pattern="^strat_perf:"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: strat_back(u, c, loader), pattern="^strat_back$"))
    app.add_handler(CallbackQueryHandler(show_params, pattern="^strat_params$"))
    app.add_handler(CallbackQueryHandler(param_handler, pattern="^param:"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: set_param(u, c, loader, strategies_dir), pattern="^set:"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: cmd_strategi(u, c, loader), pattern="^menu_strategi$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: strat_back(u, c, loader), pattern="^menu_main$"))