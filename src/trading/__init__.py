"""Trading engine package."""
from .engine import TradingEngine
from .position_manager import PositionManager

try:
    from .signals import generate_signal, compute_ema, compute_rsi, check_ema_crossover, compute_adx
except ImportError:
    pass

__all__ = ["TradingEngine", "PositionManager"]