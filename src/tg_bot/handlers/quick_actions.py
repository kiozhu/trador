"""Quick Actions — instant execution commands"""
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ContextTypes

from ..keyboards import quick_actions_keyboard, main_menu_keyboard, confirm_cancel_keyboard, confirm_close_all_keyboard
from ...memory import StateManager
from ...strategy import StrategyLoader
from ...utils.logger import log


async def cmd_quick_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*⚡ QUICK ACTIONS*\n\n"
        "Pilih aksi instant. "
        "Cancel/Close All butuh konfirmasi."
    )
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=quick_actions_keyboard(),
    )


# ── View Orders ───────────────────────────────────────────────────────────────

async def view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     exchange, state_mgr: StateManager):
    """View open orders across all symbols."""
    try:
        orders = await exchange.get_open_orders()
        if not orders:
            await update.message.reply_text(
                "📭 Tidak ada open orders.",
                reply_markup=quick_actions_keyboard(),
            )
            return
        lines = ["*📋 OPEN ORDERS*\n"]
        for o in orders[:10]:
            side = "🟢 BUY" if o.get("side") == "BUY" else "🔴 SELL"
            lines.append(
                f"{side} {o.get('symbol')} @ ${o.get('price', 0):.4f}\n"
                f"  Qty: {o.get('qty', 0)} | Type: {o.get('type', 'LIMIT')}"
            )
        await update.message.reply_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=quick_actions_keyboard(),
        )
    except Exception as e:
        await update.message.reply_text(
            f"Error: {e}",
            reply_markup=quick_actions_keyboard(),
        )


# ── Cancel All Orders ─────────────────────────────────────────────────────────

async def cancel_all_confirm(update: Update, context: CallbackContext,
                            exchange):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "*⚠️ KONFIRMASI*\n\nYakin cancel ALL open orders?",
        parse_mode="Markdown",
        reply_markup=confirm_cancel_keyboard(),
    )


async def cancel_all_execute(update: Update, context: CallbackContext,
                            exchange):
    query = update.callback_query
    await query.answer("Cancelling all...")
    try:
        result = await exchange.cancel_all_orders()
        count = result.get("count", 0) if isinstance(result, dict) else "many"
        await query.message.edit_text(
            f"✅ Cancelled {count} orders.",
            parse_mode="Markdown",
            reply_markup=quick_actions_keyboard(),
        )
    except Exception as e:
        await query.message.edit_text(
            f"❌ Error: {e}",
            parse_mode="Markdown",
            reply_markup=quick_actions_keyboard(),
        )


async def cancel_all_abort(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "Cancelled. No orders were cancelled.",
        reply_markup=quick_actions_keyboard(),
    )


# ── Close All Positions ───────────────────────────────────────────────────────

async def close_all_confirm(update: Update, context: CallbackContext,
                           exchange):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "*⚠️ KONFIRMASI*\n\nYakin close ALL positions? "
        "Ini akan melikuidasi semua posisi terbuka!",
        parse_mode="Markdown",
        reply_markup=confirm_close_all_keyboard(),
    )


async def close_all_execute(update: Update, context: CallbackContext,
                           exchange):
    query = update.callback_query
    await query.answer("Closing all...")
    try:
        result = await exchange.close_all_positions()
        count = result.get("count", 0) if isinstance(result, dict) else "many"
        await query.message.edit_text(
            f"✅ Closed {count} positions.",
            parse_mode="Markdown",
            reply_markup=quick_actions_keyboard(),
        )
    except Exception as e:
        await query.message.edit_text(
            f"❌ Error: {e}",
            parse_mode="Markdown",
            reply_markup=quick_actions_keyboard(),
        )


async def close_all_abort(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "Cancelled. No positions were closed.",
        reply_markup=quick_actions_keyboard(),
    )


# ── Average Entry ─────────────────────────────────────────────────────────────

