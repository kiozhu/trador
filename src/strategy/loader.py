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
        self.active_ids: set[str] = set()  # multiple active strategies

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

        # ── Activate ALL strategies by default ────────────────────────────
        for sid in self.strategies:
            self.active_ids.add(sid)
        log.info("All %d strategies activated by default", len(self.active_ids))

    def get(self, strategy_id: str) -> dict[str, Any] | None:
        """Get strategy by ID."""
        return self.strategies.get(strategy_id)

    def set_active(self, strategy_id: str) -> bool:
        """Add strategy to active set (multi-strategy support)."""
        if strategy_id not in self.strategies:
            log.error("Cannot activate unknown strategy: %s", strategy_id)
            return False
        self.active_ids.add(strategy_id)
        log.info("Strategy activated: %s (active: %s)", strategy_id, self.list_active_ids())
        return True

    def set_inactive(self, strategy_id: str) -> bool:
        """Remove strategy from active set."""
        if strategy_id in self.active_ids:
            self.active_ids.discard(strategy_id)
            log.info("Strategy deactivated: %s (active: %s)", strategy_id, self.list_active_ids())
        return True

    def toggle(self, strategy_id: str) -> bool:
        """Toggle strategy active/inactive."""
        if strategy_id not in self.strategies:
            return False
        if strategy_id in self.active_ids:
            return self.set_inactive(strategy_id)
        return self.set_active(strategy_id)

    def list_active_ids(self) -> list[str]:
        """List IDs of active strategies."""
        return list(self.active_ids)

    def list_active(self) -> list[dict[str, Any]]:
        """List all active strategy dicts."""
        return [self.strategies[sid] for sid in self.active_ids if sid in self.strategies]

    def active(self) -> dict[str, Any] | None:
        """Get first active strategy (backward compat)."""
        if not self.active_ids:
            return None
        first = next(iter(self.active_ids))
        return self.strategies.get(first)

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
