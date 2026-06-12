"""AutoTrader — main trading loop that scans, generates signals, executes trades.
Phase 1: Integrated scanner-driven signal generation + rule-based scoring.
"""
import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Any

from ..utils.logger import log
from ..scanners import (
    WhaleScanner, LiquidationScanner, OrderbookScanner,
    VolumeProfileScanner, FundingScanner, SMCScanner,
)
from .engine import TradingEngine
from .risk_guard import RiskGuard, RiskGuardConfig, TradingMode
from .kelly_sizer import KellySizer
from .rolling_buffer import RollingBuffer
from .var_calc import compute_var
from . import stress_test as stress_test_module
from .strategies import StrategyScorer


class AutoTrader:
    """Continuously scans market via scanners + price action, generates signals, executes trades."""

    def __init__(
        self,
        engine: TradingEngine,
        state_mgr,
        loader,
        trade_log,
        perf,
        scan_interval: int = 8,
        hermes_reporter=None,
        risk_guard: RiskGuard | None = None,
    ):
        self.engine = engine
        self.state_mgr = state_mgr
        self.loader = loader
        self.trade_log = trade_log
        self.perf = perf
        self.scan_interval = scan_interval
        self.hermes_reporter = hermes_reporter  # HermesReporter instance for trade reporting
        self._task: asyncio.Task | None = None
        self.running = False

        # ── Risk Engine ──────────────────────────────────────────────────────────
        # RiskGuard — 10-layer pre-trade validation + kill/resume
        if risk_guard is not None:
            self.risk_guard = risk_guard
        else:
            # Default config from state
            state = state_mgr.get()
            cfg = RiskGuardConfig(
                max_open_positions=state.get("max_concurrent_positions", 5),
                max_trades_per_day=state.get("max_trades_per_day", 20),
                max_trades_per_hour=state.get("max_trades_per_hour", 5),
                daily_loss_limit_pct=state.get("daily_loss_limit_pct", 5.0),
            )
            self.risk_guard = RiskGuard(config=cfg, state_mgr=state_mgr)

        # KellySizer — dynamic position sizing
        self.kelly_sizer = KellySizer(base_kelly_pct=25.0, max_kelly_pct=50.0)

        # RollingBuffer — trade history stats (for Kelly adjustment factors)
        from pathlib import Path
        memory_dir = Path(__file__).parent.parent / "memory"
        self.rolling_buffer = RollingBuffer(maxlen=200, persist_path=memory_dir / "rolling_stats.json")

        # VaR cache (updated periodically)
        self._var_cache: dict = {}

        # ── Configurable symbol pool ─────────────────────────────────────────
        self.symbol_pool = [
            "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
            "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT",
            "MATIC/USDT", "LTC/USDT", "UNI/USDT", "ATOM/USDT", "ETC/USDT",
            "XLM/USDT", "ALGO/USDT", "AAVE/USDT", "FIL/USDT", "APE/USDT",
        ]

        # ── Scanner instances (Phase 1: all 6 scanners) ────────────────────────
        # Convert pool to lowercase no-slash format for scanner APIs
        _pool_keys = [s.lower().replace("/", "") for s in self.symbol_pool]
        self.scanners = {
            "whale": WhaleScanner(symbols=_pool_keys),
            "liquidation": LiquidationScanner(symbols=_pool_keys),
            "orderbook": OrderbookScanner(),
            "volume_profile": VolumeProfileScanner(),
            "funding": FundingScanner(symbols=_pool_keys),
            "smc": SMCScanner(symbols=_pool_keys),
        }
        self.max_symbols_per_scan = 10  # scan top N per cycle to avoid rate limits
        self._symbol_refresh_interval = 3600  # refresh pool every 60 min
        self._last_symbol_refresh = 0.0

        # ── Market regime ────────────────────────────────────────────────────
        self._market_regime = "sideway"  # "bullish", "bearish", "sideway"

        # ── Cooldown per symbol (avoid spam) ─────────────────────────────────
        self._cooldowns: dict[str, float] = {}  # symbol -> last trade time
        self._cooldown_seconds = 120

        # ── Last known scanner data ──────────────────────────────────────────
        self._whale_clusters: list = []
        self._liq_clusters: list = []
        self._orderbook_data: dict = {}
        self._ob_walls: list = []
        self._funding_snapshots: list = []
        self._smc_ob: list = []
        self._smc_fvg: list = []
        self._smc_sweeps: list = []
        self._smc_structure: list = []

        # ── Scanner warmup — give WS time to collect initial data ─────────────────
        self._warmup_seconds = 20  # seconds to wait before first scan cycle
        self._first_scan_done = False

    # ── Lifecycle ───────────────────────────────────────────────────────────────

    async def start(self):
        """Start scanners + trading loop."""
        self.running = True

        # Refresh symbol pool BEFORE starting scanners so they get correct symbols
        refreshed = await self._get_top_symbols(20)
        if refreshed:
            self.symbol_pool = refreshed
            _pool_keys = [s.lower().replace("/", "") for s in self.symbol_pool]
            # Update scanner symbol lists
            if "whale" in self.scanners:
                self.scanners["whale"].symbols = _pool_keys
            if "liquidation" in self.scanners:
                self.scanners["liquidation"].symbols = _pool_keys
            if "funding" in self.scanners:
                self.scanners["funding"].symbols = _pool_keys
            if "smc" in self.scanners:
                self.scanners["smc"].symbols = _pool_keys
            log.info("Symbol pool ready: %s", self.symbol_pool[:5])

        # Start all async scanners
        for name, scanner in self.scanners.items():
            if hasattr(scanner, 'start') and asyncio.iscoroutinefunction(scanner.start):
                asyncio.create_task(scanner.start())
            elif hasattr(scanner, 'start') and not asyncio.iscoroutinefunction(scanner.start):
                # sync scanner — run in thread pool
                loop = asyncio.get_event_loop()
                loop.run_in_executor(None, scanner.start)
            log.info("Scanner '%s' started", name)

        self._task = asyncio.create_task(self._loop())
        log.info("AutoTrader started (interval=%ds, pool=%d symbols)", self.scan_interval, len(self.symbol_pool))

    async def stop(self):
        """Stop scanners + loop."""
        self.running = False

        for name, scanner in self.scanners.items():
            if hasattr(scanner, 'stop'):
                if asyncio.iscoroutinefunction(scanner.stop):
                    await scanner.stop()
                else:
                    scanner.stop()

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("AutoTrader stopped")

    # ── Risk state sync ─────────────────────────────────────────────────────────

    async def _sync_risk_state(self):
        """Sync RiskGuard state to state_mgr for UI display."""
        state = self.state_mgr.get()
        mode = state.get("mode", "dry_run")
        balance_key = "dry_run_balance" if mode == "dry_run" else "live_balance"
        balance = state.get(balance_key, 10000)

        # Get open positions count
        mode = state.get("mode", "dry_run")
        open_pos = self.trade_log.get_active(mode=mode) if self.trade_log else []
        open_count = len(open_pos)

        # Get rolling stats
        stats = self.rolling_buffer.get_stats()
        win_rate = stats.win_rate / 100.0 if stats.win_rate else 0.55

        # VaR calculation (1d and 7d)
        var_cache_key = f"{balance_key}_{balance:.0f}"
        var_1d = self._var_cache.get(var_cache_key, {})
        if not var_1d:
            # Try to get BTC price for VaR
            try:
                import aiohttp
                async with aiohttp.ClientSession() as sess:
                    async with sess.get("https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT",
                                       timeout=aiohttp.ClientTimeout(total=3)) as r:
                        if r.status == 200:
                            data = await r.json()
                            btc_price = float(data["price"])
                            # Fetch 30d candles for VaR
                            async with sess.get(
                                "https://fapi.binance.com/fapi/v1/klines",
                                params={"symbol": "BTCUSDT", "interval": "1d", "limit": 30},
                                timeout=aiohttp.ClientTimeout(total=5)
                            ) as kr:
                                if kr.status == 200:
                                    klines = await kr.json()
                                    prices = [float(k[4]) for k in klines]
                                    notional = balance * 0.2  # 20% exposure
                                    var_cache_key_1d = f"{balance_key}_{balance:.0f}"
                                    var_cache_key_7d = f"{balance_key}_{balance:.0f}_7d"
                                    var_1d = compute_var(prices, notional, "historical", 0.95, 1)
                                    var_7d = compute_var(prices, notional, "historical", 0.95, 7)
                                    self._var_cache[var_cache_key_1d] = var_1d
                                    self._var_cache[var_cache_key_7d] = var_7d
            except Exception:
                pass

        var_cache_key = f"{balance_key}_{balance:.0f}"
        var_1d = self._var_cache.get(var_cache_key, {})
        var_7d = self._var_cache.get(var_cache_key + "_7d", {})

        # Kelly fraction (from KellySizer)
        kelly_pct = self.kelly_sizer.size(
            balance=balance,
            trade={"win_rate": win_rate, "open_positions": open_count,
                   "market_regime": self._market_regime},
            win_rate=win_rate,
            avg_win_pct=3.0,
            avg_loss_pct=-2.0,
        )

        # Daily PnL
        session_start = state.get("session_start_balance", balance)
        daily_pnl = balance - session_start
        daily_pnl_pct = (daily_pnl / session_start * 100) if session_start else 0

        # Risk state snapshot
        risk_state = {
            "risk_trading_enabled": not self.risk_guard.is_killed(),
            "risk_volatility_regime": self._market_regime,
            "risk_kelly_pct": round(kelly_pct, 2),
            "risk_var_1d_usd": var_1d.get("var_usd", 0),
            "risk_cvar_1d_usd": var_1d.get("cvar_usd", 0),
            "risk_var_7d_usd": var_7d.get("var_usd", 0),
            "risk_cvar_7d_usd": var_7d.get("cvar_usd", 0),
            "risk_daily_pnl_usd": round(daily_pnl, 2),
            "risk_daily_pnl_pct": round(daily_pnl_pct, 2),
            "risk_open_positions": open_count,
            "risk_consecutive_losses": self.risk_guard._consecutive_losses,
            "risk_killswitch_reason": self.risk_guard.killswitch_reason(),
            "sideways_mode": self.risk_guard._sideways_mode,
        }
        self.state_mgr.update(**risk_state)

    # ── Main loop ───────────────────────────────────────────────────────────────

    async def _loop(self):
        """Main scan loop — runs every scan_interval seconds."""
        while self.running:
            try:
                await self._scan_and_trade()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("AutoTrader loop error: %s", e)
            await asyncio.sleep(self.scan_interval)

    async def _scan_and_trade(self):
        """Full scan cycle: market regime → candidate scoring → execute top signals."""
        # ── Warmup: wait for scanners to collect initial data ─────────────────
        if not self._first_scan_done:
            log.info("AutoTrader warming up — waiting %ds for scanner data...", self._warmup_seconds)
            await asyncio.sleep(self._warmup_seconds)
            self._first_scan_done = True

        state = self.state_mgr.get()

        # Sync state with actual AutoTrader status
        if self.running and state.get("bot_status") != "running":
            self.state_mgr.set_status("running")

        # ── Handle _risk_action from Telegram UI ───────────────────────────
        risk_action = state.get("_risk_action", "")
        if risk_action == "kill":
            self.risk_guard.kill("Manual kill via UI")
            self.state_mgr.set("_risk_action", "")
        elif risk_action == "resume":
            self.risk_guard.resume()
            self.state_mgr.set("_risk_action", "")

        # ── Sync sideways mode from state to risk_guard ──────────────────
        self.risk_guard.sync_sideways_mode(state)
        # ── Sync time filter enabled from state to risk_guard ───────────────
        if hasattr(self.risk_guard.config, 'time_filter_enabled'):
            tfe = state.get("time_filter_enabled", False)
            self.risk_guard.set_config(time_filter_enabled=tfe)

        # ── Sync risk state to state_mgr (for UI display) ─────────────────
        await self._sync_risk_state()

        if not state.get("trading_enabled", False):
            return

        mode = state.get("mode", "dry_run")
        direction = state.get("direction", "both")

        # ── Get all active strategies ─────────────────────────────────────────
        active_strategies = self.loader.list_active() if self.loader else []
        if not active_strategies:
            strategies = self.loader.list_all() if self.loader else []
            if not strategies:
                return
            active_strategies = [strategies[0]]

        strategy = active_strategies[0]

        log.info("AutoTrader cycle | regime=%s | direction=%s | strategies=%s | pool=%d symbols",
                 self._market_regime, direction,
                 [s.get("id","?") for s in active_strategies],
                 len(self.symbol_pool))
        now = datetime.now(timezone.utc).timestamp()
        if now - self._last_symbol_refresh > self._symbol_refresh_interval:
            self.symbol_pool = await self._get_top_symbols(20)
            self._last_symbol_refresh = now
            log.info("Symbol pool refreshed: %s", self.symbol_pool[:5])

        # ── Step 2: Market regime detection ────────────────────────────────
        self._market_regime = await self._detect_market_regime(strategy)
        log.info("AutoTrader cycle | regime=%s | direction=%s | strategy=%s | pool=%d symbols",
                 self._market_regime, direction, strategy.get("id", "unknown"), len(self.symbol_pool))

        # ── Step 2: Collect scanner data ───────────────────────────────────
        await self._collect_scanner_data()

        # ── Step 3: Score all candidates ───────────────────────────────────
        smart_mode = state.get("smart_mode", False)

        if smart_mode and len(active_strategies) > 1:
            # Smart Mode: score ALL strategies on ALL symbols once, cache per symbol
            # Then merge all candidates and pick top 2
            smart_candidates = []
            # Cache: key = (symbol, timeframe) → candles to avoid redundant HTTP calls
            _candles_cache: dict[tuple[str, str], list] = {}

            async def _get_cached_candles(symbol: str, tf: str) -> list:
                key = (symbol, tf)
                if key not in _candles_cache:
                    c = await self.engine.fetch_ohlcv(symbol, tf, limit=100)
                    if not c or len(c) < 50:
                        c = await self._get_candles_fallback(symbol, tf, 100)
                    _candles_cache[key] = c
                return _candles_cache[key]

            for strat in active_strategies:
                for sym in self.symbol_pool[:self.max_symbols_per_scan]:
                    try:
                        last_trade = self._cooldowns.get(sym, 0)
                        if (datetime.now(timezone.utc).timestamp() - last_trade) < self._cooldown_seconds:
                            continue
                        signal = await self._check_symbol_with_candles(sym, strat, direction, _get_cached_candles)
                        if signal and signal.get("score", 0) >= signal.get("min_score", 65):
                            smart_candidates.append(signal)
                    except Exception as e:
                        log.debug("Smart scoring error %s: %s", sym, e)

            if smart_candidates:
                smart_candidates.sort(key=lambda x: x["score"], reverse=True)
                candidates = smart_candidates[:2]
                log.info("Smart Mode: %d strategies × %d symbols → %d signals, top=%.0f",
                         len(active_strategies), self.max_symbols_per_scan,
                         len(smart_candidates), smart_candidates[0]["score"])
            else:
                candidates = []
        else:
            # Normal mode: single strategy scoring
            candidates = await self._score_candidates(strategy, direction)

        if not candidates:
            await self._log_cycle_summary(mode=mode, candidates=[], trades_executed=0, regime=self._market_regime)
            return

        # ── Step 4: Execute top candidate(s) ───────────────────────────────
        # ENFORCE max_orders_per_cycle from state
        max_orders_per_cycle = state.get("max_orders_per_cycle", 2)
        max_orders_per_cycle = max(1, min(max_orders_per_cycle, 10))  # clamp to 1-10

        state = self.state_mgr.get()
        mode = state.get("mode", "dry_run")
        balance_key = "dry_run_balance" if mode == "dry_run" else "live_balance"
        balance = state.get(balance_key, 10000)

        # Count current open positions
        open_count = len(self.trade_log.get_active(mode=mode)) if self.trade_log else 0
        remaining_slots = max(0, max_orders_per_cycle - open_count)
        if remaining_slots == 0:
            log.info("Max positions reached (%d/%d) — skipping cycle", open_count, max_orders_per_cycle)
            await self._log_cycle_summary(mode=mode, candidates=[], trades_executed=0, regime=self._market_regime)
            return

        candidates = candidates[:remaining_slots]  # never execute more than remaining slots

        for candidate in candidates:
            state = self.state_mgr.get()
            mode = state.get("mode", "dry_run")
            # In normal mode all candidates come from the same strategy; in smart mode
            # the strategy is not needed for execution (signal already scored)
            best_strategy = strategy
            # ── RiskGuard pre-trade validation ──────────────────────────
            trade_for_check = {
                "symbol": candidate["symbol"],
                "side": candidate["side"],
                "size_value": state.get("balance_per_trade_pct", 10),
                "open_positions": self.trade_log.get_active(mode=mode) if self.trade_log else [],
                "market_regime": self._market_regime,
                "atr_pct": candidate.get("atr_pct", 0),
            }
            can_trade, risk_results = self.risk_guard.can_trade(trade_for_check, balance)
            if not can_trade:
                blocked = [r for r in risk_results if not r.passed]
                log.warning("RiskGuard blocked %s %s: %s",
                            candidate["symbol"], candidate["side"],
                            blocked[0].reason if blocked else "unknown")
                continue
            # ── End RiskGuard check ──────────────────────────────────────

            await self._execute_trade(candidate, best_strategy, mode)

    async def _detect_market_regime(self, strategy: dict) -> str:
        """Detect if market is bullish, bearish, or sideway using EMA slope + trend indicators."""
        try:
            # Use BTC as market proxy
            tf = strategy.get("timeframe", "1h")
            candles = await self.engine.fetch_ohlcv("BTC/USDT", tf, limit=50)
            if not candles or len(candles) < 30:
                return "sideway"

            closes = [c[4] for c in candles[-30:]]
            ema20 = self._ema(closes, 20)
            ema50 = self._ema(closes, 50)

            ema20_slope = (ema20 - self._ema(closes[:-10], 20)) / self._ema(closes[:-10], 20)
            ema50_slope = (ema50 - self._ema(closes[:-10], 50)) / self._ema(closes[:-10], 50)

            # ── Volatility check — skip if too narrow (chop) ──────────────
            # ATR-style: (max-high - min-low) / mid price as %
            highs = [c[2] for c in candles[-30:]]
            lows  = [c[3] for c in candles[-30:]]
            max_high = max(highs)
            min_low  = min(lows)
            atr_pct  = (max_high - min_low) / max_high * 100

            if atr_pct < 0.3:
                return "sideway"  # too choppy

            # ── EMA slope direction ─────────────────────────────────────────
            # Use very small threshold — even slight trend qualifies
            if ema20_slope > 0.001 and ema50_slope > 0.0005:
                return "bullish"
            elif ema20_slope < -0.001 and ema50_slope < -0.0005:
                return "bearish"
            else:
                return "sideway"

        except Exception as e:
            log.debug("Regime detection error: %s", e)
            return "sideway"

    # ── Scanner data collection ─────────────────────────────────────────────────

    async def _collect_scanner_data(self):
        """Pull latest data from all running scanners."""
        # Whale clusters
        whale_scanner = self.scanners["whale"]
        self._whale_clusters = whale_scanner.get_active_clusters()

        # Liquidation clusters
        liq_scanner = self.scanners["liquidation"]
        self._liq_clusters = liq_scanner.get_active_clusters()

        # Orderbook avg tops + wall data
        ob_scanner = self.scanners["orderbook"]
        with ob_scanner._lock:
            self._orderbook_data = dict(ob_scanner._avg_top)
            # Also extract wall ratios if available from the scanner's wall events
            self._ob_walls = getattr(ob_scanner, "_recent_walls", [])

        # Funding rate snapshots
        funding_scanner = self.scanners["funding"]
        self._funding_snapshots = funding_scanner.get_active()

        # SMC scanner data
        smc_scanner = self.scanners["smc"]
        self._smc_ob = smc_scanner.get_active_ob()
        self._smc_fvg = smc_scanner.get_active_fvg()
        self._smc_sweeps = smc_scanner.get_active_sweeps()
        self._smc_structure = smc_scanner.get_active_structure()

    # ── Candidate scoring ────────────────────────────────────────────────────────

    async def _score_candidates(self, strategy: dict, direction: str) -> list[dict]:
        """Score all symbols — return sorted list of trade signals above threshold."""
        scored = []

        # Select symbols to scan (cap at max per cycle)
        symbols_to_scan = self.symbol_pool[:self.max_symbols_per_scan]

        for symbol in symbols_to_scan:
            try:
                # Skip if on cooldown
                last_trade = self._cooldowns.get(symbol, 0)
                if (datetime.now(timezone.utc).timestamp() - last_trade) < self._cooldown_seconds:
                    continue

                signal = await self._check_symbol(symbol, strategy, direction)
                if signal and signal.get("score", 0) >= signal.get("min_score", 65):
                    scored.append(signal)
            except Exception as e:
                log.debug("Scoring error for %s: %s", symbol, e)

        # Sort by score descending
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    async def _check_symbol_with_candles(
        self, symbol: str, strategy: dict, direction: str,
        get_candles_fn
    ) -> dict | None:
        """Same as _check_symbol but accepts a candle-fetching function for caching."""
        try:
            candles = await get_candles_fn(symbol, strategy.get("timeframe", "15m"))
            if not candles or len(candles) < 50:
                return None

            closes = [c[4] for c in candles[-50:]]
            indicators = strategy.get("indicators", {})
            ema_fast_p = indicators.get("ema_fast", 9)
            ema_mid_p = indicators.get("ema_mid", 21)
            ema_slow_p = indicators.get("ema_slow", 50)

            ema_fast = self._ema(closes, ema_fast_p)
            ema_mid = self._ema(closes, ema_mid_p)
            ema_slow = self._ema(closes, ema_slow_p)
            prev_fast = self._ema(closes[:-3], ema_fast_p)
            prev_mid = self._ema(closes[:-3], ema_mid_p)

            bullish_cross = prev_fast <= prev_mid and ema_fast > ema_mid
            bearish_cross = prev_fast >= prev_mid and ema_fast < ema_mid
            bull_align = ema_fast > ema_mid > ema_slow
            bear_align = ema_fast < ema_mid < ema_slow

            rsi = self._rsi(closes, 14)
            oversold = rsi < 35
            overbought = rsi > 65

            long_signal = bullish_cross or bull_align or oversold
            short_signal = bearish_cross or bear_align or overbought

            if not long_signal and not short_signal:
                return None

            if direction == "long" and not long_signal:
                return None
            if direction == "short" and not short_signal:
                return None
            if self._market_regime == "sideway":
                return None

            if bullish_cross or bull_align:
                side = "LONG"
                entry_price = closes[-1]
            elif oversold:
                side = "LONG"
                entry_price = closes[-1]
            elif bearish_cross or bear_align:
                side = "SHORT"
                entry_price = closes[-1]
            elif overbought:
                side = "SHORT"
                entry_price = closes[-1]
            else:
                return None

            # ── Scanner scoring ────────────────────────────────────────────
            score = 50
            scanner_signals = []

            if bullish_cross or bearish_cross:
                score += 15
                scanner_signals.append("ema_cross")
            elif bull_align or bear_align:
                score += 10
                scanner_signals.append("ema_align")
            elif oversold:
                score += 10
                scanner_signals.append(f"rsi_oversold({rsi:.0f})")
            elif overbought:
                score += 10
                scanner_signals.append(f"rsi_overbought({rsi:.0f})")

            whale_score = self._score_whale(symbol, side)
            score += whale_score
            if whale_score > 0:
                scanner_signals.append(f"whale+{whale_score}")

            liq_score = self._score_liquidation(symbol, side)
            score += liq_score
            if liq_score > 0:
                scanner_signals.append(f"liq+{liq_score}")

            vp_score = self._score_volume_profile(symbol, entry_price)
            score += vp_score
            if vp_score > 0:
                scanner_signals.append(f"vp+{vp_score}")

            funding_score = self._score_funding_rate(symbol, side)
            score += funding_score
            if funding_score != 0:
                scanner_signals.append(f"funding{funding_score:+d}")

            smc_score = self._score_smc(symbol, side, entry_price)
            score += smc_score
            if smc_score > 0:
                scanner_signals.append(f"smc+{smc_score}")

            ob_score = self._score_orderbook(symbol, side, entry_price)
            score += ob_score
            if ob_score > 0:
                scanner_signals.append(f"ob+{ob_score}")

            min_score = strategy.get("min_score", 65)

            return {
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "score": score,
                "min_score": min_score,
                "leverage": strategy.get("position", {}).get("leverage", 3),
                "sl_pct": strategy.get("risk", {}).get("sl_percent", 2),
                "tp_pct": strategy.get("risk", {}).get("tp_percent", 4),
                "scanner_signals": ", ".join(scanner_signals),
                "strategy_id": strategy.get("id", "unknown"),
            }
        except Exception:
            return None

    async def _check_symbol(self, symbol: str, strategy: dict, direction: str) -> dict | None:
        """Full check on a single symbol: price action + scanners + regime alignment."""
        try:
            tf = strategy.get("timeframe", "15m")
            candles = await self.engine.fetch_ohlcv(symbol, tf, limit=100)
            if not candles or len(candles) < 50:
                # Fallback synthetic candles
                candles = await self._get_candles_fallback(symbol, tf, 100)

            closes = [c[4] for c in candles[-50:]]

            # ── Price action signals ───────────────────────────────────────
            indicators = strategy.get("indicators", {})
            ema_fast_p = indicators.get("ema_fast", 9)
            ema_mid_p = indicators.get("ema_mid", 21)
            ema_slow_p = indicators.get("ema_slow", 50)

            ema_fast = self._ema(closes, ema_fast_p)
            ema_mid = self._ema(closes, ema_mid_p)
            ema_slow = self._ema(closes, ema_slow_p)

            prev_fast = self._ema(closes[:-3], ema_fast_p)
            prev_mid = self._ema(closes[:-3], ema_mid_p)

            # EMA crossover detection
            bullish_cross = prev_fast <= prev_mid and ema_fast > ema_mid
            bearish_cross = prev_fast >= prev_mid and ema_fast < ema_mid

            # EMA alignment (trend confirmation)
            bull_align = ema_fast > ema_mid > ema_slow
            bear_align = ema_fast < ema_mid < ema_slow

            # ── RSI momentum (mean-reversion signal) ─────────────────────────
            rsi = self._rsi(closes, 14)
            oversold = rsi < 35
            overbought = rsi > 65

            # ── Build signal from ANY strong indicator ─────────────────────
            # Long: bull cross OR bull align OR (oversold AND not overbought)
            # Short: bear cross OR bear align OR (overbought AND not oversold)
            long_signal = bullish_cross or bull_align or oversold
            short_signal = bearish_cross or bear_align or overbought

            if not long_signal and not short_signal:
                return None

            # ── Direction filter ────────────────────────────────────────────
            if direction == "long" and not long_signal:
                return None
            if direction == "short" and not short_signal:
                return None

            # ── Regime filter (hard block for sideway) ───────────────────────────
            # Sideway = no trades at all (price too choppy)
            if self._market_regime == "sideway":
                return None

            # ── Determine side + entry ────────────────────────────────────
            if bullish_cross or bull_align:
                side = "LONG"
                entry_price = closes[-1]
            elif oversold:
                side = "LONG"
                entry_price = closes[-1]
            elif bearish_cross or bear_align:
                side = "SHORT"
                entry_price = closes[-1]
            elif overbought:
                side = "SHORT"
                entry_price = closes[-1]
            else:
                return None

            # ── Scanner scoring ────────────────────────────────────────────
            score = 50  # base: momentum signal
            scanner_signals = []

            # Signal type bonus
            if bullish_cross or bearish_cross:
                score += 15
                scanner_signals.append("ema_cross")
            elif bull_align or bear_align:
                score += 10
                scanner_signals.append("ema_align")
            elif oversold:
                score += 10
                scanner_signals.append(f"rsi_oversold({rsi:.0f})")
            elif overbought:
                score += 10
                scanner_signals.append(f"rsi_overbought({rsi:.0f})")

            # Whale signal
            whale_score = self._score_whale(symbol, side)
            score += whale_score
            if whale_score > 0:
                scanner_signals.append(f"whale+{whale_score}")

            # Liquidation cluster signal
            liq_score = self._score_liquidation(symbol, side)
            score += liq_score
            if liq_score > 0:
                scanner_signals.append(f"liq+{liq_score}")

            # Volume profile signal
            vp_score = self._score_volume_profile(symbol, entry_price)
            score += vp_score
            if vp_score > 0:
                scanner_signals.append(f"vp+{vp_score}")

            # Funding rate signal
            funding_score = self._score_funding_rate(symbol, side)
            score += funding_score
            if funding_score != 0:
                scanner_signals.append(f"funding{funding_score:+d}")

            # SMC signal
            smc_score = self._score_smc(symbol, side, entry_price)
            score += smc_score
            if smc_score > 0:
                scanner_signals.append(f"smc+{smc_score}")

            # Orderbook wall signal
            ob_score = self._score_orderbook(symbol, side, entry_price)
            score += ob_score
            if ob_score > 0:
                scanner_signals.append(f"ob+{ob_score}")

            # ── Risk params ────────────────────────────────────────────────
            risk = strategy.get("risk", {}) or {}
            sl_pct = abs(risk.get("sl_percent", 2) or 2)
            tp_pct = risk.get("tp_percent", 2) or 2
            leverage = strategy.get("position", {}).get("leverage", 3)

            return {
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "sl_pct": sl_pct,
                "tp_pct": tp_pct,
                "leverage": leverage,
                "score": score,
                "min_score": 50,  # lowered from 65 — allow more signals through
                "scanner_signals": scanner_signals,
            }

        except Exception as e:
            log.error("Symbol check error %s: %s", symbol, e)
            return None

    def _score_whale(self, symbol: str, side: str) -> int:
        """Score whale clusters for a symbol. +20 if strong cluster on same side."""
        clusters = [c for c in self._whale_clusters if c.symbol == symbol.lower().replace("/", "")]
        if not clusters:
            return 0

        side_clusters = [c for c in clusters if c.side == side]
        if not side_clusters:
            # Counter-trend whale — negative signal
            return -10

        total_qty = sum(c.total_quote_qty for c in side_clusters)
        if total_qty > 500_000:
            return 20
        elif total_qty > 200_000:
            return 15
        elif total_qty > 50_000:
            return 10
        return 0

    def _score_liquidation(self, symbol: str, side: str) -> int:
        """Score liquidation clusters. +15 if cluster on same side (indicates squeeze)."""
        clusters = [c for c in self._liq_clusters if c.symbol == symbol.lower().replace("/", "")]
        if not clusters:
            return 0

        # Long liquidation = short squeeze potential (buy signal)
        # Short liquidation = long squeeze potential (sell signal)
        counter_side = "SELL" if side == "LONG" else "BUY"

        counter_clusters = [c for c in clusters if c.side == counter_side]
        if counter_clusters:
            total = sum(c.total_qty for c in counter_clusters)
            if total > 100_000:
                return 15
            elif total > 50_000:
                return 10

        return 0

    def _score_volume_profile(self, symbol: str, current_price: float) -> int:
        """Score volume profile. +10 if price within 0.5% of POC (high probability revert)."""
        vp_scanner = self.scanners.get("volume_profile")
        if not vp_scanner:
            return 0

        sym_key = symbol.lower().replace("/", "")
        with vp_scanner._lock:
            profile = vp_scanner._profiles.get(sym_key)
        if not profile:
            return 0

        # Price within 0.5% of POC = high volume concentration zone
        if current_price > 0 and profile.poc > 0:
            deviation = abs(current_price - profile.poc) / profile.poc
            if deviation <= 0.005:
                return 10
            elif deviation <= 0.01:
                return 5
        return 0

    def _score_funding_rate(self, symbol: str, side: str) -> int:
        """Score funding rate bias. +15 for extreme rates that squeeze against the other side.

        Positive funding rate = longs pay shorts (bearish bias for longs).
        Negative funding rate = shorts pay longs (bullish bias for shorts).

        High funding rate (> 0.01% = 0.0001) on the opposite side = squeeze potential.
        """
        sym_key = symbol.lower().replace("/", "")
        snapshot = None
        for s in self._funding_snapshots:
            if s.symbol == sym_key:
                snapshot = s
                break
        if not snapshot:
            return 0

        rate = snapshot.rate

        # Extreme funding rate (> 0.01% per 8h) signals strong sentiment
        # Counter-side liquidity pool = squeeze setup
        if rate > 0.0003:  # 0.03% per funding cycle
            # High positive = longs paying = bearish for long positions
            if side == "SHORT":
                return 15  # Short squeeze likely
            elif side == "LONG":
                return -5   # Headwind for longs
        elif rate < -0.0003:
            # High negative = shorts paying = bullish for short positions
            if side == "LONG":
                return 15  # Long squeeze likely
            elif side == "SHORT":
                return -5   # Headwind for shorts

        return 0

    def _score_orderbook(self, symbol: str, side: str, entry_price: float) -> int:
        """Score orderbook walls from recent wall events.
        +15 for wall on same side near entry, +10 for wall within 0.5%, -5 counter-side."""
        if not self._ob_walls:
            return 0

        sym_key = symbol.lower().replace("/", "")
        score = 0

        # Get walls for this symbol from last 5 minutes
        cutoff = datetime.now(timezone.utc).timestamp() - 300
        recent = [w for w in self._ob_walls if w.symbol == sym_key and w.local_time.timestamp() > cutoff]

        if not recent:
            return 0

        for wall in recent:
            if wall.side == "BID":
                # Bid wall (buy wall) = support zone
                price_diff_pct = abs(entry_price - wall.price) / entry_price * 100
                if side == "LONG" and price_diff_pct < 0.5:
                    score += 15
                elif side == "SHORT":
                    score -= 5
            elif wall.side == "ASK":
                # Ask wall (sell wall) = resistance zone
                price_diff_pct = abs(entry_price - wall.price) / entry_price * 100
                if side == "SHORT" and price_diff_pct < 0.5:
                    score += 15
                elif side == "LONG":
                    score -= 5

        # Cap score
        return min(score, 20)

    def _score_smc(self, symbol: str, side: str, entry_price: float) -> int:
        """Score SMC signals: Order Blocks, FVG, Liquidity Sweeps, Market Structure.
        +15 for same-side OB/FVG, +10 for structure confirmation, +10 for sweep reversal.
        """
        sym_key = symbol.lower().replace("/", "")
        score = 0

        # ── Order Blocks ───────────────────────────────────────────────────
        for ob in self._smc_ob:
            if ob.symbol != sym_key:
                continue
            # Bullish OB zone: price retracing into the zone = buy opportunity
            if ob.ob_type.value == "bullish_ob" and side == "LONG":
                if ob.zone_low <= entry_price <= ob.zone_high:
                    score += 15
            elif ob.ob_type.value == "bearish_ob" and side == "SHORT":
                if ob.zone_low <= entry_price <= ob.zone_high:
                    score += 15

        # ── Fair Value Gaps ────────────────────────────────────────────────
        for fvg in self._smc_fvg:
            if fvg.symbol != sym_key:
                continue
            if fvg.direction.value == "bullish_fvg" and side == "LONG":
                score += 10
            elif fvg.direction.value == "bearish_fvg" and side == "SHORT":
                score += 10

        # ── Liquidity Sweeps ───────────────────────────────────────────────
        for sweep in self._smc_sweeps:
            if sweep.symbol != sym_key:
                continue
            # Sweep of low → reversal up = LONG signal
            if sweep.direction.value == "bullish_sweep" and side == "LONG":
                score += 10
            # Sweep of high → reversal down = SHORT signal
            elif sweep.direction.value == "bearish_sweep" and side == "SHORT":
                score += 10

        # ── Market Structure ───────────────────────────────────────────────
        for struct in self._smc_structure:
            if struct.symbol != sym_key:
                continue
            if struct.direction.value == "bullish_structure" and side == "LONG":
                score += 10
            elif struct.direction.value == "bearish_structure" and side == "SHORT":
                score += 10

        return score

    # ── Execute trade ──────────────────────────────────────────────────────────

    async def _execute_trade(self, signal: dict, strategy: dict, mode: str):
        """Execute a scored trade signal."""
        symbol = signal["symbol"]
        side = signal["side"]
        entry = signal["entry_price"]
        sl_pct = signal.get("sl_pct", 2)
        tp_pct = signal.get("tp_pct", 2)
        leverage = signal["leverage"]

        # Calculate SL/TP prices
        if side == "LONG":
            sl_price = entry * (1 - sl_pct / 100)
            tp_price = entry * (1 + tp_pct / 100)
        else:
            sl_price = entry * (1 + sl_pct / 100)
            tp_price = entry * (1 - tp_pct / 100)

        position = strategy.get("position", {})
        size_type = position.get("size_type", "fixed_percent")
        state = self.state_mgr.get()

        # ── Position sizing ──────────────────────────────────────────────
        sizing_mode = state.get("position_sizing_mode", "fixed_percent")
        llm_enabled = state.get("llm_enabled", False)
        mode = state.get("mode", "dry_run")
        balance_key = "dry_run_balance" if mode == "dry_run" else "live_balance"
        balance = state.get(balance_key, 10000)
        max_pos_pct = state.get("max_position_size_pct", 20)
        fixed_pct = state.get("balance_per_trade_pct", 10)

        if llm_enabled and sizing_mode == "llm_smart":
            # LLM decides size
            from ..llm import LLMScorer
            import os
            minimax_key = os.getenv("MINIMAX_API_KEY", "")
            if minimax_key:
                scorer = LLMScorer(minimax_key)
                size_pct = scorer.position_size(balance, signal, self._market_regime)
                size_pct = min(size_pct, max_pos_pct)  # Safety cap
            else:
                # Fallback to Kelly sizing
                kelly_pct = self.kelly_sizer.size(
                    balance=balance,
                    trade={
                        "win_rate": 0.55,
                        "open_positions": len(self.trade_log.get_active(mode=mode)) if self.trade_log else 0,
                        "market_regime": self._market_regime,
                        "atr_pct": 1.5,
                    },
                    win_rate=0.55,
                    avg_win_pct=3.0,
                    avg_loss_pct=-2.0,
                )
                size_pct = min(kelly_pct, max_pos_pct)
        else:
            # Use KellySizer for dynamic sizing (replaces fixed_pct)
            kelly_pct = self.kelly_sizer.size(
                balance=balance,
                trade={
                    "win_rate": 0.55,
                    "open_positions": len(self.trade_log.get_active(mode=mode)) if self.trade_log else 0,
                    "market_regime": self._market_regime,
                    "atr_pct": 1.5,
                },
                win_rate=0.55,
                avg_win_pct=3.0,
                avg_loss_pct=-2.0,
            )
            size_pct = min(kelly_pct, max_pos_pct)

        trade = {
            "id": f"auto_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "side": side,
            "entry_price": entry,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "leverage": leverage,
            "size_type": sizing_mode,
            "size_value": size_pct,  # % of balance
            "strategy_id": strategy.get("id"),
            "mode": mode,
            "status": "open",
            "pnl": 0,
            "pnl_pct": 0,
            "score": signal.get("score", 0),
            "scanner_signals": signal.get("scanner_signals", []),
            "balance_at_entry": balance,
        }

        if mode == "dry_run":
            result = await self._simulate_trade(trade)
            self.trade_log.add(result)
            self.perf.update(mode=mode)

            # ── Update RollingBuffer (for Kelly adjustment factors) ───
            self.rolling_buffer.add(result)

            # ── Update RiskGuard with trade outcome ──────────────────────
            self.risk_guard.record_trade_result(result.get("pnl_pct", 0))
            self.risk_guard.update_balance(balance + result.get("pnl", 0))

            if self.hermes_reporter:
                self.hermes_reporter.write_trade(result)

            # Update mode-specific balance
            balance_key = "dry_run_balance" if mode == "dry_run" else "live_balance"
            balance = state.get(balance_key, 10000 if mode == "dry_run" else 0)
            pnl_amt = result.get("pnl", 0)
            new_balance = balance + pnl_amt
            self.state_mgr.set(balance_key, new_balance)

            # Increment trade count
            trades_key = "dry_run_trades" if mode == "dry_run" else "live_trades"
            cur_trades = state.get(trades_key, 0)
            self.state_mgr.set(trades_key, cur_trades + 1)

            self._cooldowns[symbol] = datetime.now(timezone.utc).timestamp()
            # Sync state
            self.state_mgr.update(
                last_trade_at=datetime.now(timezone.utc).isoformat(),
                open_positions=len(self.trade_log.get_active(mode=mode)),
            )
            log.info(
                "═══════════════════════════════════════════",
            )
            log.info(
                "▶ ENTRY  %s  %s @ %.4f  |  Lev: %dx  |  Size: %.1f%%  |  Bal: $%.2f",
                side, symbol, entry, leverage, size_pct, balance,
            )
            log.info(
                "  Signal: %s  |  Score: %d  |  Scanner: %s",
                signal.get("strategy", "?"), signal["score"],
                ", ".join(signal.get("scanner_signals", [])) or "none",
            )
            log.info(
                "  TP: %.2f%% → %.4f  |  SL: %.2f%% → %.4f",
                tp_pct, tp_price, sl_pct, sl_price,
            )
            log.info(
                "  Regime: %s  |  Direction: %s  |  Cooldown: %ds",
                self._market_regime, self.state_mgr.get().get("direction", "both"), self._cooldown_seconds,
            )
            log.info(
                "═══════════════════════════════════════════",
            )
            log.info(
                "  ✅ CLOSED @ %.4f  |  %s  |  PnL: %+.2f%%  |  $%+.2f  |  Bal: $%.2f",
                trade.get("exit_price", entry), trade.get("exit_reason", "?").upper(),
                result.get("pnl_pct", 0), result.get("pnl", 0), new_balance,
            )
        else:
            try:
                result = await self.engine.place_order(
                    symbol=symbol,
                    side=side.lower(),
                    order_type="limit",
                    amount=size_pct,
                    price=entry,
                    sl_pct=sl_pct,
                    tp_pct=tp_pct,
                    leverage=leverage,
                )
                trade["order_id"] = result.get("id")
                trade["status"] = "open"
                self.trade_log.add(trade)
                self._cooldowns[symbol] = datetime.now(timezone.utc).timestamp()
                if self.hermes_reporter:
                    self.hermes_reporter.write_trade(trade)
                trades_key = "live_trades"
                cur_trades = state.get(trades_key, 0)
                self.state_mgr.set(trades_key, cur_trades + 1)
                log.info("🟢 LIVE ORDER placed: %s %s @ %.4f (score=%d, size=%.1f%%, lev=%d)",
                    side, symbol, entry, signal["score"], size_pct, leverage)
            except Exception as e:
                log.error("Live order failed: %s", e)

    # ═══════════════════════════════════════════════════════════════════════
    # CYCLE SUMMARY — logged at end of each _scan_and_trade cycle
    # ═══════════════════════════════════════════════════════════════════════
    async def _log_cycle_summary(self, mode, candidates, trades_executed, regime):
        """Print end-of-cycle summary."""
        state = self.state_mgr.get()
        perf = self.perf.get(mode=mode) if self.perf else {}
        bal = state.get(f"{mode}_balance", 0)
        stats = perf.get("stats", {})
        win_r = stats.get("win_rate", 0)
        total = stats.get("total_trades", 0)
        log.info(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        )
        log.info(
            "  📊 CYCLE DONE  |  regime=%s  |  candidates=%d  |  executed=%d",
            regime, len(candidates), trades_executed,
        )
        log.info(
            "  💰 Balance: $%.2f  |  Total PnL: %+.2f%%  |  Win Rate: %.0f%%  |  Trades: %d",
            bal, stats.get("total_pnl_pct", 0), win_r * 100 if win_r else 0, total,
        )
        log.info(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        )

    async def _simulate_trade(self, trade: dict) -> dict:
        """Simulate trade with real Binance price data + accurate fees.
        
        Entry: real Binance Futures current price
        Exit:  real Binance Futures price (checked via API)
        Fee:  Binance Futures maker 0.02% / taker 0.04%
        PnL:  position_value × leverage × (price_move%) - fees
        """
        import random, aiohttp
        symbol = trade.get("symbol", "BTC/USDT")
        # Normalize to Binance format: BTC/USDT → BTCUSDT
        sym_binance = symbol.replace("/", "")
        side = trade.get("side", "LONG")
        entry = trade.get("entry_price", 0)
        tp_pct = trade.get("tp_pct", 2)
        sl_pct = trade.get("sl_pct", 2)
        leverage = trade.get("leverage", 3)
        balance = trade.get("balance_at_entry", 10000)
        size_pct = trade.get("size_value", 10)

        # ── Binance Futures taker fee (0.04%) ──────────────────────────────
        fee_rate = 0.0004  # 0.04%

        # ── Get real entry price from Binance ─────────────────────────────
        try:
            url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym_binance}"
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=3)) as r:
                    if r.status == 200:
                        data = await r.json()
                        entry = float(data["price"])
        except Exception:
            pass  # keep original entry if API fails

        # ── Get current price (for exit decision) ─────────────────────────
        current_price = entry
        try:
            url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym_binance}"
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=3)) as r:
                    if r.status == 200:
                        data = await r.json()
                        current_price = float(data["price"])
        except Exception:
            pass

        # ── Calculate PnL based on real price movement ───────────────────
        # TP/SL are in PRICE terms (not margin terms)
        # With leverage L: price moves X% → margin moves X% × L
        if side == "LONG":
            price_move_pct = (current_price - entry) / entry * 100  # e.g. +2%
            margin_move_pct = price_move_pct * leverage  # e.g. +10%
            tp_price = entry * (1 + tp_pct / 100)
            sl_price = entry * (1 - sl_pct / 100)
            if current_price >= tp_price:
                exit_reason = "tp"
                pnl_pct = tp_pct * leverage
            elif current_price <= sl_price:
                exit_reason = "sl"
                pnl_pct = -sl_pct * leverage
            else:
                # Price still between SL and TP — use realistic random
                # Probability based on how close to TP vs SL
                dist_to_tp = (tp_price - current_price) / (tp_price - entry) if tp_price != entry else 0.5
                tp_hit = random.random() < (1 - dist_to_tp) * 0.5  # conservative
                exit_reason = "tp" if tp_hit else "sl"
                pnl_pct = (tp_pct * leverage) if tp_hit else (-sl_pct * leverage)
        else:  # SHORT
            price_move_pct = (entry - current_price) / entry * 100
            margin_move_pct = price_move_pct * leverage
            tp_price = entry * (1 - tp_pct / 100)
            sl_price = entry * (1 + sl_pct / 100)
            if current_price <= tp_price:
                exit_reason = "tp"
                pnl_pct = tp_pct * leverage
            elif current_price >= sl_price:
                exit_reason = "sl"
                pnl_pct = -sl_pct * leverage
            else:
                dist_to_tp = (current_price - tp_price) / (entry - tp_price) if entry != tp_price else 0.5
                tp_hit = random.random() < (1 - dist_to_tp) * 0.5
                exit_reason = "tp" if tp_hit else "sl"
                pnl_pct = (tp_pct * leverage) if tp_hit else (-sl_pct * leverage)

        # ── Calculate position value and PnL in $ ────────────────────────
        position_value = balance * (size_pct / 100)  # $ amount at risk
        pnl_amt = position_value * (pnl_pct / 100)

        # ── Subtract fees (entry + exit) ──────────────────────────────────
        # Fee on position value (both entry and exit)
        entry_fee = position_value * fee_rate
        exit_fee = position_value * fee_rate
        total_fees = entry_fee + exit_fee
        pnl_amt -= total_fees

        exit_price = (
            entry * (1 + pnl_pct / 100) if side == "LONG"
            else entry * (1 - pnl_pct / 100)
        )

        trade["status"] = "closed"
        trade["entry_price"] = entry  # real price
        trade["exit_price"] = round(exit_price, 8)
        trade["exit_fee"] = round(total_fees, 4)
        trade["pnl_pct"] = round(pnl_pct, 4)
        trade["pnl"] = round(pnl_amt, 4)
        trade["exit_reason"] = exit_reason
        trade["close_timestamp"] = datetime.now(timezone.utc).isoformat()

        return trade

    # ── Utilities ───────────────────────────────────────────────────────────────

    async def _get_top_symbols(self, limit: int = 20) -> list[str]:
        """Fetch top symbols by 24h quote volume from public Binance API, fallback to hardcoded pool.
        Probes klines for each candidate to skip symbols unavailable on futures (e.g. tokenized stocks)."""
        try:
            url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        data = await r.json()
                        usdt_pairs = [
                            t for t in data
                            if t.get("symbol", "").endswith("USDT") and float(t.get("quoteVolume", 0) or 0) > 0
                        ]
                        usdt_pairs.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)

                        # Probe klines for each symbol — skip if400 (unavailable on futures)
                        kline_url = "https://fapi.binance.com/fapi/v1/klines"
                        validated = []
                        for t in usdt_pairs[:limit * 3]:  # probe extra to get enough valid ones
                            sym_raw = t["symbol"]  # e.g. BTCUSDT
                            sym_fmt = f"{sym_raw[:-4]}/{sym_raw[-4:]}"  # BTC/USDT
                            try:
                                params = {"symbol": sym_raw, "interval": "1h", "limit": 1}
                                async with sess.get(kline_url, params=params,
 timeout=aiohttp.ClientTimeout(total=3)) as kr:
                                    if kr.status == 200:
                                        validated.append(sym_fmt)
                            except Exception:
                                pass
                            if len(validated) >= limit:
                                break

                        if validated:
                            log.info("Top symbols refreshed (validated): %s", validated[:5])
                            return validated[:limit]
        except Exception as e:
            log.debug("Top symbols fetch failed: %s", e)
        return self.symbol_pool[:limit]

    async def _get_candles_fallback(self, symbol: str, timeframe: str, limit: int):
        """Generate synthetic candles for dry run testing."""
        import random
        base_prices = {
            "BTC/USDT": 67000, "ETH/USDT": 3800, "BNB/USDT": 600,
            "SOL/USDT": 170, "XRP/USDT": 0.62, "ADA/USDT": 0.48,
            "DOGE/USDT": 0.14, "AVAX/USDT": 35, "DOT/USDT": 7.5,
            "LINK/USDT": 14, "MATIC/USDT": 0.72, "LTC/USDT": 85,
            "UNI/USDT": 9.5, "ATOM/USDT": 8.2, "ETC/USDT": 26,
            "XLM/USDT": 0.11, "ALGO/USDT": 0.18, "AAVE/USDT": 88,
            "FIL/USDT": 5.5, "APE/USDT": 1.2,
        }
        base = base_prices.get(symbol, 1000)
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        interval_ms = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000}.get(timeframe, 900000)

        candles = []
        price = base
        for i in range(limit):
            ts = now - (limit - i) * interval_ms
            open_ = price
            high = price * (1 + random.uniform(0.001, 0.015))
            low = price * (1 - random.uniform(0.001, 0.015))
            close = price * (1 + random.uniform(-0.008, 0.012))
            volume = random.uniform(100, 1000)
            candles.append([ts, float(f"{open_:.2f}"), float(f"{high:.2f}"), float(f"{low:.2f}"), float(f"{close:.2f}"), volume])
            price = close

        return candles

    def _ema(self, prices: list, period: int) -> float:
        """Calculate EMA."""
        if len(prices) < period:
            return prices[-1] if prices else 0
        k = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = price * k + ema * (1 - k)
        return ema

    def _rsi(self, prices: list, period: int = 14) -> float:
        """Calculate RSI."""
        if len(prices) < period + 1:
            return 50 # neutral
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    # ═══════════════════════════════════════════════════════════════════════
    # FOCUS MODE — re-analyze open positions when max positions reached
    # ═══════════════════════════════════════════════════════════════════════
    async def focus_open_positions(self) -> int:
        """Re-analyze open positions, amend TP/SL based on new MTF signals.
        
        Returns number of positions reviewed.
        """
        state = self.state_mgr.get()
        mode = state.get("mode", "dry_run")
        open_pos = self.trade_log.get_active(mode=mode) if self.trade_log else []
        
        if not open_pos:
            log.info("[Focus] No open positions to review")
            return 0
        
        # Import MTF locally (not stored as self._mtf in this version)
        from .mtf_analyzer import MultiTimeframeAnalyzer
        mtf = MultiTimeframeAnalyzer()
        
        now = datetime.now(timezone.utc)
        reviewed = 0
        
        for pos in open_pos:
            sym = pos.get("symbol", "")
            side = pos.get("side", "")
            entry_price = pos.get("entry_price", 0)
            
            if not sym or not side:
                continue
            
            # Check cooldown — skip if reviewed within 5 minutes
            last_reviewed = pos.get("last_reviewed_at")
            if last_reviewed:
                try:
                    last_ts = datetime.fromisoformat(last_reviewed.replace("Z", "+00:00"))
                    if (now - last_ts).total_seconds() < 300:
                        continue  # still in cooldown
                except (ValueError, TypeError):
                    pass
            
            # Run MTF analysis for this symbol
            try:
                analysis = await mtf.analyze(sym)
                signal = analysis.get("signal", "neutral")
                score = analysis.get("score", 0)
                regime = analysis.get("regime", "unknown")
            except Exception as e:
                log.error("[Focus] MTF analysis failed for %s: %s", sym, e)
                continue
            
            # Update last_reviewed_at
            pos["last_reviewed_at"] = now.isoformat()
            self.trade_log.add(pos)
            
            # Calculate current PnL %
            pnl_pct = pos.get("pnl_pct", 0)
            
            # Determine amendment action
            action_taken = None
            
            if side.upper() == "LONG":
                # Near-TP: lock profit (move SL to breakeven) when PnL > 1.5%
                if pnl_pct >= 1.5:
                    new_sl = entry_price
                    action_taken = f"lock_profit@+{pnl_pct:.2f}%"
                    log.info("[Focus] %s LONG lock profit: SL=%.4f (entry=%.4f, PnL=+%.2f%%)",
                             sym, new_sl, entry_price, pnl_pct)
                
                # Near-SL: move SL to breakeven when PnL < -1.0%
                elif pnl_pct <= -1.0:
                    new_sl = entry_price * 1.001  # small buffer
                    action_taken = f"breakeven@{pnl_pct:.2f}%"
                    log.info("[Focus] %s LONG breakeven: SL=%.4f (PnL=%.2f%%)",
                             sym, new_sl, pnl_pct)
                
                # Strong bullish signal: widen TP
                elif signal == "bullish" and score >= 75:
                    log.info("[Focus] %s LONG strong bullish (%s, score=%d) — hold", sym, regime, score)
            
            elif side.upper() == "SHORT":
                # Near-TP: lock profit when PnL > 1.5%
                if pnl_pct >= 1.5:
                    new_sl = entry_price
                    action_taken = f"lock_profit@+{pnl_pct:.2f}%"
                    log.info("[Focus] %s SHORT lock profit: SL=%.4f (entry=%.4f, PnL=+%.2f%%)",
                             sym, new_sl, entry_price, pnl_pct)
                
                # Near-SL: move SL to breakeven when PnL < -1.0%
                elif pnl_pct <= -1.0:
                    new_sl = entry_price * 0.999
                    action_taken = f"breakeven@{pnl_pct:.2f}%"
                    log.info("[Focus] %s SHORT breakeven: SL=%.4f (PnL=%.2f%%)",
                             sym, new_sl, pnl_pct)
                
                # Strong bearish signal: hold
                elif signal == "bearish" and score >= 75:
                    log.info("[Focus] %s SHORT strong bearish (%s, score=%d) — hold", sym, regime, score)
            
            if action_taken:
                log.info("[Focus] %s %s %s — action: %s", sym, side, pnl_pct, action_taken)
            
            reviewed += 1
        
        log.info("[Focus] Reviewed %d/%d open positions", reviewed, len(open_pos))
        return reviewed