"""Stress testing — 5 scenarios with severity scoring and recommendations."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from ..utils.logger import log


class Severity(str, Enum):
    LOW = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class Scenario(str, Enum):
    BLACK_SWAN       = "black swan"
    LIQUIDATION_CASCADE = "liquidation cascade"
    MARKET_MAKER_WITHDRAWAL = "market maker withdrawal"
    CORRELATION_BREAKDOWN = "correlation breakdown"
    SUDDEN_FUNDING_SPIKE    = "sudden funding spike"


@dataclass
class StressResult:
    scenario: str
    severity: Severity
    estimated_loss_pct: float
    estimated_loss_usd: float
    recommendation: str
    details: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def passed(self) -> bool:
        return self.severity not in (Severity.HIGH, Severity.CRITICAL)

    def summary(self) -> str:
        icon = "✅" if self.passed else "🚨"
        return (
            f"{icon} [{self.scenario.upper()}] "
            f"Severity: {self.severity.value.upper()} | "
            f"Est. Loss: {self.estimated_loss_pct:.2f}% (${self.estimated_loss_usd:.2f})"
        )


# ── Price shock simulators ────────────────────────────────────────────────────

def _shock_prices(prices: list[float], shock_pct: float) -> list[float]:
    """Apply a uniform percentage shock to a price series."""
    factor = 1.0 + shock_pct
    return [p * factor for p in prices]


def _shock_volatility(prices: list[float], vol_multiplier: float) -> list[float]:
    """Increase price volatility by scaling returns."""
    if len(prices) < 2:
        return prices
    rets = [prices[i] / prices[i - 1] - 1 for i in range(1, len(prices))]
    new_prices = [prices[0]]
    for r in rets:
        new_r = r * vol_multiplier
        new_prices.append(new_prices[-1] * (1 + new_r))
    return new_prices


# ── Scenario builders ──────────────────────────────────────────────────────────

def _scenario_black_swan(
    prices: list[float],
    notional: float,
    position_entry: float,
    position_size: float,
) -> StressResult:
    """Black Swan — rare, extreme adverse event (tail risk).

    Simulates a sudden -30% gap drop overnight (e.g. black-hat news,
    exchange hack, macro shock).  Used to verify stop-loss adequacy.
    """
    shock = -0.30
    shocked = _shock_prices(prices, shock)
    entry = position_entry
    exit_price = shocked[-1] if shocked else entry * (1 + shock)

    if position_size <= 0 or entry <= 0:
        loss_pct = 0.0
    else:
        loss_pct = abs(exit_price - entry) / entry * 100

    loss_usd = notional * (loss_pct / 100)

    # Stop-loss adequacy check
    sl_adequate = abs(shock) < 0.20  # shock is larger than typical SL range
    recommendation = (
        "✅ Stop-loss adequately covers a -30% overnight gap. "
        "No position adjustment needed."
        if sl_adequate else
        "⚠️  Black swan scenario exceeds stop-loss range. "
        "Consider tightening SL or reducing position size to survive a -30% gap."
    )

    return StressResult(
        scenario=Scenario.BLACK_SWAN.value,
        severity=Severity.CRITICAL if abs(loss_pct) > 20 else Severity.HIGH,
        estimated_loss_pct=round(loss_pct, 4),
        estimated_loss_usd=round(loss_usd, 2),
        recommendation=recommendation,
        details={
            "shock_pct": shock,
            "exit_price": round(exit_price, 4),
            "entry_price": entry,
            "sl_adequate": sl_adequate,
        },
    )


def _scenario_liquidation_cascade(
    prices: list[float],
    notional: float,
    position_entry: float,
    position_size: float,
    leverage: int = 3,
) -> StressResult:
    """Liquidation Cascade — leveraged positions getting wiped in a vol spike.

    Simulates a 15% adverse move with3× leverage =45% margin loss,
    likely triggering liquidation at typical80% maintenance margin.
    """
    shock = -0.15
    shocked = _shock_prices(prices, shock)
    exit_price = shocked[-1] if shocked else position_entry * (1 + shock)

    if position_size <= 0 or position_entry <= 0:
        loss_pct = 0.0
    else:
        loss_pct = abs(exit_price - position_entry) / position_entry * 100 * leverage

    loss_usd = notional * (loss_pct / 100)

    liquidation_threshold = 100 / leverage # e.g. 33% for 3×
    actual_move = abs(shock) * 100 * leverage
    likely_liquidated = actual_move > liquidation_threshold * 0.8

    recommendation = (
        "🚨 LIQUIDATION RISK: A -15% move with current leverage ({leverage}×) "
        "would trigger forced liquidation. "
        "Reduce leverage to ≤2× or increase collateral to survive a vol spike."
        if likely_liquidated else
        f"⚠️  A -15% move would cause ~{actual_move:.0f}% margin loss. "
        f"Current liquidation threshold is ~{liquidation_threshold:.0f}%. "
        "Consider reducing leverage or adding buffer margin."
    )

    return StressResult(
        scenario=Scenario.LIQUIDATION_CASCADE.value,
        severity=Severity.CRITICAL if likely_liquidated else Severity.HIGH,
        estimated_loss_pct=round(loss_pct, 4),
        estimated_loss_usd=round(loss_usd, 2),
        recommendation=recommendation,
        details={
            "shock_pct": shock,
            "leverage": leverage,
            "liquidation_threshold_pct": liquidation_threshold,
            "actual_margin_loss_pct": round(actual_move, 2),
            "likely_liquidated": likely_liquidated,
            "exit_price": round(exit_price, 4),
        },
    )


def _scenario_mm_withdrawal(
    prices: list[float],
    notional: float,
    position_entry: float,
    position_size: float,
) -> StressResult:
    """Market Maker Withdrawal — wide spreads, sudden liquidity withdrawal.

    Simulates a -8% mid-price drop combined with a 3× spread widening,
    meaning the fill price is significantly worse than mid. Tests
    execution quality and slippage assumption.
    """
    mid_shock = -0.08
    spread_multiplier = 3.0

    # Just shock the prices to simulate the mid move
    shocked = _shock_prices(prices, mid_shock)
    exit_price = shocked[-1] if shocked else position_entry * (1 + mid_shock)

    if position_size <= 0 or position_entry <= 0:
        loss_pct = 0.0
    else:
        loss_pct = abs(exit_price - position_entry) / position_entry * 100

    # Spread widening adds execution cost
    spread_penalty = spread_multiplier * 0.002  # assume base spread = 0.2%
    total_loss_pct = loss_pct + spread_penalty * 100
    loss_usd = notional * (total_loss_pct / 100)

    recommendation = (
        "⚠️  Market maker withdrawal scenario: wide spreads significantly "
        "increase execution cost.  Use limit orders over market orders "
        "during low-liquidity periods and size positions accordingly."
    )

    return StressResult(
        scenario=Scenario.MARKET_MAKER_WITHDRAWAL.value,
        severity=Severity.MEDIUM,
        estimated_loss_pct=round(total_loss_pct, 4),
        estimated_loss_usd=round(loss_usd, 2),
        recommendation=recommendation,
        details={
            "mid_shock_pct": mid_shock,
            "spread_multiplier": spread_multiplier,
            "spread_penalty_pct": round(spread_penalty * 100, 4),
            "exit_price": round(exit_price, 4),
        },
    )


def _scenario_correlation_breakdown(
    prices: list[float],
    notional: float,
    position_entry: float,
    position_size: float,
) -> StressResult:
    """Correlation Breakdown — hedged pairs moving together (basis risk).

    Simulates a -10% move in both legs of a supposedly neutral pair trade,
    revealing hidden directional exposure.  Tests portfolio correlation
    assumptions.
    """
    shock = -0.10
    shocked = _shock_prices(prices, shock)
    exit_price = shocked[-1] if shocked else position_entry * (1 + shock)

    if position_size <= 0 or position_entry <= 0:
        loss_pct = 0.0
    else:
        loss_pct = abs(exit_price - position_entry) / position_entry * 100

    loss_usd = notional * (loss_pct / 100)

    recommendation = (
        "⚠️  Correlation breakdown: hedged positions moved together, eliminating "
        "the intended hedge.  Review pair correlations and consider position "
        "reduction or exit when correlation exceeds 0.7 during stress."
    )

    return StressResult(
        scenario=Scenario.CORRELATION_BREAKDOWN.value,
        severity=Severity.HIGH,
        estimated_loss_pct=round(loss_pct, 4),
        estimated_loss_usd=round(loss_usd, 2),
        recommendation=recommendation,
        details={
            "shock_pct": shock,
            "exit_price": round(exit_price, 4),
            "assumed_correlation": 0.0,
            "stress_correlation": 1.0,
        },
    )


def _scenario_funding_spike(
    prices: list[float],
    notional: float,
    position_entry: float,
    position_size: float,
) -> StressResult:
    """Sudden Funding Spike — funding rate reversal on perpetual futures.

    Simulates a +0.1% funding charge applied every 8 hours for 3 days,
    accumulating to significant carry cost that erodes yield.
    """
    funding_rate =0.001  # 0.1% per 8h
    periods = 9  # 3 days × 3 periods/day
    total_funding_cost_pct = funding_rate * periods * 100  # as % of notional

    loss_usd = notional * (total_funding_cost_pct / 100)

    recommendation = (
        f"⚠️  Funding spike scenario: accumulated funding cost of "
        f"{total_funding_cost_pct:.2f}% over 3 days (at0.1%/8h). "
        "Monitor funding rates before entering perpetual futures positions. "
        "Pre-set alerts for funding rate reversals and consider taking the "
        "opposite side of the funding trade if rate exceeds 0.15%/8h."
    )

    return StressResult(
        scenario=Scenario.SUDDEN_FUNDING_SPIKE.value,
        severity=Severity.MEDIUM,
        estimated_loss_pct=round(total_funding_cost_pct, 4),
        estimated_loss_usd=round(loss_usd, 2),
        recommendation=recommendation,
        details={
            "funding_rate_pct": funding_rate * 100,
            "periods": periods,
            "total_cost_pct": round(total_funding_cost_pct, 4),
            "hours_simulated": periods * 8,
        },
    )


# ── Public API ────────────────────────────────────────────────────────────────

def run_stress_test(
    prices: list[float],
    notional: float,
    position_entry: float,
    position_size: float,
    leverage: int = 3,
) -> dict[str, Any]:
    """Run all 5 stress scenarios and return a full report.

    Args:
        prices:        price series (oldest → newest)
        notional:     USD notional of the portfolio
        position_entry: entry price of the active position
        position_size:  size of the active position (contracts)
        leverage:     current leverage multiplier

    Returns:
        dict with overall_passed, severity, results list, summary
    """
    log.info("Running stress test (notional=%.2f, leverage=%d)", notional, leverage)

    scenarios = [
        _scenario_black_swan(prices, notional, position_entry, position_size),
        _scenario_liquidation_cascade(
            prices, notional, position_entry, position_size, leverage
        ),
        _scenario_mm_withdrawal(prices, notional, position_entry, position_size),
        _scenario_correlation_breakdown(prices, notional, position_entry, position_size),
        _scenario_funding_spike(prices, notional, position_entry, position_size),
    ]

    severity_order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
    worst = Severity.LOW
    for r in scenarios:
        if severity_order.index(r.severity) > severity_order.index(worst):
            worst = r.severity

    overall_passed = worst not in (Severity.HIGH, Severity.CRITICAL)

    results_list = []
    for r in scenarios:
        results_list.append({
            "scenario": r.scenario,
            "severity": r.severity.value,
            "estimated_loss_pct": r.estimated_loss_pct,
            "estimated_loss_usd": r.estimated_loss_usd,
            "recommendation": r.recommendation,
            "details": r.details,
            "timestamp": r.timestamp,
            "passed": r.passed,
        })

    total_loss_usd = sum(r.estimated_loss_usd for r in scenarios)
    worst_loss_usd = max(r.estimated_loss_usd for r in scenarios)

    report = {
        "overall_passed": overall_passed,
        "worst_severity": worst.value,
        "total_estimated_loss_usd": round(total_loss_usd, 2),
        "worst_scenario_loss_usd": round(worst_loss_usd, 2),
        "notional": notional,
        "leverage": leverage,
        "scenarios": results_list,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    log.info(
        "Stress test complete — overall_passed=%s, worst=%s, total_loss=$%.2f",
        overall_passed, worst.value, total_loss_usd,
    )
    return report


def print_stress_report(report: dict) -> str:
    """Format a stress test report as a readable string."""
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        " 📊 STRESS TEST REPORT",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"  Overall:   {'✅ PASSED' if report['overall_passed'] else '🚨 FAILED'}",
        f"  Worst:     {report['worst_severity'].upper()}",
        f"  Notional:  ${report['notional']:,.2f}",
        f"  Leverage:  {report['leverage']}×",
        f"  Total Est. Loss: ${report['total_estimated_loss_usd']:,.2f}",
        "",
 ]
    for s in report["scenarios"]:
        icon = "✅" if s["passed"] else "🚨"
        lines.append(
            f"  {icon} [{s['scenario'].upper()}]  severity={s['severity'].upper()}"
        )
        lines.append(
            f"     Est. loss: {s['estimated_loss_pct']:.2f}% "
            f"(${s['estimated_loss_usd']:,.2f})"
        )
        lines.append(f" 💡 {s['recommendation']}")
        lines.append("")

    lines.append(f"  Generated: {report['timestamp']}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)
