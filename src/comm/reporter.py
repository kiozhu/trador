"""Hermes reporter — write trade reports to shared/trador_reports/"""
import json
from datetime import datetime, timezone
from pathlib import Path

from ..utils.helpers import atomic_write_json
from ..utils.logger import log


class HermesReporter:
    def __init__(self, reports_dir: Path):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def write_status(self, state: dict, positions: list[dict], perf: dict) -> None:
        pos = positions[0] if positions else None
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bot_status": state.get("bot_status", "unknown"),
            "strategy_active": state.get("strategy_active", ""),
            "position": pos,
            "today": perf.get("24h", {}),
            "open_positions": len(positions),
            "max_drawdown": perf.get("24h", {}).get("max_drawdown", 0),
        }
        atomic_write_json(self.reports_dir / "status.json", data)

    def write_trade(self, trade: dict) -> None:
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trade": trade,
        }
        atomic_write_json(self.reports_dir / "trades.json", data)
        log.info("Trade report written for %s", trade.get("symbol"))

    def write_metrics(self, perf: dict) -> None:
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "period": "24h",
            **perf.get("24h", {}),
        }
        atomic_write_json(self.reports_dir / "metrics.json", data)