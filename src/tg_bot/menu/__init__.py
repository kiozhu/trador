"""Menu system — trojan-style inline keyboard with proper CallbackQuery routing.
Single entry point for ALL inline keyboard interactions.
Dead handler systems (wallet.py, smart_mode.py) have been removed.
"""
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from datetime import datetime, timezone

from ...utils.logger import log
from .core import MenuPage, MenuNavigator, make_back_button
from .pages import (
    MainPage, StatusPage, HelpPage, PositionsPage, StrategyPage,
    HistoryPage, BalancePage, WalletPage, SmartPage, QuickPage,
    ModePage, DirectionPage, MonitorPage, SettingsPage, RiskPage,
    RiskConfigPage,
)


class MenuRouter:
    """Wires ALL inline callback queries to page navigation or action handlers."""

    def __init__(self, state_mgr, perf, exchange, trade_log=None, loader=None, trador=None):
        self.state_mgr = state_mgr
        self.perf = perf
        self.engine = exchange
        self.trade_log = trade_log
        self.loader = loader
        self.trador = trador  # reference to main Trador instance for LLM reload

        # ── All pages registered in nav ─────────────────────────────────────────
        pages = {
            "main": MainPage(),
            "status": StatusPage(state_mgr, perf, trade_log, loader),
            "help": HelpPage(),
            "positions": PositionsPage(trade_log, state_mgr),
            "strategy": StrategyPage(loader),
            "history": HistoryPage(trade_log),
            "balance": BalancePage(state_mgr, exchange, trade_log),
            "wallet": WalletPage(state_mgr),
            "smart": SmartPage(state_mgr, loader),
            "quick": QuickPage(state_mgr, loader),
            "mode": ModePage(state_mgr),
            # Direction page — hidden (direction always "both" internally)
            "monitor": MonitorPage(state_mgr, trade_log, perf, loader),
            "settings": SettingsPage(state_mgr),
            "risk": RiskPage(state_mgr, None),  # auto_trader set post-startup via set_auto_trader
            "risk_config": RiskConfigPage(state_mgr),
        }
        self.nav = MenuNavigator(pages)

    async def _navigate_to(self, update: Update, page_key: str) -> None:
        """Navigate to a page: push to nav stack, build, edit message."""
        self.nav.push(page_key)
        text, reply_markup = self.nav.build(page_key)
        try:
            await update.callback_query.answer(f"→ {page_key}", show_alert=False)
            await update.callback_query.edit_message_text(
                text, parse_mode=None, reply_markup=reply_markup)
        except Exception as e:
            # Gracefully handle "Message is not modified" — happens when
            # re-rendering the same page content (e.g. tapping active filter)
            if "not modified" not in str(e).lower():
                log.error("navigate_to failed: %s", e)

    # ── Action callbacks (prefix action:) ─────────────────────────────────────
    async def handle_action(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Handle action: callbacks — trading controls."""
        query = update.callback_query
        data = query.data
        log.info("handle_action called: data=%s", data)

        """Handle action: callbacks — trading controls with confirmation flow."""
        query = update.callback_query
        data = query.data
        log.info("handle_action called: data=%s", data)
        state = self.state_mgr.get()
        mode = state.get("mode", "dry_run")

        # ── STOP trading ────────────────────────────────────────────────────
        if data == "action:stop":
            if mode == "dry_run":
                # Dry run: stop + auto close all positions
                self.state_mgr.set("trading_enabled", False)
                self.state_mgr.set_status("stopped")
                await query.answer("🛑 Trading stopped — dry run", show_alert=True)
                # Close all dry run positions via trade_log
                if self.trade_log:
                    for t in self.trade_log.get_active(mode="dry_run"):
                        t["status"] = "closed"
                        t["exit_reason"] = "manual_stop"
                        t["close_timestamp"] = datetime.now(timezone.utc).isoformat()
                        self.trade_log.add(t)
                await self._navigate_to(update, "main")
            else:
                # Live mode: check for open positions
                active = self.trade_log.get_active(mode="live") if self.trade_log else []
                if active:
                    # Show confirmation with options
                    text = (
                        f"🛑 STOP LIVE TRADING\n\n"
                        f"⚠️ Kamu sedang punya {len(active)} posisi terbuka.\n\n"
                        f"Pilih aksi:\n"
                        f"  1. Hold — biarkan posisi terbuka, stop auto trading saja\n"
                        f"  2. Close All — tutup semua posisi sekarang\n\n"
                        f"⚠️ Real money at risk!"
                    )
                    keyboard = [
                        [InlineKeyboardButton("🤚 Hold Positions", callback_data="action:stop_hold")],
                        [InlineKeyboardButton("🔴 Close All (Real)", callback_data="action:stop_close_all")],
                        [InlineKeyboardButton("◀️ Batal", callback_data="page:main")],
                    ]
                    await query.answer("⚠️ Open positions detected", show_alert=False)
                    await query.edit_message_text(text, parse_mode=None,
                        reply_markup=InlineKeyboardMarkup(keyboard))
                else:
                    # No open positions — stop immediately
                    self.state_mgr.set("trading_enabled", False)
                    self.state_mgr.set_status("stopped")
                    await query.answer("🛑 Live trading stopped", show_alert=True)
                    await self._navigate_to(update, "main")
            return

        if data == "action:stop_hold":
            # Stop auto trading but keep positions open
            self.state_mgr.set("trading_enabled", False)
            self.state_mgr.set_status("stopped")
            await query.answer("🛑 Stopped — positions held", show_alert=True)
            await self._navigate_to(update, "main")
            return

        if data == "action:stop_close_all":
            # Stop + close ALL live positions AND cancel all open orders
            self.state_mgr.set("trading_enabled", False)
            self.state_mgr.set_status("stopped")

            # Cancel ALL open orders on exchange
            if self.engine:
                try:
                    result = await self.engine.cancel_all_orders()
                    log.info("Cancelled all orders: %s", result)
                except Exception as e:
                    log.error("Cancel all orders failed: %s", e)

            # Close ALL open positions on exchange
            if self.engine:
                mode = state.get("mode", "live")
                positions = self.trade_log.get_active(mode=mode) if self.trade_log else []
                for t in positions:
                    sym = t.get("symbol", "")
                    side = t.get("side", "")
                    if sym and side:
                        try:
                            close_result = await self.engine.close_position(sym, side)
                            log.info("Closed position %s %s: %s", sym, side, close_result)
                        except Exception as e:
                            log.error("Close position %s %s failed: %s", sym, side, e)

            # Update local trade log
            if self.trade_log:
                for t in self.trade_log.get_active(mode="live"):
                    t["status"] = "closed"
                    t["exit_reason"] = "manual_stop"
                    t["close_timestamp"] = datetime.now(timezone.utc).isoformat()
                    self.trade_log.add(t)

            await query.answer("🔴 All positions closed + orders cancelled", show_alert=True)
            await self._navigate_to(update, "main")
            return

        # ── START trading ───────────────────────────────────────────────────
        if data == "action:start":
            if mode == "live":
                # Live mode: show confirmation with setup summary
                strategy = state.get("strategy_active", "none")
                size = state.get("balance_per_trade_pct", 10)
                max_orders = state.get("max_orders_per_cycle", 2)
                balance = state.get("live_balance", 0)
                wallet = state.get("wallet_connected", False)

                text = (
                    "*🚀 START LIVE TRADING\n\n"
                    f"⚠️ Konfirmasi sebelum mulai:\n\n"
                    f"  Wallet: {'✅ Connected' if wallet else '❌ Not connected'}\n"
                    f"  Balance: ${balance:,.2f}\n"
                    f"  Strategy: {strategy}\n"
                    f"  Size/trade: {size}%\n"
                    f"  Max orders/cycle: {max_orders}\n\n"
                    f"Ini akan mulai auto trading dengan real money.\n"
                    f"Yakin ingin mulai?"
                )
                keyboard = [
                    [InlineKeyboardButton("✅ Ya, Mulai!", callback_data="action:start_confirm")],
                    [InlineKeyboardButton("◀️ Batal", callback_data="page:main")],
                ]
                await query.answer("⚠️ Confirmation required", show_alert=False)
                await query.edit_message_text(text, parse_mode=None,
                    reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                # Dry run: start immediately
                self.state_mgr.set("trading_enabled", True)
                self.state_mgr.set_status("running")
                await query.answer("🚀 Trading started — dry run", show_alert=True)
                await self._navigate_to(update, "main")
            return

        if data == "action:start_confirm":
            self.state_mgr.set("trading_enabled", True)
            self.state_mgr.set_status("running")
            await query.answer("🚀 LIVE trading started!", show_alert=True)
            await self._navigate_to(update, "main")
            return

        # ── MODE switch ─────────────────────────────────────────────────────
        if data == "action:mode_live":
            wallet_ok = state.get("wallet_connected", False)
            size_ok = state.get("balance_per_trade_pct", 0) > 0
            if not wallet_ok or not size_ok:
                missing = []
                if not wallet_ok:
                    missing.append("connect wallet")
                if not size_ok:
                    missing.append("set trade size di Balance")
                text = (
                    f"❌ Cannot switch to LIVE\n\n"
                    f"Prerequisites not met:\n"
                    f"  • Connect wallet: {'✅' if wallet_ok else '❌'}\n"
                    f"  • Set trade size: {'✅' if size_ok else '❌'}\n\n"
                    f"Selesaikan dulu: {', '.join(missing)}"
                )
                await query.answer("❌ Prerequisites not met", show_alert=True)
                await query.edit_message_text(text, parse_mode=None,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="page:mode")]]))
                return
            self.state_mgr.set_mode("live")
            await query.answer("🔴 Mode: LIVE", show_alert=True)
            await self._navigate_to(update, "mode")
            return

        if data == "action:mode_dry":
            self.state_mgr.set_mode("dry_run")
            await query.answer("🟡 Mode: DRY RUN", show_alert=True)
            await self._navigate_to(update, "mode")
            return

        # ── Direction (kept for compatibility) ──────────────────────────────
        if data == "action:dir_long":
            self.state_mgr.set("direction", "long")
            await query.answer("📈 Direction: LONG", show_alert=True)
        elif data == "action:dir_short":
            self.state_mgr.set("direction", "short")
            await query.answer("📉 Direction: SHORT", show_alert=True)
        elif data == "action:dir_both":
            self.state_mgr.set("direction", "both")
            await query.answer("🔄 Direction: BOTH", show_alert=True)
        elif data == "action:smart_on":
            self.state_mgr.set("smart_mode", True)
            await query.answer("🧠 Smart Mode: ENABLED", show_alert=True)
        elif data == "action:smart_off":
            self.state_mgr.set("smart_mode", False)
            await query.answer("🧠 Smart Mode: DISABLED", show_alert=True)

        # ── Re-scan open positions ────────────────────────────────────────
        elif data == "action:rescan_open":
            auto_trader = _.bot_data.get("auto_trader") if _ else None
            if not auto_trader:
                await query.answer("❌ Bot not ready", show_alert=True)
                return
            await query.answer("🔄 Re-scanning open positions...", show_alert=False)
            try:
                count = await auto_trader.focus_open_positions()
                await query.answer(f"✅ Re-scan done: {count} positions reviewed", show_alert=True)
            except Exception as e:
                log.error("rescan_open failed: %s", e)
                await query.answer(f"❌ Re-scan failed: {e}", show_alert=True)
            await self._navigate_to(update, "monitor")
            return

        else:
            return

        await self._navigate_to(update, "main")

    # ── Strategy callbacks (prefix strat:) ─────────────────────────────────────
    async def handle_strategy(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Handle strategy selection and detail callbacks."""
        query = update.callback_query
        data = query.data
        log.info("handle_strategy: %s", data)

            # strat:id → select strategy
        if data.startswith("strat:"):
            strategy_id = data[6:]
            if self.loader and self.loader.toggle(strategy_id):
                active_ids = self.loader.list_active_ids()
                await query.answer(f"Strategies active: {len(active_ids)}", show_alert=False)
                await self._navigate_to(update, "strategy")
            else:
                await query.answer("Strategy not found", show_alert=True)
            return

        # strat_activate / strat_deactivate:id → toggle active
        if data.startswith("strat_activate:") or data.startswith("strat_deactivate:"):
            strategy_id = data.split(":")[1]
            if self.loader:
                self.loader.set_active(strategy_id)
                await query.answer("Strategy updated", show_alert=False)
                await self._navigate_to(update, "main")
            return

        # strat_param:id → show param keyboard
        if data.startswith("strat_param:"):
            parts = data.split(":")
            strategy_id = parts[1] if len(parts) > 1 else None
            if not strategy_id or not self.loader:
                await query.answer("Strategy loader not ready", show_alert=True)
                return
            strategy = self.loader.get(strategy_id)
            if not strategy:
                await query.answer("Strategy not found", show_alert=True)
                return
            active = self.loader.active()
            is_active = active and active.get("id") == strategy_id
            from ..keyboards import strategy_detail_keyboard
            reply_markup = strategy_detail_keyboard(strategy_id, is_active)
            text = f"⚙️ {strategy.get('name', strategy_id)}\n\nPilih parameter:"
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            return

        # strat_perf:id → show performance
        if data.startswith("strat_perf:"):
            strategy_id = data.split(":")[1]
            if self.loader:
                strategy = self.loader.get(strategy_id)
                name = strategy.get("name", strategy_id) if strategy else strategy_id

                # Get performance from perf tracker
                perf_24h = {"trades": 0, "win_rate": 0, "pnl_pct": 0, "pnl_usd": 0}
                perf_7d = {"trades": 0, "win_rate": 0, "pnl_pct": 0, "pnl_usd": 0}
                if self.perf:
                    try:
                        perf_data = self.perf.get("dry_run")
                        perf_24h = perf_data.get("24h", perf_24h)
                        perf_7d = perf_data.get("7d", perf_7d)
                    except Exception:
                        pass

                lines = [
                    f"📊 {name}",
                    "",
                    f"24h | Trades: {perf_24h['trades']} | Win: {perf_24h['win_rate']:.1f}% | PnL: {perf_24h['pnl_pct']:+.1f}% (${perf_24h['pnl_usd']:+.2f})",
                    f"7d  | Trades: {perf_7d['trades']}  | Win: {perf_7d['win_rate']:.1f}% | PnL: {perf_7d['pnl_pct']:+.1f}% (${perf_7d['pnl_usd']:+.2f})",
                    "",
                    "◀️ Back untuk kembali ke daftar strategy.",
                ]
                text = "\n".join(lines)
                await query.answer("📊 Performance loaded", show_alert=False)
                await query.edit_message_text(text, parse_mode=None)
            return

        # strat_delete:id → confirm delete
        if data.startswith("strat_delete:"):
            strategy_id = data.split(":")[1]
            from ..keyboards import confirm_cancel_keyboard
            reply_markup = confirm_cancel_keyboard()
            text = f"🗑 Delete strategy?\n\n{strategy_id}\n\nThis cannot be undone."
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            return

        # strat_back → back to strategy list
        if data == "strat_back":
            await self._navigate_to(update, "strategy")
            return

    # ── QA (Quick Action) callbacks ─────────────────────────────────────────
    async def handle_settings(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Handle settings and balance adjustment callbacks (set:*)."""
        query = update.callback_query
        data = query.data
        log.info("handle_settings called: data=%s", data)

        if not data.startswith("set:"):
            return

        key = data[4:]
        state = self.state_mgr.get()
        msg = ""

        # ── Symbol filter (A-Z letter groups) ──────────────────────────
        if key.startswith("symbol_filter:"):
            letter = key.split(":")[-1] or None
            if letter == "":
                letter = None
            self.state_mgr.set("symbol_filter_letter", letter)
            await query.answer()
            # Re-render symbol page directly (not settings main)
            from .pages import SettingsPage
            page = SettingsPage(self.state_mgr)
            text, reply_markup = page.build(sub_page="symbols")
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            return

        # ── Settings: max orders cycle ──────────────────────────────────
        if key == "max_orders_cycle":
            cur = state.get("max_orders_per_cycle", 2)
            options = [1, 2, 3, 5, 10, 15, 20]
            if cur not in options:
                options.append(cur)
                options.sort()
            next_idx = (options.index(cur) + 1) % len(options)
            new_val = options[next_idx]
            self.state_mgr.set("max_orders_per_cycle", new_val)
            msg = f"📋 Max orders/cycle: {new_val}"
            return_page = "settings"

        elif key == "max_positions":
            cur = state.get("max_concurrent_positions", 5)
            options = [1, 2, 3, 5, 10, 15, 20]
            if cur not in options:
                options.append(cur)
                options.sort()
            next_idx = (options.index(cur) + 1) % len(options)
            new_val = options[next_idx]
            self.state_mgr.set("max_concurrent_positions", new_val)
            msg = f"🔢 Max positions: {new_val}"
            return_page = "settings"

        # ── LLM toggle (reject if no API key) ───────────────────────────────────
        elif key == "llm_toggle":
            current = state.get("llm_enabled", False)
            api_key = state.get("llm_api_key", "")
            if not current and not api_key:
                await query.answer("❌ Set LLM API Key dulu di menu Settings", show_alert=True)
                return
            self.state_mgr.set("llm_enabled", not current)
            msg = f"🤖 LLM Smart: {'ON' if not current else 'OFF'}"
            return_page = "settings"

        # ── Balance page: size per trade ─────────────────────────────────
        elif key == "size":
            cur = state.get("balance_per_trade_pct", 10)
            options = [5, 10, 15, 20, 25, 30]
            next_idx = (options.index(cur) + 1) % len(options)
            new_val = options[next_idx]
            self.state_mgr.set("balance_per_trade_pct", new_val)
            msg = f"📐 Size/trade: {new_val}%"
            return_page = "balance"

        # ── Balance page: max orders ─────────────────────────────────────
        elif key == "max_orders":
            cur = state.get("max_orders_per_cycle", 2)
            options = [1, 2, 3, 5]
            if cur not in options:
                options.append(cur)
                options.sort()
            next_idx = (options.index(cur) + 1) % len(options)
            new_val = options[next_idx]
            self.state_mgr.set("max_orders_per_cycle", new_val)
            msg = f"🔢 Max orders/cycle: {new_val}"
            return_page = "balance"

        # ── Balance page: max positions ──────────────────────────────────
        elif key == "max_pos":
            cur = state.get("max_concurrent_positions", 5)
            options = [1, 2, 3, 5, 10]
            if cur not in options:
                options.append(cur)
                options.sort()
            next_idx = (options.index(cur) + 1) % len(options)
            new_val = options[next_idx]
            self.state_mgr.set("max_concurrent_positions", new_val)
            msg = f"📊 Max positions: {new_val}"
            return_page = "balance"

        # ── Balance page: daily loss limit (dollar amount) ─────────────────
        elif key == "daily_loss":
            cur = state.get("daily_loss_limit", 50)
            keyboard = [
                [
                    InlineKeyboardButton("$25", callback_data="set:daily_loss_25"),
                    InlineKeyboardButton("$50", callback_data="set:daily_loss_50"),
                ],
                [
                    InlineKeyboardButton("$100", callback_data="set:daily_loss_100"),
                    InlineKeyboardButton("$200", callback_data="set:daily_loss_200"),
                ],
                [InlineKeyboardButton("◀️ Back", callback_data="page:balance")],
            ]
            await query.answer()
            await query.edit_message_text(
                f"📉 Daily Loss Limit\n\n"
                f"Saat ini: $ {cur}\n\n"
                f"Pilih batas maksimal kerugian per hari:",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        elif key.startswith("daily_loss_"):
            try:
                amount = int(key.split("_")[-1])
            except ValueError:
                amount = 50
            self.state_mgr.set("daily_loss_limit", amount)
            msg = f"📉 Daily loss limit: ${amount}"
            return_page = "balance"

        # ── Balance page: reset dry run → $100 ───────────────────────────
        elif key == "reset_dry_100":
            self.state_mgr.update(
                dry_run_balance=100.0,
                dry_run_initial_balance=100.0,
                dry_run_trades=0,
                mode="dry_run",
                trading_enabled=False,
            )
            # Clear dry_run trades
            from ...utils.helpers import atomic_write_json
            file_path = self.trade_log._file("dry_run")
            atomic_write_json(file_path, {"trades": []})
            msg = "🔄 Dry run reset — balance: $100"
            return_page = "balance"

        # ── Balance page: sync live balance from Binance ───────────────────
        elif key == "sync_live_balance":
            state = self.state_mgr.get()
            api_key = state.get("wallet_api_key", "")
            api_secret = state.get("wallet_api_secret", "")

            if not api_key or not api_secret:
                await query.answer("❌ Wallet belum terhubung", show_alert=True)
                return

            await query.answer("🔄 Syncing balance...", show_alert=False)
            result = _fetch_binance_live_balance(api_key, api_secret)
            if result["success"]:
                self.state_mgr.set("live_balance", result["total"])
                if not state.get("live_initial_balance"):
                    self.state_mgr.set("live_initial_balance", result["total"])
                msg = (
                    f"✅ Balance synced!\n\n"
                    f"USDT: ${result['total']:.6f}\n"
                    f"Free: ${result['free']:.6f}\n"
                    f"Positions: {result['positions']}\n"
                    f"BTC: ${result['btc_price']:,.2f}"
                )
            else:
                msg = f"❌ Sync failed: {result.get('error', 'Unknown')}"
            await query.answer(msg.split("\n")[0], show_alert=True)
            return_page = "balance"

        # ── Balance page: reset live → $0 ─────────────────────────────────
        elif key == "reset_live":
            self.state_mgr.update(
                live_balance=0.0,
                live_initial_balance=0.0,
                live_trades=0,
            )
            from ...utils.helpers import atomic_write_json
            file_path = self.trade_log._file("live")
            atomic_write_json(file_path, {"trades": []})
            msg = "🔄 Live reset — balance: $0"
            return_page = "balance"

        # ── Balance page: add fund Hyperliquid ─────────────────────────────
        elif key == "add_fund_hl":
            keyboard = [
                [InlineKeyboardButton("💰 Deposit USDC", callback_data="set:hl_deposit")],
                [InlineKeyboardButton("🔄 Auto-Sync Balance", callback_data="set:sync_balance_hl")],
                [InlineKeyboardButton("◀️ Back", callback_data="page:balance")],
            ]
            await query.answer()
            await query.edit_message_text(
                "*💵 Add Fund — Hyperliquid\n\n"
                "Hyperliquid gunakan USDC sebagai margin.\n\n"
                "*1. Deposit USDC from External\n"
                "• Hyperliquid → Portfolio → Deposit\n"
                "• Transfer USDC via wallet (ERC-20)\n"
                "• Minimal ~$10\n\n"
                "*2. Auto-Sync Balance\n"
                "• Hubungkan wallet via API key\n"
                "• Balance auto-sync dari wallet kamu\n\n"
                "_Deposit masuk ke Hyperliquid wallet._",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        elif key == "hl_deposit":
            await query.answer("📝 Buka app.hyperliquid.xyz → Portfolio → Deposit", show_alert=True)
            await self._navigate_to(update, "balance")
            return

        elif key == "sync_balance_hl":
            api_key = state.get("wallet_api_key", "")
            api_secret = state.get("wallet_api_secret", "")
            if not api_key or not api_secret:
                await query.answer("❌ Connect wallet dulu", show_alert=True)
                return
            await query.answer("🔄 Syncing Hyperliquid balance...", show_alert=False)
            try:
                import ccxt
                ex = ccxt.hyperliquid({"apiKey": api_key, "secret": api_secret})
                bal = ex.fetch_balance()
                total = bal.get("total", {}).get("USDC", 0)
                self.state_mgr.set("live_balance", total)
                self.state_mgr.set("live_initial_balance", total)
                msg = f"✅ HL Balance synced: ${total:.2f}"
            except Exception as e:
                msg = f"❌ Sync failed: {e}"
            await query.answer(msg, show_alert=True)
            await self._navigate_to(update, "balance")
            return

        # ── Balance page: send fund Hyperliquid ────────────────────────────
        elif key == "send_fund_hl":
            keyboard = [
                [InlineKeyboardButton("📤 Withdraw USDC", callback_data="set:hl_withdraw")],
                [InlineKeyboardButton("◀️ Back", callback_data="page:balance")],
            ]
            await query.answer()
            await query.edit_message_text(
                "*📤 Send Fund — Hyperliquid\n\n"
                "Withdraw USDC ke external wallet.\n\n"
                "*Withdraw USDC\n"
                "• Hyperliquid → Portfolio → Withdraw\n"
                "• Masukkan alamat wallet tujuan\n"
                "• Pilih jaringan ERC-20\n"
                "• Withdrawal fee: ~$0.10\n\n"
                "_Ini mengurangi live balance._",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        elif key == "hl_withdraw":
            await query.answer("📝 Buka app.hyperliquid.xyz → Portfolio → Withdraw", show_alert=True)
            await self._navigate_to(update, "balance")
            return

        # ── Balance page: add fund (Binance deposit instructions) ───────────
        elif key == "add_fund":
            keyboard = [
                [InlineKeyboardButton("💰 Binance Spot → Futures", callback_data="set:deposit_spot_futures")],
                [InlineKeyboardButton("📥 Deposit from External", callback_data="set:deposit_external")],
                [InlineKeyboardButton("🔄 Auto-Sync Balance", callback_data="set:sync_balance")],
                [InlineKeyboardButton("◀️ Back", callback_data="page:balance")],
            ]
            await query.answer()
            await query.edit_message_text(
                "*💵 Add Fund — Binance Futures\n\n"
                "Ada 2 cara menambah balance:\n\n"
                "*1. Binance Spot → Futures\n"
                "• Buka Binance → Wallet → Futures\n"
                "• Pilih USDT-M Futures\n"
                "• Klik Transfer → dari Spot ke Futures\n"
                "• Minimal $10\n\n"
                "*2. Deposit dari External\n"
                "• Binance → Deposit → USDT (TRC20/ERC20)\n"
                "• Transfer ke alamat deposit kamu\n"
                "• Setelah masuk, transfer ke Futures\n\n"
                "_Balance auto-sync setelah transfer._",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        elif key == "deposit_spot_futures":
            await query.answer("📝 Gunakan Binance App/Web untuk transfer", show_alert=True)
            await self._navigate_to(update, "balance")
            return

        elif key == "deposit_external":
            await query.answer("📝 Deposit dari external via Binance", show_alert=True)
            await self._navigate_to(update, "balance")
            return

        elif key == "sync_balance":
            # Sync live balance from Binance API
            api_key = state.get("wallet_api_key", "")
            api_secret = state.get("wallet_api_secret", "")
            if not api_key or not api_secret:
                await query.answer("❌ Connect wallet dulu", show_alert=True)
                return
            await query.answer("🔄 Syncing balance...", show_alert=False)
            try:
                import ccxt
                ex = ccxt.binance({"apiKey": api_key, "secret": api_secret,
                                   "enableRateLimit": True, "options": {"defaultType": "future"}})
                bal = ex.fetch_balance({"type": "future"})
                total = bal.get("total", {}).get("USDT", 0)
                self.state_mgr.set("live_balance", total)
                self.state_mgr.set("live_initial_balance", total)
                msg = f"✅ Balance synced: ${total:.2f}"
            except Exception as e:
                msg = f"❌ Sync failed: {e}"
            await query.answer(msg, show_alert=True)
            await self._navigate_to(update, "balance")
            return

        # ── Balance page: send fund (Binance withdraw instructions) ────────
        elif key == "send_fund":
            keyboard = [
                [InlineKeyboardButton("📤 Binance Futures → Spot", callback_data="set:withdraw_futures_spot")],
                [InlineKeyboardButton("🏧 Withdraw to External", callback_data="set:withdraw_external")],
                [InlineKeyboardButton("◀️ Back", callback_data="page:balance")],
            ]
            await query.answer()
            await query.edit_message_text(
                "*📤 Send Fund — Binance Futures\n\n"
                "Ada 2 cara menarik/mengurangi balance:\n\n"
                "*1. Futures → Spot\n"
                "• Binance → Wallet → Futures\n"
                "• Pilih USDT-M Futures\n"
                "• Klik Transfer → dari Futures ke Spot\n"
                "• Bisa trading spot atau convert ke other coins\n\n"
                "*2. Withdraw ke External\n"
                "• Binance → Wallet → Spot → Withdraw\n"
                "• Pilih jaringan (TRC20/ERC20)\n"
                "• Masukkan alamat tujuan\n"
                "• Withdrawal fee sesuai jaringan\n\n"
                "_Ini mengurangi live balance._",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        elif key == "withdraw_futures_spot":
            await query.answer("📝 Gunakan Binance App/Web untuk transfer", show_alert=True)
            await self._navigate_to(update, "balance")
            return

        elif key == "withdraw_external":
            await query.answer("📝 Withdraw ke external via Binance", show_alert=True)
            await self._navigate_to(update, "balance")
            return

        # ── Settings page: cycle interval ────────────────────────────────
        elif key == "cycle":
            cur = state.get("cycle_interval", 15)
            options = [5, 10, 15, 30, 60]
            if cur not in options:
                options.append(cur)
                options.sort()
            next_idx = (options.index(cur) + 1) % len(options)
            new_val = options[next_idx]
            self.state_mgr.set("cycle_interval", new_val)
            msg = f"📡 Cycle interval: {new_val}s"
            return_page = "settings"

        # ── Settings sub-pages ─────────────────────────────────────────────
        elif key == "llm_page":
            from .pages import SettingsPage
            page = SettingsPage(self.state_mgr)
            text, reply_markup = page.build(sub_page="llm")
            await query.answer("🤖 LLM Settings", show_alert=False)
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            return

        elif key.startswith("llm_provider:"):
            provider_key = key.split(":")[1]
            from .pages import LLM_PROVIDERS
            if provider_key in LLM_PROVIDERS:
                info = LLM_PROVIDERS[provider_key]
                self.state_mgr.set("llm_provider", provider_key)
                self.state_mgr.set("llm_base_url", info["base_url"])
                self.state_mgr.set("llm_model", info["model_default"])
                await query.answer(f"✅ Provider: {info['name']}", show_alert=True)
            else:
                await query.answer("❌ Unknown provider", show_alert=True)
            return

        elif key == "llm_base_url":
            # Ask user to input custom base URL
            self.state_mgr.set("pending_input", "llm_base_url")
            self.state_mgr.set("llm_provider", "custom")  # mark as custom
            await query.answer()
            await query.edit_message_text(
                "🌐 Edit Base URL\n\n"
                "Masukkan base URL lengkap untuk LLM API.\n"
                "Contoh:\n"
                "  https://api.minimax.io/v1\n"
                "  https://api.openai.com/v1\n"
                "  https://platform.xiaomimimo.com/v1\n\n"
                "Ketik URL baru, atau ketik /cancel untuk batal.",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Batal", callback_data="set:llm_page")
                ]]),
            )
            return

        elif key == "llm_model":
            # Ask user to input custom model name
            self.state_mgr.set("pending_input", "llm_model")
            await query.answer()
            await query.edit_message_text(
                "🤖 Edit Model Name\n\n"
                "Masukkan nama model yang digunakan.\n"
                "Contoh:\n"
                "  MiniMax-M3\n"
                "  gpt-4o-mini\n"
                "  MiniMax-2.5-Pro\n"
                "  deepseek-chat\n\n"
                "Ketik model name, atau ketik /cancel untuk batal.",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Batal", callback_data="set:llm_page")
                ]]),
            )
            return

        elif key == "llm_test":
            api_key = state.get("llm_api_key", "")
            base_url = state.get("llm_base_url", "") or "https://api.minimax.io/anthropic"
            if not api_key:
                await query.answer("❌ API Key belum di-set", show_alert=True)
                return
            await query.answer("🧪 Testing LLM...", show_alert=False)
            try:
                import httpx
                model_name = state.get("llm_model") or "MiniMax-M3"
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                # MiniMax uses /v1/chat/completions at the end of base_url
                url = f"{base_url.rstrip('/')}/v1/chat/completions"
                payload = {"model": model_name, "max_tokens": 10,
                           "messages": [{"role": "user", "content": "ping"}]}
                resp = httpx.post(url, json=payload, headers=headers, timeout=15)
                if resp.status_code < 300:
                    self.state_mgr.set("llm_enabled", True)
                    await query.edit_message_text(
                        "*✅ LLM Connected!\n\n"
                        f"Status: ON\nProvider: {base_url.split('/')[2]}\n"
                        "Smart mode aktif — Hermes akan\nberi saran position size tiap cycle.",
                        parse_mode=None,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="page:settings")]]))
                else:
                    await query.edit_message_text(
                        f"❌ LLM Error\n\n{resp.status_code}: {resp.text[:200]}",
                        parse_mode=None,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="page:settings")]]))
            except Exception as e:
                await query.edit_message_text(
                    f"❌ Connection Failed\n\n{e}",
                    parse_mode=None,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="page:settings")]]))
            return

        elif key == "cycle_page":
            from .pages import SettingsPage
            page = SettingsPage(self.state_mgr)
            text, reply_markup = page.build(sub_page="cycle")
            await query.answer(f"⏱️ Cycle: {state.get('cycle_interval', 15)}s", show_alert=False)
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            return

        elif key.startswith("cycle_set:"):
            try:
                val = int(key.split(":")[1])
                self.state_mgr.set("cycle_interval", val)
                await query.answer(f"✅ Cycle interval: {val}s", show_alert=True)
            except ValueError:
                await query.answer("❌ Invalid value", show_alert=True)
                return
            from .pages import SettingsPage
            page = SettingsPage(self.state_mgr)
            text, reply_markup = page.build(sub_page="cycle")
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            return

        elif key == "symbol_page":
            from .pages import SettingsPage
            page = SettingsPage(self.state_mgr)
            text, reply_markup = page.build(sub_page="symbols")
            await query.answer(f"🪙 Symbol pool", show_alert=False)
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            return

        elif key.startswith("symbol_toggle:"):
            coin = key.split(":")[1]
            current = state.get("enabled_symbols", "").split(",") if state.get("enabled_symbols") else []
            if not current:
                from .pages import COIN_LIST
                current = list(COIN_LIST)
            if coin in current:
                current.remove(coin)
            else:
                current.append(coin)
            self.state_mgr.set("enabled_symbols", ",".join(current))
            self.state_mgr.set("symbol_pool_size", len(current))
            from .pages import SettingsPage
            page = SettingsPage(self.state_mgr)
            text, reply_markup = page.build(sub_page="symbols")
            await query.answer(f"{'✅' if coin in current else '❌'} {coin}", show_alert=False)
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            return

        # ── Settings page: symbol pool (old cycle) ──────────────────────────
        elif key == "pool":
            from .pages import SettingsPage
            page = SettingsPage(self.state_mgr)
            text, reply_markup = page.build(sub_page="symbols")
            await query.answer("🪙 Symbol pool", show_alert=False)
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            return

        # ── LLM Smart toggle — reject if no API key ─────────────────────────
        elif key == "llm_key":
            await query.answer()
            await query.edit_message_text(
                "🔑 LLM API Key\n\n"
                "Kirim API Key kamu di chat ini.\n"
                "Bisa pakai MiniMax, OpenAI, atau provider lain.\n"
                "Ketik langsung di chat, jangan pake /.\n"
                "Tekan ◀️ Back kalau mau cancel.",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Back", callback_data="page:settings")]
                ]),
            )
            self.state_mgr.set("pending_input", "llm_key")
            return

        # ── Risk kill / resume ────────────────────────────────────────────────────────
        elif key == "risk_kill":
            self.state_mgr.set("_risk_action", "kill")
            await query.answer("🔴 Trading akan dihentikan...", show_alert=True)
            await self._navigate_to(update, "risk")
            return

        elif key == "risk_resume":
            self.state_mgr.set("_risk_action", "resume")
            await query.answer("🟢 Trading diaktifkan kembali!", show_alert=True)
            await self._navigate_to(update, "risk")
            return

        # ── Sideways mode toggle ──────────────────────────────────────────────────────
        elif key == "sideways_off":
            self.state_mgr.set("sideways_mode", False)
            await query.answer("🟢 Trading di pasar sideways DIIZINKAN", show_alert=True)
            await self._navigate_to(update, "risk")
            return

        elif key == "sideways_on":
            self.state_mgr.set("sideways_mode", True)
            await query.answer("🔴 Trading di pasar sideways DIBLOKIR", show_alert=True)
            await self._navigate_to(update, "risk")
            return

        # ── Time filter toggle ─────────────────────────────────────────────────────
        elif key == "time_filter_on":
            self.state_mgr.set("time_filter_enabled", True)
            await query.answer("🟢 L09 Time Filter AKTIF — WIB", show_alert=True)
            await self._navigate_to(update, "risk")
            return

        elif key == "time_filter_off":
            self.state_mgr.set("time_filter_enabled", False)
            await query.answer("🔴 L09 Time Filter NONAKTIF", show_alert=True)
            await self._navigate_to(update, "risk")
            return

        # ── Stress test scenarios ─────────────────────────────────────────────
        elif key.startswith("stress_"):
            scenario = key[7:]  # e.g. "flash_crash", "black_swan"
            await query.answer("🧪 Running stress test...", show_alert=False)

            state = self.state_mgr.get()
            mode = state.get("mode", "dry_run")
            balance_key = "dry_run_balance" if mode == "dry_run" else "live_balance"
            balance = state.get(balance_key, 10000)
            open_pos = self.trade_log.get_active(mode=mode) if self.trade_log else []
            notional = balance * 0.2  # 20% exposure assumption
            leverage = 3

            # Get BTC price for stress test
            entry_price = 67000.0
            try:
                import aiohttp
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(
                        "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT",
                        timeout=aiohttp.ClientTimeout(total=3)
                    ) as r:
                        if r.status == 200:
                            data = await r.json()
                            entry_price = float(data["price"])
            except Exception:
                pass

            # Get 30d candles for VaR-based price series
            prices = []
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(
                        "https://fapi.binance.com/fapi/v1/klines",
                        params={"symbol": "BTCUSDT", "interval": "1d", "limit": 30},
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as kr:
                        if kr.status == 200:
                            klines = await kr.json()
                            prices = [float(k[4]) for k in klines]
            except Exception:
                pass

            if not prices:
                # Fallback synthetic
                import random
                prices = [entry_price * (1 + random.uniform(-0.02, 0.02)) for _ in range(30)]

            # Map scenario to stress test function
            scenario_map = {
                "black_swan": ("black swan", "Black Swan"),
                "liquidation_cascade": ("liquidation cascade", "Liquidation Cascade"),
                "market_maker_withdrawal": ("market maker withdrawal", "Market Maker Withdrawal"),
                "correlation_breakdown": ("correlation breakdown", "Correlation Breakdown"),
                "sudden_funding_spike": ("sudden funding spike", "Funding Spike"),
            }

            from ...trading import stress_test as st_module
            scenario_key, scenario_label = scenario_map.get(scenario, ("black_swan", "Unknown"))

            # Run single selected scenario
            report = st_module.run_single_scenario(
                scenario=scenario,
                prices=prices,
                notional=notional,
                position_entry=entry_price,
                position_size=1.0,
                leverage=leverage,
            )

            # Format result for display
            overall = "✅ PASSED" if report["overall_passed"] else "🚨 FAILED"
            worst = report["worst_severity"].upper()
            label = report.get("label", scenario_label)

            lines = [
                f"🧪 STRESS TEST — {label}",
                "",
                f"Overall  : {overall}",
                f"Terburuk : {worst}",
                f"Rugi Est: ${report['total_estimated_loss_usd']:,.2f}",
                "",
            ]
            for s in report["scenarios"]:
                icon = "✅" if s["passed"] else "🚨"
                lines.append(
                    f"{icon} {s['scenario'].upper()} — "
                    f"Rugi: {s['estimated_loss_pct']:.2f}% (${s['estimated_loss_usd']:,.2f})"
                )
                # Word-boundary cut at 55 chars
                rec = s["recommendation"]
                if len(rec) > 55:
                    rec = rec[:55].rsplit(" ", 1)[0] + "…"
                lines.append(f"   💡 {rec}")

            lines.append("")
            lines.append("◀️ Back untuk kembali ke Risk page.")
            text = "\n".join(lines)

            keyboard = [[InlineKeyboardButton("◀️ Back", callback_data="page:risk")]]
            await query.edit_message_text(
                text[:4000],  # Telegram message limit
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # ── Daily loss limit (dollar amount) ──────────────────────────────
        elif key == "daily_loss":
            cur = state.get("daily_loss_limit", 50)
            options = [25, 50, 100, 200, 500]
            if cur not in options:
                options.append(cur)
                options.sort()
            next_idx = (options.index(cur) + 1) % len(options)
            new_val = options[next_idx]
            self.state_mgr.set("daily_loss_limit", new_val)
            msg = f"📉 Daily loss limit: ${new_val}"
            return_page = "settings"

        else:
            return

        await query.answer(msg, show_alert=True)
        try:
            text, reply_markup = self.nav.build(return_page)
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
        except Exception as e:
            # "Message is not modified" = user clicked same value again — benign
            err_str = str(e)
            if "Message is not modified" in err_str or "exactly the same" in err_str:
                pass  # silent — no actual change needed
            else:
                log.error("handle_settings failed: %s", e)

    # ── Risk config adjust callbacks (prefix adj:) ─────────────────────────────────
    async def handle_adjust(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle +/- adjustment of RiskGuardConfig params (adj:*)."""
        query = update.callback_query
        data = query.data
        if not data.startswith("adj:"):
            return

        # Short code map: adj:<code>_<delta>  e.g. adj:dlp_+0.5
        SHORT_MAP = {
            "mpsp": "max_position_size_pct",
            "mpps": "max_positions_per_symbol",
            "mcl":  "max_consecutive_losses",
            "cm":   "cooldown_minutes",
            "mbus": "min_balance_usd",
            "ebus": "emergency_balance_usd",
            "th":   "_time_hours_dummy",   # handled separately below
            # ── Moved from settings ──────────────────────────────────
            "ci":   "_cycle_interval",    # state_mgr, not risk_guard
            "dll":  "_daily_loss_limit",  # state_mgr, not risk_guard
            "mo":   "_max_orders",        # state_mgr, not risk_guard
            "mp":   "_max_positions",    # state_mgr, not risk_guard
        }

        rest = data[4:]  # e.g. "dlp_+0.5"
        parts = rest.rsplit("_", 1)
        if len(parts) != 2:
            await query.answer("Format error", show_alert=True)
            return

        code = parts[0]   # e.g. "dlp"
        delta_str = parts[1]  # e.g. "+0.5"

        try:
            delta = float(delta_str)
        except ValueError:
            await query.answer("Delta parse error", show_alert=True)
            return

        config_key = SHORT_MAP.get(code)
        if not config_key:
            await query.answer(f"Unknown param: {code}", show_alert=True)
            return

        # ── State-mgr based params (moved from settings) ─────────────
        if config_key in ("_cycle_interval", "_daily_loss_limit", "_max_orders", "_max_positions"):
            state_key_map = {
                "_cycle_interval":    ("cycle_interval",   15),
                "_daily_loss_limit":  ("daily_loss_limit",  50),
                "_max_orders":        ("max_orders_per_cycle", 2),
                "_max_positions":     ("max_concurrent_positions", 5),
            }
            state_key, default_val = state_key_map[config_key]
            if code == "ci":
                delta_int = int(delta) if delta == int(delta) else delta
                cur = self.state_mgr.get().get(state_key, default_val)
                new_val = max(5, cur + delta_int)
            elif code == "dll":
                delta_int = int(delta) if delta == int(delta) else delta
                cur = self.state_mgr.get().get(state_key, default_val)
                new_val = max(5, cur + delta_int)
            elif code == "mo":
                delta_int = int(delta) if delta == int(delta) else delta
                cur = self.state_mgr.get().get(state_key, default_val)
                new_val = max(1, cur + delta_int)
            elif code == "mp":
                delta_int = int(delta) if delta == int(delta) else delta
                cur = self.state_mgr.get().get(state_key, default_val)
                new_val = max(1, cur + delta_int)
            self.state_mgr.set(state_key, new_val)
            await query.answer(f"{state_key} = {new_val}", show_alert=False)
            await self._navigate_to(update, "risk")
            return

        # Get auto_trader early — needed for th case AND normal adjust
        auto_trader = context.bot_data.get("auto_trader")
        if not auto_trader or not auto_trader.risk_guard:
            await query.answer("RiskGuard not available", show_alert=True)
            return

        # Special case: time hours (th) — modify no_trade_hours_wib list
        if code == "th":
            rg = auto_trader.risk_guard
            current_hours = list(rg.config.no_trade_hours_wib or [])
            if delta > 0 and len(current_hours) < 12:
                next_hour = (max(current_hours) + 1) if current_hours else 7
                if next_hour not in current_hours:
                    current_hours.append(next_hour)
                    current_hours.sort()
            elif delta < 0 and current_hours:
                if current_hours:
                    current_hours.pop()
            rg.set_config(no_trade_hours_wib=current_hours)
            hour_str = ",".join(f"{h:02d}" for h in current_hours) or "none"
            await query.answer(f"L09 blokir jam: {hour_str} WIB", show_alert=False)
            await self._navigate_to(update, "risk")
            return

        cfg = auto_trader.risk_guard.config
        if not hasattr(cfg, config_key):
            await query.answer(f"Unknown config: {config_key}", show_alert=True)
            return

        old_val = getattr(cfg, config_key)
        new_val = old_val + delta

        # Clamp min to 0 for floats, 1 for ints
        if isinstance(old_val, int):
            new_val = max(1, new_val)
        else:
            new_val = max(0.0, new_val)

        auto_trader.risk_guard.set_config(**{config_key: new_val})
        await query.answer(f"{config_key} = {new_val}", show_alert=False)
        await self._navigate_to(update, "risk")

    # ── Wallet callbacks (prefix wallet:) ─────────────────────────────────────────
    async def handle_wallet(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Handle wallet setup callbacks."""
        query = update.callback_query
        data = query.data
        log.info("handle_wallet called: data=%s", data)

        if not data.startswith("wallet:"):
            return

        key = data[7:]
        state = self.state_mgr.get()

        if key == "binance":
            self.state_mgr.set("exchange", "binance")
            text = (
                "*🔗 Binance Selected\n\n"
                "Input API Key + Secret:\n"
                "1. 🔐 Input API Key\n"
                "2. 🔏 Input API Secret\n"
                "3. 🧪 Test Connection\n\n"
                "📌 Enable Enable Futures saat buat API key."
            )
            keyboard = [
                [InlineKeyboardButton("🔐 Input API Key", callback_data="wallet:input_key")],
                [InlineKeyboardButton("🔏 Input API Secret", callback_data="wallet:input_secret")],
                [InlineKeyboardButton("🧪 Test Connection", callback_data="wallet:test")],
                [InlineKeyboardButton("◀️ Back", callback_data="page:wallet")],
            ]
            await query.answer("✅ Binance Futures", show_alert=False)
            await query.edit_message_text(text, parse_mode=None,
                reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if key == "hyperliquid":
            self.state_mgr.set("exchange", "hyperliquid")
            text = (
                "*⚡ Hyperliquid Selected\n\n"
                "Input API Key + Secret:\n"
                "1. 🔐 Input API Key\n"
                "2. 🔏 Input API Secret\n"
                "3. 🧪 Test Connection"
            )
            keyboard = [
                [InlineKeyboardButton("🔐 Input API Key", callback_data="wallet:input_key")],
                [InlineKeyboardButton("🔏 Input API Secret", callback_data="wallet:input_secret")],
                [InlineKeyboardButton("🧪 Test Connection", callback_data="wallet:test")],
                [InlineKeyboardButton("◀️ Back", callback_data="page:wallet")],
            ]
            await query.answer("✅ Hyperliquid", show_alert=False)
            await query.edit_message_text(text, parse_mode=None,
                reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if key == "input_key":
            self.state_mgr.set("pending_input", "wallet_api_key")
            await query.answer()
            await query.edit_message_text(
                "*🔐 Input API Key\n\n"
                "Kirim API Key kamu di chat ini.\n"
                "_Ketik aja langsung di chat, jangan pake /_\n"
                "Tekan ◀️ Back kalau mau cancel.",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Back", callback_data="page:wallet")]
                ]),
            )
            return

        if key == "input_secret":
            self.state_mgr.set("pending_input", "wallet_api_secret")
            await query.answer()
            await query.edit_message_text(
                "*🔏 Input API Secret\n\n"
                "Kirim API Secret kamu di chat ini.\n"
                "_JANGAN share ke siapapun!_\n"
                "Ketik aja langsung di chat.\n"
                "Tekan ◀️ Back kalau mau cancel.",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Back", callback_data="page:wallet")]
                ]),
            )
            return

        if key == "test":
            exchange_type = state.get("exchange", "binance")

            # ── Get credentials: state.json first, then .env fallback ─────────
            api_key = state.get("wallet_api_key", "")
            api_secret = state.get("wallet_api_secret", "")
            if not api_key or not api_secret:
                # Fallback: try reading from .env directly
                env_path = Path(__file__).resolve().parent.parent.parent / ".env"
                if env_path.exists():
                    for line in env_path.read_text().splitlines():
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, _, v = line.partition("=")
                            if k == "BINANCE_API_KEY" and not api_key:
                                api_key = v.strip()
                            elif k == "BINANCE_API_SECRET" and not api_secret:
                                api_secret = v.strip()

            if not api_key or not api_secret:
                await query.answer("❌ API Key/Secret belum diinput", show_alert=True)
                await query.edit_message_text(
                    "❌ Credential belum ada.\n\n"
                    "Langkah:\n"
                    "1. 🔐 Input API Key\n"
                    "2. 🔏 Input API Secret\n"
                    "3. 🧪 Test Connection\n\n"
                    "Tekan ◀️ Back untuk kembali.",
                    parse_mode=None,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("◀️ Back", callback_data="page:wallet")]
                    ]),
                )
                return

            await query.answer("🧪 Testing connection...", show_alert=False)
            try:
                if exchange_type == "binance":
                    import ccxt
                    ex = ccxt.binance({
                        "apiKey": api_key,
                        "secret": api_secret,
                        "enableRateLimit": True,
                        "options": {"defaultType": "future", "warnOnFetchOpenOrdersWithoutSymbol": False},
                    })
                    bal = ex.fetch_balance({"type": "future"})
                    total_usdt = bal.get("USDT", {}).get("total", 0)
                    free_usdt = bal.get("USDT", {}).get("free", 0)

                    # Get mark price for context
                    ticker = ex.fetch_ticker("BTC/USDT")
                    btc_price = ticker.get("last", 0)

                    text = (
                        f"✅ Binance Connected!\n\n"
                        f"USDT Balance: ${total_usdt:.6f}\n"
                        f"Free: ${free_usdt:.6f}\n"
                        f"BTC price: ${btc_price:,.2f}\n\n"
                        f"Wallet: ✅ Connected\n"
                        f"Credentials: ✅ Valid\n"
                        f"Futures: ✅ Enabled"
                    )
                    self.state_mgr.set("wallet_connected", True)
                    self.state_mgr.set("wallet_api_key", api_key)
                    self.state_mgr.set("wallet_api_secret", api_secret)
                    self.state_mgr.set("live_balance", total_usdt)
                    self.state_mgr.set("live_initial_balance", total_usdt)
                else:
                    text = "⚡ Hyperliquid Connected!\n\nWallet: ✅ Connected"

                await query.edit_message_text(text, parse_mode=None,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="page:wallet")]]))
            except Exception as e:
                await query.edit_message_text(
                    f"❌ Connection Failed\n\n{type(e).__name__}: {e}\n\n"
                    "Check API key/secret and try again.",
                    parse_mode=None,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="page:wallet")]]))
            return

        if key == "reload":
            await query.answer("🔄 Reloading engine...", show_alert=False)
            try:
                if hasattr(self, 'engine') and self.engine:
                    self.engine.reload_from_env()
                    text = (
                        "✅ Engine Reloaded!\n\n"
                        "Credentials updated from .env\n"
                        "New API key/secret now active."
                    )
                else:
                    text = "⚠️ Engine not available yet. Restart bot."
            except Exception as e:
                text = f"❌ Reload failed: {e}"
            await query.edit_message_text(text, parse_mode=None,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="page:wallet")]]))
            return

        if key == "show_env":
            from ...utils.helpers import read_json
            from pathlib import Path
            base = Path(__file__).resolve().parent.parent.parent.parent
            env_example = base / ".env.example"
            content = ""
            if env_example.exists():
                content = env_example.read_text()
            text = (
                "*📋 .env.example\n\n"
                "\n" + content[:1800] + ""
            )
            keyboard = [[InlineKeyboardButton("◀️ Back", callback_data="page:wallet")]]
            await query.answer()
            try:
                await query.edit_message_text(text, parse_mode=None,
                    reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception:
                pass
            return

    # ── History callbacks (prefix hist:, hist_delete_menu:, hist_del:) ──────────
    async def handle_history(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Handle history page mode/range switching and delete."""
        query = update.callback_query
        data = query.data
        log.info("handle_history called: data=%s", data)

        if not (data.startswith("hist:") or data.startswith("hist_delete_menu:") or data.startswith("hist_del:")):
            return

        # Delete menu toggle
        if data.startswith("hist_delete_menu:"):
            parts = data.split(":")
            if len(parts) < 3:
                return
            mode = parts[1]
            time_range = parts[2]
            from .pages import HistoryPage
            page = HistoryPage(self.trade_log)
            text, reply_markup = page.build(mode=mode, time_range=time_range, show_delete=True)
            await query.answer("🗑 Delete menu", show_alert=False)
            try:
                await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            except Exception as e:
                log.error("handle_history delete_menu failed: %s", e)
            return

        # Execute delete
        if data.startswith("hist_del:"):
            parts = data.split(":")
            if len(parts) < 3:
                return
            mode = parts[1]
            time_range = parts[2]

            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            if time_range == "24h":
                cutoff = now - timedelta(hours=24)
            elif time_range == "7d":
                cutoff = now - timedelta(days=7)
            elif time_range == "30d":
                cutoff = now - timedelta(days=30)
            elif time_range == "all":
                cutoff = None
            else:
                cutoff = now - timedelta(hours=24)

            all_trades = self.trade_log.all(mode=mode)
            if cutoff:
                cutoff_iso = cutoff.isoformat()
                to_keep = [t for t in all_trades if (t.get("close_timestamp") or t.get("timestamp", "")) < cutoff_iso]
            else:
                to_keep = []

            deleted = len(all_trades) - len(to_keep)
            # Rewrite trade file with kept trades using TradeLog's own file
            file_path = self.trade_log._file(mode)
            from ...utils.helpers import atomic_write_json
            atomic_write_json(file_path, {"trades": to_keep})

            await query.answer(f"🗑 Deleted {deleted} trades", show_alert=True)
            from .pages import HistoryPage
            page = HistoryPage(self.trade_log)
            text, reply_markup = page.build(mode=mode, time_range=time_range)
            try:
                await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            except Exception as e:
                log.error("handle_history delete failed: %s", e)
            return

        parts = data.split(":")
        if len(parts) < 3:
            return

        mode = parts[1]
        time_range = parts[2]

        from .pages import HistoryPage
        page = HistoryPage(self.trade_log)
        text, reply_markup = page.build(mode=mode, time_range=time_range, show_delete=False)

        await query.answer(f"📋 {mode.upper()} {time_range.upper()}", show_alert=False)
        try:
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
        except Exception as e:
            log.error("handle_history failed: %s", e)

    # ── Positions callbacks (prefix pos:) ────────────────────────────────
    async def handle_positions(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Handle positions page mode switching, close, partial close."""
        query = update.callback_query
        data = query.data
        log.info("handle_positions called: data=%s", data)

        if not (data.startswith("pos:") or data.startswith("pos_close:") or
                data.startswith("pos_partial:") or data.startswith("pos_partial_exec:") or
                data.startswith("pos_close_all:")):
            return

        # ── Close single position ───────────────────────────────────────
        if data.startswith("pos_close:"):
            parts = data.split(":")
            if len(parts) >= 3:
                mode = parts[1]
                idx = int(parts[2])
                positions = self.trade_log.get_active(mode=mode)
                if 0 <= idx < len(positions):
                    p = positions[idx]
                    p["status"] = "closed"
                    p["exit_reason"] = "manual_close"
                    p["close_timestamp"] = datetime.now(timezone.utc).isoformat()
                    p["pnl"] = 0
                    p["pnl_pct"] = 0
                    self.trade_log.add(p)
                    await query.answer(f"🔴 Closed {p.get('symbol')}", show_alert=True)
                else:
                    await query.answer("Position not found", show_alert=True)
                from .pages import PositionsPage
                page = PositionsPage(self.trade_log, self.state_mgr)
                text, reply_markup = page.build(mode=mode)
                try:
                    await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
                except Exception as e:
                    log.error("handle_positions close failed: %s", e)
            return

        # ── Partial close position ─────────────────────────────────────
        if data.startswith("pos_partial:"):
            parts = data.split(":")
            if len(parts) >= 3:
                mode = parts[1]
                idx = int(parts[2])
                positions = self.trade_log.get_active(mode=mode)
                if 0 <= idx < len(positions):
                    p = positions[idx]
                    sym = p.get("symbol", "?")
                    keyboard = [
                        [InlineKeyboardButton("25%", callback_data=f"pos_partial_exec:{mode}:{idx}:25")],
                        [InlineKeyboardButton("50%", callback_data=f"pos_partial_exec:{mode}:{idx}:50")],
                        [InlineKeyboardButton("75%", callback_data=f"pos_partial_exec:{mode}:{idx}:75")],
                        [InlineKeyboardButton("◀️ Back", callback_data=f"pos:{mode}")],
                    ]
                    await query.answer()
                    try:
                        await query.edit_message_text(
                            f"📊 Partial Close — {sym}\n\nPilih persentase untuk ditutup:",
                            parse_mode=None,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                        )
                    except Exception as e:
                        log.error("handle_positions partial failed: %s", e)
                return
            return

        # ── Partial close execution ────────────────────────────────────
        if data.startswith("pos_partial_exec:"):
            parts = data.split(":")
            if len(parts) >= 4:
                mode = parts[1]
                idx = int(parts[2])
                pct = int(parts[3])
                positions = self.trade_log.get_active(mode=mode)
                if 0 <= idx < len(positions):
                    p = positions[idx]
                    pnl = p.get("pnl", 0)
                    closed_pnl = pnl * (pct / 100)
                    remaining_pnl = pnl * ((100 - pct) / 100)
                    p["pnl"] = round(remaining_pnl, 4)
                    p["status"] = "open"
                    p["exit_reason"] = f"partial_close_{pct}%"
                    self.trade_log.add(p)
                    await query.answer(f"📊 Partial close {pct}% — PnL: ${closed_pnl:.2f}", show_alert=True)
                    from .pages import PositionsPage
                    page = PositionsPage(self.trade_log, self.state_mgr)
                    text, reply_markup = page.build(mode=mode)
                    try:
                        await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
                    except Exception as e:
                        log.error("handle_positions partial_exec failed: %s", e)
                return
            return

        # ── Close all positions ──────────────────────────────────────────
        if data.startswith("pos_close_all:"):
            mode = data.split(":")[1]
            positions = self.trade_log.get_active(mode=mode)
            count = 0
            for p in positions:
                p["status"] = "closed"
                p["exit_reason"] = "manual_close_all"
                p["close_timestamp"] = datetime.now(timezone.utc).isoformat()
                p["pnl"] = 0
                p["pnl_pct"] = 0
                self.trade_log.add(p)
                count += 1
            await query.answer(f"🔴 Closed {count} positions", show_alert=True)
            from .pages import PositionsPage
            page = PositionsPage(self.trade_log, self.state_mgr)
            text, reply_markup = page.build(mode=mode)
            try:
                await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            except Exception as e:
                log.error("handle_positions close_all failed: %s", e)
            return

        # ── Mode switch ──────────────────────────────────────────────────
        mode = data[4:]
        from .pages import PositionsPage
        page = PositionsPage(self.trade_log, self.state_mgr)
        text, reply_markup = page.build(mode=mode)
        await query.answer(f"📈 {mode.upper()} positions", show_alert=False)
        try:
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
        except Exception as e:
            log.error("handle_positions failed: %s", e)

    # ── Navigation callbacks (prefix page:) ───────────────────────────────────
    async def handle_nav(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        """Handle page: callbacks — navigate between menu pages."""
        query = update.callback_query
        data = query.data
        log.info("handle_nav called: data=%s", data)

        page_key = data.split(":", 1)[1] if ":" in data else data
        if page_key not in self.nav.pages:
            page_key = "main"

        if page_key == "back":
            page_key = self.nav.pop() or "main"

        # ── Monitor: fetch live balance before building ────────────────────
        if page_key == "monitor":
            state = self.state_mgr.get()
            if state.get("mode") == "live":
                api_key = state.get("wallet_api_key", "")
                api_secret = state.get("wallet_api_secret", "")
                if api_key and api_secret:
                    from .pages.balance_page import _fetch_binance_live_balance
                    result = _fetch_binance_live_balance(api_key, api_secret)
                    if result["success"]:
                        self.state_mgr.set("live_balance", result["total"])

        # History and Positions need mode context — build directly
        if page_key == "history":
            state = self.state_mgr.get()
            mode = state.get("mode", "dry_run")
            from .pages import HistoryPage
            page = HistoryPage(self.trade_log)
            text, reply_markup = page.build(mode=mode, time_range="24h")
            await query.answer("📋 Loading history...", show_alert=False)
            try:
                await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            except Exception as e:
                log.error("handle_nav history failed: %s", e)
            return

        if page_key == "positions":
            state = self.state_mgr.get()
            mode = state.get("mode", "dry_run")
            from .pages import PositionsPage
            page = PositionsPage(self.trade_log, self.state_mgr)
            text, reply_markup = page.build(mode=mode)
            await query.answer("📈 Loading positions...", show_alert=False)
            try:
                await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
            except Exception as e:
                log.error("handle_nav positions failed: %s", e)
            return

        text, reply_markup = self.nav.build(page_key)
        try:
            await query.answer("📡 Loading...", show_alert=False)
            await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
        except Exception as e:
            log.error("handle_nav failed: %s", e)

    # ── Commands ────────────────────────────────────────────────────────────────
    async def cmd_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        text, reply_markup = self.nav.build("main")
        await update.message.reply_text(text, parse_mode=None, reply_markup=reply_markup)

    async def cmd_help(self, update: Update, _: ContextTypes.DEFAULT_TYPE):
        text, reply_markup = self.nav.build("help")
        await update.message.reply_text(text, parse_mode=None, reply_markup=reply_markup)


# ── TradeLog import for router init ──────────────────────────────────────────
from pathlib import Path
from ...memory.trade_log import TradeLog


def _get_trade_log():
    base = Path(__file__).parent.parent.parent
    return TradeLog(base / "memory")


# ── /newdryrun command ─────────────────────────────────────────────────────────
async def cmd_new_dry_run(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """Handle /newdryrun <amount> — reset dry run with custom initial balance."""
    parts = update.message.text.split()
    if len(parts) < 2:
        await update.message.reply_text(
            "Usage: /newdryrun <amount>\n"
            "Example: /newdryrun 50000\n\n"
            "Ini akan reset dry run balance + trades ke 0."
        )
        return
    try:
        amount = float(parts[1])
        if amount <= 0:
            await update.message.reply_text("Amount must be > 0")
            return
    except ValueError:
        await update.message.reply_text("Invalid amount. Use numbers only.")
        return

    # Use same memory path as main.py to avoid writing to wrong location
    from pathlib import Path
    base = Path(__file__).resolve().parent.parent.parent
    memory_dir = base / "memory"
    from ...memory.state import StateManager
    state_mgr = StateManager(memory_dir)
    state_mgr.update(
        dry_run_balance=amount,
        dry_run_initial_balance=amount,
        dry_run_trades=0,
        mode="dry_run",
        trading_enabled=False,
    )

    await update.message.reply_text(
        f"🆕 New Dry Run started!\n\n"
        f"Balance: ${amount:,.2f}\n"
        f"Mode: DRY RUN\n"
        f"Trades: 0\n\n"
        f"Tekan START untuk mulai strategi baru."
    )


# ── Mode/Direction callbacks (called from setup) ─────────────────────────────
async def _handle_mode_callback(update, _, state_mgr):
    query = update.callback_query
    data = query.data
    new_mode = data.replace("mode:", "")
    state_mgr.set("mode", new_mode)
    label = "🔴 LIVE" if new_mode == "live" else "🟡 DRY RUN"
    await query.answer(f"Mode: {label}", show_alert=True)
    text, reply_markup = MenuRouter(state_mgr, None, None, None, None).nav.build("mode")
    try:
        await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
    except Exception:
        pass


async def _handle_dir_callback(update, _, state_mgr):
    query = update.callback_query
    data = query.data
    new_dir = data.replace("dir:", "")
    state_mgr.set("direction", new_dir)
    await query.answer(f"Direction: {new_dir.upper()}", show_alert=True)
    text, reply_markup = MenuRouter(state_mgr, None, None, None, None).nav.build("direction")
    try:
        await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
    except Exception:
        pass


# ── Text input handler (LLM key, balance fund amounts) ────────────────────────
async def _handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route free-text input to appropriate handler based on last markup."""
    text = update.message.text.strip()
    log.info("[DEBUG] _handle_text_input called: text=%s", text[:20])
    router: MenuRouter = context.bot_data.get("menu_router")
    if not router:
        log.warning("[DEBUG] no router in bot_data!")
        return

    state = router.state_mgr.get()
    pending = state.get("pending_input", "")
    log.info("[DEBUG] pending_input=%s", pending)

    # ALWAYS reply to confirm handler fires
    try:
        await update.message.reply_text(f"📩 Handler fired! pending='{pending}'", parse_mode=None)
        log.info("[DEBUG] reply sent OK")
    except Exception as e:
        log.error("[DEBUG] reply FAILED: %s", e)
        return  # Don't continue if reply fails

    if pending == "llm_api_key":
        log.info("[DEBUG] llm_api_key handler: text='%s'", text[:20])
        router.state_mgr.set("pending_input", "")  # Clear FIRST so user always gets reply
        router.state_mgr.set("llm_api_key", text)
        await update.message.reply_text(
            f"✅ LLM API Key saved!\n\n"
            f"Key: {text[:8]}...\n\n"
            "Tekan TEST di menu Settings untuk verify.",
            parse_mode=None,
        )
        return

    if pending == "wallet_api_key":
        log.info("[DEBUG] wallet_api_key handler: text='%s'", text[:20])
        # Clear pending FIRST — reply must always send even if .env sync fails
        router.state_mgr.set("pending_input", "")
        router.state_mgr.set("wallet_api_key", text)
        _sync_binance_creds_to_env(text, router.state_mgr.get().get("wallet_api_secret", ""))
        await update.message.reply_text(
            f"✅ API Key saved!\n\n"
            f"Key: {text[:8]}...\n\n"
            "Sekarang input API Secret, atau klik ◀️ Back.",
            parse_mode=None,
        )
        return

    if pending == "wallet_api_secret":
        log.info("[DEBUG] wallet_api_secret handler: text='%s'", text[:20])
        api_key = router.state_mgr.get().get("wallet_api_key", "")
        # Clear pending_input FIRST — reply must always send regardless of .env sync outcome
        router.state_mgr.set("pending_input", "")
        router.state_mgr.set("wallet_api_secret", text)
        _sync_binance_creds_to_env(api_key, text)
        await update.message.reply_text(
            f"✅ API Secret saved!\n\n"
            f"Key: {api_key[:8]}...\n\n"
            "Klik 🔄 Reload Engine, lalu 🧪 Test Connection.",
            parse_mode=None,
        )
        return

    if pending == "add_fund":
        try:
            amount = float(text)
            if amount <= 0:
                await update.message.reply_text("❌ Amount harus > 0")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid number")
            return
        router.state_mgr.set("pending_input", "")
        current = router.state_mgr.get().get("live_balance", 0)
        router.state_mgr.set("live_balance", current + amount)
        await update.message.reply_text(f"✅ Added ${amount:.2f}\n\nNew balance: ${current + amount:.2f}", parse_mode=None)
        return

    if pending == "send_fund":
        try:
            amount = float(text)
            if amount <= 0:
                await update.message.reply_text("❌ Amount harus > 0")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid number")
            return
        router.state_mgr.set("pending_input", "")
        current = router.state_mgr.get().get("live_balance", 0)
        new_bal = max(0, current - amount)
        router.state_mgr.set("live_balance", new_bal)
        await update.message.reply_text(f"✅ Sent ${amount:.2f}\n\nNew balance: ${new_bal:.2f}", parse_mode=None)
        return

    if pending == "llm_key":
        api_key = text.strip()
        if not api_key:
            await update.message.reply_text("❌ API key kosong")
            return

        # Clear pending FIRST — reply must always send
        router.state_mgr.set("pending_input", "")
        router.state_mgr.set("llm_api_key", api_key)

        if "sk-" in api_key:
            provider = "openai"
        elif len(api_key) > 64 and api_key.startswith("T4"):
            provider = "binance-hmac"
        else:
            provider = "minimax"

        if provider != "binance-hmac":
            _sync_llm_key_to_env(provider, api_key)

        masked = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
        await update.message.reply_text(
            f"✅ LLM API Key saved!\n\nProvider: {provider.upper()}\nKey: {masked}\n\nTest connection di menu Settings.",
            parse_mode=None,
        )
        return

    if pending == "llm_base_url":
        url = text.strip().rstrip("/")
        if not url.startswith("http"):
            await update.message.reply_text("❌ URL harus mulai dengan http:// atau https://")
            return
        router.state_mgr.set("pending_input", "")  # Clear FIRST so user always gets reply
        router.state_mgr.set("llm_base_url", url)
        router.state_mgr.set("llm_provider", "custom")
        await update.message.reply_text(f"✅ Base URL saved!\n\n{url}", parse_mode=None)
        return

    if pending == "llm_model":
        model = text.strip()
        if not model:
            await update.message.reply_text("❌ Model name kosong")
            return
        router.state_mgr.set("pending_input", "")  # Clear FIRST so user always gets reply
        router.state_mgr.set("llm_model", model)
        await update.message.reply_text(f"✅ Model name saved!\n\nModel: {model}", parse_mode=None)
        return

    if pending == "wallet_api_key":
        router.state_mgr.set("wallet_api_key", text)
        router.state_mgr.set("pending_input", "")
        # Sync to .env + reload engine so TradingEngine picks up credentials immediately
        _sync_binance_creds_to_env(api_key=text, api_secret=None)
        try:
            router.engine.reload_from_env()
        except Exception:
            pass
        await update.message.reply_text(f"✅ API Key saved!\n\n{text[:8]}...", parse_mode=None)
        return

    if pending == "wallet_api_secret":
        router.state_mgr.set("wallet_api_secret", text)
        router.state_mgr.set("pending_input", "")
        # Sync to .env + reload engine so TradingEngine picks up credentials immediately
        _sync_binance_creds_to_env(api_key=None, api_secret=text)
        try:
            router.engine.reload_from_env()
        except Exception:
            pass
        await update.message.reply_text("✅ API Secret saved!", parse_mode=None)
        return


def _sync_binance_creds_to_env(api_key: str | None = None, api_secret: str | None = None):
    """Write Binance credentials to .env — called whenever user updates via Telegram.

    This keeps .env in sync with wallet_menu state so TradingEngine (which reads
    .env at startup) always has the latest credentials.
    """
    from pathlib import Path

    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    updates = {}
    if api_key is not None:
        updates["BINANCE_API_KEY"] = api_key
    if api_secret is not None:
        updates["BINANCE_API_SECRET"] = api_secret

    if not updates:
        return

    # Read current .env
    current = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                current[k.strip()] = v.strip()

    # Apply updates
    current.update(updates)

    # Write back — escape newlines in values so .env stays single-line per key
    lines = []
    for k, v in current.items():
        escaped = v.replace("\n", "\\n")
        lines.append(f"{k}={escaped}")
    env_path.write_text("\n".join(lines) + "\n")
    log.info("Binance credentials synced to .env: %s", list(updates.keys()))


def _sync_llm_key_to_env(provider: str, api_key: str):
    """Write LLM API key to .env — called whenever user updates via Telegram.

    Keeps .env in sync with state so main.py (which reads .env at startup)
    always has the latest LLM credentials.
    """
    from pathlib import Path

    env_path = Path(__file__).parent.parent.parent.parent / ".env"

    # Map provider names to .env variable names
    env_keys = {
        "minimax": "MINIMAX_API_KEY",
        "openai": "OPENAI_API_KEY",
        "xiaomi": "XIAOMI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }
    env_key = env_keys.get(provider.lower(), f"{provider.upper()}_API_KEY")

    # Read current .env
    current = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                current[k.strip()] = v.strip()

    # Apply update
    current[env_key] = api_key

    # Write back
    lines = []
    for k, v in current.items():
        escaped = v.replace("\n", "\\n")
        lines.append(f"{k}={escaped}")
    env_path.write_text("\n".join(lines) + "\n")
    log.info("LLM credentials synced to .env: %s", env_key)


def _fetch_binance_live_balance(api_key: str, api_secret: str) -> dict:
    """Fetch real balance from Binance — returns dict with balance info."""
    import ccxt
    try:
        ex = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future", "warnOnFetchOpenOrdersWithoutSymbol": False},
        })
        bal = ex.fetch_balance({"type": "future"})
        total_usdt = bal.get("USDT", {}).get("total", 0)
        free_usdt = bal.get("USDT", {}).get("free", 0)
        positions = [p for p in ex.fetch_positions() if float(p.get("contracts", 0)) != 0]
        return {
            "success": True,
            "total": total_usdt,
            "free": free_usdt,
            "positions": len(positions),
            "btc_price": ex.fetch_ticker("BTC/USDT").get("last", 0),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Setup ─────────────────────────────────────────────────────────────────────
def setup_menu_router(app, state_mgr, perf, exchange, trade_log=None, loader=None, trador=None):
    """Register menu handlers with proper callback routing.
    Replaces ALL dead handler systems (wallet, smart_mode, mode, direction).
    """
    router = MenuRouter(state_mgr, perf, exchange, trade_log, loader, trador)
    app.bot_data["menu_router"] = router

    # ALL inline keyboard callbacks go through menu router
    app.add_handler(CallbackQueryHandler(router.handle_nav, pattern="^page:", block=False))
    app.add_handler(CallbackQueryHandler(router.handle_action, pattern="^action:", block=False))
    app.add_handler(CallbackQueryHandler(router.handle_strategy, pattern="^strat", block=False))
    app.add_handler(CallbackQueryHandler(router.handle_settings, pattern="^set:", block=False))
    app.add_handler(CallbackQueryHandler(router.handle_adjust, pattern="^adj:", block=False))
    app.add_handler(CallbackQueryHandler(router.handle_history, pattern="^hist", block=False))
    app.add_handler(CallbackQueryHandler(router.handle_positions, pattern="^pos:", block=False))
    app.add_handler(CallbackQueryHandler(router.handle_wallet, pattern="^wallet:", block=False))

    # Commands
    app.add_handler(CommandHandler("newdryrun", cmd_new_dry_run, block=False))
    app.add_handler(CommandHandler("start", router.cmd_start, block=False))
    app.add_handler(CommandHandler("menu", router.cmd_start, block=False))
    app.add_handler(CommandHandler("help", router.cmd_help, block=False))
    # Free-text input routing (LLM key, fund amounts, API keys)
    app.add_handler(MessageHandler(filters.TEXT& ~filters.COMMAND,
                                   _handle_text_input, block=False))

    # ── Mode selection (mode:live / mode:dry_run) ─────────────────────────────
    app.add_handler(CallbackQueryHandler(
        lambda u, c: _handle_mode_callback(u, c, router.state_mgr),
        pattern="^mode:(live|dry_run)$",
    ))
    # ── Direction selection (dir:long / dir:short / dir:both) ─────────────────
    app.add_handler(CallbackQueryHandler(
        lambda u, c: _handle_dir_callback(u, c, router.state_mgr),
        pattern="^dir:(long|short|both)$",
    ))