"""Trading engine — ccxt Binance Futures wrapper + public OHLCV fallback"""
import asyncio
from typing import Any

import aiohttp
import ccxt

from ..utils.logger import log

# Public Binance Futures API base (no auth needed for market data)
_BINANCE_FUTURES_API = "https://fapi.binance.com/fapi/v1"

# Timeframe map: our format → Binance format
_TF_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "2h": "2h", "4h": "4h",
    "6h": "6h", "8h": "8h", "12h": "12h", "1d": "1d",
    "3d": "3d", "1w": "1w",
}


class TradingEngine:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.testnet = testnet
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        if testnet:
            self.exchange.set_sandbox_mode(True)
        log.info("Trading engine init (testnet=%s)", testnet)

    def reload_credentials(self, api_key: str, api_secret: str):
        """Reload exchange credentials at runtime — for when API key/secret
        is updated via Telegram wallet menu after bot startup.

        CCXT auto-detects Ed25519 vs HMAC-SHA256 based on secret format:
          - Ed25519: secret contains "-----BEGIN PRIVATE KEY-----"
          - HMAC-SHA256: plain hex/base64 string
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        if self.testnet:
            self.exchange.set_sandbox_mode(True)
        log.info("Trading engine credentials reloaded (testnet=%s, ed25519=%s)",
                 self.testnet, "PRIVATE KEY" in api_secret)

    def reload_from_env(self, env_path: str = ".env"):
        """Reload credentials from a .env file — called after wallet menu
        updates .env so the engine picks up new credentials without restart.

        Ed25519 PEM keys are stored with literal \\n (escaped newlines) in .env
        so dotenv can parse them as single-line values. Unescape when loading.
        """
        import os
        from dotenv import dotenv_values
        vals = dotenv_values(env_path)
        api_key = vals.get("BINANCE_API_KEY") or ""
        # Unescape \\n → actual newline for Ed25519 PEM keys
        api_secret = (vals.get("BINANCE_API_SECRET") or "").replace("\\n", "\n")
        self.reload_credentials(api_key, api_secret)

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 100) -> list:
        """Fetch OHLCV candles — multiple public sources with fallback chain.

        Priority:
        1. Binance Futures public klines (fastest, most reliable for futures pairs)
        2. Binance spot public klines (for tokens not on futures)
        3. CoinGecko public OHLCV (last resort, limited timeframes)
        4. Synthetic fallback (only in dry_run mode, logged as warning)
        """
        sym = symbol.replace("/", "")
        tf = _TF_MAP.get(timeframe, timeframe)
        is_dry_run = self.api_key in ("", "dry_run", "test")

        # ── Source 1: Binance Futures public API ──────────────────────────────
        try:
            url = f"{_BINANCE_FUTURES_API}/klines"
            params = {"symbol": sym, "interval": tf, "limit": limit}
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, params=params,
                                    timeout=aiohttp.ClientTimeout(total=4)) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data:
                            log.debug("OHLCV %s %s from Binance Futures", symbol, tf)
                            return [
                                [int(k[0]), float(k[1]), float(k[2]),
                                 float(k[3]), float(k[4]), float(k[5])]
                                for k in data
                            ]
                    elif r.status in (400, 404):
                        # Symbol not available on futures — try spot below
                        log.debug("Not on futures (HTTP %d): %s", r.status, sym)
                    else:
                        raise Exception(f"HTTP {r.status}")
        except Exception as e:
            log.debug("Futures klines failed %s: %s", symbol, e)

        # ── Source 2: Binance Spot public klines ─────────────────────────────
        try:
            spot_url = "https://api.binance.com/api/v3/klines"
            params = {"symbol": sym, "interval": tf, "limit": limit}
            async with aiohttp.ClientSession() as sess:
                async with sess.get(spot_url, params=params,
                                    timeout=aiohttp.ClientTimeout(total=4)) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data:
                            log.debug("OHLCV %s %s from Binance Spot", symbol, tf)
                            return [
                                [int(k[0]), float(k[1]), float(k[2]),
                                 float(k[3]), float(k[4]), float(k[5])]
                                for k in data
                            ]
        except Exception as e:
            log.debug("Spot klines failed %s: %s", symbol, e)

        # ── Source 3: CoinGecko OHLCV (only supports daily) ──────────────────
        if tf in ("1d", "4h", "1h"):
            coingecko_id_map = {
                "BTC/USDT": "bitcoin", "ETH/USDT": "ethereum",
                "SOL/USDT": "solana", "BNB/USDT": "binancecoin",
                "XRP/USDT": "ripple", "ADA/USDT": "cardano",
                "DOGE/USDT": "dogecoin", "AVAX/USDT": "avalanche-2",
                "DOT/USDT": "polkadot", "LINK/USDT": "chainlink",
            }
            cg_id = coingecko_id_map.get(symbol)
            if cg_id:
                try:
                    cg_tf = {"1h": 1, "4h": 7, "1d": 0}.get(tf, 1)
                    cg_url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/ohlc"
                    params = {"vs_currency": "usd", "days": cg_tf}
                    async with aiohttp.ClientSession() as sess:
                        async with sess.get(cg_url, params=params,
                                            timeout=aiohttp.ClientTimeout(total=4)) as r:
                            if r.status == 200:
                                data = await r.json()
                                if data:
                                    # CG returns [timestamp, open, high, low, close]
                                    log.debug("OHLCV %s from CoinGecko", symbol)
                                    return [[int(k[0]) * 1000, float(k[1]),
                                             float(k[2]), float(k[3]),
                                             float(k[4]), 0.0] for k in data]
                except Exception as e:
                    log.debug("CoinGecko OHLCV failed %s: %s", symbol, e)

        # ── Source 4: ccxt authenticated fallback ────────────────────────────
        if not is_dry_run:
            try:
                data = await asyncio.to_thread(
                    self.exchange.fetch_ohlcv, symbol, timeframe, None, limit
                )
                if data:
                    return data
            except Exception as e:
                log.error("ccxt OHLCV failed %s: %s", symbol, e)

        # ── Source 5: Synthetic fallback (dry-run only) ───────────────────────
        if is_dry_run:
            log.warning("Using synthetic candles for %s (dry-run mode)", symbol)
            return await self._synthetic_ohlcv(symbol, tf, limit)
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

    async def place_order(
            self,
            symbol: str,
            side: str,
            order_type: str,
            amount: float,
            price: float | None = None,
            sl_pct: float | None = None,
            tp_pct: float | None = None,
            leverage: int = 3,
        ) -> dict:
            """Place order with proper leverage and SL/TP calculation.

            SL/TP percentages are in PRICE terms (not margin terms).
            With leverage L: a 1% price move = L% margin change.

            Amount: if <= 100, treated as percentage of balance (2.1 = 2.1%).
                   if > 100, treated as absolute quantity (e.g. 0.05 BTC).
            """
            # ── Validate & adjust leverage to exchange max ─────────────────────
            try:
                exchange_info = await asyncio.to_thread(
                    self.exchange.fetch_leverage_tiers, symbol
                )
                # Find max allowed leverage for this symbol's tier
                max_lev = 20  # conservative default
                for tier in (exchange_info or []):
                    if str(symbol).replace("/", "") in str(tier):
                        max_lev = min(max_lev, int(tier.get("maxLeverage", 20)))
                if leverage > max_lev:
                    log.warning("Leverage %d > max %d for %s, capping", leverage, max_lev, symbol)
                    leverage = max_lev
            except Exception:
                pass  # ignore — use requested leverage

            # Convert percentage to actual quantity if amount is a percentage
            # amount <= 100 means it's a % of balance (e.g. 2.1 = 2.1% of balance)
            # amount > 100 means it's an absolute quantity (e.g. 0.05 BTC)
            if amount <= 100:
                bal = await self.get_balance()
                if isinstance(bal, dict):
                    bal_total = bal.get("total", 0) or bal.get("free", 0) or bal.get("USDT", {}).get("total", 0)
                else:
                    bal_total = float(bal) if bal else 0
                if price and price > 0 and bal_total > 0:
                    amount = (bal_total * amount / 100) / price
                else:
                    amount = 0.001  # fallback minimum

            try:
                # Set leverage
                await asyncio.to_thread(self.exchange.set_leverage, leverage, symbol)

                # Build params with reduce-only SL/TP
                params: dict[str, Any] = {
                    "leverage": leverage,
                    "reduceOnly": False,
                }

                # Calculate SL/TP prices from percentage (price terms)
                if sl_pct is not None:
                    sl_pct_price = abs(sl_pct) / leverage  # price movement allowed
                    if side.upper() == "BUY" or side == "LONG":
                        params["stopLossPrice"] = round(price * (1 - sl_pct_price) if price else 0, 8)
                    else:
                        params["stopLossPrice"] = round(price * (1 + sl_pct_price) if price else 0, 8)

                if tp_pct is not None:
                    tp_pct_price = abs(tp_pct) / leverage  # price movement for TP
                    if side.upper() == "BUY" or side == "LONG":
                        params["takeProfitPrice"] = round(price * (1 + tp_pct_price) if price else 0, 8)
                    else:
                        params["takeProfitPrice"] = round(price * (1 - tp_pct_price) if price else 0, 8)

                # Convert LONG/SHORT to BUY/SELL for Binance futures
                if side.upper() == "LONG":
                    order_side = "BUY"
                elif side.upper() == "SHORT":
                    order_side = "SELL"
                else:
                    order_side = side.upper()

                order = await asyncio.to_thread(
                    self.exchange.create_order, symbol, order_type, order_side, amount, price, params
                )
                log.info(
                    "Order placed: %s %s %s %s @ %s, lev=%d, SL=%.4f, TP=%.4f",
                    order_side, order_type, symbol, amount, price, leverage,
                    params.get("stopLossPrice"), params.get("takeProfitPrice"),
                )
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

    async def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        """Get all open orders, optionally filtered by symbol."""
        try:
            # ccxt: fetch_open_orders(symbol, ...)
            fetch = getattr(self.exchange, "fetch_open_orders", None)
            if fetch:
                orders = await asyncio.to_thread(fetch, symbol, limit=100)
                return orders if isinstance(orders, list) else []
            return []
        except Exception as e:
            log.error("Get open orders failed: %s", e)
            return []

    async def cancel_all_orders(self, symbol: str | None = None) -> dict:
        """Cancel all open orders, optionally for a specific symbol."""
        try:
            count = 0
            orders = await self.get_open_orders(symbol)
            for order in orders:
                sym = order.get("symbol", symbol) or ""
                oid = str(order.get("id", ""))
                if oid and sym:
                    ok = await self.cancel_order(oid, sym)
                    if ok:
                        count += 1
            return {"cancelled": count, "failed": len(orders) - count}
        except Exception as e:
            log.error("Cancel all orders failed: %s", e)
            return {"cancelled": 0, "failed": 0, "error": str(e)}

    async def close_position(self, symbol: str, side: str) -> dict:
        """Close an open position using an opposing market order.
        
        Args:
            symbol: e.g. 'BTC/USDT'
            side: 'SHORT' to close a SHORT (needs BUY), 'LONG' to close a LONG (needs SELL)
        Returns:
            dict with 'success' bool and optional 'order' or 'error' key
        """
        try:
            # Determine closing side (opposite of position side)
            close_side = "buy" if side.upper() == "SHORT" else "sell"
            
            # Fetch position info from exchange
            positions = await asyncio.to_thread(
                self.exchange.fetch_positions, [symbol]
            )
            pos_size = 0
            pos_side = None
            for p in positions:
                if p.get("symbol", "").replace("/", "") == symbol.replace("/", ""):
                    size = p.get("contracts", 0) or p.get("size", 0)
                    if size != 0:
                        pos_size = abs(float(size))
                        pos_side = "SHORT" if float(size) < 0 else "LONG"
                        break
            
            if pos_size <= 0:
                return {"success": False, "error": "No open position found"}
            
            # Use correct closing side based on actual position
            close_side = "buy" if pos_side == "SHORT" else "sell"
            
            # Get current price
            try:
                ticker = await asyncio.to_thread(self.exchange.fetch_ticker, symbol)
                price = ticker.get("last", 0)
            except Exception:
                price = None
            
            # Set leverage
            lev = 1
            await asyncio.to_thread(self.exchange.set_leverage, lev, symbol)
            
            # Place closing market order
            order = await asyncio.to_thread(
                self.exchange.create_order,
                symbol,
                "market",
                close_side,
                pos_size,
                price,
                {"reduceOnly": True},
            )
            log.info("Position closed: %s %s %.4f contracts @ %s", 
                     symbol, close_side.upper(), pos_size, price)
            return {"success": True, "order": order}
            
        except Exception as e:
            log.error("Close position %s failed: %s", symbol, e)
            return {"success": False, "error": str(e)}

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        try:
            await asyncio.to_thread(
                self.exchange.set_leverage, leverage, symbol
            )
            return True
        except Exception as e:
            log.error("Set leverage failed: %s", e)
            return False

    # ── Synthetic candles (dry-run only) ────────────────────────────────────────

    async def _synthetic_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list:
        """Generate realistic synthetic candles for dry-run testing."""
        import random
        base_prices = {
            "BTC/USDT": 67000, "ETH/USDT": 3800, "BNB/USDT": 600,
            "SOL/USDT": 170, "XRP/USDT": 0.62, "ADA/USDT": 0.48,
            "DOGE/USDT": 0.14, "AVAX/USDT": 35, "DOT/USDT": 7.5,
            "LINK/USDT": 14, "MATIC/USDT": 0.72, "LTC/USDT": 85,
            "UNI/USDT": 9.5, "ATOM/USDT": 8.2, "ETC/USDT": 26,
            "XLM/USDT": 0.11, "ALGO/USDT": 0.18, "AAVE/USDT": 88,
            "FIL/USDT": 5.5, "APE/USDT": 1.2, "ZEC/USDT": 24,
            "HYPE/USDT": 12, "MKR/USDT": 2800, "NEAR/USDT": 5.5,
        }
        base = base_prices.get(symbol, 100)
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        interval_ms = {
            "1m": 60000, "3m": 180000, "5m": 300000,
            "15m": 900000, "30m": 1800000, "1h": 3600000,
            "2h": 7200000, "4h": 14400000, "1d": 86400000,
        }.get(timeframe, 900000)

        candles = []
        price = base
        for i in range(limit):
            ts = now - (limit - i) * interval_ms
            open_ = round(price, 4)
            high = round(price * (1 + random.uniform(0.002, 0.018)), 4)
            low = round(price * (1 - random.uniform(0.002, 0.018)), 4)
            close = round(price * (1 + random.uniform(-0.01, 0.014)), 4)
            volume = round(random.uniform(50, 800), 2)
            candles.append([ts, open_, high, low, close, volume])
            price = close

        return candles