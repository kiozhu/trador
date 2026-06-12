# Trador — Crypto Futures Trading Bot

**Purpose:** Independent crypto futures trading bot that runs on VPS, manages its own strategy, communicates with Hermes via file-based JSON, and exposes a Telegram reply keyboard for manual control.

**Core principle:** Trador is the BODY. It follows its strategy exactly. Hermes is the CONTROLLER that can modify Trador's strategy files. Trador does NOT think — it executes. LLM only scores execution quality, never changes strategy.

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    TRADOR (Independent)                 │
│                                                         │
│  Telegram Bot (reply keyboard) ← user controls here     │
│  Trading Engine (ccxt → Binance Futures)               │
│  Strategy Config (JSON files) │
│  Memory System (trade history, performance)             │
│  LLM Scorer (execution quality only)                    │
│  File Watcher (auto-reload when Hermes edits strategy)  │
│                                                         │
│  Runs on VPS, standalone, no Hermes dependency │
└─────────────────────────────────────────────────────────┘
 ↕
              shared/trador_reports/*.json  (Hermes reads)
              shared/hermes_suggestions/*.json  (Hermes writes → Trador reads)
```

---

## 2. Project Structure

```
trador/
├── .env                        # Trador's own env (Binance API, Telegram token, LLM config)
├── .env.example
├── SPEC.md
├── README.md
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py                  # Entry point
│   ├── tg_bot/
│   │   ├── __init__.py
│   │   ├── keyboards.py         # Reply + inline keyboard builders
│   │   └── handlers/
│   │       ├── __init__.py
│   │       ├── menu.py         # /start, status, balance, help
│   │       ├── positions.py    # View positions, PnL
│   │       ├── strategy.py     # Strategy CRUD + param adjustment
│   │       ├── trades.py       # Trade history
│   │       ├── smart_mode.py   # Auto trading + Hermes smart panel
│   │       ├── quick_actions.py # Instant execution commands
│   │       ├── wallet.py       # Wallet connect + mode + direction
│   │       ├── pnl.py          # PnL chart menu
│   │       └── pnl_chart.py    # Chart generator (matplotlib)
│   ├── scanners/              # Market data scanners (public API — no key needed)
│   │   ├── __init__.py
│   │   ├── liquidation_scanner.py    # Binance REST orderbook depth
│   │   ├── orderbook_scanner.py     # Binance REST depth data
│   │   ├── whale_scanner.py         # Binance OHLCV volume spike
│   │   ├── funding_scanner.py       # Binance funding rate API
│   │   ├── volume_profile_scanner.py # Binance klines (POC/VAH/VAL)
│   │   └── smc_scanner.py           # SMC: OB/FVG/sweeps/BOS (Binance REST)
│   ├── trading/
│   │   ├── __init__.py
│   │   ├── engine.py            # ccxt Binance Futures wrapper + leverage math
│   │   ├── signals.py           # Signal generation (EMA, RSI, MACD, ADX)
│   │   └── position_manager.py  # Position tracking, SL/TP, trailing
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── loader.py            # Load/reload strategy JSON files
│   │   ├── watcher.py           # File system watcher (watch strategy changes)
│   │   └── validator.py        # Validate strategy JSON schema
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── trade_log.py         # Record every trade
│   │   ├── performance.py       # Win rate, drawdown, Sharpe
│   │   └── lessons.py           # Lessons learned from trades
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── scorer.py            # Score execution quality (NOT strategy)
│   │   └── client.py            # MiniMax API client
│   ├── comm/
│   │   ├── __init__.py
│   │   ├── reporter.py          # Write reports to shared/trador_reports/
│   │   └── reader.py            # Read suggestions from shared/hermes_suggestions/
│   └── utils/
│       ├── __init__.py
│       ├── logger.py            # Logging setup
│       └── helpers.py           # JSON atomic write, formatting
├── strategies/               # 11 strategy JSON files
│   ├── momentum_ema.json        # EMA20/50 crossover + ADX
│   ├── scalp_rapid.json         # Scalping EMA9/21 + RSI + volume
│   ├── liquidation_hunter.json  # Liquidation cascade (WS)
│   ├── grid_hunter.json         # Bollinger Bands grid
│   ├── breakout_pro.json        # Breakout + volume confirmation
│   ├── swing_stealth.json       # Swing trade EMA50/200
│   ├── orderblock_hunter.json   # SMC: Order Block reclaim
│   ├── fvg_catcher.json         # SMC: Fair Value Gap
│   ├── liquidity_sweep.json     # SMC: Liquidity sweep reversal
│   ├── funding_arbitrage.json   # Funding rate edge
│   └── whale_rider.json         # Whale activity (>$50K trades)
├── shared/                       # File communication with Hermes
│   ├── trador_reports/          # Written by Trador, read by Hermes
│   │   ├── status.json
│   │   ├── trades.json
│   │   └── metrics.json
│   └── hermes_suggestions/      # Written by Hermes, read by Trador
│       └── pending/
│           └── *.json
├── memory/ # Trador's own memory
│   ├── trade_history.json
│   ├── performance.json
│   └── state.json
├── logs/
└── tests/
```

---

## 3. Strategy Config Format

Each strategy is a JSON file in `strategies/`. Trador watches this directory and reloads when files change.

```json
{
  "id": "momentum_ema",
  "name": "Momentum EMA Crossover",
  "version": 1,
  "description": "EMA20/50 crossover with ADX filter",

  "direction": "both",  // "long", "short", or "both" — trade direction filter

  "indicators": {
    "ema_fast": 20,
    "ema_slow": 50,
    "adx_period": 14,
    "adx_threshold": 25,
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30
  },

  "entry": {
    "signal": "ema_crossover",
    "confirm": ["adx_above_threshold", "rsi_not_overbought"],
    "min_mcap_usd": 10000,
    "max_mcap_usd": 500000
  },

  "position": {
    "size_type": "fixed_percent",
    "size_value": 10,
    "leverage": 3,
    "max_open": 2
  },

  "risk": {
    "sl_percent": -3,
    "tp_percent": 6,
    "trailing": true,
    "trailing_trigger_pct": 2,
    "trailing_distance_pct": 1.5,
    "max_hold_minutes": 30,
    "breakeven_after_pct": 1.5
  },

  "filters": {
    "min_volume_24h_usd": 50000,
    "no_news_hours": [0, 1, 2, 3, 4, 5]
  }
}
```

---

## 4. Telegram Bot UI

###4.1 Reply Keyboard (Persistent Menu)

```
┌──────────────────────────────────────────┐
│  [📊 Status]      [📈 Positions]         │
│  [⚙️ Strategi]    [📋 History]           │
│  [🚀 Start]       [🛑 Stop]              │
│  [💰 Balance]     [🧠 Smart Mode]        │
│  [⚡ Quick Actions] [🔗 Wallet]           │
│  [🎮 Mode]        [❓ Help]               │
└──────────────────────────────────────────┘
```

### 4.2 Mode + Direction

```
🎮 Mode: 🔴 LIVE | Direction: BOTH
Wallet: ✅ Connected (Binance)

[🔴 LIVE]  [🟡 DRY RUN]  — switch trading mode
[📈 LONG]  [📉 SHORT]  [🔄 BOTH] — switch direction
```

### 4.3 Wallet Connect Panel

```
🔗 CONNECT EXCHANGE

[🟣 Binance Futures]  [🔵 Bybit]  [🟠 OKX]

API keys from .env — no secrets stored in memory
```

### 4.4 Inline Keyboard — Strategy Selection

Sent as response to "⚙️ Strategi" button:

```
Pilih Strategi Aktif:

[📈 Momentum EMA] [🔲 Grid Trading]
[⚡ Scalping]      [📋 Lihat Config]

Ubah Parameter:
[📊 Risk %]  [📏 TP/SL]  [🔢 Leverage]
[⏱️ Max Hold]  [📦 Position Size]
```

### 4.5 Inline Keyboard — Parameter Adjustment

```
Risk Per Trade:
[1%] [2%] [3%] [5%] [10%]

Leverage:
[1x] [2x] [3x] [5x] [10x]

Trailing Stop:
[Off] [Breakeven] [Secure] [Trail]
```

### 4.6 Status Display (on "📊 Status")

```
🔥 TRADOR STATUS

Mode: 🔴 LIVE | Direction: BOTH
Wallet: ✅ | Strategy: `momentum_ema`
Trading: 🟢 Active | Open Positions: 2

24h Performance
Trades: 47 | Win Rate: 61.7%
PnL: $1240.50
```

### 4.7 Smart Mode Panel

```
🧠 SMART MODE

Auto Trading: 🟢 ON | Hermes: Passive
Strategy: `breakout_pro`

[🟢 Auto Trading ON] [🟡 Hermes: Passive]
[🎯 Best Strategy] [🔄 Force Scan]
[🧪 Simulate Signal] [📊 Performance]
```

### 4.8 Quick Actions

```
⚡ QUICK ACTIONS

[📋 View Orders] [❌ Cancel All]
[💸 Close All]   [📈 Avg Entry]
[🔍 Scan Market] [📐 Direction]
```

---

## 5. Bot Modes

### Live vs Dry Run

| | 🔴 LIVE | 🟡 DRY RUN |
|-|---------|------------|
| Real money | ✅ Yes | ❌ No |
| Exchange trades | ✅ Executed | ❌ Simulated |
| Wallet required | ✅ Connected | ❌ Not needed |
| Balance affected | ✅ Yes | ❌ No |

### Trade Direction

| Mode | Description |
|------|-------------|
| `long` | Only go LONG (profit when price rises) |
| `short` | Only go SHORT (profit when price drops) |
| `both` | Both directions (recommended for futures) |

**Why both?** Futures allows shorting — profit in any market direction. The key is *analysis quality + strategy*, not market direction.

### Supported Exchanges

- 🟣 **Binance Futures** — `BINANCE_API_KEY` + `BINANCE_API_SECRET`
- 🔵 **Bybit Unified** — `BYBIT_API_KEY` + `BYBIT_API_SECRET`
- 🟠 **OKX** — `OKX_API_KEY` + `OKX_API_SECRET`

Strategy: Momentum EMA v1
Position: LONG ETHUSDT @ 3420.50
Size: 0.1 BTC | Leverage: 3x
PnL: +$124.50 (+3.2%)
Unrealized: +$18.20

Today: 5 trades | 3W/2L | +$312
Win Rate: 60% | Drawdown: -2.1%

Last Trade: LONG SOL @ 182.30 → 185.10 (+1.5%)
Exit: Take Profit

[🚀 Start] [🛑 Stop] [📈 Positions]
```

---

## 6. LLM Role — Execution Scorer ONLY

LLM is used ONLY to score execution quality. It CANNOT change strategy.

### Score Execution Prompt

```
Kamu adalah EXECUTION SCORER. Kamu menilai SEKALIUS bagaimana eksekusi trade dilakukan.
Kamu TIDAK boleh mengubah strategi. Kamu hanya menilai.

Konteks trade:
- Entry price: {entry_price}
- Exit price: {exit_price}
- Side: {side}
- Hold time: {hold_minutes} menit
- Strategy used: {strategy_id}
- Market condition: {market_regime}

Penilaian (1-10):
1. Entry timing — apakah entry di harga yang bagus?
2. Exit timing — apakah exit di waktu yang tepat?
3. Risk management — apakah SL/TP dihit dengan benar?
4. Overall execution

Berikan jawaban dalam format:
Score: {nilai 1-10}
Reason: {alasan singkat 1-2 kalimat}
Lesson: {jika ada lesson untuk di记录, kalau tidak ada kosongkan}
```

### What LLM CAN do:
- Score execution quality (1-10)
- Suggest lessons learned from trade outcomes
- Validate if a suggested strategy change from Hermes makes sense (but NOT implement it)

### What LLM CANNOT do:
- Change strategy parameters
- Override risk rules
- Decide to enter/exit outside strategy rules
- Interpret market conditions to change strategy

---

## 7. Hermes Communication

###6.1 Trador → Hermes (Reports)

Written to `shared/trador_reports/`:

**status.json** (updated every 30s):
```json
{
  "timestamp": "2026-06-09T12:00:00Z",
  "bot_status": "running",
  "strategy_active": "momentum_ema",
  "position": {
    "side": "LONG",
    "symbol": "ETHUSDT",
    "entry_price": 3420.50,
    "current_price": 3445.20,
    "size": 0.1,
    "leverage": 3,
    "pnl_usd": 124.50,
    "pnl_pct": 3.2,
    "unrealized_usd": 18.20
  },
  "today": {
    "trades": 5,
    "wins": 3,
    "losses": 2,
    "pnl_usd": 312.40,
    "win_rate": 60.0
  },
  "open_positions": 1,
  "max_drawdown": -2.1
}
```

**trades.json** (updated after each trade):
```json
{
  "timestamp": "2026-06-09T12:00:00Z",
  "trade": {
    "id": "trade_20260609_001",
    "strategy_id": "momentum_ema",
    "symbol": "ETHUSDT",
    "side": "LONG",
    "entry_price": 3420.50,
    "exit_price": 3450.00,
    "size": 0.1,
    "leverage": 3,
    "pnl_usd": 177.00,
    "pnl_pct": 4.8,
    "hold_minutes": 12,
    "exit_reason": "TAKE_PROFIT",
    "execution_score": 8,
    "llm_lesson": "Good entry on EMA crossover confirmation",
    "opened_at": "2026-06-09T11:48:00Z",
    "closed_at": "2026-06-09T12:00:00Z"
  }
}
```

**metrics.json** (updated every hour):
```json
{
  "timestamp": "2026-06-09T12:00:00Z",
  "period": "24h",
  "total_trades": 47,
  "wins": 29,
  "losses": 18,
  "win_rate": 61.7,
  "net_pnl_usd": 1240.50,
  "avg_win_usd": 62.30,
  "avg_loss_usd": -28.10,
  "profit_factor": 2.21,
  "max_drawdown": -4.2,
  "sharpe_ratio": 1.84,
  "best_trade_pct": 8.4,
  "worst_trade_pct": -3.2
}
```

### 6.2 Hermes → Trador (Suggestions)

Read from `shared/hermes_suggestions/pending/`:

```json
{
  "timestamp": "2026-06-09T12:05:00Z",
  "type": "strategy_adjustment",
  "strategy_id": "momentum_ema",
  "confidence": 0.82,
  "reason": "ADX dropping — reduce exposure",
  "changes": {
    "position.size_value": 5,
    "risk.sl_percent": -2
  },
  "expires_at": "2026-06-09T13:05:00Z"
}
```

**Trador behavior on receiving suggestion:**
1. Read JSON from `hermes_suggestions/pending/`
2. Validate schema
3. If valid → apply changes to strategy file
4. Move file to `hermes_suggestions/processed/`
5. Reload strategy
6. Log what was changed

**Trador ignores suggestion if:**
- File is expired (`expires_at` < now)
- Changes would violate hard risk limits (e.g., SL > -10%)
- Trador is in cooling-off period after loss

---

## 6.3 Memory & Role Separation

```
HERMES (memori sendiri, fokus analisis)
──────────────────────────────────────────────────
• Analisa hasil trade → belajar pattern error
• Evaluasi strategi → worth it atau perlu ganti
• Ubah strategy JSON files di Trador's strategies/
• GA BISA skoring / ubah eksekusi Trador
• GA BACA .env atau memory internal Trador
• GA PUNYA akses ke Trador's LLM scorer
• Fokus: learning + strategy improvement
• Memory: error_patterns, strategy_effectiveness

TRADOR (memori sendiri, fokus eksekusi)
──────────────────────────────────────────────────
• Execute trading berdasarkan strategy file
• Enforce hard limits sendiri
• LLM scorer sendiri → evaluasi execution quality
• GA BISA ubah strategy sendiri
• GA BISA interpretasi suggestion Hermes bebas
• GA REMEMBER apa yang Hermes suggestion
  → Hermes rubah strategy → Trador follow
  → ga ada "learn from Hermes analysis"
• Fokus: eksekusi taat + report hasil
• Memory: trade_history, performance, state

COMMUNICATION — FILE-BASED ONLY
──────────────────────────────────────────────────
Trador → Hermes:  shared/trador_reports/
  • status.json     — bot state, positions, perf
  • trades.json     — individual trade results
  • metrics.json    — 24h/7d/30d metrics

Hermes → Trador:  shared/hermes_suggestions/pending/
  • *.json          — strategy file modifications only
  Trador READS → APPLIES → MOVES to processed/
  Trador does NOT interpret, discuss, or respond

Hermes NEVER receives:
  ✗ Trador's LLM scorer output
  ✗ Trador's internal execution decisions
  ✗ Trador's .env or API keys
```

---

## 8. State Manager

```python
state = {
    "bot_status": "running",
    "strategy_active": "momentum_ema",
    "trading_enabled": True,
    "mode": "live",           # "live" or "dry_run"
    "exchange": "binance",   # "binance", "bybit", "okx"
    "wallet_connected": True,
    "wallet_address": "binance_user_ax2...",
    "direction": "both",     # "long", "short", "both"
    "open_positions": 2,
    "last_trade_at": "2026-06-10T...",
    "cooling_until": None,
}
```

Methods:
- `set_mode("live"|"dry_run")` — switch trading mode
- `set_wallet(exchange, address, connected)` — update wallet state
- `set("direction", "both")` — set trade direction

---

## 9. File Watcher — Hot Reload Strategy

Trador uses `watchdog` to monitor `strategies/` directory.

```
strategies/*.json changed
  → Validate JSON schema
  → Validate values (no invalid risk params)
  → If valid → reload strategy config
  → If invalid → rollback + alert via Telegram
  → Log reload event
```

**Hard limits (cannot be exceeded even if Hermes suggests):**
- `sl_percent` >= -10 (never wider than -10%)
- `leverage` <= 5
- `position.size_value` <= 20%
- `risk.max_hold_minutes` <= 60

---

## 10. Memory System

Trador maintains its own memory in `memory/` directory.

###8.1 trade_history.json

```json
{
  "trades": [
    {
      "id": "trade_20260609_001",
      "strategy_id": "momentum_ema",
      "symbol": "ETHUSDT",
      "side": "LONG",
      "entry_price": 3420.50,
      "exit_price": 3450.00,
      "pnl_usd": 177.00,
      "pnl_pct": 4.8,
      "exit_reason": "TAKE_PROFIT",
      "execution_score": 8,
      "opened_at": "2026-06-09T11:48:00Z",
      "closed_at": "2026-06-09T12:00:00Z"
    }
  ]
}
```

### 8.2 performance.json

```json
{
  "updated_at": "2026-06-09T12:00:00Z",
  "24h": { "trades": 47, "wins": 29, "losses": 18, "pnl_usd": 1240.50, "win_rate": 61.7 },
  "7d": { "trades": 203, "wins": 124, "losses": 79, "pnl_usd": 4820.30, "win_rate": 61.1 },
  "30d": { "trades": 891, "wins": 534, "losses": 357, "pnl_usd": 18420.10, "win_rate": 59.9 }
}
```

### 8.3 state.json

```json
{
  "bot_status": "running",
  "strategy_active": "momentum_ema",
  "trading_enabled": true,
  "open_positions": 1,
  "last_trade_at": "2026-06-09T12:00:00Z",
  "last_report_at": "2026-06-09T12:00:00Z",
  "cooling_until": null
}
```

---

## 11. Tech Stack

| Component | Library |
|-----------|---------|
| Telegram Bot | `python-telegram-bot` v22+ (async) |
| Exchange API | `ccxt` (unified, Binance Futures) |
| Strategy Files | JSON (watchdog for hot-reload) |
| Memory | JSON files (no database needed) |
| LLM Scorer | MiniMax API (MiniMax-M3) |
| Process Manager | systemd (VPS) |
| Logging | `logging` module → `logs/trador.log` |

---

## 12. Implementation Phases

### Phase 1: Core Infrastructure
- [ ] Project setup (requirements.txt, .env.example, folder structure)
- [ ] Logging setup
- [ ] Strategy loader + validator
- [ ] File watcher for hot-reload

### Phase 2: Trading Engine
- [ ] ccxt Binance Futures connection
- [ ] Signal generation (EMA, RSI, MACD, ADX)
- [ ] Position manager (entry/exit, SL/TP, trailing)
- [ ] Risk rules enforcement

### Phase 3: Telegram Bot
- [ ] /start command + reply keyboard
- [ ] Status display
- [ ] Position viewer
- [ ] Strategy switcher (inline keyboard)
- [ ] Parameter adjustment (inline keyboard)

### Phase 4: Memory + Reporting
- [ ] Trade history logging
- [ ] Performance metrics calculation
- [ ] Hermes report writer (status.json, trades.json, metrics.json)
- [ ] Hermes suggestion reader

### Phase 5: LLM Scorer
- [ ] MiniMax API client
- [ ] Execution scorer (post-trade)
- [ ] Lesson extraction

### Phase 6: Production
- [ ] systemd service file
- [ ] PM2 setup (optional alternative)
- [ ] Auto-start on VPS reboot
- [ ] VPS deployment guide

---

## 13. Hard Rules

1. **LLM never changes strategy** — only scores execution
2. **Strategy file is the source of truth** — not memory, not runtime state
3. **Hermes can modify strategy files only** — no direct access to trading engine
4. **Trador ignores expired suggestions** — `expires_at` check is mandatory
5. **Hard risk limits cannot be exceeded** — even if Hermes suggests it
6. **File writes are atomic** — temp file + rename pattern

---

## 14. Changelog

### v2 — Emergency Stop Fixes + Startup Sync (2026-06-12)

**Bug Fixes:**
- `stop_close_all`: Fix close side — use `side` field instead of `size < 0` (CCXT returns `size=None`, `contracts=8.0` positive for both long & short)
- `stop_close_all`: Fix size field — use `contracts` not `size` (CCXT Binance returns `size=None`)
- `stop_close_all`: Add async/await, single exchange instance, Ed25519 support
- `pos_close_all`, `pos_partial_exec`: Same fixes applied
- `action:stop_close_all`: Add cancel all orders before closing positions

**Startup Sync (bidirectional):**
- Direction 1: Stale trades (in file but not on Binance) → close them
- Direction 2: Extra positions (on Binance but not in file) → close them
- Reload AutoTrader positions after sync

**Emergency Stop Flow:**
1. Set `trading_enabled = False`
2. Read credentials from `.env` + state.json
3. Build CCXT exchange with Ed25519 support
4. Cancel ALL open orders across 12 symbols
5. Close ALL open positions (use `side` field for direction)
6. Update `trade_history.json` with `status=closed`, `exit_reason=manual_stop`
7. Reply with count of cancelled/closed

**Credentials:**
- `.env` not in git history ✅
- `.env` staged → unstaged immediately ✅
- Wallet menu syncs to both state.json AND .env ✅
- Engine reloads via `reload_from_env()` without restart ✅
7. **No database** — JSON files only for simplicity
