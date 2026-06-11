"""Rolling buffer — fixed-size trade history + running statistics.

Keeps the last N closed trades in memory and computes aggregate stats
(win rate, PnL%, profit factor, avg hold time, max drawdown) over the
full buffer and over configurable time windows (24 h, 7 d, 30 d).
Thread-safe via a threading.RLock so it can be read from the sync
callbacks of async scanners without tearing.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from ..utils.logger import log


# ── Dataclasses ─────────────────────────────────────────────────────────────────

@dataclass
class RollingStats:
    """Snapshot of rolling trade statistics."""
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0          # %
    pnl_pct: float = 0.0          # % of initial balance
    pnl_usd: float = 0.0
    profit_factor: float = 0.0    # gross wins / gross losses
    avg_winner_pct: float = 0.0
    avg_loser_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_hold_minutes: float = 0.0
    largest_win_pct: float = 0.0
    largest_loss_pct: float = 0.0
    updated_at: str = ""           # ISO8601

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PeriodStats:
    """Lightweight stats for a specific time period."""
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    pnl_pct: float = 0.0
    pnl_usd: float = 0.0
    avg_hold_minutes: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── RollingBuffer ───────────────────────────────────────────────────────────────

class RollingBuffer:
    """Thread-safe rolling trade history with running statistics.

    Parameters
    ----------
    maxlen : int
        Maximum number of closed trades to keep in the deque.
    initial_balance : float
        Starting balance (used for PnL% calculation). Default 10 000.
    persist_path : Path | None
        If given, stats are flushed to this file on every update so they
        survive process restarts.
    """

    def __init__(
        self,
        maxlen: int = 200,
        initial_balance: float = 10_000.0,
        persist_path: Path | None = None,
    ):
        self.maxlen = maxlen
        self.initial_balance = initial_balance
        self.persist_path = persist_path
        self._lock = Lock()

        # Main trade deque — stores full trade dicts
        self._trades: deque[dict[str, Any]] = deque(maxlen=maxlen)

        # Equity curve (in order of trade close) for drawdown calculation
        self._equity: deque[float] = deque(maxlen=maxlen)

        # ── Precomputed cutoffs (updated on every add/flush) ───────────────────
        self._cutoff_24h: float = 0.0
        self._cutoff_7d: float = 0.0
        self._cutoff_30d: float = 0.0
        self._refresh_cutoffs()

        # Restore from disk if path exists
        if persist_path and persist_path.exists():
            self._load()

    # ── Public API ──────────────────────────────────────────────────────────────

    def add(self, trade: dict[str, Any]) -> None:
        """Add a closed trade; triggers a stats recalculation.

        ``trade`` must contain at least:
          close_timestamp, pnl, pnl_pct, side, hold_minutes
        """
        with self._lock:
            self._trades.append(trade)

            # Update equity curve
            equity = self._equity[-1] if self._equity else self.initial_balance
            equity += trade.get("pnl", 0)
            self._equity.append(equity)

            self._refresh_cutoffs()
            self._flush_if_persist()

    def get_stats(self) -> RollingStats:
        """Return stats over the entire rolling buffer."""
        with self._lock:
            return self._calc_stats(list(self._trades))

    def get_stats_24h(self) -> PeriodStats:
        """Return stats for the last 24 hours."""
        return self._period_stats(self._cutoff_24h)

    def get_stats_7d(self) -> PeriodStats:
        """Return stats for the last 7 days."""
        return self._period_stats(self._cutoff_7d)

    def get_stats_30d(self) -> PeriodStats:
        """Return stats for the last 30 days."""
        return self._period_stats(self._cutoff_30d)

    def get_all_trades(self) -> list[dict[str, Any]]:
        """Return all trades as a plain list (newest last)."""
        with self._lock:
            return list(self._trades)

    def get_recent(self, n: int = 20) -> list[dict[str, Any]]:
        """Return the N most recent closed trades."""
        with self._lock:
            return list(self._trades)[-n:]

    @property
    def trade_count(self) -> int:
        with self._lock:
            return len(self._trades)

    def snapshot(self) -> dict[str, Any]:
        """Full snapshot suitable for serialisation (e.g. Telegram status)."""
        s = self.get_stats()
        h = self.get_stats_24h()
        d = self.get_stats_7d()
        t = self.get_stats_30d()
        return {
            "all": s.to_dict(),
            "24h": h.to_dict(),
            "7d": d.to_dict(),
            "30d": t.to_dict(),
            "initial_balance": self.initial_balance,
        }

    # ── Internal helpers ────────────────────────────────────────────────────────

    def _refresh_cutoffs(self) -> None:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        self._cutoff_24h = today_start.timestamp() * 1000
        self._cutoff_7d  = (today_start.timestamp() - 7  * 86400) * 1000
        self._cutoff_30d = (today_start.timestamp() - 30 * 86400) * 1000

    def _period_stats(self, cutoff_ms: float) -> PeriodStats:
        with self._lock:
            trades = [t for t in self._trades
                      if self._ts_ms(t) >= cutoff_ms]
        return self._calc_period_stats(trades)

    def _ts_ms(self, trade: dict[str, Any]) -> float:
        """Extract close timestamp in ms from a trade dict."""
        ts = trade.get("close_timestamp") or trade.get("timestamp") or ""
        # ISO string → ms
        if isinstance(ts, str) and "T" in ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.timestamp() * 1000
            except ValueError:
                return 0.0
        try:
            return float(ts)
        except (TypeError, ValueError):
            return 0.0

    def _calc_period_stats(self, trades: list[dict[str, Any]]) -> PeriodStats:
        if not trades:
            return PeriodStats()

        wins   = [t for t in trades if t.get("pnl_pct", 0) > 0]
        losses = [t for t in trades if t.get("pnl_pct", 0) < 0]
        total  = len(trades)

        win_rate = len(wins) / total * 100 if total else 0
        pnl_pct  = sum(t.get("pnl_pct", 0) for t in trades)
        pnl_usd  = sum(t.get("pnl", 0)    for t in trades)
        holds    = [t.get("hold_minutes", 0) for t in trades]

        return PeriodStats(
            trades=total,
            wins=len(wins),
            losses=len(losses),
            win_rate=round(win_rate, 2),
            pnl_pct=round(pnl_pct, 2),
            pnl_usd=round(pnl_usd, 2),
            avg_hold_minutes=round(sum(holds) / len(holds), 1) if holds else 0,
        )

    def _calc_stats(self, trades: list[dict[str, Any]]) -> RollingStats:
        if not trades:
            return RollingStats(updated_at=datetime.now(timezone.utc).isoformat())

        wins   = [t for t in trades if t.get("pnl_pct", 0) > 0]
        losses = [t for t in trades if t.get("pnl_pct", 0) < 0]
        total  = len(trades)

        win_rate     = len(wins) / total * 100 if total else 0
        pnl_pct      = sum(t.get("pnl_pct", 0) for t in trades)
        pnl_usd      = sum(t.get("pnl", 0)     for t in trades)

        gross_wins   = sum(t.get("pnl", 0) for t in wins)
        gross_losses = abs(sum(t.get("pnl", 0) for t in losses)) or 1e-9
        profit_factor = gross_wins / gross_losses

        win_pcts  = [t.get("pnl_pct", 0) for t in wins]
        loss_pcts = [abs(t.get("pnl_pct", 0)) for t in losses]

        avg_winner = sum(win_pcts)  / len(win_pcts)  if win_pcts  else 0
        avg_loser  = sum(loss_pcts) / len(loss_pcts) if loss_pcts else 0

        largest_win = max(win_pcts)  if win_pcts  else 0
        largest_loss = max(loss_pcts) if loss_pcts else 0

        holds = [t.get("hold_minutes", 0) for t in trades]
        avg_hold = sum(holds) / len(holds) if holds else 0

        # Max drawdown from equity curve
        max_dd = self._max_drawdown_from_equity(list(self._equity))

        return RollingStats(
            trades=total,
            wins=len(wins),
            losses=len(losses),
            win_rate=round(win_rate, 2),
            pnl_pct=round(pnl_pct, 2),
            pnl_usd=round(pnl_usd, 2),
            profit_factor=round(profit_factor, 3),
            avg_winner_pct=round(avg_winner, 3),
            avg_loser_pct=round(avg_loser, 3),
            max_drawdown_pct=round(max_dd, 2),
            avg_hold_minutes=round(avg_hold, 1),
            largest_win_pct=round(largest_win, 3),
            largest_loss_pct=round(largest_loss, 3),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def _max_drawdown_from_equity(self, equity: list[float]) -> float:
        if not equity:
            return 0.0
        running_max = equity[0]
        max_dd = 0.0
        for e in equity:
            if e > running_max:
                running_max = e
            dd = (running_max - e) / running_max * 100 if running_max else 0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    # ── Persistence ────────────────────────────────────────────────────────────

    def _flush_if_persist(self) -> None:
        if not self.persist_path:
            return
        try:
            self._save()
        except Exception as e:
            log.warning("RollingBuffer save failed: %s", e)

    def _save(self) -> None:
        """Atomically write full buffer state to JSON."""
        path = Path(self.persist_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": 1,
            "initial_balance": self.initial_balance,
            "trades": list(self._trades),
            "equity": list(self._equity),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with open(fd, "w") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            shutil.move(tmp, path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.remove(tmp)
            except OSError:
                pass

    def _load(self) -> None:
        """Restore buffer state from persist_path."""
        import os
        try:
            with open(self.persist_path) as f:
                data = json.load(f)

            self._trades = deque(
                data.get("trades", []),
                maxlen=self.maxlen,
            )
            self._equity = deque(
                data.get("equity", []),
                maxlen=self.maxlen,
            )
            self._refresh_cutoffs()
            log.info(
                "RollingBuffer restored %d trades from %s",
                len(self._trades), self.persist_path,
            )
        except Exception as e:
            log.warning("RollingBuffer restore failed: %s", e)