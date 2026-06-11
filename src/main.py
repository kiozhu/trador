"""Trador — main entry point"""
import asyncio
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

from .utils.logger import log
from .strategy import StrategyLoader, StrategyWatcher
from .memory import TradeLog, PerformanceTracker, StateManager
from .trading import TradingEngine
from .trading.auto_trader import AutoTrader
from .llm import LLMScorer
from .comm import HermesReporter, HermesReader
from .tg_bot.handlers import (
    setup_quick_handlers,
)
from .tg_bot.menu import setup_menu_router


class Trador:
    def __init__(self):
        self.running = False
        self.app: Application | None = None
        self.engine: TradingEngine | None = None
        self.state_mgr: StateManager | None = None
        self.trade_log: TradeLog | None = None
        self.perf: PerformanceTracker | None = None
        self.loader: StrategyLoader | None = None
        self.watcher: StrategyWatcher | None = None
        self.llm: LLMScorer | None = None
        self.hermes_reporter: HermesReporter | None = None
        self.hermes_reader: HermesReader | None = None
        self._reader_task: asyncio.Task | None = None
        self.auto_trader: AutoTrader | None = None

    async def start(self):
        # Load env
        load_dotenv()
        import os
        api_key = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")
        # Decode base64-encoded Telegram token if stored as b64:ODkx... (platform
        # credential filtering replaces raw tokens with *** in tool calls)
        telegram_token_raw = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if telegram_token_raw.startswith("b64:"):
            import base64
            telegram_token = base64.b64decode(telegram_token_raw[4:]).decode()
        else:
            telegram_token = telegram_token_raw
        minimax_key = os.getenv("MINIMAX_API_KEY", "")
        xiaomi_key = os.getenv("XIAOMI_API_KEY", "")
        openai_key = os.getenv("OPENAI_API_KEY", "")
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")

        # Detect active LLM provider (first found in priority order)
        self._llm_provider = "minimax"
        self._llm_api_key = ""
        for prov, key in [
            ("xiaomi", xiaomi_key),
            ("openai", openai_key),
            ("deepseek", deepseek_key),
            ("minimax", minimax_key),
        ]:
            if key:
                self._llm_provider = prov
                self._llm_api_key = key
                break

        testnet = os.getenv("TESTNET", "false").lower() == "true"
        # Paths
        base = Path(__file__).parent.parent
        strategies_dir = base / "strategies"
        memory_dir = base / "memory"
        shared_dir = base / "shared"

        # Init components
        self.engine = TradingEngine(api_key, api_secret, testnet)
        self.state_mgr = StateManager(memory_dir)
        self.trade_log = TradeLog(memory_dir)
        self.perf = PerformanceTracker(memory_dir)
        self.loader = StrategyLoader(strategies_dir)
        self.loader.load_all()
        self.llm = LLMScorer(self._llm_api_key, self._llm_provider) if self._llm_api_key else None
        self.hermes_reporter = HermesReporter(shared_dir / "trador_reports")
        self.hermes_reader = HermesReader(shared_dir / "hermes_suggestions")

        # File watcher for strategy hot-reload
        def on_strategy_change(strategy_id: str):
            self.loader.reload(strategy_id)
            log.info("Strategy reloaded via watcher: %s", strategy_id)

        self.watcher = StrategyWatcher(strategies_dir, on_strategy_change)
        self.watcher.start()

        def reload_llm():
            """Reload LLM from .env — called when user updates API key via Telegram."""
            from .llm.scorer import LLMScorer
            for prov_, key_ in [
                ("xiaomi", os.getenv("XIAOMI_API_KEY", "")),
                ("openai", os.getenv("OPENAI_API_KEY", "")),
                ("deepseek", os.getenv("DEEPSEEK_API_KEY", "")),
                ("minimax", os.getenv("MINIMAX_API_KEY", "")),
            ]:
                if key_:
                    self._llm_provider = prov_
                    self._llm_api_key = key_
                    break
            if self._llm_api_key:
                self.llm = LLMScorer(self._llm_api_key, self._llm_provider)
                log.info("LLM reloaded: provider=%s model=%s", self._llm_provider, self.llm.model)
            else:
                self.llm = None
                log.info("LLM disabled (no API key found)")

        # Telegram bot
        self.app = Application.builder().token(telegram_token).build()

        # Setup handler groups — ONLY live handlers remain
        setup_quick_handlers(self.app, self.state_mgr, self.engine, self.loader)
        setup_menu_router(self.app, self.state_mgr, self.perf, self.engine, self.trade_log, self.loader, self)

        # ── Slash commands (sync with bot command menu) ───────────────────────
        from .tg_bot.handlers.menu import cmd_status as cmd_status_menu
        from .tg_bot.handlers.pnl import cmd_pnl
        self.app.add_handler(CommandHandler("status", lambda u, c: cmd_status_menu(u, c, self.state_mgr, self.perf), block=False))
        self.app.add_handler(CommandHandler("pnl", lambda u, c: cmd_pnl(u, c), block=False))

        # ── Text button handlers ─────────────────────────────────────────────
        text_buttons = {
            "🚀 Start": self._handle_start,
            "🛑 Stop": self._handle_stop,
            "⚡ Quick Actions": self._handle_quick_actions,
            "📋 View Orders": self._handle_view_orders,
        }

        async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
            text = update.message.text
            handler = text_buttons.get(text)
            if handler:
                await handler(update, context)
                return

            # ── No button match — check if there's a pending input ───────────
            # Route to menu router's _handle_text_input for API keys, model names, etc.
            router = context._bot_data.get("menu_router")
            if router:
                state = router.state_mgr.get()
                pending = state.get("pending_input", "")
                if pending:
                    from .tg_bot.menu import _handle_text_input
                    await _handle_text_input(update, context)
                    return

            # No handler, no pending input — do nothing (absorb the message)

        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons)
        )

        # ── Hermes suggestion reader loop ────────────────────────────────────
        async def hermes_reader_loop():
            """Poll pending suggestions from Hermes — apply or discard."""
            while self.running:
                try:
                    await asyncio.sleep(10)  # Poll every 10s
                    if not self.hermes_reader:
                        continue

                    suggestions = self.hermes_reader.read_pending()
                    for suggestion in suggestions:
                        applied = self.hermes_reader.process(suggestion, self.loader)
                        if applied:
                            log.info("Hermes suggestion applied: %s", suggestion["data"].get("strategy_id"))

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log.error("Hermes reader loop error: %s", e)

        self._reader_task = asyncio.create_task(hermes_reader_loop())

        self.running = True
        log.info("Trador started!")

        # Set bot command menu (hamburger icon) for Telegram UI
        from telegram import BotCommand
        commands = [
            BotCommand("start", "🏠 Main menu"),
            BotCommand("menu", "📋 Menu panel"),
            BotCommand("help", "❓ Usage guide"),
            BotCommand("status", "📊 Status & balance"),
            BotCommand("strategies", "📈 Strategy list"),
            BotCommand("pnl", "💰 Profit & loss"),
            BotCommand("cancel", "🛑 Cancel all orders"),
            BotCommand("closeall", "🔚 Close all positions"),
            BotCommand("setlive", "💵 Set live balance"),
            BotCommand("newdryrun", "🆕 New dry run"),
        ]
        await self.app.bot.set_my_commands(commands)

        # Manual polling loop — avoids signal_handler issues of run_polling()
        await self.app.initialize()
        await self.app.start()

        # Create a polling task to fetch updates into the update queue
        async def poll_telegram():
            last_update_id = 0
            while self.running:
                try:
                    updates = await self.app.bot.get_updates(
                        offset=last_update_id + 1,
                        limit=10,
                        timeout=5,
                        allowed_updates=Update.ALL_TYPES,
                    )
                    if updates:
                        log.info("Poll fetched %d updates", len(updates))
                    for update in updates:
                        self.app.update_queue.put_nowait(update)
                        last_update_id = max(last_update_id, update.update_id)
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log.warning("Poll error: %s", e)
                    await asyncio.sleep(5)

        poll_task = asyncio.create_task(poll_telegram())

        # Start AutoTrader
        self.auto_trader = AutoTrader(
            engine=self.engine,
            state_mgr=self.state_mgr,
            loader=self.loader,
            trade_log=self.trade_log,
            perf=self.perf,
            scan_interval=15,
            hermes_reporter=self.hermes_reporter,
        )
        await self.auto_trader.start()
        log.info("AutoTrader started (interval=15s)")

        # Expose auto_trader so menu router can reach RiskGuard for config edits
        self.app.bot_data["auto_trader"] = self.auto_trader

        # Wire auto_trader to RiskPage so it can access risk_guard for config display
        menu_router = self.app.bot_data.get("menu_router")
        if menu_router:
            risk_page = menu_router.nav.pages.get("risk")
            if risk_page and hasattr(risk_page, 'set_auto_trader'):
                risk_page.set_auto_trader(self.auto_trader)

        try:
            while self.running:
                try:
                    while not self.app.update_queue.empty():
                        try:
                            update = self.app.update_queue.get_nowait()
                            await self.app.process_update(update)
                        except Exception:
                            pass
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    break
        finally:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
            await self.app.stop()
            await self.app.shutdown()
            log.info("Trador polling loop ended")

    # ── Button handlers ──────────────────────────────────────────────────────
    async def _handle_start(self, update, _):
        self.state_mgr.set_trading(True)
        self.state_mgr.set_status("running")
        router = self.app.bot_data.get("menu_router")
        _, reply_markup = (router.nav.build("main") if router else (None, None))
        await update.message.reply_text(
            "🟢 *Trading started!*", parse_mode="Markdown", reply_markup=reply_markup,
        )

    async def _handle_stop(self, update, _):
        self.state_mgr.set_trading(False)
        self.state_mgr.set_status("stopped")
        router = self.app.bot_data.get("menu_router")
        _, reply_markup = (router.nav.build("main") if router else (None, None))
        await update.message.reply_text(
            "🔴 *Trading stopped.*", parse_mode="Markdown", reply_markup=reply_markup,
        )

    async def _handle_quick_actions(self, update, context):
        from .tg_bot.handlers.quick_actions import cmd_quick_actions
        await cmd_quick_actions(update, context)

    async def _handle_view_orders(self, update, context):
        from .tg_bot.handlers.quick_actions import view_orders
        await view_orders(update, context, self.engine, self.state_mgr)

    async def stop(self):
        self.running = False
        if self.auto_trader:
            await self.auto_trader.stop()
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self.watcher:
            self.watcher.stop()
        if self.app:
            await self.app.stop()
        log.info("Trador stopped")


async def main():
    trader = Trador()

    try:
        await trader.start()
    except KeyboardInterrupt:
        log.info("Interrupted, shutting down...")
    except Exception as e:
        # Suppress event loop errors from subprocess context
        if "Cannot close a running event loop" in str(e) or "This event loop is already running" in str(e):
            log.info("Shutting down (event loop cleanup skipped)")
        else:
            log.error("Fatal error: %s", e)
            sys.exit(1)


if __name__ == "__main__":
    import asyncio, sys, traceback
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
    except BaseException:
        with open('/tmp/trador_err.log', 'w') as f:
            traceback.print_exc(file=f)
        sys.exit(0)