"""Hermes suggestion reader — read strategy suggestions from Hermes"""
import json
from pathlib import Path
from datetime import datetime, timezone

from ..strategy.validator import apply_hard_limits, validate_strategy
from ..utils.helpers import atomic_write_json
from ..utils.logger import log


class HermesReader:
    def __init__(self, suggestions_dir: Path):
        self.suggestions_dir = Path(suggestions_dir)
        self.processed_dir = self.suggestions_dir.parent / "processed"
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def read_pending(self) -> list[dict]:
        """Read all pending suggestion files."""
        pending_dir = self.suggestions_dir / "pending"
        if not pending_dir.exists():
            return []

        files = list(pending_dir.glob("*.json"))
        suggestions = []
        for f in files:
            try:
                with open(f) as fh:
                    data = json.load(f)
                suggestions.append({"file": f, "data": data})
            except Exception as e:
                log.error("Failed to read suggestion %s: %s", f, e)
        return suggestions

    def process(self, suggestion: dict, loader) -> bool:
        """Process a single suggestion. Returns True if applied."""
        data = suggestion["data"]
        file = suggestion["file"]

        # Check expiry
        expires = data.get("expires_at")
        if expires:
            exp_time = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp_time:
                log.info("Suggestion expired, moving to processed: %s", file.name)
                self._move_processed(file, "expired")
                return False

        # Get strategy
        strategy_id = data.get("strategy_id")
        changes = data.get("changes", {})
        if not strategy_id or not changes:
            return False

        strategy = loader.get(strategy_id)
        if not strategy:
            log.error("Unknown strategy in suggestion: %s", strategy_id)
            self._move_processed(file, "unknown_strategy")
            return False

        # Apply changes
        applied = []
        for key, value in changes.items():
            keys = key.split(".")
            target = strategy
            for k in keys[:-1]:
                target = target.setdefault(k, {})
            target[keys[-1]] = value
            applied.append(f"{key}={value}")

        # Apply hard limits
        strategy = apply_hard_limits(strategy)

        # Validate
        valid, err = validate_strategy(strategy)
        if not valid:
            log.error("Suggestion would make strategy invalid: %s", err)
            self._move_processed(file, "invalid")
            return False

        # Save
        from ..utils.helpers import atomic_write_json as atomic_json
        file_path = loader.strategies_dir / f"{strategy_id}.json"
        atomic_json(file_path, strategy)
        loader.reload(strategy_id)

        log.info("Applied Hermes suggestion: %s", applied)
        self._move_processed(file, "applied")
        return True

    def _move_processed(self, file: Path, reason: str) -> None:
        dest = self.processed_dir / f"{file.stem}_{reason}_{int(datetime.now(timezone.utc).timestamp())}.json"
        try:
            file.rename(dest)
        except Exception:
            pass