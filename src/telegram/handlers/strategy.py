"""Strategy handlers — switch strategy, adjust parameters via inline keyboard"""
import json
from telegram import Update
from telegram.ext import CallbackContext, ContextTypes

from ..keyboards import (
    main_menu_keyboard,
    strategy_selection_keyboard,
    strategy_param_keyboard,
    risk_percent_keyboard,
    leverage_keyboard,
    trailing_keyboard,
)
from ...strategy import StrategyLoader
from ...strategy.validator import validate_strategy, apply_hard_limits
from ...utils.helpers import atomic_write_json
from ...utils.logger import log


# ── Strategy Selection ──────────────────────────────────────────────────────

async def cmd_strategi(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      loader: StrategyLoader):
    strategies = loader.list_all()
    active = loader.active_id
    text = "*⚙️ PILIH STRATEGI*\n\nPilih strategi yang ingin digunakan:"
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=strategy_selection_keyboard(strategies, active),
    )


async def view_config(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     loader: StrategyLoader):
    active = loader.active()
    if not active:
        await update.callback_query.answer("No active strategy", show_alert=True)
        return
    cfg = json.dumps(active, indent=2)
    text = f"*📋 CONFIG — {active['name']}*\n\n`{cfg[:4000]}`"
    await update.callback_query.message.reply_text(text, parse_mode="Markdown")


async def select_strategy(update: Update, context: CallbackContext,
                         loader: StrategyLoader):
    query = update.callback_query
    strategy_id = query.data.replace("strat_select:", "")
    await query.answer()
    if loader.set_active(strategy_id):
        await query.edit_message_text(
            f"✅ Strategi aktif: `{strategy_id}`",
            parse_mode="Markdown",
        )
    else:
        await query.answer("Gagal mengaktifkan strategi", show_alert=True)


# ── Parameter Adjustment ─────────────────────────────────────────────────────

async def show_params(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "*UBAH PARAMETER*\n\nPilih parameter yang ingin diubah:",
        parse_mode="Markdown",
        reply_markup=strategy_param_keyboard(),
    )


async def param_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "*📊 Risk Per Trade*\n\nPilih nilai:",
        parse_mode="Markdown",
        reply_markup=risk_percent_keyboard(),
    )


async def param_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "*🔢 Leverage*\n\nPilih:",
        parse_mode="Markdown",
        reply_markup=leverage_keyboard(),
    )


async def param_trailing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "*Trailing Stop*\n\nPilih mode:",
        parse_mode="Markdown",
        reply_markup=trailing_keyboard(),
    )


async def set_param(update: Update, context: CallbackContext,
                   loader: StrategyLoader, strategies_dir):
    query = update.callback_query
    parts = query.data.replace("set:", "").split(":")
    if len(parts) != 3:
        return
    param_type, _, value = parts
    await query.answer()

    active = loader.active()
    if not active:
        await query.answer("No active strategy", show_alert=True)
        return

    # Apply change
    changed = False
    if param_type == "risk":
        active["position"]["size_value"] = float(value.replace("%", ""))
        changed = True
    elif param_type == "leverage":
        active["position"]["leverage"] = int(value.replace("x", ""))
        changed = True
    elif param_type == "trailing":
        mode_map = {"off": False, "breakeven": "breakeven", "secure": "secure", "trail": True}
        active["risk"]["trailing"] = mode_map.get(value, True)
        changed = True

    if changed:
        active = apply_hard_limits(active)
        valid, err = validate_strategy(active)
        if not valid:
            await query.answer(f"Invalid: {err}", show_alert=True)
            return
        # Save back to file
        file = strategies_dir / f"{active['id']}.json"
        atomic_write_json(file, active)
        loader.reload(active["id"])
        await query.answer(f"Updated: {param_type} = {value}")


def setup_strategy_handlers(app, loader: StrategyLoader, strategies_dir: str):
    app.add_handler(CallbackQueryHandler(
        lambda u, c: select_strategy(u, c, loader),
        pattern="^strat_select:",
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: view_config(u, c, loader),
        pattern="^strat_view_config$",
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: show_params(u, c),
        pattern="^strat_params$",
    ))
    app.add_handler(CallbackQueryHandler(param_risk, pattern="^param:risk$"))
    app.add_handler(CallbackQueryHandler(param_leverage, pattern="^param:leverage$"))
    app.add_handler(CallbackQueryHandler(param_trailing, pattern="^param:trailing$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: set_param(u, c, loader, strategies_dir),
        pattern="^set:",
    ))
    app.add_handler(CommandHandler("strategi", lambda u, c: cmd_strategi(u, c, loader)))