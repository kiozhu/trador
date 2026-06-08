"""Strategy loader — load/reload strategy JSON files"""
import json
import re
from pathlib import Path
from typing import Any

from ..utils.logger import log


class StrategyLoader:
    def __init__(self, strategies_dir: Path):
        self.strategies_dir = Path(strategies_dir)
        self.strategies: dict[str, dict] = {}
        self.active_id: str | None = None

    def load_all(self) -> None:
        """Load all strategy JSON files from strategies directory."""
        if not self.strategies_dir.exists():
            log.warning("Strategies dir not found: %s", self.strategies_dir)
            return

        for file in self.strategies_dir.glob("*.json"):
            try:
                with open(file) as f:
                    data = json.load(f)
                sid = data.get("id")
                if not sid:
                    log.warning("Strategy file %s missing 'id' field", file)
                    continue
                self.strategies[sid] = data
                log.info("Loaded strategy: %s (%s)", sid, data.get("name", ""))
            except Exception as e:
                log.error("Failed to load %s: %s", file, e)

        if not self.strategies:
            log.warning("No strategies loaded from %s", self.strategies_dir)

    def get(self, strategy_id: str) -> dict[str, Any] | None:
        """Get strategy by ID."""
        return self.strategies.get(strategy_id)

    def set_active(self, strategy_id: str) -> bool:
        """Set active strategy."""
        if strategy_id not in self.strategies:
            log.error("Cannot activate unknown strategy: %s", strategy_id)
            return False
        self.active_id = strategy_id
        log.info("Active strategy set to: %s", strategy_id)
        return True

    def active(self) -> dict[str, Any] | None:
        """Get active strategy."""
        if not self.active_id:
            return None
        return self.strategies.get(self.active_id)

    def reload(self, strategy_id: str) -> bool:
        """Reload a single strategy file."""
        file = self.strategies_dir / f"{strategy_id}.json"
        if not file.exists():
            log.error("Strategy file not found: %s", file)
            return False

        try:
            with open(file) as f:
                data = json.load(f)
            self.strategies[strategy_id] = data
            log.info("Reloaded strategy: %s", strategy_id)
            return True
        except Exception as e:
            log.error("Failed to reload %s: %s", strategy_id, e)
            return False

    def list_all(self) -> list[dict[str, Any]]:
        """List all strategies."""
        return list(self.strategies.values())
