"""Telegram handlers package"""
from .menu import setup_menu_handlers
from .positions import setup_position_handlers
from .strategy import setup_strategy_handlers
from .trades import setup_trade_handlers
from .smart_mode import setup_smart_handlers
from .quick_actions import setup_quick_handlers

__all__ = [
    "setup_menu_handlers",
    "setup_position_handlers",
    "setup_strategy_handlers",
    "setup_trade_handlers",
    "setup_smart_handlers",
    "setup_quick_handlers",
]