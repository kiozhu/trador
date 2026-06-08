"""Trade history handlers"""
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes

from ..keyboards import main_menu_keyboard
from ...memory import TradeLog


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE, trade_log: TradeLog):
    trades = trade_log.recent(10)
    if not trades:
        await update.message.reply_text(
            "📭 Belum ada trade.",
            reply_markup=main_menu_keyboard(),
        )
        return

    lines = ["*📋 RECENT TRADES*\n"]
    for t in reversed(trades):
        side = "🟢 LONG" if t.get("side") == "LONG" else "🔴 SHORT"
        pnl = t.get("pnl_pct", 0)
        pnl_sign = "+" if pnl >= 0 else ""
        exit = t.get("exit_reason", "?")
        lines.append(
            f"{side} {t.get('symbol')} — {exit}\n"
            f"  {pnl_sign}{pnl:.2f}% | {t.get('hold_minutes', 0)}min hold"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown",
                                    reply_markup=main_menu_keyboard())


def setup_trade_handlers(app, trade_log: TradeLog):
    app.add_handler(CommandHandler("history", lambda u, c: cmd_history(u, c, trade_log)))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex("^📋 History$"),
        lambda u, c: cmd_history(u, c, trade_log),
    ))