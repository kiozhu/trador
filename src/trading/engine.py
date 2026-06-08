"""Trading engine — ccxt Binance Futures wrapper"""
import asyncio
from typing import Any

import ccxt

from ..utils.logger import log


class TradingEngine:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.testnet = testnet
        self.exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        if testnet:
            self.exchange.set_sandbox_mode(True)
        log.info("Trading engine init (testnet=%s)", testnet)

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 100) -> list:
        """Fetch OHLCV candles."""
        try:
            data = await asyncio.to_thread(
                self.exchange.fetch_ohlcv, symbol, timeframe, None, limit
            )
            return data
        except Exception as e:
            log.error("Failed to fetch OHLCV %s: %s", symbol, e)
            return []

    async def get_balance(self) -> dict[str, float]:
        try:
            balance = await asyncio.to_thread(self.exchange.fetch_balance)
            futures = balance.get("future", {})
            total = futures.get("total", {}).get("USDT", 0)
            used = futures.get("used", {}).get("USDT", 0)
            free = futures.get("free", {}).get("USDT", 0)
            return {"total": total, "used": used, "free": free, "unrealized_pnl": 0}
        except Exception as e:
            log.error("Failed to fetch balance: %s", e)
            return {"total": 0, "used": 0, "free": 0, "unrealized_pnl": 0}

    async def get_positions(self) -> list[dict]:
        try:
            positions = await asyncio.to_thread(self.exchange.fetch_positions)
            # Filter for active positions with non-zero size
            active = []
            for p in positions:
                size = float(p.get("contracts", 0) or p.get("positionAmt", 0))
                if size != 0:
                    active.append({
                        "symbol": p.get("symbol"),
                        "side": "LONG" if size > 0 else "SHORT",
                        "size": abs(size),
                        "entry_price": float(p.get("entryPrice", 0)),
                        "current_price": float(p.get("markPrice", 0)),
                        "leverage": int(p.get("leverage", 1)),
                        "pnl_usd": float(p.get("unrealizedPnl", 0)),
                        "pnl_pct": float(p.get("percentage", 0)),
                    })
            return active
        except Exception as e:
            log.error("Failed to fetch positions: %s", e)
            return []

    async def place_order(self, symbol: str, side: str, order_type: str,
                         amount: float, price: float | None = None,
                         sl: float | None = None, tp: float | None = None) -> dict:
        try:
            params = {"leverage": 3}  # will be overridden per strategy
            order = await asyncio.to_thread(
                self.exchange.create_order, symbol, order_type, side, amount, price, params
            )
            log.info("Order placed: %s %s %s %s", side, order_type, symbol, amount)
            return order
        except Exception as e:
            log.error("Order failed: %s", e)
            return {}

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        try:
            await asyncio.to_thread(self.exchange.cancel_order, order_id, symbol)
            return True
        except Exception as e:
            log.error("Cancel order failed: %s", e)
            return False

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        try:
            await asyncio.to_thread(
                self.exchange.set_leverage, leverage, symbol
            )
            return True
        except Exception as e:
            log.error("Set leverage failed: %s", e)
            return False