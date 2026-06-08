"""Position manager — track positions, SL/TP, trailing"""
from datetime import datetime, timezone
from typing import Any

from ..utils.logger import log


class PositionManager:
    def __init__(self):
        self.positions: list[dict[str, Any]] = []

    def add(self, position: dict[str, Any]) -> None:
        self.positions.append(position)
        log.info("Position added: %s %s @ %s", position.get("symbol"),
                 position.get("side"), position.get("entry_price"))

    def get_open_positions(self) -> list[dict[str, Any]]:
        return list(self.positions)

    def close(self, symbol: str, reason: str) -> dict | None:
        for i, p in enumerate(self.positions):
            if p.get("symbol") == symbol:
                p["exit_reason"] = reason
                p["closed_at"] = datetime.now(timezone.utc).isoformat()
                closed = self.positions.pop(i)
                log.info("Position closed: %s — %s", symbol, reason)
                return closed
        return None

    def update_prices(self, prices: dict[str, float]) -> None:
        for p in self.positions:
            sym = p.get("symbol")
            if sym in prices:
                p["current_price"] = prices[sym]
                entry = p.get("entry_price", 0)
                current = prices[sym]
                if entry > 0:
                    if p.get("side") == "LONG":
                        p["pnl_pct"] = ((current - entry) / entry) * 100
                        p["pnl_usd"] = p.get("size", 0) * (current - entry)
                    else:
                        p["pnl_pct"] = ((entry - current) / entry) * 100
                        p["pnl_usd"] = p.get("size", 0) * (entry - current)

    def count(self) -> int:
        return len(self.positions)

    def clear(self) -> None:
        self.positions.clear()