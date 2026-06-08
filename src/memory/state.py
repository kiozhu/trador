"""State manager — bot status, trading on/off, active strategy"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.helpers import atomic_write_json, read_json
from ..utils.logger import log


class StateManager:
    def __init__(self, memory_dir: Path):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.memory_dir / "state.json"
        self._ensure_file()

    def _ensure_file(self):
        if not self.file.exists():
            atomic_write_json(self.file, {
                "bot_status": "stopped",
                "strategy_active": None,
                "trading_enabled": False,
                "mode": "dry_run",  # "live" or "dry_run"
                "exchange": None,  # "binance", "bybit", etc.
                "wallet_connected": False,
                "wallet_address": None,
                "open_positions": 0,
                "last_trade_at": None,
                "last_report_at": None,
                "cooling_until": None,
            })

    def get(self) -> dict[str, Any]:
        return read_json(self.file) or {}

    def set(self, key: str, value: Any) -> None:
        """Set a single key-value pair."""
        self.update({key: value})

    def update(self, **kwargs) -> None:
        data = self.get()
        data.update(kwargs)
        atomic_write_json(self.file, data)

    def set_status(self, status: str) -> None:
        self.update(bot_status=status)
        log.info("Bot status: %s", status)

    def set_trading(self, enabled: bool) -> None:
        self.update(trading_enabled=enabled)
        log.info("Trading %s", "enabled" if enabled else "disabled")

    def set_strategy(self, strategy_id: str) -> None:
        self.update(strategy_active=strategy_id)

    def set_mode(self, mode: str) -> None:
        """Set mode: 'live' or 'dry_run'."""
        self.update(mode=mode)
        log.info("Trading mode: %s", mode)

    def set_wallet(self, exchange: str, address: str | None, connected: bool) -> None:
        self.update(exchange=exchange, wallet_address=address, wallet_connected=connected)

    def set_cooling(self, until_ms: int | None) -> None:
        self.update(cooling_until=until_ms)

    def is_cooling(self) -> bool:
        data = self.get()
        cooling_until = data.get("cooling_until")
        if not cooling_until:
            return False
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return now_ms < cooling_until
