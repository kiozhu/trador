"""PnL chart handler — inline period selection, chart generation, text summary."""
from __future__ import annotations

import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..keyboards import main_menu_keyboard
from . import pnl_chart as chart_mod

logger = logging.getLogger(__name__)

# ── period → label ──────────────────────────────────────────
PERIODS = ["24h", "7d", "30d", "all"]

PERIOD_EMOJI = {
    "24h": "⏱️",
    "7d":  "📅",
    "30d": "🗓️",
    "all": "♾️",
}

PERIOD_LABEL = {
    "24h": "24 Jam",
    "7d":  "7 Hari",
    "30d": "30 Hari",
    "all": "Semua",
}


def _period_keyboard() -> InlineKeyboardMarkup:
    kb = []
    row = []
    for i, p in enumerate(PERIODS):
        row.append(
            InlineKeyboardButton(
                f"{PERIOD_EMOJI[p]} {PERIOD_LABEL[p]}",
                callback_data=f"pnl_{p}",
            )
        )
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("📋 Text Summary", callback_data="pnl_summary")])
    kb.append([InlineKeyboardButton("◀️ Back", callback_data="pnl_back")])
    return InlineKeyboardMarkup(kb)


async def cmd_pnl(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point — show period picker."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "📊 *PnL Chart*\n\nPilih periode:",
            reply_markup=_period_keyboard(),
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "📊 *PnL Chart*\n\nPilih periode:",
            reply_markup=_period_keyboard(),
            parse_mode="Markdown",
        )


async def _show_chart(update: Update, period: str) -> None:
    """Generate and send chart image for given period."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    msg = await query.edit_message_text(f"⏳ Generating {PERIOD_LABEL[period]} chart...")
    if msg is None:
        return
    chart_path = chart_mod.generate_pnl_chart(period=period)

    if chart_path and Path(chart_path).exists():
        with open(chart_path, "rb") as img:
            await msg.delete()
            await update.effective_message.reply_photo(
                photo=img,
                caption=f"📊 PnL Chart — {PERIOD_LABEL[period]}",
                reply_markup=_period_keyboard(),
            )
    else:
        await msg.edit_text(
            f"📊 *PnL Chart — {PERIOD_LABEL[period]}*\n\n"
            "❌ Belum ada data trade untuk periode ini.",
            reply_markup=_period_keyboard(),
            parse_mode="Markdown",
        )


async def _show_summary(update: Update) -> None:
    """Send text PnL summary."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    text = chart_mod.pnl_summary_text()
    await query.edit_message_text(
        text,
        reply_markup=_period_keyboard(),
        parse_mode="Markdown",
    )


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="pnl_back")]])


async def _back(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to main menu."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await query.edit_message_text("🏠 Main Menu", reply_markup=main_menu_keyboard())


def setup_pnl_handlers(app) -> None:
    """Register all PnL handlers."""
    app.add_callback_query_handler(cmd_pnl, pattern="^pnl$")
    app.add_callback_query_handler(lambda u, c: _show_chart(u, "24h"), pattern="^pnl_24h$")
    app.add_callback_query_handler(lambda u, c: _show_chart(u, "7d"),  pattern="^pnl_7d$")
    app.add_callback_query_handler(lambda u, c: _show_chart(u, "30d"), pattern="^pnl_30d$")
    app.add_callback_query_handler(lambda u, c: _show_chart(u, "all"),  pattern="^pnl_all$")
    app.add_callback_query_handler(_show_summary, pattern="^pnl_summary$")
    app.add_callback_query_handler(_back, pattern="^pnl_back$")