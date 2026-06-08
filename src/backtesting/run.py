"""Backtesting engine — historical data simulation.

Usage:
    python -m src.backtesting.run --strategy scalp_rapid --symbol BTCUSDT --timeframe 15m --days 30
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.strategy.loader import StrategyLoader
from src.trading.signals import generate_signal, compute_ema, compute_rsi

try:
    import ccxt
    HAS_CCXT = True
except ImportError:
    HAS_CCXT = False


@dataclass
class TradeResult:
    entry_time: datetime
    exit_time: datetime | None
    side: str
    entry_price: float
    exit_price: float | None
    size: float
    pnl_pct: float
    pnl_usd: float
    exit_reason: str  # TP / SL / TIMEOUT / END
    commission: float = 0.0


@dataclass
class BacktestResult:
    strategy_id: str
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl_pct: float
    total_pnl_usd: float
    max_drawdown_pct: float
    profit_factor: float
    avg_trade_pct: float
    avg_trade_duration_min: float
    trades: list[TradeResult] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)


class BacktestEngine:
    """Simulate strategy trading on historical data."""

    def __init__(
        self,
        strategy: dict[str, Any],
        symbol: str,
        timeframe: str = "15m",
        initial_balance: float = 10_000.0,
        commission: float = 0.0004,
    ):
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe
        self.initial_balance = initial_balance
        self.commission = commission  # 0.04% binance maker fee

        self.balance = initial_balance
        self.position = None  # {"side": "LONG"/"SHORT", "size": float, "entry": float}
        self.trades: list[TradeResult] = []
        self.equity_curve: list[float] = []
        self.entry_time: datetime | None = None

    def _get_sl_tp(self, entry_price: float, side: str) -> tuple[float, float]:
        risk = self.strategy.get("risk", {})
        lev = self.strategy.get("position", {}).get("leverage", 3)
        sl_pct = risk.get("sl_percent", 3) / 100 / lev
        tp_pct = risk.get("tp_percent", 6) / 100 / lev

        if side == "LONG":
            sl = entry_price * (1 - sl_pct)
            tp = entry_price * (1 + tp_pct)
        else:
            sl = entry_price * (1 + sl_pct)
            tp = entry_price * (1 - tp_pct)
        return sl, tp

    def _run_indicators(self, candles: list[list]) -> dict[str, Any]:
        if len(candles) < 50:
            return {}
        closes = [c[4] for c in candles]
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]
        ind = self.strategy.get("indicators", {})

        return {
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "ema_fast": compute_ema(closes, ind.get("ema_fast", 20)),
            "ema_slow": compute_ema(closes, ind.get("ema_slow", 50)),
            "rsi": compute_rsi(closes, ind.get("rsi_period", 14)),
            "crossover": self._check_crossover(closes, ind.get("ema_fast", 20), ind.get("ema_slow", 50)),
        }

    def _check_crossover(self, closes: list, fast: int, slow: int) -> str | None:
        if len(closes) < slow + 2:
            return None
        ef_prev = compute_ema(closes[:-1], fast)
        ef_curr = compute_ema(closes, fast)
        es_prev = compute_ema(closes[:-1], slow)
        es_curr = compute_ema(closes, slow)
        if ef_prev < es_prev and ef_curr > es_curr:
            return "bullish"
        if ef_prev > es_prev and ef_curr < es_curr:
            return "bearish"
        return None

    async def fetch_historical(self, exchange, days: int = 30) -> list[list]:
        """Fetch historical candles from exchange."""
        if not HAS_CCXT:
            print("ccxt not installed, using mock data")
            return self._generate_mock_data(days)

        timeframe_map = {
            "1m": 1, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "4h": 240, "1d": 1440,
        }
        tf_minutes = timeframe_map.get(self.timeframe, 15)
        limit = (days * 24 * 60) // tf_minutes

        try:
            data = await asyncio.to_thread(
                exchange.fetch_ohlcv, self.symbol, self.timeframe, None, limit
            )
            return data
        except Exception as e:
            print(f"Failed to fetch data: {e}, using mock data")
            return self._generate_mock_data(days)

    def _generate_mock_data(self, days: int) -> list[list]:
        """Generate realistic mock OHLCV data for testing."""
        tf_minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}.get(self.timeframe, 15)
        num_candles = days * 24 * 60 // tf_minutes

        base_price = 100_000
        candles = []
        ts = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        for i in range(num_candles):
            change = np.random.normal(0, 0.002)
            open_price = base_price * (1 + change * 0.3)
            high_price = open_price * (1 + abs(change) * 1.5)
            low_price = open_price * (1 - abs(change) * 1.5)
            close_price = open_price * (1 + change)
            volume = np.random.uniform(100, 1000)

            candles.append([ts, open_price, high_price, low_price, close_price, volume])
            ts += tf_minutes * 60 * 1000
            base_price = close_price

        return candles

    async def run(self, exchange=None, days: int = 30) -> BacktestResult:
        print(f"Running backtest: {self.strategy['id']} on {self.symbol} {self.timeframe} for {days} days")
        print(f"Initial balance: ${self.initial_balance:.2f}")

        candles = await self.fetch_historical(exchange, days)
        if not candles:
            print("No data fetched!")
            return self._empty_result(datetime.now() - timedelta(days=days), datetime.now())

        print(f"Loaded {len(candles)} candles")

        risk = self.strategy.get("risk", {})
        max_hold_minutes = risk.get("max_hold_minutes", 30)
        direction = self.strategy.get("direction", "both")

        tf_minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}.get(self.timeframe, 15)
        max_bars = max_hold_minutes // tf_minutes if tf_minutes > 0 else 1

        # Run backtest
        for i in range(50, len(candles)):
            window = candles[max(0, i - 200):i + 1]
            indicators = self._run_indicators(window)
            crossover = indicators.get("crossover")
            current_price = candles[i][4]
            current_time = datetime.fromtimestamp(candles[i][0] / 1000)

            # Entry logic
            if self.position is None and crossover:
                if crossover == "bullish" and direction in ("both", "long"):
                    self._open_position("LONG", current_price, current_time)
                elif crossover == "bearish" and direction in ("both", "short"):
                    self._open_position("SHORT", current_price, current_time)
            # Exit logic
            elif self.position:
                bars_held = i - self._find_entry_bar(candles)
                pnl_pct = self._calc_pnl_pct(current_price)
                sl, tp = self._get_sl_tp(self.position["entry"], self.position["side"])

                exit_reason = None
                if self.position["side"] == "LONG":
                    if current_price >= tp:
                        exit_reason = "TP"
                    elif current_price <= sl:
                        exit_reason = "SL"
                else:
                    if current_price <= tp:
                        exit_reason = "TP"
                    elif current_price >= sl:
                        exit_reason = "SL"

                if exit_reason or bars_held >= max_bars:
                    if not exit_reason:
                        exit_reason = "TIMEOUT"
                    self._close_position(current_price, current_time, exit_reason)

            # Record equity
            self.equity_curve.append(self.balance)

        return self._build_result(candles)

    def _open_position(self, side: str, price: float, time: datetime):
        size_pct = self.strategy.get("position", {}).get("size_value", 10) / 100
        size = (self.balance * size_pct) / price  # in base currency
        self.balance -= size * price * (1 + self.commission)
        self.position = {"side": side, "size": size, "entry": price}
        self.entry_time = time
        self.entry_bar = len(self._get_candles_buffer())

    def _get_candles_buffer(self):
        return self.trades  # placeholder, actually tracked in run loop

    def _find_entry_bar(self, candles):
        return getattr(self, "_entry_bar", 0)

    def _calc_pnl_pct(self, current_price: float) -> float:
        if not self.position:
            return 0.0
        entry = self.position["entry"]
        if self.position["side"] == "LONG":
            return (current_price - entry) / entry
        else:
            return (entry - current_price) / entry

    def _close_position(self, price: float, time: datetime, reason: str):
        if not self.position:
            return
        entry = self.position["entry"]
        size = self.position["size"]
        side = self.position["side"]

        if side == "LONG":
            pnl_usd = size * (price - entry) - (size * price * self.commission)
        else:
            pnl_usd = size * (entry - price) - (size * price * self.commission)

        self.balance += size * entry + pnl_usd

        pnl_pct = self._calc_pnl_pct(price)
        hold_minutes = (time - self.entry_time).total_seconds() / 60 if self.entry_time else 0

        trade = TradeResult(
            entry_time=self.entry_time or time,
            exit_time=time,
            side=side,
            entry_price=entry,
            exit_price=price,
            size=size,
            pnl_pct=pnl_pct * 100,
            pnl_usd=pnl_usd,
            exit_reason=reason,
            commission=size * price * self.commission,
        )
        self.trades.append(trade)
        self.position = None
        self.entry_time = None

    def _build_result(self, candles: list[list]) -> BacktestResult:
        wins = [t for t in self.trades if t.pnl_usd > 0]
        losses = [t for t in self.trades if t.pnl_usd <= 0]
        total_pnl = sum(t.pnl_usd for t in self.trades)
        durations = [(t.exit_time - t.entry_time).total_seconds() / 60
                     for t in self.trades if t.exit_time]

        # Max drawdown
        equity = np.array(self.equity_curve) if self.equity_curve else np.array([self.initial_balance])
        running_max = np.maximum.accumulate(equity)
        drawdowns = (running_max - equity) / running_max * 100
        max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        return BacktestResult(
            strategy_id=self.strategy.get("id", "unknown"),
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_date=datetime.fromtimestamp(candles[0][0] / 1000),
            end_date=datetime.fromtimestamp(candles[-1][0] / 1000),
            total_trades=len(self.trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=len(wins) / len(self.trades) * 100 if self.trades else 0,
            total_pnl_pct=(self.balance - self.initial_balance) / self.initial_balance * 100,
            total_pnl_usd=total_pnl,
            max_drawdown_pct=max_dd,
            profit_factor=sum(t.pnl_usd for t in wins) / abs(sum(t.pnl_usd for t in losses)) if losses and sum(t.pnl_usd for t in losses) != 0 else 0,
            avg_trade_pct=np.mean([t.pnl_pct for t in self.trades]) if self.trades else 0,
            avg_trade_duration_min=np.mean(durations) if durations else 0,
            trades=self.trades,
            equity_curve=self.equity_curve,
        )

    def _empty_result(self, start, end) -> BacktestResult:
        return BacktestResult(
            strategy_id=self.strategy.get("id", "unknown"),
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_date=start,
            end_date=end,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0,
            total_pnl_pct=0,
            total_pnl_usd=0,
            max_drawdown_pct=0,
            profit_factor=0,
            avg_trade_pct=0,
            avg_trade_duration_min=0,
        )


def print_result(result: BacktestResult):
    print("\n" + "=" * 60)
    print(f"BACKTEST RESULT: {result.strategy_id}")
    print(f"Symbol: {result.symbol} | Timeframe: {result.timeframe}")
    print(f"Period: {result.start_date.strftime('%Y-%m-%d')} → {result.end_date.strftime('%Y-%m-%d')}")
    print("=" * 60)
    print(f"Total Trades : {result.total_trades}")
    print(f"Win / Loss   : {result.winning_trades} / {result.losing_trades}")
    print(f"Win Rate     : {result.win_rate:.1f}%")
    print(f"Total PnL    : {result.total_pnl_usd:+.2f} USD ({result.total_pnl_pct:+.2f}%)")
    print(f"Profit Factor: {result.profit_factor:.2f}")
    print(f"Max Drawdown : {result.max_drawdown_pct:.2f}%")
    print(f"Avg Trade    : {result.avg_trade_pct:+.3f}% ({result.avg_trade_duration_min:.1f} min)")
    print("=" * 60)
    if result.trades:
        print("\nLast 5 trades:")
        for t in result.trades[-5:]:
            print(f"  {t.entry_time.strftime('%m-%d %H:%M')} {t.side:5} {t.entry_price:.2f} → {t.exit_price:.2f} | {t.pnl_pct:+.2f}% | {t.exit_reason}")
    print()


async def main():
    parser = argparse.ArgumentParser(description="Trador Backtesting Engine")
    parser.add_argument("--strategy", default="scalp_rapid", help="Strategy ID")
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading symbol")
    parser.add_argument("--timeframe", default="15m", help="Timeframe (1m/5m/15m/1h/4h)")
    parser.add_argument("--days", type=int, default=30, help="Days to backtest")
    parser.add_argument("--balance", type=float, default=10_000.0, help="Initial balance USDT")
    args = parser.parse_args()

    loader = StrategyLoader(Path(__file__).parent.parent.parent / "strategies")
    loader.load_all()
    strategy = loader.get(args.strategy)
    if not strategy:
        print(f"Strategy '{args.strategy}' not found")
        return

    engine = BacktestEngine(
        strategy=strategy,
        symbol=args.symbol,
        timeframe=args.timeframe,
        initial_balance=args.balance,
    )

    exchange = None
    if HAS_CCXT:
        exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})

    result = await engine.run(exchange, days=args.days)
    print_result(result)

    # Save result
    output_dir = Path(__file__).parent.parent.parent / "backtest_results"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / f"{args.strategy}_{args.symbol}_{args.timeframe}.json"
    data = {
        "strategy_id": result.strategy_id,
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "start_date": result.start_date.isoformat(),
        "end_date": result.end_date.isoformat(),
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "win_rate": round(result.win_rate, 2),
        "total_pnl_pct": round(result.total_pnl_pct, 4),
        "total_pnl_usd": round(result.total_pnl_usd, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        "profit_factor": round(result.profit_factor, 2),
        "avg_trade_pct": round(result.avg_trade_pct, 4),
        "avg_trade_duration_min": round(result.avg_trade_duration_min, 1),
    }
    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Result saved to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())