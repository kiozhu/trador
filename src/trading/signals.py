"""Signal generation — EMA, RSI, MACD, ADX"""
import pandas as pd
from typing import Any

from ..utils.logger import log


def compute_ema(closes: list, period: int) -> float:
    """Compute latest EMA value."""
    if len(closes) < period:
        return 0
    df = pd.DataFrame({"close": closes})
    ema = df["close"].ewm(span=period, adjust=False).mean().iloc[-1]
    return float(ema)


def compute_rsi(closes: list, period: int = 14) -> float:
    """Compute latest RSI value."""
    if len(closes) < period + 1:
        return 50
    df = pd.DataFrame({"close": closes})
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def compute_adx(highs: list, lows: list, closes: list, period: int = 14) -> float:
    """Compute ADX."""
    if len(closes) < period * 2:
        return 0
    df = pd.DataFrame({"high": highs, "low": lows, "close": closes})
    high_diff = df["high"].diff()
    low_diff = -df["low"].diff()
    plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0)
    minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0)
    tr = pd.DataFrame({
        "tr1": df["high"] - df["low"],
        "tr2": (df["high"] - df["close"]).abs(),
        "tr3": (df["low"] - df["close"]).abs(),
    }).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = (plus_dm.rolling(period).mean() / atr) * 100
    minus_di = (minus_dm.rolling(period).mean() / atr) * 100
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di)) * 100
    adx = dx.rolling(period).mean().iloc[-1]
    return float(adx)


def check_ema_crossover(closes: list, fast: int, slow: int) -> str | None:
    """Return 'bullish', 'bearish', or None."""
    if len(closes) < slow + 2:
        return None
    fast_ema_prev = compute_ema(closes[:-1], fast)
    fast_ema_curr = compute_ema(closes, fast)
    slow_ema_prev = compute_ema(closes[:-1], slow)
    slow_ema_curr = compute_ema(closes, slow)
    # Bullish: fast crossed above slow
    if fast_ema_prev < slow_ema_prev and fast_ema_curr > slow_ema_curr:
        return "bullish"
    # Bearish: fast crossed below slow
    if fast_ema_prev > slow_ema_prev and fast_ema_curr < slow_ema_curr:
        return "bearish"
    return None


def generate_signal(ohlcv: list[list], strategy: dict[str, Any]) -> dict | None:
    """Generate trading signal from OHLCV data and strategy config.

    Returns dict with signal or None.
    """
    if not ohlcv or len(ohlcv) < 50:
        return None

    closes = [c[4] for c in ohlcv]
    highs = [c[2] for c in ohlcv]
    lows = [c[3] for c in ohlcv]

    ind = strategy.get("indicators", {})
    ema_fast = ind.get("ema_fast", 20)
    ema_slow = ind.get("ema_slow", 50)
    adx_thresh = ind.get("adx_threshold", 25)
    rsi_ob = ind.get("rsi_overbought", 70)
    rsi_os = ind.get("rsi_oversold", 30)

    adx = compute_adx(highs, lows, closes, ind.get("adx_period", 14))
    rsi = compute_rsi(closes, ind.get("rsi_period", 14))
    crossover = check_ema_crossover(closes, ema_fast, ema_slow)

    # ADX filter
    if adx < adx_thresh:
        return None

    # RSI filter
    if rsi > rsi_ob or rsi < rsi_os:
        return None

    if crossover == "bullish":
        return {"action": "LONG", "reason": f"EMA{ema_fast}/{ema_slow} bullish crossover, ADX={adx:.1f}, RSI={rsi:.1f}"}
    if crossover == "bearish":
        return {"action": "SHORT", "reason": f"EMA{ema_fast}/{ema_slow} bearish crossover, ADX={adx:.1f}, RSI={rsi:.1f}"}

    return None