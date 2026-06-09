"""Performance tracker — mode-aware, separate data per mode (dry_run/live)."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.helpers import atomic_write_json, read_json
from ..utils.logger import log


class PerformanceTracker:
    """Tracks win rate, PnL per mode."""

    def __init__(self, memory_dir: Path):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _perf_file(self, mode: str) -> Path:
        d = self.memory_dir / mode
        d.mkdir(parents=True, exist_ok=True)
        return d / "performance.json"

    def _trade_file(self, mode: str) -> Path:
        d = self.memory_dir / mode
        d.mkdir(parents=True, exist_ok=True)
        return d / "trade_history.json"

    def update(self, mode: str = "dry_run", trades: list[dict[str, Any]] | None = None) -> None:
        """Recalculate performance for given mode from its trade history."""
        tf = self._trade_file(mode)
        pf = self._perf_file(mode)
        all_trades = read_json(tf).get("trades", []) if tf.exists() else []

        now = datetime.now(timezone.utc)
        cutoff_24h = datetime.timestamp(now.replace(hour=0, minute=0, second=0)) * 1000
        cutoff_7d = cutoff_24h - 7 * 86400 * 1000
        cutoff_30d = cutoff_24h - 30 * 86400 * 1000

        def period_stats(cutoff: float) -> dict[str, Any]:
            cutoff_iso = datetime.fromtimestamp(cutoff / 1000, tz=timezone.utc).isoformat()[:19]
            period_trades = [t for t in all_trades if (t.get("close_timestamp", "") or "")[:19] >= cutoff_iso]
            wins = [t for t in period_trades if t.get("pnl_pct", 0) > 0]
            losses = [t for t in period_trades if t.get("pnl_pct", 0) < 0]
            total = len(period_trades)
            win_rate = (len(wins) / total * 100) if total > 0 else 0
            pnl_pct = sum(t.get("pnl_pct", 0) for t in period_trades)
            pnl_usd = sum(t.get("pnl", 0) for t in period_trades)
            return {
                "trades": total,
                "wins": len(wins),
                "losses": len(losses),
                "pnl_pct": round(pnl_pct, 1),
                "pnl_usd": round(pnl_usd, 2),
                "win_rate": round(win_rate, 1),
            }

        data = {
            "updated_at": now.isoformat(),
            "mode": mode,
            "24h": period_stats(cutoff_24h),
            "7d": period_stats(cutoff_7d),
            "30d": period_stats(cutoff_30d),
        }
        atomic_write_json(pf, data)

    def get(self, mode: str = "dry_run") -> dict[str, Any]:
        """Get performance data for given mode."""
        pf = self._perf_file(mode)
        return read_json(pf) or {}

    def get_combined(self) -> dict[str, Any]:
        """Get combined performance across all modes."""
        combined = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "24h": {"trades": 0, "wins": 0, "losses": 0, "pnl_pct": 0, "pnl_usd": 0, "win_rate": 0},
            "7d": {"trades": 0, "wins": 0, "losses": 0, "pnl_pct": 0, "pnl_usd": 0, "win_rate": 0},
            "30d": {"trades": 0, "wins": 0, "losses": 0, "pnl_pct": 0, "pnl_usd": 0, "win_rate": 0},
        }
        for mode in ["dry_run", "live"]:
            data = self.get(mode)
            for period in ["24h", "7d", "30d"]:
                pd = data.get(period, {})
                combined[period]["trades"] += pd.get("trades", 0)
                combined[period]["wins"] += pd.get("wins", 0)
                combined[period]["losses"] += pd.get("losses", 0)
                combined[period]["pnl_pct"] += pd.get("pnl_pct", 0)
                combined[period]["pnl_usd"] += pd.get("pnl_usd", 0)
        # Recalculate win rate
        for period in ["24h", "7d", "30d"]:
            total = combined[period]["trades"]
            wins = combined[period]["wins"]
            combined[period]["win_rate"] = round((wins / total * 100) if total > 0 else 0, 1)
            combined[period]["pnl_pct"] = round(combined[period]["pnl_pct"], 1)
            combined[period]["pnl_usd"] = round(combined[period]["pnl_usd"], 2)
        return combined