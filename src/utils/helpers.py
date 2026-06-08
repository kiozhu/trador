"""JSON helpers — atomic write, formatting"""
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically: temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    shutil.move(tmp, path)


def read_json(path: Path) -> Any:
    """Read JSON file, return None if missing."""
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def format_price(price: float, decimals: int = 2) -> str:
    """Format price with commas."""
    return f"${price:,.{decimals}f}"


def format_pct(pct: float) -> str:
    """Format percentage with sign."""
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"
