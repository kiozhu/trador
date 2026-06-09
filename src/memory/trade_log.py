"""Trade log — mode-aware, separate files per mode (dry_run/live)."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.helpers import atomic_write_json, read_json
from ..utils.logger import log


class TradeLog:
    """Handles trade history per mode. Mode determined at call time."""

    def __init__(self, memory_dir: Path):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        # Default base (root memory dir — mode subdirs added at call time)
        self._root = self.memory_dir

    def _file(self, mode: str) -> Path:
        """Get trade history file path for given mode."""
        d = self._root / mode
        d.mkdir(parents=True, exist_ok=True)
        return d / "trade_history.json"

    def _ensure_file(self, mode: str) -> None:
        f = self._file(mode)
        if not f.exists():
            atomic_write_json(f, {"trades": []})

    def add(self, trade: dict[str, Any]) -> None:
        """Add a trade to the mode-specific file."""
        mode = trade.get("mode", "dry_run")
        self._ensure_file(mode)
        data = read_json(self._file(mode)) or {"trades": []}
        data["trades"].append(trade)
        # Keep last 1000 trades per mode
        if len(data["trades"]) > 1000:
            data["trades"] = data["trades"][-1000:]
        atomic_write_json(self._file(mode), data)
        log.info("Trade logged: %s %s %s %s",
                 trade.get("symbol"), trade.get("side"),
                 trade.get("pnl_pct"), trade.get("exit_reason"))

    def recent(self, n: int = 20, mode: str = "dry_run") -> list[dict[str, Any]]:
        """Return last N trades for given mode."""
        self._ensure_file(mode)
        data = read_json(self._file(mode)) or {"trades": []}
        return data["trades"][-n:]

    def all(self, mode: str = "dry_run") -> list[dict[str, Any]]:
        """Return all trades for given mode."""
        self._ensure_file(mode)
        data = read_json(self._file(mode)) or {"trades": []}
        return data["trades"]

    def get_active(self, mode: str = "dry_run") -> list[dict[str, Any]]:
        """Return open positions for given mode."""
        self._ensure_file(mode)
        data = read_json(self._file(mode)) or {"trades": []}
        return [t for t in data["trades"] if t.get("status") == "open"]

    def get_closed(self, n: int = 100, mode: str = "dry_run") -> list[dict[str, Any]]:
        """Return last N closed trades for given mode."""
        self._ensure_file(mode)
        data = read_json(self._file(mode)) or {"trades": []}
        return [t for t in data["trades"] if t.get("status") == "closed"][-n:]

    def by_timerange(self, mode: str, start_ts: str | None = None,
                    end_ts: str | None = None) -> list[dict[str, Any]]:
        """Return trades within time range (ISO timestamps)."""
        self._ensure_file(mode)
        data = read_json(self._file(mode)) or {"trades": []}
        result = []
        for t in data["trades"]:
            ts = t.get("close_timestamp") or t.get("timestamp", "")
            if start_ts and ts < start_ts:
                continue
            if end_ts and ts > end_ts:
                continue
            result.append(t)
        return result

    def count(self, mode: str = "dry_run") -> int:
        """Total trades for mode."""
        self._ensure_file(mode)
        data = read_json(self._file(mode)) or {"trades": []}
        return len(data["trades"])