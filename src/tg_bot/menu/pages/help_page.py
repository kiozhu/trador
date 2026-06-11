"""Help page — synced with actual menu structure."""
from telegram import InlineKeyboardMarkup

from ..core import MenuPage, make_back_button


class HelpPage(MenuPage):
    name = "help"
    back_callback = "main"

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        text = (
            "❓ TRADOR HELP\n\n"

            "🚀 Start/Stop Trading\n"
            "  Start: mulai auto trading (dry run langsung,\n"
            "  live minta konfirmasi dulu)\n"
            "  Stop: hentikan + konfirmasi jika live\n\n"

            "📡 Status\n"
            "  Overview bot: balance, positions, win rate,\n"
            "  active strategies, regime\n\n"

            "📈 Positions\n"
            "  Lihat open positions per mode\n"
            "  Toggle dry_run / live\n\n"

            "📋 History\n"
            "  Trade history dengan filter 24h/7d/30d/all\n"
            "  Win rate, PnL, exit reason\n\n"

            "📊 Strategy\n"
            "  Multi-strategy: tap untuk toggle aktif/nonaktif\n"
            "  Semua strategi aktif di-eval setiap cycle\n\n"

            "💰 Balance\n"
            "  Trade size, max orders, max positions,\n"
            "  daily loss limit\n\n"

            "🎮 Mode\n"
            "  DRY RUN: simulated trading\n"
            "  LIVE: real money (butuh wallet connected)\n\n"

            "🧠 Smart Mode\n"
            "  Rule-based scoring — tidak pakai LLM\n"
            "  LLM Smart: Hermes kasih saran position size\n"
            "  Fixed: % fixed dari balance\n\n"

            "🔗 Wallet\n"
            "  Connect exchange (Binance / Hyperliquid)\n"
            "  Input API Key + Secret, test connection\n"
            "  Untuk live trading\n\n"

            "⚡ Quick Actions\n"
            "  Cancel all: batalkan semua order\n"
            "  Close all: tutup semua posisi\n\n"

            "📡 Monitor\n"
            "  Real-time: scanner states, open positions,\n"
            "  recent trades, settings sync\n\n"

            "⚙️ Settings\n"
            "  Konfigurasi umum (LLM, cycle interval,\n"
            "  symbol pool, daily loss limit)\n"
            "  Trade size ada di Balance, bukan di sini"
        )
        keyboard = make_back_button("main")
        return text, InlineKeyboardMarkup(keyboard)