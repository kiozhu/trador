"""Trade log — record every trade"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.helpers import atomic_write_json, read_json
from ..utils.logger import log


class TradeLog:
    def __init__(self, memory_dir: Path):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.memory_dir / "trade_history.json"
        self._ensure_file()

    def _ensure_file(self):
        if not self.file.exists():
            atomic_write_json(self.file, {"trades": []})

    def add(self, trade: dict[str, Any]) -> None:
        data = read_json(self.file) or {"trades": []}
        data["trades"].append(trade)
        # Keep last 1000 trades
        if len(data["trades"]) > 1000:
            data["trades"] = data["trades"][-1000:]
        atomic_write_json(self.file, data)
        log.info("Trade logged: %s %s %s %s",
                 trade.get("symbol"), trade.get("side"),
                 trade.get("pnl_pct"), trade.get("exit_reason"))

    def recent(self, n: int = 20) -> list[dict[str, Any]]:
        data = read_json(self.file) or {"trades": []}
        return data["trades"][-n:]

    def all(self) -> list[dict[str, Any]]:
        data = read_json(self.file) or {"trades": []}
        return data["trades"]
