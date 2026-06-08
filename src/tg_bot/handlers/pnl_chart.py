"""Generate PnL chart images for Telegram."""
from __future__ import annotations

import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


CHART_DIR = Path("memory/charts")
CHART_DIR.mkdir(parents=True, exist_ok=True)


def _load_trades():
    """Load trade history from memory/trades.json."""
    path = Path("memory/trades.json")
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("trades", [])
    return data


def _load_state():
    """Load state from memory/state.json."""
    path = Path("memory/state.json")
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def generate_pnl_chart(
    period: str = "7d",
    width: int = 14,
    height: int = 6,
) -> Optional[str]:
    """
    Generate a PnL line chart and save as PNG.

    period: '24h', '7d', '30d', 'all'
    Returns path to saved chart image, or None if no data.
    """
    trades = _load_trades()
    state = _load_state()

    if not trades:
        return None

    # filter by period
    now = datetime.now()
    if period == "24h":
        cutoff = now.timestamp() - 86400
    elif period == "7d":
        cutoff = now.timestamp() - 7 * 86400
    elif period == "30d":
        cutoff = now.timestamp() - 30 * 86400
    else:  # all
        cutoff = 0

    filtered = [
        t for t in trades
        if t.get("timestamp", 0) >= cutoff
    ]

    if not filtered:
        return None

    # build cumulative PnL series
    filtered.sort(key=lambda t: t.get("timestamp", 0))

    pnl_cumulative = []
    running = 0.0
    timestamps = []

    for t in filtered:
        pnl = float(t.get("pnl", 0) or 0)
        running += pnl
        pnl_cumulative.append(running)
        ts = t.get("timestamp")
        if ts:
            timestamps.append(datetime.fromtimestamp(ts))

    if not timestamps:
        return None

    # colors
    mode = state.get("mode", "dry_run")
    direction = state.get("direction", "both")
    is_live = mode == "live"

    line_color = "#00E676" if running >= 0 else "#FF5252"
    fill_color = "#00E676" if running >= 0 else "#FF5252"

    fig, ax = plt.subplots(figsize=(width, height), facecolor="#1E1E1E")
    ax.set_facecolor("#1E1E1E")
    ax.spines["bottom"].set_color("#444")
    ax.spines["left"].set_color("#444")
    ax.spines["top"].set_color("none")
    ax.spines["right"].set_color("none")
    ax.tick_params(colors="#CCC", labelsize=8)
    ax.yaxis.label.set_color("#CCC")
    ax.xaxis.label.set_color("#CCC")

    # grid
    ax.grid(True, alpha=0.15, color="#888", linewidth=0.5)
    ax.set_axisbelow(True)

    # fill under curve
    ax.fill_between(timestamps, pnl_cumulative, alpha=0.12, color=fill_color)

    # line
    ax.plot(
        timestamps,
        pnl_cumulative,
        color=line_color,
        linewidth=2,
        label=f"PNL ({period})",
    )

    # zero line
    ax.axhline(0, color="#666", linewidth=0.8, linestyle="--")

    # format x axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=30, ha="right", fontsize=7)

    # labels
    mode_label = "🔴 LIVE" if is_live else "🟡 DRY RUN"
    dir_label = direction.upper()
    strategy = state.get("active_strategy", "-")
    ax.set_title(
        f"📊 PnL Chart  |  {mode_label}  |  Direction: {dir_label}  |  Strategy: {strategy}",
        color="#FFF",
        fontsize=10,
        pad=10,
    )
    ax.set_ylabel("Cumulative PnL (USDT)", color="#CCC", fontsize=8)

    # final PnL annotation
    final = pnl_cumulative[-1]
    emoji = "🟢" if final >= 0 else "🔴"
    ax.annotate(
        f"{emoji} {final:+.2f} USDT",
        xy=(timestamps[-1], final),
        xytext=(8, 0),
        textcoords="offset points",
        color=line_color,
        fontsize=9,
        fontweight="bold",
    )

    plt.tight_layout()

    filename = f"pnl_{period}_{datetime.now().strftime('%H%M%S')}.png"
    out_path = CHART_DIR / filename
    plt.savefig(out_path, dpi=100, facecolor="#1E1E1E")
    plt.close(fig)

    return str(out_path)


def pnl_summary_text() -> str:
    """Return a text summary of PnL stats."""
    trades = _load_trades()
    state = _load_state()

    if not trades:
        return "📊 *PnL Summary*\n\n❌ Belum ada trade."

    # overall stats
    total_pnl = sum(float(t.get("pnl", 0) or 0) for t in trades)
    wins = [t for t in trades if float(t.get("pnl", 0) or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl", 0) or 0) < 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    mode = state.get("mode", "dry_run")
    mode_emoji = "🔴 LIVE" if mode == "live" else "🟡 DRY RUN"

    text = (
        f"📊 *PnL Summary*\n\n"
        f"Mode: {mode_emoji}\n"
        f"Total Trades: {len(trades)}\n"
        f"Win Rate: {win_rate:.1f}%\n"
        f"Wins: {len(wins)} | Losses: {len(losses)}\n"
        f"Total PnL: {total_pnl:+.2f} USDT\n"
    )

    # recent 5 trades
    recent = sorted(trades, key=lambda t: t.get("timestamp", 0), reverse=True)[:5]
    if recent:
        text += "\n*Recent Trades:*\n"
        for t in reversed(recent):
            pnl = float(t.get("pnl", 0) or 0)
            emoji = "🟢" if pnl >= 0 else "🔴"
            symbol = t.get("symbol", "?")
            direction = t.get("direction", "?")
            text += f"{emoji} {symbol} {direction.upper()} {pnl:+.2f}\n"

    return text