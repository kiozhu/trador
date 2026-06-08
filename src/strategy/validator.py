"""Strategy validator — validate strategy JSON schema and hard limits"""
from typing import Any

from ..utils.logger import log

# Hard limits — cannot be exceeded even if Hermes suggests
HARD_LIMITS = {
    "sl_percent": -10,  # never wider than -10%
    "leverage": 5,
    "position.size_value": 20,  # max20% of wallet per trade
    "risk.max_hold_minutes": 60,
}


def validate_strategy(data: dict[str, Any]) -> tuple[bool, str]:
    """Validate strategy JSON structure and values.

    Returns (is_valid, error_message).
    """
    required_fields = ["id", "name", "indicators", "position", "risk"]
    for field in required_fields:
        if field not in data:
            return False, f"Missing required field: {field}"

    # Validate indicators
    indicators = data.get("indicators", {})
    if "ema_fast" not in indicators or "ema_slow" not in indicators:
        return False, "indicators.ema_fast and ema_slow required"

    if indicators["ema_fast"] >= indicators["ema_slow"]:
        return False, "indicators.ema_fast must be < ema_slow"

    # Validate position
    position = data.get("position", {})
    if "size_value" not in position:
        return False, "position.size_value required"
    if position["size_value"] <= 0 or position["size_value"] > HARD_LIMITS["position.size_value"]:
        return False, f"position.size_value must be 0-{HARD_LIMITS['position.size_value']}%"

    lev = position.get("leverage", 1)
    if lev < 1 or lev > HARD_LIMITS["leverage"]:
        return False, f"leverage must be 1-{HARD_LIMITS['leverage']}x"

    # Validate risk
    risk = data.get("risk", {})
    sl = risk.get("sl_percent", 0)
    if sl >= 0:
        return False, "risk.sl_percent must be negative"
    if sl < HARD_LIMITS["sl_percent"]:
        return False, f"risk.sl_percent cannot be below {HARD_LIMITS['sl_percent']}%"

    tp = risk.get("tp_percent", 0)
    if tp <= 0:
        return False, "risk.tp_percent must be positive"

    max_hold = risk.get("max_hold_minutes", 0)
    if max_hold > HARD_LIMITS["risk.max_hold_minutes"]:
        return False, f"max_hold_minutes cannot exceed {HARD_LIMITS['risk.max_hold_minutes']} min"

    return True, ""


def apply_hard_limits(data: dict[str, Any]) -> dict[str, Any]:
    """Clamp strategy values to hard limits."""
    # Deep-clone to avoid mutating original
    import copy
    data = copy.deepcopy(data)

    # Leverage
    if data.get("position", {}).get("leverage", 1) > HARD_LIMITS["leverage"]:
        data["position"]["leverage"] = HARD_LIMITS["leverage"]

    # Size
    if data.get("position", {}).get("size_value", 0) > HARD_LIMITS["position.size_value"]:
        data["position"]["size_value"] = HARD_LIMITS["position.size_value"]

    # SL
    if data.get("risk", {}).get("sl_percent", 0) < HARD_LIMITS["sl_percent"]:
        data["risk"]["sl_percent"] = HARD_LIMITS["sl_percent"]

    # Max hold
    if data.get("risk", {}).get("max_hold_minutes", 0) > HARD_LIMITS["risk.max_hold_minutes"]:
        data["risk"]["max_hold_minutes"] = HARD_LIMITS["risk.max_hold_minutes"]

    return data
