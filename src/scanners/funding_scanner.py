"""Funding rate scanner — Binance REST + WebSocket (no API key).

Monitors funding rates for perpetual futures using:
  • REST : https://fapi.binance.com/fapi/v1/premiumIndex
  • WS    : wss://fstream.binance.com/stream?streams=!premiumIndex@arr

No API key required.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Callable, Optional

import websockets

log = logging.getLogger(__name__)

FUNDING_ALERT_THRESHOLD = 0.01 # 1% — flag rates above this


@dataclass
class FundingRateEvent:
    symbol: str
    funding_rate: float # e.g. 0.0001 = 0.01%
    last_funding_rate: float # previous rate
    next_funding_time: int   # ms timestamp
    timestamp: int           # ms


@dataclass
class FundingSnapshot:
    """Current funding state for a symbol."""
    symbol: str
    rate: float
    prev_rate: float
    next_funding_time: int
    updated_at: datetime


class FundingScanner:
    """
    Tracks funding rates for Binance perpetual futures.

    Uses:
      • REST /fapi/v1/premiumIndex  — initial snapshot and rate changes
      • WS  !premiumIndex@arr       — real-time funding rate updates

    Fires callbacks on FundingRateEvent when rate changes significantly.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        alert_threshold: float = FUNDING_ALERT_THRESHOLD,
    ):
        """
        symbols          : list of symbols to monitor, None = all
        alert_threshold  : funding rate (absolute) to trigger alert callback
        """
        self.symbols = symbols or [
            "btcusdt", "ethusdt", "bnbusdt", "solusdt",
            "xrpusdt", "adausdt", "dogeusdt", "avaxusdt",
        ]
        self.alert_threshold = alert_threshold

        self._snapshots: dict[str, FundingSnapshot] = {}
        self._ws: Optional[asyncio.Task] = None
        self._running = False
        self._lock = Lock()

        # callbacks: (FundingRateEvent) -> None
        self._callbacks: list[Callable[[FundingRateEvent], None]] = []

    # ── public ────────────────────────────────────────────────────────────────

    def add_callback(self, cb: Callable[[FundingRateEvent], None]):
        self._callbacks.append(cb)

    async def start(self):
        """Start REST polling and WebSocket stream."""
        self._running = True
        # Initial REST snapshot
        await self._fetch_initial()
        # Then WS for real-time
        self._ws = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        if self._ws:
            self._ws.cancel()
            try:
                await self._ws
            except asyncio.CancelledError:
                pass

    def get_active(self) -> list[FundingSnapshot]:
        """Return current funding snapshots for all tracked symbols."""
        with self._lock:
            return list(self._snapshots.values())

    def get_by_symbol(self, symbol: str) -> Optional[FundingSnapshot]:
        return self._snapshots.get(symbol.lower())

    # ── REST ──────────────────────────────────────────────────────────────────

    async def _fetch_initial(self):
        """Fetch initial funding rates via REST."""
        try:
            import requests as _req
            url = "https://fapi.binance.com/fapi/v1/premiumIndex"
            async with asyncio.timeout(15):
                # Run sync request in thread to avoid blocking
                raw = await asyncio.to_thread(
                    _req.get, url, timeout=10
                )
            self._process_rest_message(raw.text)
        except Exception as e:
            log.warning("FundingScanner[REST] initial fetch failed: %s", e)

    def _process_rest_message(self, raw: bytes | str):
        """Parse REST premiumIndex response."""
        try:
            data = json.loads(raw) if isinstance(raw, bytes) else json.loads(raw)
        except Exception:
            return

        # REST returns a list of premium index records
        items = data if isinstance(data, list) else [data]
        for item in items:
            self._apply_funding_item(item)

    # ── WebSocket ─────────────────────────────────────────────────────────────

    async def _run(self):
        """Connect to combined funding rate WebSocket stream."""
        url = "wss://fstream.binance.com/stream?streams=!premiumIndex@arr"

        while self._running:
            try:
                async with websockets.connect(url, ping_interval=30) as ws:
                    log.info("FundingScanner[WS]: connected to %s", url)
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._process_ws_message(raw)
            except websockets.exceptions.ConnectionClosed:
                log.warning("FundingScanner[WS]: connection closed, reconnecting in 5s")
                await asyncio.sleep(5)
            except Exception as e:
                log.warning("FundingScanner[WS] error: %s, reconnecting in 5s", e)
                await asyncio.sleep(5)

    async def _process_ws_message(self, raw: bytes | str):
        try:
            msg = json.loads(raw) if isinstance(raw, bytes) else json.loads(raw)
        except Exception:
            return

        data = msg.get("data")
        if not data:
            return

        # WS sends array of funding rate objects
        items = data if isinstance(data, list) else [data]
        for item in items:
            self._apply_funding_item(item)

    def _apply_funding_item(self, item: dict):
        """Apply a funding rate item to state and fire callbacks if rate changed."""
        try:
            symbol = item["symbol"].lower()
        except Exception:
            return

        if self.symbols and symbol not in self.symbols:
            return

        try:
            rate = float(item.get("lastFundingRate", item.get("fundingRate", 0)))
            # Handle rate string like "0.00010000"
            if isinstance(item.get("lastFundingRate"), str):
                rate = float(item["lastFundingRate"])
            prev_rate = float(item.get("prevLastFundingRate", 0))
            if isinstance(item.get("prevLastFundingRate"), str):
                prev_rate = float(item["prevLastFundingRate"])
            next_funding_time = int(item.get("nextFundingTime", 0))
            timestamp = int(item.get("time", 0))
        except Exception:
            return

        now = datetime.now()
        prev = None

        with self._lock:
            if symbol in self._snapshots:
                prev = self._snapshots[symbol]
                prev_rate = prev.rate

            self._snapshots[symbol] = FundingSnapshot(
                symbol=symbol,
                rate=rate,
                prev_rate=prev_rate,
                next_funding_time=next_funding_time,
                updated_at=now,
            )

        # Fire callback if rate changed meaningfully
        if prev is None or abs(rate - prev_rate) > 1e-8:
            ev = FundingRateEvent(
                symbol=symbol,
                funding_rate=rate,
                last_funding_rate=prev_rate,
                next_funding_time=next_funding_time,
                timestamp=timestamp,
            )
            log.debug(
                "Funding rate update: %s | rate=%.4f%% prev=%.4f%%",
                symbol.upper(), rate * 100, prev_rate * 100
            )
            for cb in self._callbacks:
                try:
                    cb(ev)
                except Exception as e:
                    log.error("FundingScanner callback error: %s", e)

    def summary_text(self) -> str:
        """Telegram-ready text summary of current funding rates."""
        snapshots = self.get_active()
        if not snapshots:
            return "📊 No funding rate data available."

        lines = ["📊 *Funding Rates:*\n"]
        for s in sorted(snapshots, key=lambda x: abs(x.rate), reverse=True):
            emoji = "🟢" if s.rate >= 0 else "🔴"
            rate_pct = s.rate * 100
            prev_pct = s.prev_rate * 100
            # Direction arrow
            arrow = "↑" if s.rate > s.prev_rate else "↓" if s.rate < s.prev_rate else "→"
            lines.append(
                f"{emoji} {s.symbol.upper()} | {rate_pct:+.4f}% {arrow} "
                f"(was {prev_pct:+.4f}%) | next in {self._fmt_next_funding(s.next_funding_time)}"
            )
        return "\n".join(lines)

    def _fmt_next_funding(self, next_time_ms: int) -> str:
        """Format next funding time as human-readable."""
        if not next_time_ms:
            return "N/A"
        remaining = (next_time_ms - datetime.now().timestamp() * 1000) / 1000
        if remaining <= 0:
            return "soon"
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        return f"{hours}h {minutes}m"
