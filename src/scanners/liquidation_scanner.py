"""Liquidation cluster scanner — Binance Futures WebSocket (no API key).

Wss endpoint: wss://fstream.binance.com/stream?streams=<symbol>@forceOrder
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Callable, Optional

import websockets

log = logging.getLogger(__name__)


@dataclass
class LiquidationEvent:
    symbol: str
    side: str          # BUY = long liq, SELL = short liq
    price: float
    quantity: float    # in quote asset (USDT)
    order_type: str
    timestamp: int     # ms


@dataclass
class Cluster:
    """Price cluster of liquidation events."""
    symbol: str
    price_center: float
    side: str          # BUY or SELL
    total_qty: float   # total liquidated in USDT
    event_count: int
    first_seen: datetime
    last_seen: datetime


class LiquidationScanner:
    """
    Subscribes to Binance Futures force-order (liquidation) WebSocket.
    Aggregates events into price clusters.
    Emits callbacks on new significant clusters.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        cluster_threshold_usdt: float = 50_000,
        cluster_width_pct: float = 0.1,
        cluster_ttl_seconds: int = 60,
    ):
        """
        symbols       : list of symbols to monitor, None = all
        cluster_threshold_usdt : min total USDT in cluster to be significant
        cluster_width_pct      : price range (%) to group as same cluster
        cluster_ttl_seconds    : expire clusters after this long
        """
        self.symbols = symbols or [
            "btcusdt", "ethusdt", "bnbusdt", "solusdt",
            "xrpusdt", "adausdt", "dogeusdt", "avaxusdt",
        ]
        self.cluster_threshold = cluster_threshold_usdt
        self.cluster_width_pct = cluster_width_pct
        self.cluster_ttl = timedelta(seconds=cluster_ttl_seconds)

        self._clusters: dict[str, Cluster] = {}   # key = f"{side}:{bucket_key}"
        self._ws: Optional[asyncio.Task] = None
        self._running = False
        self._lock = Lock()

        # callbacks: (cluster: Cluster) -> None
        self._callbacks: list[Callable[[Cluster], None]] = []

    # ── public ────────────────────────────────────────────────────────────────

    def add_callback(self, cb: Callable[[Cluster], None]):
        self._callbacks.append(cb)

    async def start(self):
        """Start WebSocket connection."""
        self._running = True
        self._ws = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        if self._ws:
            self._ws.cancel()
            try:
                await self._ws
            except asyncio.CancelledError:
                pass

    def get_active_clusters(self) -> list[Cluster]:
        """Return all non-expired clusters."""
        now = datetime.now()
        with self._lock:
            expired = [
                k for k, c in self._clusters.items()
                if now - c.last_seen > self.cluster_ttl
            ]
            for k in expired:
                del self._clusters[k]
            return list(self._clusters.values())

    def get_clusters_by_side(self, side: str) -> list[Cluster]:
        return [c for c in self.get_active_clusters() if c.side == side]

    # ── internal ──────────────────────────────────────────────────────────────

    async def _run(self):
        """Connect to combined WebSocket stream for all symbols."""
        streams = "/".join(f"{s}@forceOrder" for s in self.symbols)
        url = f"wss://fstream.binance.com/stream?streams={streams}"

        while self._running:
            try:
                async with websockets.connect(url, ping_interval=30) as ws:
                    log.info("LiquidationScanner: connected to %s", url)
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._process_message(raw)
            except websockets.exceptions.ConnectionClosed:
                log.warning("LiquidationScanner: connection closed, reconnecting in 5s")
                await asyncio.sleep(5)
            except Exception as e:
                log.warning("LiquidationScanner error: %s, reconnecting in 5s", e)
                await asyncio.sleep(5)

    async def _process_message(self, raw: bytes | str):
        try:
            msg = json.loads(raw) if isinstance(raw, bytes) else json.loads(raw)
        except Exception:
            return

        data = msg.get("data")
        if not data:
            return

        ev = self._parse_event(data)
        if ev is None:
            return

        cluster = self._aggregate(ev)
        if cluster and cluster.total_qty >= self.cluster_threshold:
            log.info(
                "🔥 Liquidation cluster: %s %s @ %.4f — total %.0f USDT (%d events)",
                ev.symbol, ev.side, cluster.price_center, cluster.total_qty, cluster.event_count
            )
            for cb in self._callbacks:
                try:
                    cb(cluster)
                except Exception as e:
                    log.error("LiquidationScanner callback error: %s", e)

    def _parse_event(self, data: dict) -> Optional[LiquidationEvent]:
        try:
            return LiquidationEvent(
                symbol=data["symbol"].lower(),
                side=data["side"],          # BUY or SELL
                price=float(data["price"]),
                quantity=float(data["qty"]) * float(data["price"]),  # USDT
                order_type=data["type"],
                timestamp=data["time"],
            )
        except Exception:
            return None

    def _aggregate(self, ev: LiquidationEvent) -> Optional[Cluster]:
        """Add event to cluster, create new cluster if needed."""
        width = ev.price * (self.cluster_width_pct / 100)
        bucket_key = round(ev.price / width) * width

        cluster_key = f"{ev.symbol}:{ev.side}:{bucket_key}"

        with self._lock:
            if cluster_key in self._clusters:
                c = self._clusters[cluster_key]
                c.quantity += ev.quantity
                c.event_count += 1
                c.last_seen = datetime.now()
                # update center as weighted average
                total = c.total_qty + ev.quantity
                c.price_center = (c.price_center * c.total_qty + ev.price * ev.quantity) / total
                c.total_qty = total
                return c
            else:
                now = datetime.now()
                c = Cluster(
                    symbol=ev.symbol,
                    price_center=ev.price,
                    side=ev.side,
                    total_qty=ev.quantity,
                    event_count=1,
                    first_seen=now,
                    last_seen=now,
                )
                self._clusters[cluster_key] = c
                return c

    def cluster_summary(self) -> str:
        """Text summary of current clusters."""
        clusters = self.get_active_clusters()
        if not clusters:
            return "No active liquidation clusters."

        lines = ["🔥 *Liquidation Clusters:*\n"]
        for c in sorted(clusters, key=lambda x: x.total_qty, reverse=True):
            emoji = "🟢" if c.side == "BUY" else "🔴"
            lines.append(
                f"{emoji} {c.side} | {c.total_qty:,.0f} USDT "
                f"@ {c.price_center:.4f} | {c.event_count}x | {c.symbol.upper()}"
            )
        return "\n".join(lines)