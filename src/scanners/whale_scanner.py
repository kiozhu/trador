"""Whale trade scanner — DexScreener API + Binance Futures WebSocket.

Detects large trades (> $50K) from:
  • Binance Futures trade stream (wss://fstream.binance.com/stream?streams=<symbol>@trade)
  • DexScreener recent trades API (no auth required)

No API keys needed.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Callable, Optional

import websockets

log = logging.getLogger(__name__)

WHALE_THRESHOLD_USDT = 50_000


@dataclass
class WhaleTradeEvent:
    symbol: str
    side: str          # BUY or SELL
    price: float
    quantity: float    # base asset quantity
    quote_quantity: float  # USDT notional
    is_buyer_maker: bool
    trade_time: int    # ms
    source: str        # 'binance' or 'dexscreener'


@dataclass
class WhaleCluster:
    """Aggregated whale activity for a symbol."""
    symbol: str
    side: str          # BUY or SELL
    total_quote_qty: float   # total USDT
    trade_count: int
    avg_price: float
    first_seen: datetime
    last_seen: datetime


class WhaleScanner:
    """
    Monitors large trades (> $50K notional) from:
1. Binance Futures WebSocket trade stream
      2. DexScreener /dex Vinci/recent-trades endpoint

    Calls registered callbacks with WhaleTradeEvent on each whale trade.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        threshold_usdt: float = WHALE_THRESHOLD_USDT,
        cluster_ttl_seconds: int = 60,
    ):
        """
        symbols         : list of symbols to monitor, None = defaults
        threshold_usdt  : min USDT notional to be considered a whale trade
        cluster_ttl_seconds : expire clusters after this long
        """
        self.symbols = symbols or [
            "btcusdt", "ethusdt", "bnbusdt", "solusdt",
            "xrpusdt", "adausdt", "dogeusdt", "avaxusdt",
        ]
        self.threshold = threshold_usdt
        self.cluster_ttl_seconds = cluster_ttl_seconds

        self._clusters: dict[str, WhaleCluster] = {}
        self._ws_binance: Optional[asyncio.Task] = None
        self._dex_task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = Lock()

        # callbacks: (WhaleTradeEvent) -> None
        self._callbacks: list[Callable[[WhaleTradeEvent], None]] = []

    # ── public ────────────────────────────────────────────────────────────────

    def add_callback(self, cb: Callable[[WhaleTradeEvent], None]):
        self._callbacks.append(cb)

    async def start(self):
        """Start Binance WS and DexScreener polling."""
        self._running = True
        self._ws_binance = asyncio.create_task(self._run_binance())
        self._dex_task = asyncio.create_task(self._run_dexscreener())

    async def stop(self):
        self._running = False
        for task in (self._ws_binance, self._dex_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    def get_active_clusters(self) -> list[WhaleCluster]:
        """Return all non-expired clusters."""
        now = datetime.now()
        with self._lock:
            expired = [
                k for k, c in self._clusters.items()
                if (now - c.last_seen).total_seconds() > self.cluster_ttl_seconds
            ]
            for k in expired:
                del self._clusters[k]
            return list(self._clusters.values())

    def get_clusters_by_side(self, side: str) -> list[WhaleCluster]:
        return [c for c in self.get_active_clusters() if c.side == side]

    # ── Binance Futures WebSocket ────────────────────────────────────────────

    async def _run_binance(self):
        """Connect to Binance Futures trade stream."""
        streams = "/".join(f"{s}@trade" for s in self.symbols)
        url = f"wss://fstream.binance.com/stream?streams={streams}"

        while self._running:
            try:
                async with websockets.connect(url, ping_interval=30) as ws:
                    log.info("WhaleScanner[Binance]: connected to %s", url)
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._process_binance_message(raw)
            except websockets.exceptions.ConnectionClosed:
                log.warning("WhaleScanner[Binance]: connection closed, reconnecting in 5s")
                await asyncio.sleep(5)
            except Exception as e:
                log.warning("WhaleScanner[Binance] error: %s, reconnecting in 5s", e)
                await asyncio.sleep(5)

    async def _process_binance_message(self, raw: bytes | str):
        try:
            msg = json.loads(raw) if isinstance(raw, bytes) else json.loads(raw)
        except Exception:
            return

        data = msg.get("data")
        if not data:
            return

        ev = self._parse_binance_trade(data)
        if ev is None:
            return

        if ev.quote_quantity >= self.threshold:
            await self._emit_whale(ev)

    def _parse_binance_trade(self, data: dict) -> Optional[WhaleTradeEvent]:
        try:
            return WhaleTradeEvent(
                symbol=data["s"].lower(),
                side="SELL" if data["m"] else "BUY",  # m = buyer is maker
                price=float(data["p"]),
                quantity=float(data["q"]),
                quote_quantity=float(data["q"]) * float(data["p"]),
                is_buyer_maker=data["m"],
                trade_time=data["T"],
                source="binance",
            )
        except Exception:
            return None

    # ── DexScreener polling ───────────────────────────────────────────────────

    async def _run_dexscreener(self):
        """Poll DexScreener recent trades for each symbol every 10s."""
        while self._running:
            try:
                await self._poll_dexscreener()
            except Exception as e:
                log.warning("WhaleScanner[DexScreener] error: %s", e)
            await asyncio.sleep(10)

    async def _poll_dexscreener(self):
        """Fetch recent trades from DexScreener for tracked symbols."""
        for symbol in self.symbols:
            if not self._running:
                break
            try:
                # DexScreener API: fetch recent trades for pair
                url = f"https://api.dexscreener.com/dex/v1/trades?chain=bsc&tokenSymbol={symbol.upper().replace('USDT', '')}"
                async with asyncio.timeout(10):
                    async with websockets.connect(url) as ws:
                        raw = await ws.recv()
                self._process_dexscreener_message(raw, symbol)
            except Exception as e:
                # DexScreener may not have the pair; skip silently
                log.debug("WhaleScanner[DexScreener] no data for %s: %s", symbol, e)

    def _process_dexscreener_message(self, raw: bytes | str, symbol: str):
        """Parse DexScreener trades and emit whale events."""
        try:
            data = json.loads(raw) if isinstance(raw, bytes) else json.loads(raw)
        except Exception:
            return

        trades = data.get("trades") or []
        for t in trades:
            try:
                ev = WhaleTradeEvent(
                    symbol=symbol,
                    side=t.get("side", "").upper(),
                    price=float(t.get("price", 0)),
                    quantity=float(t.get("quantity", 0)),
                    quote_quantity=float(t.get("quoteQuantity", 0)),
                    is_buyer_maker=t.get("isBuyerMaker", False),
                    trade_time=int(t.get("timestamp", 0)),
                    source="dexscreener",
                )
            except Exception:
                continue

            if ev.quote_quantity >= self.threshold:
                asyncio.create_task(self._emit_whale(ev))

    # ── internal ──────────────────────────────────────────────────────────────

    async def _emit_whale(self, ev: WhaleTradeEvent):
        """Update cluster and fire callbacks."""
        cluster_key = f"{ev.symbol}:{ev.side}"
        now = datetime.now()

        with self._lock:
            if cluster_key in self._clusters:
                c = self._clusters[cluster_key]
                total = c.total_quote_qty + ev.quote_quantity
                c.total_quote_qty = total
                c.trade_count += 1
                c.avg_price = (c.avg_price * c.total_quote_qty + ev.price * ev.quote_quantity) / total
                c.last_seen = now
            else:
                self._clusters[cluster_key] = WhaleCluster(
                    symbol=ev.symbol,
                    side=ev.side,
                    total_quote_qty=ev.quote_quantity,
                    trade_count=1,
                    avg_price=ev.price,
                    first_seen=now,
                    last_seen=now,
                )

        log.info(
            "🐋 Whale trade: %s %s | %.2f USDT @ %.4f | %s",
            ev.symbol.upper(), ev.side, ev.quote_quantity, ev.price, ev.source
        )
        for cb in self._callbacks:
            try:
                cb(ev)
            except Exception as e:
                log.error("WhaleScanner callback error: %s", e)

    def summary_text(self) -> str:
        """Telegram-ready text summary of current whale clusters."""
        clusters = self.get_active_clusters()
        if not clusters:
            return "🐋 No active whale clusters."

        lines = ["🐋 *Whale Clusters:*\n"]
        for c in sorted(clusters, key=lambda x: x.total_quote_qty, reverse=True):
            emoji = "🟢" if c.side == "BUY" else "🔴"
            lines.append(
                f"{emoji} {c.side} | {c.total_quote_qty:,.0f} USDT "
                f"@ {c.avg_price:.4f} | {c.trade_count}x | {c.symbol.upper()}"
            )
        return "\n".join(lines)
