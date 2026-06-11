"""VaR / CVaR calculator — historical, parametric, Monte Carlo methods."""
import math
import random
from datetime import datetime, timezone
from typing import Literal

import numpy as np

from ..utils.logger import log


Method = Literal["historical", "parametric", "mc"]


def _returns(prices: list[float]) -> np.ndarray:
    """Convert price series to log returns."""
    if len(prices) < 2:
        return np.array([0.0])
    arr = np.array(prices, dtype=float)
    arr = np.maximum(arr, 1e-10)
    return np.diff(np.log(arr))


# ── Normal CDF / PDF (no scipy) ───────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _norm_ppf(q: float) -> float:
    """Inverse standard normal CDF via bisection — machine-precision for all q."""
    if q <= 0.0:
        return float("-inf")
    if q >= 1.0:
        return float("inf")
    if q == 0.5:
        return 0.0
    lo, hi = -12.0, 12.0
    for _ in range(150):
        mid = (lo + hi) * 0.5
        if abs(_norm_cdf(mid) - q) < 1e-15:
            return mid
        if _norm_cdf(mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) * 0.5


# ── Historical VaR / CVaR ──────────────────────────────────────────────────────

def historical_var(
    prices: list[float],
    quantile: float = 0.95,
    horizon: int = 1,
) -> float:
    """Historical VaR at `quantile` confidence.

    VaR = -percentile(returns, 1-quantile) → always a positive loss.
    """
    rets = _returns(prices)
    if rets.size < 2:
        return 0.0
    # (1 - quantile) gives the left-tail percentile:0.05 for95% VaR
    var_pct = float(np.percentile(rets, (1.0 - quantile) * 100))
    return max(0.0, -var_pct) * math.sqrt(horizon)


def historical_cvar(
    prices: list[float],
    quantile: float = 0.95,
    horizon: int = 1,
) -> float:
    """Historical CVaR (Expected Shortfall) at `quantile` confidence.

    CVaR = -mean(returns where returns <= VaR_threshold)
    """
    rets = _returns(prices)
    if rets.size < 2:
        return 0.0
    threshold = float(np.percentile(rets, (1.0 - quantile) * 100))
    tail = rets[rets <= threshold]
    if tail.size == 0:
        return 0.0
    cvar_pct = float(np.mean(tail))
    return max(0.0, -cvar_pct) * math.sqrt(horizon)


# ── Parametric VaR / CVaR ──────────────────────────────────────────────────────

def parametric_var(
    prices: list[float],
    quantile: float = 0.95,
    horizon: int = 1,
) -> float:
    """Parametric VaR — analytical percentile of the assumed Gaussian distribution.

    VaR = -percentile(returns, 1-quantile).  Always positive (positive loss).
    """
    rets = _returns(prices)
    if rets.size < 2:
        return 0.0
    # (1-quantile) is the left-tail area: 0.05 for95% VaR
    var_pct = float(np.percentile(rets, (1.0 - quantile) * 100))
    return max(0.0, -var_pct) * math.sqrt(horizon)


def parametric_cvar(
    prices: list[float],
    quantile: float = 0.95,
    horizon: int = 1,
) -> float:
    """Parametric CVaR — conditional expectation below the VaR threshold.

    CVaR = -mean(returns where returns <= VaR_threshold)
    where VaR_threshold = percentile(returns, 1-quantile).
    """
    rets = _returns(prices)
    if rets.size < 2:
        return 0.0
    threshold = float(np.percentile(rets, (1.0 - quantile) * 100))
    tail = rets[rets <= threshold]
    if tail.size == 0:
        return 0.0
    cvar_pct = float(np.mean(tail))
    return max(0.0, -cvar_pct) * math.sqrt(horizon)


# ── Monte Carlo VaR / CVaR ─────────────────────────────────────────────────────

def mc_var(
    prices: list[float],
    quantile: float = 0.95,
    horizon: int = 1,
    n_sims: int = 10_000,
    seed: int = 42,
) -> float:
    """Monte Carlo VaR — simulate `n_sims` return paths from historical moments."""
    random.seed(seed)
    np.random.seed(seed)
    rets = _returns(prices)
    if rets.size < 2:
        return 0.0
    mu = float(np.mean(rets))
    sigma = float(np.std(rets))
    sims = np.random.normal(mu * horizon, sigma * math.sqrt(horizon), n_sims)
    var_pct = float(np.percentile(sims, (1.0 - quantile) * 100))
    return max(0.0, -var_pct)


def mc_cvar(
    prices: list[float],
    quantile: float = 0.95,
    horizon: int = 1,
    n_sims: int = 10_000,
    seed: int = 42,
) -> float:
    """Monte Carlo CVaR."""
    random.seed(seed)
    np.random.seed(seed)
    rets = _returns(prices)
    if rets.size < 2:
        return 0.0
    mu = float(np.mean(rets))
    sigma = float(np.std(rets))
    sims = np.random.normal(mu * horizon, sigma * math.sqrt(horizon), n_sims)
    threshold = float(np.percentile(sims, (1.0 - quantile) * 100))
    tail = sims[sims <= threshold]
    cvar_pct = float(np.mean(tail)) if tail.size else 0.0
    return max(0.0, -cvar_pct)


# ── Public API ────────────────────────────────────────────────────────────────

def compute_var(
    prices: list[float],
    notional: float,
    method: Method = "historical",
    quantile: float = 0.95,
    horizon: int = 1,
    n_sims: int = 10_000,
) -> dict:
    """Compute VaR and CVaR in USD for a given notional exposure.

    Returns:
        dict with var_usd, cvar_usd, var_pct, cvar_pct, method, horizon, quantile
    """
    if len(prices) < 10:
        log.warning("VaR: insufficient price data (%d bars)", len(prices))
        return _zero_result(method, quantile, horizon)

    dispatch = {
        "historical": (historical_var, historical_cvar),
        "parametric": (parametric_var, parametric_cvar),
        "mc": (mc_var, mc_cvar),
    }

    var_fn, cvar_fn = dispatch.get(method, (historical_var, historical_cvar))

    try:
        var_pct = var_fn(prices, quantile, horizon)
        cvar_pct = cvar_fn(prices, quantile, horizon)
    except Exception as e:
        log.error("VaR computation failed (%s): %s", method, e)
        return _zero_result(method, quantile, horizon)

    var_usd = var_pct * notional
    cvar_usd = cvar_pct * notional

    return {
        "var_usd": round(var_usd, 4),
        "cvar_usd": round(cvar_usd, 4),
        "var_pct": round(var_pct * 100, 4),
        "cvar_pct": round(cvar_pct * 100, 4),
        "method": method,
        "horizon": horizon,
        "quantile": quantile,
        "notional": notional,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _zero_result(method: str, quantile: float, horizon: int) -> dict:
    return {
        "var_usd": 0.0,
        "cvar_usd": 0.0,
        "var_pct": 0.0,
        "cvar_pct": 0.0,
        "method": method,
        "horizon": horizon,
        "quantile": quantile,
        "notional": 0.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def var_summary(
    prices: list[float],
    notional: float,
    quantile: float = 0.95,
    horizon: int = 1,
) -> dict:
    """Run all three methods and return a comparative summary."""
    results = {}
    for method in ("historical", "parametric", "mc"):
        results[method] = compute_var(
            prices, notional, method, quantile, horizon
        )
    return {
        "notional": notional,
        "quantile": quantile,
        "horizon": horizon,
        "methods": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
