"""Wallet connect handlers — exchange API key management + connection status"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ContextTypes

from ..keyboards import wallet_panel_keyboard, wallet_connecting_keyboard, main_menu_keyboard
from ...memory import StateManager
from ...utils.logger import log


# ── Entry: Wallet Panel ───────────────────────────────────────────────────────

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE,
                    state_mgr: StateManager):
    state = state_mgr.get()
    connected = state.get("wallet_connected", False)
    exchange = state.get("exchange")
    address = state.get("wallet_address")

    if connected:
        text = (
            f"*🔗 WALLET CONNECTED*\n\n"
            f"Exchange: `{(exchange or '').upper()}`\n"
            f"Address: `{address or '—'}`\n\n"
            f"Pilih aksi:"
        )
    else:
        text = (
            "*🔗 CONNECT EXCHANGE*\n\n"
            "Pilih platform untuk connect:\n"
            "• 🟣 Binance Futures — CCXT\n"
            "• 🔵 Bybit Unified — CCXT\n"
            "• 🟠 OKX — CCXT\n\n"
            "_API keys ada di file .env_"
        )

    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=wallet_panel_keyboard(connected, exchange, address),
    )


# ── Exchange Connect ─────────────────────────────────────────────────────────

async def connect_exchange(update: Update, context: CallbackContext,
                          state_mgr: StateManager):
    query = update.callback_query
    exchange = query.data.replace("wallet:", "")
    await query.answer("🔄 Connecting...", show_alert=False)

    # Update UI to show connecting state
    await query.message.edit_text(
        f"*🔄 Connecting to {(exchange or '').upper()}...*\n\n"
        "Mohon tunggu sebentar...",
        parse_mode="Markdown",
        reply_markup=wallet_connecting_keyboard(),
    )

    # Validate .env credentials
    from dotenv import load_dotenv
    import os
    load_dotenv()

    key_var = f"{exchange.upper()}_API_KEY"
    secret_var = f"{exchange.upper()}_API_SECRET"
    api_key = os.getenv(key_var)
    api_secret = os.getenv(secret_var)

    if not api_key or not api_secret:
        await query.message.edit_text(
            f"*❌ {exchange.upper()} not configured*\n\n"
            f"Set `{key_var}` dan `{secret_var}` di file `.env`\n\n"
            "Contoh:\n"
            f"`{key_var}=your_api_key`\n"
            f"`{secret_var}=your_api_secret`",
            parse_mode="Markdown",
            reply_markup=wallet_panel_keyboard(False, None, None),
        )
        return

    # Test connection via ccxt
    try:
        if exchange == "binance":
            import ccxt.async_support as ccxt
            client = ccxt.binance({
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
            })
            # Test: fetch balance
            balance = await client.fetch_balance(params={"type": "future"})
            total_usdt = float(balance.get("total", {}).get("USDT", 0))
            address = f"binance_user_{api_key[:8]}"
            await client.close()

        elif exchange == "bybit":
            import ccxt.async_support as ccxt
            client = ccxt.bybit({
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
            })
            balance = await client.fetch_balance(params={"type": "swap"})
            total_usdt = float(balance.get("total", {}).get("USDT", 0))
            address = f"bybit_user_{api_key[:8]}"
            await client.close()

        elif exchange == "okx":
            import ccxt.async_support as ccxt
            client = ccxt.okx({
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
            })
            balance = await client.fetch_balance(params={"type": "swap"})
            total_usdt = float(balance.get("total", {}).get("USDT", 0))
            address = f"okx_user_{api_key[:8]}"
            await client.close()

        else:
            raise ValueError(f"Unknown exchange: {exchange}")

        # Save connected state
        state_mgr.set_wallet(exchange, address, True)
        state_mgr.set_mode("live")

        await query.message.edit_text(
            f"*✅ {exchange.upper()} CONNECTED*\n\n"
            f"Address: `{address}`\n"
            f"USDT Balance: `${total_usdt:,.2f}`\n\n"
            f"Mode: 🔴 LIVE\n\n"
            "Ready to trade futures!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Start Trading", callback_data="wallet_start_trading")],
                [InlineKeyboardButton("◀️ Back", callback_data="menu_main")],
            ]),
        )
        log.info("Wallet connected: %s %s", exchange, address)

    except Exception as e:
        log.error("Wallet connect failed: %s", e)
        await query.message.edit_text(
            f"*❌ Connection Failed*\n\n"
            f"Error: `{str(e)[:200]}`\n\n"
            "Cek API key/secret di .env atau coba lagi.",
            parse_mode="Markdown",
            reply_markup=wallet_panel_keyboard(False, None, None),
        )


# ── Disconnect ────────────────────────────────────────────────────────────────

async def wallet_disconnect(update: Update, context: CallbackContext,
                           state_mgr: StateManager):
    query = update.callback_query
    await query.answer()
    state_mgr.set_wallet(None, None, False)
    state_mgr.set_mode("dry_run")
    await query.message.edit_text(
        "*🔌 Wallet Disconnected*\n\n"
        "Mode set to 🟡 DRY RUN.\n"
        "No real trades will be executed.",
        parse_mode="Markdown",
        reply_markup=wallet_panel_keyboard(False, None, None),
    )


# ── Reconnect ─────────────────────────────────────────────────────────────────

async def wallet_reconnect(update: Update, context: CallbackContext,
                          state_mgr: StateManager):
    """Reconnect = show platform options again."""
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "*🔄 RECONNECT*\n\nPilih platform:",
        parse_mode="Markdown",
        reply_markup=wallet_panel_keyboard(False, None, None),
    )


# ── Start Trading after connect ───────────────────────────────────────────────

async def wallet_start_trading(update: Update, context: CallbackContext,
                               state_mgr: StateManager):
    query = update.callback_query
    await query.answer("🚀 Starting live trading...")
    state_mgr.set_trading(True)
    state_mgr.set_status("running")
    await query.message.edit_text(
        "🟢 *LIVE TRADING STARTED*\n\n"
        "Bot will execute real futures trades.\n"
        "Monitor closely!",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


# ── Mode Selection ────────────────────────────────────────────────────────────

async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE,
                  state_mgr: StateManager):
    state = state_mgr.get()
    current = state.get("mode", "dry_run")
    wallet = state.get("wallet_connected", False)

    text = (
        f"*🎮 TRADING MODE*\n\n"
        f"Current: *{'🔴 LIVE' if current == 'live' else '🟡 DRY RUN'}*\n"
        f"Wallet: {'✅ Connected' if wallet else '❌ Not connected'}\n\n"
        "Pilih mode:"
    )
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=mode_selection_keyboard(current),
    )


async def set_mode(update: Update, context: CallbackContext,
                  state_mgr: StateManager):
    query = update.callback_query
    new_mode = query.data.replace("mode:", "")
    await query.answer()

    if new_mode == "live":
        state = state_mgr.get()
        if not state.get("wallet_connected"):
            await query.answer("❌ Connect wallet first!", show_alert=True)
            return

    state_mgr.set_mode(new_mode)
    label = "🔴 LIVE" if new_mode == "live" else "🟡 DRY RUN"
    state = state_mgr.get()
    wallet = state.get("wallet_connected", False)

    text = (
        f"*🎮 MODE CHANGED*\n\n"
        f"Current: *{label}*\n"
        f"Wallet: {'✅ Connected' if wallet else '❌ Not connected'}\n\n"
        f"{'Real trades akan dieksekusi!' if new_mode == 'live' else 'Hanya simulasi, tidak ada trade nyata.'}"
    )
    await query.message.edit_text(
        text, parse_mode="Markdown",
        reply_markup=mode_selection_keyboard(new_mode),
    )


async def mode_info(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    text = (
        "*📊 MODE INFO*\n\n"
        "*🔴 LIVE*\n"
        "• Real money at stake\n"
        "• Execute trades di exchange\n"
        "• Wallet must be connected\n"
        "• ⚠️ High risk — monitor closely\n\n"
        "*🟡 DRY RUN*\n"
        "• Simulated trades only\n"
        "• No real money used\n"
        "• Test strategi dengan data real\n"
        "• Safe untuk belajar + development"
    )
    await query.message.edit_text(text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Back", callback_data="mode:back")],
        ]),
    )


# ── Direction (Long/Short/Both) ────────────────────────────────────────────────

async def cmd_direction(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       state_mgr: StateManager):
    state = state_mgr.get()
    current = state.get("direction", "both")
    text = (
        f"*📈 DIRECTION MODE*\n\n"
        f"Current: `{current.upper()}`\n\n"
        "Pilih arah trade:\n"
        "• LONG — hanya naik\n"
        "• SHORT — hanya turun\n"
        "• BOTH — keduanya (recommended)"
    )
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=direction_keyboard(current),
    )


async def set_direction(update: Update, context: CallbackContext,
                       state_mgr: StateManager):
    query = update.callback_query
    new_dir = query.data.replace("dir:", "")
    await query.answer(f"Direction: {new_dir.upper()}")
    state_mgr.set("direction", new_dir)
    await query.message.edit_reply_markup(
        reply_markup=direction_keyboard(new_dir),
    )


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_wallet_handlers(app, state_mgr: StateManager):
    app.add_handler(CallbackQueryHandler(
        lambda u, c: cmd_wallet(u, c, state_mgr), pattern="^wallet:panel$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: connect_exchange(u, c, state_mgr), pattern="^wallet:"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: wallet_disconnect(u, c, state_mgr), pattern="^wallet_disconnect$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: wallet_reconnect(u, c, state_mgr), pattern="^wallet_reconnect$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: wallet_start_trading(u, c, state_mgr), pattern="^wallet_start_trading$"))


def setup_mode_handlers(app, state_mgr: StateManager):
    app.add_handler(CallbackQueryHandler(
        lambda u, c: cmd_mode(u, c, state_mgr), pattern="^mode:panel$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: set_mode(u, c, state_mgr), pattern="^mode:live$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: set_mode(u, c, state_mgr), pattern="^mode:dry_run$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: mode_info(u, c), pattern="^mode:info$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: cmd_mode(u, c, state_mgr), pattern="^mode:back$"))  # back → show panel


def setup_direction_handlers(app, state_mgr: StateManager):
    app.add_handler(CallbackQueryHandler(
        lambda u, c: cmd_direction(u, c, state_mgr), pattern="^dir:panel$"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: set_direction(u, c, state_mgr), pattern="^dir:"))
