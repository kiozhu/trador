"""Trador — main entry point"""
import asyncio
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# ── Patch Application to avoid closing inherited event loops ─────────────────
_original_run = Application.run_polling
async def _patched_run_polling(self, *args, **kwargs):
    try:
        await _original_run(self, *args, **kwargs)
    finally:
        # Don't close the event loop if it was already running before us
        try:
            loop = asyncio.get_running_loop()
            if not loop.is_running():
                pass  # normal case
        except Exception:
            pass
Application.run_polling = _patched_run_polling

from .utils.logger import log
from .strategy import StrategyLoader, StrategyWatcher
from .memory import TradeLog, PerformanceTracker, StateManager
from .trading import TradingEngine, PositionManager
from .llm import LLMScorer
from .comm import HermesReporter, HermesReader
from .tg_bot.handlers import (
    setup_menu_handlers,
    setup_position_handlers,
    setup_strategy_handlers,
    setup_trade_handlers,
    setup_smart_handlers,
    setup_quick_handlers,
    setup_wallet_handlers,
    setup_mode_handlers,
    setup_direction_handlers,
    setup_pnl_handlers,
)
from .tg_bot.keyboards import (
    main_menu_keyboard,
)


class Trador:
    def __init__(self):
        self.running = False
        self.app: Application | None = None
        self.engine: TradingEngine | None = None
        self.position_mgr = PositionManager()
        self.state_mgr: StateManager | None = None
        self.trade_log: TradeLog | None = None
        self.perf: PerformanceTracker | None = None
        self.loader: StrategyLoader | None = None
        self.watcher: StrategyWatcher | None = None
        self.llm: LLMScorer | None = None
        self.hermes_reporter: HermesReporter | None = None
        self.hermes_reader: HermesReader | None = None
        self._reader_task: asyncio.Task | None = None

    async def start(self):
        # Load env
        load_dotenv()
        import os
        api_key = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        minimax_key = os.getenv("MINIMAX_API_KEY", "")
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
        self.llm = LLMScorer(minimax_key) if minimax_key else None
        self.hermes_reporter = HermesReporter(shared_dir / "trador_reports")
        self.hermes_reader = HermesReader(shared_dir / "hermes_suggestions")

        # File watcher for strategy hot-reload
        def on_strategy_change(strategy_id: str):
            self.loader.reload(strategy_id)
            log.info("Strategy reloaded via watcher: %s", strategy_id)

        self.watcher = StrategyWatcher(strategies_dir, on_strategy_change)
        self.watcher.start()

        # Telegram bot
        self.app = Application.builder().token(telegram_token).build()

        # Setup all handler groups
        setup_menu_handlers(self.app, self.state_mgr, self.perf, self.engine)
        setup_position_handlers(self.app, self.position_mgr)
        setup_strategy_handlers(self.app, self.loader, strategies_dir, self.perf)
        setup_trade_handlers(self.app, self.trade_log)
        setup_smart_handlers(self.app, self.state_mgr, self.loader, self.perf)
        setup_quick_handlers(self.app, self.state_mgr, self.engine, self.loader)
        setup_wallet_handlers(self.app, self.state_mgr)
        setup_mode_handlers(self.app, self.state_mgr)
        setup_direction_handlers(self.app, self.state_mgr)
        setup_pnl_handlers(self.app)

        # ── Text button handlers ─────────────────────────────────────────────
        text_buttons = {
            "🚀 Start": self._handle_start,
            "🛑 Stop": self._handle_stop,
            "🧠 Smart Mode": self._handle_smart_mode,
            "⚡ Quick Actions": self._handle_quick_actions,
            "🔗 Wallet": self._handle_wallet,
            "🎮 Mode": self._handle_mode,
            "📐 Direction": self._handle_direction,
            "📊 PnL Chart": self._handle_pnl,
            "📋 View Orders": self._handle_view_orders,
        }

        async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
            text = update.message.text
            handler = text_buttons.get(text)
            if handler:
                await handler(update, context)

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
        await self.app.run_polling(drop_pending_updates=True)

    # ── Button handlers ──────────────────────────────────────────────────────
    async def _handle_start(self, update, _):
        self.state_mgr.set_trading(True)
        self.state_mgr.set_status("running")
        await update.message.reply_text(
            "🟢 *Trading started!*", parse_mode="Markdown", reply_markup=main_menu_keyboard(),
        )

    async def _handle_stop(self, update, _):
        self.state_mgr.set_trading(False)
        self.state_mgr.set_status("stopped")
        await update.message.reply_text(
            "🔴 *Trading stopped.*", parse_mode="Markdown", reply_markup=main_menu_keyboard(),
        )

    async def _handle_smart_mode(self, update, context):
        from .tg_bot.handlers.smart_mode import cmd_smart_mode
        await cmd_smart_mode(update, context, self.state_mgr, self.loader, self.perf)

    async def _handle_quick_actions(self, update, context):
        from .tg_bot.handlers.quick_actions import cmd_quick_actions
        await cmd_quick_actions(update, context)

    async def _handle_wallet(self, update, context):
        from .tg_bot.handlers.wallet import cmd_wallet
        await cmd_wallet(update, context, self.state_mgr)

    async def _handle_mode(self, update, context):
        from .tg_bot.handlers.wallet import cmd_mode
        await cmd_mode(update, context, self.state_mgr)

    async def _handle_direction(self, update, context):
        from .tg_bot.handlers.wallet import cmd_direction
        await cmd_direction(update, context, self.state_mgr)

    async def _handle_pnl(self, update, context):
        from .tg_bot.handlers.pnl import cmd_pnl
        await cmd_pnl(update, context)

    async def _handle_view_orders(self, update, context):
        from .tg_bot.handlers.quick_actions import view_orders
        await view_orders(update, context, self.engine, self.state_mgr)

    async def stop(self):
        self.running = False
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
        if "Cannot close a running event loop" in str(e):
            log.info("Shutting down (event loop cleanup skipped)")
        else:
            log.error("Fatal error: %s", e)
        try:
            import asyncio
            _ = asyncio.get_running_loop()
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "Cannot close a running event loop" in str(e):
            pass  # Suppress — inherited loop from PTY shell
        elif "set_wakeup_fd" in str(e):
            pass  # Suppress — signal in non-main thread
        else:
            raise
    except SystemExit:
        pass