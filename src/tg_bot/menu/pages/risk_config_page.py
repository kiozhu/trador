"""Risk Configuration Page — edit all 11 risk layer parameters."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from ..core import MenuPage


class RiskConfigPage(MenuPage):
    name = "risk_config"
    back_callback = "page:risk"

    def __init__(self, state_mgr, risk_guard=None):
        self._state_mgr = state_mgr
        self._risk_guard = risk_guard

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        cfg = self._risk_guard.config if self._risk_guard else None

        if cfg is None:
            return "⚙️ Risk Config\n\nRisk guard belum diinisialisasi.", InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Back", callback_data="page:risk")
            ]])

        lines = [
            "⚙️ KONFIGURASI RISK",
            "Edit parameter setiap layer sesuai profil risiko kamu.",
            "",
            "◀️ / ▶️ = kurangi / tambah  step",
            "📝 = simpan nilai baru",
            "",
        ]

        # ── L02: Daily Loss ──────────────────────────────────────────
        lines += [
            "── L02: BATAS RUGI HARIAN ──",
            f"  Limit Rugi Harian : {cfg.daily_loss_limit_pct:.1f}%",
            f"  Cap Profit Harian  : {cfg.daily_profit_limit_pct:.1f}%  (0=off)",
            "",
        ]

        # ── L03: Trade Count ─────────────────────────────────────────
        lines += [
            "── L03: BATAS FREKUENSI TRADE ──",
            f"  Max Trade / Hari    : {cfg.max_trades_per_day}",
            f"  Max Trade / Jam : {cfg.max_trades_per_hour}",
            "",
        ]

        # ── L04: Position Exposure ───────────────────────────────────
        lines += [
            "── L04: UKURAN POSISI ──",
            f"  Max Posisi Terbuka  : {cfg.max_open_positions}",
            f"  Size Maks per Trade : {cfg.max_position_size_pct:.1f}%",
            f"  Total Exposure Maks : {cfg.max_total_exposure_pct:.1f}%",
            "",
        ]

        # ── L05: Symbol Concentration ───────────────────────────────
        lines += [
            "── L05: KONSENTRASI SYMBOL ──",
            f"  Max per Pair       : {cfg.max_positions_per_symbol}",
            "",
        ]

        # ── L07: Drawdown ────────────────────────────────────────────
        lines += [
            "── L07: DRAWDOWN LIMIT ──",
            f"  Max Drawdown        : {cfg.max_drawdown_pct:.1f}%",
            "",
        ]

        # ── L08: Volatility ─────────────────────────────────────────
        lines += [
            "── L08: VOLATILITAS ──",
            f"  ATR Min (choppy)   : {cfg.min_volatility_threshold:.2f}%",
            f"  ATR Max (extreme)  : {cfg.max_volatility_threshold:.2f}%",
            "",
        ]

        # ── L10: Balance Floor ────────────────────────────────────────
        lines += [
            "── L10: BALANCE FLOOR ──",
            f"  Min Balance         : ${cfg.min_balance_usd:.0f}",
            f"  Emergency Floor : ${cfg.emergency_balance_usd:.0f}",
            "",
        ]

        # ── L11: Regime ──────────────────────────────────────────────
        lines += [
            "── L11: REGIME ALIGNMENT ──",
            f"  Blocked Regimes    : {cfg.blocked_regimes or 'tidak ada'}",
            "",
        ]

        text = "\n".join(lines)

        keyboard = [
            # L02
            [InlineKeyboardButton("➖ Rugi Harian", callback_data="adj:risk_daily_loss_limit_pct_-0.5"),
             InlineKeyboardButton("➕ Rugi Harian", callback_data="adj:risk_daily_loss_limit_pct_+0.5")],
            [InlineKeyboardButton("➖ Profit Cap", callback_data="adj:risk_daily_profit_limit_pct_-1"),
             InlineKeyboardButton("➕ Profit Cap", callback_data="adj:risk_daily_profit_limit_pct_+1")],
            # L03
            [InlineKeyboardButton("➖ /Hari", callback_data="adj:risk_max_trades_per_day_-2"),
             InlineKeyboardButton("➕ /Hari", callback_data="adj:risk_max_trades_per_day_+2")],
            [InlineKeyboardButton("➖ /Jam", callback_data="adj:risk_max_trades_per_hour_-1"),
             InlineKeyboardButton("➕ /Jam", callback_data="adj:risk_max_trades_per_hour_+1")],
            # L04
            [InlineKeyboardButton("➖ Max Posisi", callback_data="adj:risk_max_open_positions_-1"),
             InlineKeyboardButton("➕ Max Posisi", callback_data="adj:risk_max_open_positions_+1")],
            [InlineKeyboardButton("➖ Size%", callback_data="adj:risk_max_position_size_pct_-2"),
             InlineKeyboardButton("➕ Size%", callback_data="adj:risk_max_position_size_pct_+2")],
            [InlineKeyboardButton("➖ Exposure%", callback_data="adj:risk_max_total_exposure_pct_-5"),
             InlineKeyboardButton("➕ Exposure%", callback_data="adj:risk_max_total_exposure_pct_+5")],
            # L05
            [InlineKeyboardButton("➖ Max/Pair", callback_data="adj:risk_max_positions_per_symbol_-1"),
             InlineKeyboardButton("➕ Max/Pair", callback_data="adj:risk_max_positions_per_symbol_+1")],
            # L07
            [InlineKeyboardButton("➖ Drawdown%", callback_data="adj:risk_max_drawdown_pct_-1"),
             InlineKeyboardButton("➕ Drawdown%", callback_data="adj:risk_max_drawdown_pct_+1")],
            # L08
            [InlineKeyboardButton("➖ ATR Min", callback_data="adj:risk_min_volatility_threshold_-0.1"),
             InlineKeyboardButton("➕ ATR Min", callback_data="adj:risk_min_volatility_threshold_+0.1")],
            [InlineKeyboardButton("➖ ATR Max", callback_data="adj:risk_max_volatility_threshold_-0.5"),
             InlineKeyboardButton("➕ ATR Max", callback_data="adj:risk_max_volatility_threshold_+0.5")],
            # L10
            [InlineKeyboardButton("➖ Min Balance", callback_data="adj:risk_min_balance_usd_-10"),
             InlineKeyboardButton("➕ Min Balance", callback_data="adj:risk_min_balance_usd_+10")],
            [InlineKeyboardButton("➖ Emergency", callback_data="adj:risk_emergency_balance_usd_-5"),
             InlineKeyboardButton("➕ Emergency", callback_data="adj:risk_emergency_balance_usd_+5")],
            # Back
            [InlineKeyboardButton("◀️ Back", callback_data="page:risk")],
        ]

        return text, InlineKeyboardMarkup(keyboard)