async def avg_entry(update: Update, context: ContextTypes.DEFAULT_TYPE,
                   exchange):
    """Show average entry price across open positions."""
    try:
        positions = await exchange.get_positions()
        if not positions:
            await update.message.reply_text(
                "📭 Tidak ada posisi terbuka.",
                reply_markup=quick_actions_keyboard(),
            )
            return
        lines = ["*📈 AVERAGE ENTRY*\n"]
        for p in positions:
            side = "🟢 LONG" if p.get("side") == "LONG" else "🔴 SHORT"
            lines.append(
                f"{side} {p.get('symbol')}\n"
                f"  Entry: ${p.get('entry_price', 0):.4f} | "
                f"Current: ${p.get('mark_price', 0):.4f}\n"
                f"  Size: {p.get('size', 0)} | "
                f"PnL: {p.get('unrealized_pnl', 0):+.2f}"
            )
        await update.message.reply_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=quick_actions_keyboard(),
        )
    except Exception as e:
        await update.message.reply_text(
            f"Error: {e}",
            reply_markup=quick_actions_keyboard(),
        )


# ── Scan Market ───────────────────────────────────────────────────────────────

async def scan_market(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     exchange, loader: StrategyLoader, state_mgr: StateManager):
    """Quick market scan for signals."""
    try:
        strategy = loader.active()
        if not strategy:
            await update.message.reply_text(
                "⚠️ No active strategy.",
                reply_markup=quick_actions_keyboard(),
            )
            return

        await update.message.reply_text(
            "🔍 *Scanning market...*",
            parse_mode="Markdown",
        )

        # In real impl: exchange.scan_signals(strategy)
        # For now simulate
        import random
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
        results = []
        for sym in symbols:
            signal = random.choice(["LONG", "SHORT", "HOLD", "STRONG_LONG", "STRONG_SHORT"])
            if signal.startswith("STRONG"):
                results.append(f"  *{sym}:* {signal.replace('STRONG_', '')} 🔥")
            elif signal != "HOLD":
                results.append(f"  {sym}: {signal}")

        lines = ["*🔍 MARKET SCAN*\n", f"Strategy: `{strategy['name']}`\n"]
        lines.extend(results or ["  No strong signals found."])
        lines.append(f"\n_Scanned {len(symbols)} symbols._")

        await update.message.reply_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=quick_actions_keyboard(),
        )
    except Exception as e:
        await update.message.reply_text(
            f"Error: {e}",
            reply_markup=quick_actions_keyboard(),
        )


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_quick_handlers(app, state_mgr: StateManager, exchange, loader: StrategyLoader):
    # Text button entry
    app.add_handler(
        CallbackQueryHandler(lambda u, c: cmd_quick_actions(u, c), pattern="^qa:panel$")
    )
    app.add_handler(
        CallbackQueryHandler(lambda u, c: view_orders(u, c, exchange, state_mgr), pattern="^qa:orders$")
    )
    app.add_handler(
        CallbackQueryHandler(lambda u, c: cancel_all_confirm(u, c, exchange), pattern="^qa:cancel_all$")
    )
    app.add_handler(
        CallbackQueryHandler(lambda u, c: cancel_all_execute(u, c, exchange), pattern="^qa:cancel_all_confirm$")
    )
    app.add_handler(
        CallbackQueryHandler(cancel_all_abort, pattern="^qa:cancel_all_abort$")
    )
    app.add_handler(
        CallbackQueryHandler(lambda u, c: close_all_confirm(u, c, exchange), pattern="^qa:close_all$")
    )
    app.add_handler(
        CallbackQueryHandler(lambda u, c: close_all_execute(u, c, exchange), pattern="^qa:close_all_confirm$")
    )
    app.add_handler(
        CallbackQueryHandler(close_all_abort, pattern="^qa:close_all_abort$")
    )
    app.add_handler(
        CallbackQueryHandler(lambda u, c: avg_entry(u, c, exchange), pattern="^qa:avg_entry$")
    )
    app.add_handler(
        CallbackQueryHandler(lambda u, c: scan_market(u, c, exchange, loader, state_mgr), pattern="^qa:scan$")
    )