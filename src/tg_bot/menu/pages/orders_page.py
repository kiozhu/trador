"""Orders page — list all open orders with cancel functionality."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import MenuPage


class OrdersPage(MenuPage):
    name = "orders"

    def __init__(self, state_mgr=None, engine=None):
        self._state_mgr = state_mgr
        self._engine = engine

    def build(self) -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get() if self._state_mgr else {}
        open_orders = state.get("open_orders", [])

        text = f"📋 OPEN ORDERS ({len(open_orders)})\n\n"

        keyboard = []
        if not open_orders:
            text += "No open orders ✅"
        else:
            for order in open_orders:
                sym = order.get("symbol", "?")
                side = order.get("side", "?")
                qty = order.get("amount", order.get("remaining", "?"))
                price = order.get("price", "?")
                otype = order.get("type", "LIMIT")
                oid = order.get("id", "")[:12]

                text += f"{'📈' if side.upper() in ('BUY', 'LONG') else '📉'} {sym} {side} {qty} @ {price}\n"
                text += f"   {otype} | ID: {oid}\n\n"

                keyboard.append([
                    InlineKeyboardButton(
                        f"❌ Cancel {sym}",
                        callback_data=f"ocancel:{oid}:{sym}"
                    )
                ])

            # Bulk actions
            keyboard.append([
                InlineKeyboardButton("🗑️ Cancel ALL", callback_data="ocancel_all"),
            ])

        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="nav:monitor")])

        return text, InlineKeyboardMarkup(keyboard)


class OrderDetailPage(MenuPage):
    """Single order detail view."""
    name = "order_detail"

    def __init__(self, state_mgr=None, engine=None):
        self._state_mgr = state_mgr
        self._engine = engine

    def build(self, order_id: str = "") -> tuple[str, InlineKeyboardMarkup]:
        state = self._state_mgr.get() if self._state_mgr else {}
        open_orders = state.get("open_orders", [])

        order = None
        for o in open_orders:
            if o.get("id", "") == order_id:
                order = o
                break

        if not order:
            text = "Order not found or already filled/cancelled."
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="nav:orders")]]
        else:
            sym = order.get("symbol", "?")
            side = order.get("side", "?")
            qty = order.get("amount", "?")
            filled = order.get("filled", 0)
            price = order.get("price", "?")
            otype = order.get("type", "LIMIT")
            status = order.get("status", "?")
            created = order.get("datetime", order.get("timestamp", "?"))[:19]

            text = (
                f"📋 ORDER DETAIL\n\n"
                f"Symbol: {sym}\n"
                f"Type: {otype}\n"
                f"Side: {side}\n"
                f"Qty: {qty} | Filled: {filled}\n"
                f"Price: {price}\n"
                f"Status: {status}\n"
                f"Created: {created}"
            )

            keyboard = [
                [InlineKeyboardButton("❌ Cancel Order", callback_data=f"ocancel:{order_id}:{sym}")],
                [InlineKeyboardButton("🔙 Back", callback_data="nav:orders")],
            ]

        return text, InlineKeyboardMarkup(keyboard)