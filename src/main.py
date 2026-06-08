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
from .trading import TradingEngine, PositionManager
from .llm import LLMScorer
from .comm import HermesReporter, HermesReader
from .telegram.handlers import (
    setup_menu_handlers,
    setup_position_handlers,
    setup_strategy_handlers,
    setup_trade_handlers,
)
from .telegram.keyboards import main_menu_keyboard


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

        # File watcher
        def on_strategy_change(strategy_id: str):
            self.loader.reload(strategy_id)
            log.info("Strategy reloaded via watcher: %s", strategy_id)

        self.watcher = StrategyWatcher(strategies_dir, on_strategy_change)
        self.watcher.start()

        # Telegram bot
        self.app = Application.builder().token(telegram_token).build()

        # Setup handlers
        setup_menu_handlers(self.app, self.state_mgr, self.perf, self.engine)
        setup_position_handlers(self.app, self.position_mgr)
        setup_strategy_handlers(self.app, self.loader, strategies_dir)
        setup_trade_handlers(self.app, self.trade_log)

        # Start/Stop text handlers
        @self.app.on_message(filters.TEXT & ~filters.COMMAND)
        async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
            text = update.message.text
            if text == "🚀 Start":
                self.state_mgr.set_trading(True)
                self.state_mgr.set_status("running")
                await update.message.reply_text("🟢 Trading started!",
                                               reply_markup=main_menu_keyboard())
            elif text == "🛑 Stop":
                self.state_mgr.set_trading(False)
                self.state_mgr.set_status("stopped")
                await update.message.reply_text("🔴 Trading stopped.",
                                               reply_markup=main_menu_keyboard())

        self.running = True
        log.info("Trador started!")
        await self.app.run_polling(drop_pending_updates=True)

    async def stop(self):
        self.running = False
        if self.watcher:
            self.watcher.stop()
        if self.app:
            await self.app.stop()
        log.info("Trador stopped")


async def main():
    trader = Trador()

    def signal_handler(sig, frame):
        log.info("Received signal %s, shutting down...", sig)
        asyncio.create_task(trader.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await trader.start()
    except Exception as e:
        log.error("Fatal error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())