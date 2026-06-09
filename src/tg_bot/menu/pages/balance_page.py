"""Balance page — trade size, risk limits, dry run reset, live balance from exchange."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class BalancePage(MenuPage):
    name = "balance"

    def __init__(self, state_mgr, exchange, trade_log=None):
        self._state_mgr = state_mgr
        self._exchange = exchange
        self._trade_log = trade_log

    def build(self, highlight: str = None) -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get()
        current_mode = state.get("mode", "dry_run")

        # ── Dry Run (from trade_log — source of truth) ─────────────────────
        dr_trades_list = self._trade_log.all(mode="dry_run") if self._trade_log else []
        dr_init = state.get("dry_run_initial_balance", 100)
        dr_bal = state.get("dry_run_balance", 100)
        dr_pnl = dr_bal - dr_init
        dr_pnl_str = f"+{dr_pnl:,.2f}" if dr_pnl >= 0 else f"{dr_pnl:,.2f}"
        dr_pnl_pct = (dr_pnl / dr_init * 100) if dr_init > 0 else 0
        dr_trades = len(dr_trades_list)

        # ── Live (real wallet — from state, synced via wallet) ─────────────
        live_trades_list = self._trade_log.all(mode="live") if self._trade_log else []
        live_bal = state.get("live_balance", 0)
        live_init = state.get("live_initial_balance", 0)
        live_pnl = live_bal - live_init if live_init > 0 else 0
        live_pnl_str = f"+{live_pnl:,.2f}" if live_pnl >= 0 else f"{live_pnl:,.2f}"
        live_trades = len(live_trades_list)

        # ── Trade size settings ─────────────────────────────────────────────
        size_pct = state.get("balance_per_trade_pct", 10)
        max_orders = state.get("max_orders_per_cycle", 2)
        max_pos = state.get("max_concurrent_positions", 5)
        daily_loss_limit = state.get("daily_loss_limit", 50)

        # ── Exchange type ────────────────────────────────────────────────────
        exchange_type = state.get("wallet_exchange", "binance")

        # ── Highlight changed row ──────────────────────────────────────────
        hl = highlight or ""

        def hl_row(label, value, key):
            icon = "👉 " if key == hl else "  "
            return f"{icon}{label}: `{value}`"

        text = (
            f"*💰 BALANCE & RISK*\n\n"
            f"_Mode: `{'DRY RUN' if current_mode == 'dry_run' else 'LIVE'}`_\n\n"

            "──── *DRY RUN* ────\n"
            f"  Balance: `${dr_bal:,.2f}`\n"
            f"  Started: `${dr_init:,.2f}`\n"
            f"  PnL: `{dr_pnl_str}` ({dr_pnl_pct:+.2f}%)\n"
            f"  Trades: `{dr_trades}`\n\n"

            "──── *LIVE ({exchange_type.upper()})* ────\n"
            f"  Balance: `${live_bal:,.2f}` _(sync dari wallet)_\n"
            f"  Started: `${live_init:,.2f}`\n"
            f"  PnL: `{live_pnl_str}`\n"
            f"  Trades: `{live_trades}`\n\n"

            "──── *TRADE SIZE* ────\n"
            f"{hl_row('Size/trade', f'{size_pct}%', 'size')}\n"
            f"{hl_row('Max orders/cycle', str(max_orders), 'max_orders')}\n"
            f"{hl_row('Max open positions', str(max_pos), 'max_pos')}\n\n"

            "──── *RISK LIMITS* ────\n"
            f"{hl_row('Daily loss limit', f'${daily_loss_limit}', 'daily_loss')}\n\n"

            "──── *ACTIONS* ────\n"
            "  🔄 Reset Dry Run → $100\n\n"
            "_Tap setting untuk ubah nilainya._"
        )

        if exchange_type == "hyperliquid":
            keyboard = [
                # Trade size row
                [
                    InlineKeyboardButton(f"📐 Size: {size_pct}%", callback_data="set:size"),
                    InlineKeyboardButton(f"🔢 Orders: {max_orders}", callback_data="set:max_orders"),
                ],
                # Risk row
                [
                    InlineKeyboardButton(f"📊 Max Pos: {max_pos}", callback_data="set:max_pos"),
                    InlineKeyboardButton(f"📉 Loss Limit: ${daily_loss_limit}", callback_data="set:daily_loss"),
                ],
                # Hyperliquid actions
                [
                    InlineKeyboardButton("💰 Add Fund (HL)", callback_data="set:add_fund_hl"),
                    InlineKeyboardButton("📤 Send Fund (HL)", callback_data="set:send_fund_hl"),
                ],
                # Reset row
                [
                    InlineKeyboardButton("🔄 Reset Dry Run → $100", callback_data="set:reset_dry_100"),
                ],
                [InlineKeyboardButton("◀️ Back", callback_data="page:main")],
            ]
        else:
            keyboard = [
                # Trade size row
                [
                    InlineKeyboardButton(f"📐 Size: {size_pct}%", callback_data="set:size"),
                    InlineKeyboardButton(f"🔢 Orders: {max_orders}", callback_data="set:max_orders"),
                ],
                # Risk row
                [
                    InlineKeyboardButton(f"📊 Max Pos: {max_pos}", callback_data="set:max_pos"),
                    InlineKeyboardButton(f"📉 Loss Limit: ${daily_loss_limit}", callback_data="set:daily_loss"),
                ],
                # Binance actions
                [
                    InlineKeyboardButton("💵 Add Fund (Binance)", callback_data="set:add_fund"),
                    InlineKeyboardButton("📤 Send Fund (Binance)", callback_data="set:send_fund"),
                ],
                # Reset row
                [
                    InlineKeyboardButton("🔄 Reset Dry Run → $100", callback_data="set:reset_dry_100"),
                ],
                [InlineKeyboardButton("◀️ Back", callback_data="page:main")],
            ]
        return text, InlineKeyboardMarkup(keyboard)
