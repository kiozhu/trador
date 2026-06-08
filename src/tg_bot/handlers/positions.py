"""Position handlers — view open positions"""
from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters, ContextTypes

from ..keyboards import main_menu_keyboard
from ...utils.logger import log


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       position_manager):
    positions = position_manager.get_open_positions()
    if not positions:
        await update.message.reply_text(
            "📭 Tidak ada posisi terbuka.",
            reply_markup=main_menu_keyboard(),
        )
        return

    lines = ["*📈 OPEN POSITIONS*\n"]
    for p in positions:
        side = "🟢 LONG" if p.get("side") == "LONG" else "🔴 SHORT"
        pnl_pct = p.get("pnl_pct", 0)
        pnl_sign = "+" if pnl_pct >= 0 else ""
        lines.append(
            f"{side} {p.get('symbol')}\n"
            f"  Entry: ${p.get('entry_price'):.2f} | Current: ${p.get('current_price'):.2f}\n"
            f"  Size: {p.get('size', 0):.4f} | Leverage: {p.get('leverage', 1)}x\n"
            f"  PnL: {pnl_sign}{pnl_pct:.2f}% (${p.get('pnl_usd', 0):.2f})\n"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown",
                                    reply_markup=main_menu_keyboard())


def setup_position_handlers(app, position_manager):
    app.add_handler(CommandHandler("positions", lambda u, c: cmd_positions(u, c, position_manager)))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex("^📈 Positions$"),
        lambda u, c: cmd_positions(u, c, position_manager),
    ))