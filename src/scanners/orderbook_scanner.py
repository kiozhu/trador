"""Orderbook wall scanner — Binance WebSocket depth@100ms (no API key).

Wss endpoint: wss://<stream>.binance.com/stream?streams=<symbol>@depth20@100ms
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


@dataclass
class WallEvent:
    """Detected large orderbook wall."""
    symbol: str
    side: str            # BID (buy wall) or ASK (sell wall)
    price: float
    quantity: float      # in base asset
    quantity_usdt: float # in quote asset (USDT)
    top_qty: float       # average top-of-book quantity for comparison
    ratio: float         # wall_size / avg_top_size
    timestamp: int       # ms
    local_time: datetime


class OrderbookScanner:
    """
    Subscribes to Binance <symbol>@depth20@100ms WebSocket streams.
    Detects walls significantly larger than the moving average top-of-book size.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        wall_threshold: float = 5.0,   # wall must be > threshold × avg top size
        window_size: int = 20,          # number of snapshots to average
    ):
        """
        symbols        : list of symbols to monitor, None = defaults
        wall_threshold  : multiplier on avg top-of-book qty to flag a wall
        window_size    : rolling window for average top-of-book size
        """
        self.symbols = symbols or [
            "btcusdt", "ethusdt", "bnbusdt", "solusdt",
            "xrpusdt", "adausdt", "dogeusdt", "avaxusdt",
        ]
        self.wall_threshold = wall_threshold
        self.window_size = window_size

        # Rolling avg top-of-book quantities per symbol
        self._avg_top: dict[str, float] = {}
        # Snapshot history for rolling average
        self._history: dict[str, list[float]] = defaultdict(list)
        self._ws: Optional[asyncio.Task] = None
        self._running = False
        self._lock = Lock()

        # callbacks: (wall: WallEvent) -> None
        self._callbacks: list[Callable[[WallEvent], None]] = []

    # ── public ──────────────────────────────────────────────────────────────────

    def add_callback(self, cb: Callable[[WallEvent], None]):
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

    def get_active_symbols(self) -> list[str]:
        return list(self.symbols)

    def summary_text(self) -> str:
        """Human-readable summary of current average top-of-book sizes."""
        with self._lock:
            if not self._avg_top:
                return "OrderbookScanner: no data yet."
            lines = ["📊 *Orderbook Averages (avg top qty):*"]
            for sym in sorted(self._avg_top):
                avg = self._avg_top[sym]
                hist = self._history.get(sym, [])
                ratio_txt = ""
                if hist:
                    cur = hist[-1] if hist else avg
                    ratio_txt = f" | current/top ratio: {cur/avg:.2f}x" if avg else ""
                lines.append(f"  {sym.upper()}: {avg:,.4f}{ratio_txt}")
            return "\n".join(lines)

    # ── internal ────────────────────────────────────────────────────────────────

    async def _run(self):
        streams = "/".join(f"{s}@depth20@100ms" for s in self.symbols)
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"

        while self._running:
            try:
                async with websockets.connect(url, ping_interval=30) as ws:
                    log.info("OrderbookScanner: connected to %s", url)
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._process_message(raw)
            except websockets.exceptions.ConnectionClosed:
                log.warning("OrderbookScanner: connection closed, reconnecting in 5s")
                await asyncio.sleep(5)
            except Exception as e:
                log.warning("OrderbookScanner error: %s, reconnecting in 5s", e)
                await asyncio.sleep(5)

    async def _process_message(self, raw: bytes | str):
        try:
            msg = json.loads(raw) if isinstance(raw, bytes) else json.loads(raw)
        except Exception:
            return

        data = msg.get("data")
        if not data:
            return

        self._update_avg(data)

    def _update_avg(self, data: dict):
        sym = data.get("s", "").lower()
        bids = data.get("b", [])
        asks = data.get("a", [])

        if not bids or not asks:
            return

        # Top-of-book quantity = sum of top 1 level quantity (price * qty)
        def top_qty(levels: list) -> float:
            if not levels:
                return 0.0
            # levels are [price, qty]
            try:
                return float(levels[0][1])
            except (IndexError, ValueError):
                return 0.0

        bid_qty = top_qty(bids)
        ask_qty = top_qty(asks)

        now = datetime.now()
        ts = data.get("E", 0)

        # Update rolling average
        with self._lock:
            for side, qty in [("BID", bid_qty), ("ASK", ask_qty)]:
                if qty <= 0:
                    continue

                hist = self._history[sym]
                hist.append(qty)
                if len(hist) > self.window_size:
                    hist.pop(0)

                avg = sum(hist) / len(hist)
                self._avg_top[sym] = avg

                # Detect wall
                if avg > 0 and qty / avg >= self.wall_threshold:
                    if side == "BID":
                        wall_price = float(bids[0][0])
                    else:
                        wall_price = float(asks[0][0])
                    ev = WallEvent(
                        symbol=sym,
                        side=side,
                        price=wall_price,
                        quantity=qty,
                        quantity_usdt=qty * wall_price,
                        top_qty=avg,
                        ratio=qty / avg,
                        timestamp=ts,
                        local_time=now,
                    )

                    log.info(
                        "🧱 Wall detected: %s %s %.4f | qty=%.4f (%.1fx avg) | %s",
                        sym.upper(), side, ev.price, qty, ev.ratio, now.isoformat()
                    )
                    for cb in self._callbacks:
                        try:
                            cb(ev)
                        except Exception as e:
                            log.error("OrderbookScanner callback error: %s", e)