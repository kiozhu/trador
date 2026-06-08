"""Menu handlers — /start, status, balance, help"""
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes

from ..keyboards import main_menu_keyboard
from ...memory import StateManager, PerformanceTracker
from ...utils.logger import log


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 *TRADOR — Active*\n\nKlik tombol di bawah untuk kontrol.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE,
                    state_mgr: StateManager, perf: PerformanceTracker):
    state = state_mgr.get()
    perf_data = perf.get()
    pos_count = state.get("open_positions", 0)
    strategy = state.get("strategy_active", "none")
    trading = "🟢 Active" if state.get("trading_enabled") else "🔴 Stopped"

    cooling = state.get("cooling_until")
    cooling_msg = ""
    if cooling:
        from datetime import datetime, timezone
        remaining = (cooling - int(datetime.now(timezone.utc).timestamp() * 1000)) // 1000
        if remaining > 0:
            cooling_msg = f"\n⏳ Cooling: {remaining}s"

    text = (
        f"🔥 *TRADOR STATUS*\n\n"
        f"Trading: {trading}\n"
        f"Strategy: `{strategy}`\n"
        f"Open Positions: {pos_count}\n"
        f"{cooling_msg}\n\n"
        f"*24h Performance*\n"
        f"Trades: {perf_data.get('24h', {}).get('trades', 0)}\n"
        f"Win Rate: {perf_data.get('24h', {}).get('win_rate', 0)}%\n"
        f"PnL: ${perf_data.get('24h', {}).get('pnl_usd', 0):.2f}"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE, exchange):
    try:
        balance = await exchange.get_balance()
        text = (
            f"💰 *Balance*\n\n"
            f"Total: ${balance.get('total', 0):.2f}\n"
            f"Available: ${balance.get('available', 0):.2f}\n"
            f"Unrealized PnL: ${balance.get('unrealized_pnl', 0):.2f}"
        )
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Error: {e}", reply_markup=main_menu_keyboard())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*TRADOR — Help*\n\n"
        "*📊 Status* — Lihat status bot dan performa\n"
        "*📈 Positions* — Lihat posisi terbuka\n"
        "*⚙️ Strategi* — Ubah strategi atau parameter\n"
        "*📋 History* — Riwayat trade terakhir\n"
        "*🚀 Start* — Aktifkan trading\n"
        "*🛑 Stop* — Matikan trading\n"
        "*💰 Balance* — Lihat balance\n"
        "*❓ Help* — Help menu ini"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())


async def handle_text_menu(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           state_mgr: StateManager, perf: PerformanceTracker, exchange):
    text = update.message.text
    if text == "📊 Status":
        await cmd_status(update, context, state_mgr, perf)
    elif text == "💰 Balance":
        await cmd_balance(update, context, exchange)
    elif text == "❓ Help":
        await cmd_help(update, context)


def setup_menu_handlers(app, state_mgr: StateManager, perf: PerformanceTracker, exchange):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        lambda u, c: handle_text_menu(u, c, state_mgr, perf, exchange)
    ))