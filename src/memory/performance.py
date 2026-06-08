"""Performance tracker — win rate, drawdown, Sharpe"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.helpers import atomic_write_json, read_json
from ..utils.logger import log


class PerformanceTracker:
    def __init__(self, memory_dir: Path):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.memory_dir / "performance.json"
        self._ensure_file()

    def _ensure_file(self):
        if not self.file.exists():
            atomic_write_json(self.file, {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "24h": {"trades": 0, "wins": 0, "losses": 0, "pnl_usd": 0, "win_rate": 0},
                "7d": {"trades": 0, "wins": 0, "losses": 0, "pnl_usd": 0, "win_rate": 0},
                "30d": {"trades": 0, "wins": 0, "losses": 0, "pnl_usd": 0, "win_rate": 0},
            })

    def update(self, trades: list[dict[str, Any]]) -> None:
        now = datetime.now(timezone.utc)
        cutoff_24h = datetime.timestamp(now.replace(hour=0, minute=0, second=0)) * 1000
        cutoff_7d = cutoff_24h - 7 * 86400 * 1000
        cutoff_30d = cutoff_24h - 30 * 86400 * 1000

        def period_stats(cutoff: float) -> dict[str, Any]:
            period_trades = [t for t in trades if t.get("closed_at_ms", 0) >= cutoff]
            wins = [t for t in period_trades if t.get("pnl_usd", 0) > 0]
            losses = [t for t in period_trades if t.get("pnl_usd", 0) < 0]
            total = len(period_trades)
            win_rate = (len(wins) / total * 100) if total > 0 else 0
            pnl_usd = sum(t.get("pnl_usd", 0) for t in period_trades)
            return {
                "trades": total,
                "wins": len(wins),
                "losses": len(losses),
                "pnl_usd": round(pnl_usd, 2),
                "win_rate": round(win_rate, 1),
            }

        data = {
            "updated_at": now.isoformat(),
            "24h": period_stats(cutoff_24h),
            "7d": period_stats(cutoff_7d),
            "30d": period_stats(cutoff_30d),
        }
        atomic_write_json(self.file, data)

    def get(self) -> dict[str, Any]:
        return read_json(self.file) or {}
