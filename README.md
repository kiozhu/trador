# Trador — Bot Trading Crypto Futures Otomatis

Bot trading crypto futures dengan kontrol penuh via **Telegram**. Didesain untuk traders yang ingin automasi penuh tapi tetap bisa intervene kapan saja. Tidak ada black box — semua logic visible, semua keputusan bisa di-audit.

> ⚠️ **PERINGATAN** — Trading futures beresiko tinggi. Mode Live menggunakan uang sungguhan. Mulai dari dry-run dulu, pastikan track record profitable sebelum switch ke live.

---

## 📋 Daftar Isi

1. [Kelebihan Sistem](#-kelebihan-sistem)
2. [Arsitektur](#-arsitektur)
3. [Komponen Inti](#-komponen-inti)
4. [Persiapan & Instalasi](#-persiapan--instalasi)
5. [Konfigurasi](#-konfigurasi)
6. [Menu Telegram](#-menu-telegram)
7. [Strategi Trading](#-strategi-trading)
8. [6 Scanner Market](#-6-scanner-market)
9. [Risk Engine](#-risk-engine)
10. [Mode Trading](#-mode-trading)
11. [Troubleshooting](#-troubleshooting)
12. [Struktur Folder](#-struktur-folder)

---

## ✅ Kelebihan Sistem

| # | Kelebihan | Penjelasan |
|---|-----------|------------|
| 1 | **11 Strategi Auto** | whale_rider, funding_arbitrage, scalp_rapid, swing_stealth, breakout_pro, fvg_catcher, liquidation_hunter, orderblock_hunter, liquidity_sweep, momentum_ema, grid_hunter |
| 2 | **6 Scanner Real-time** | whale, liquidation, orderbook, volume_profile, funding, smc — semua dari public API Binance (gratis, tanpa API key) |
| 3 | **Risk Engine Terintegrasi** | RiskGuard (10-layer), Kelly Sizing, VaR/CVaR, Volatility Regime, Stress Test, Daily Loss Circuit Breaker |
| 4 | **MTF Multi-Timeframe** | Analisa 3 timeframe (15m/1h/4h) sebelum entry — konfirmasi trend sebelum buka posisi |
| 5 | **MTF Override** | Score ≥ 80 langsung execute tanpa LLM (hemat biaya API) |
| 6 | **Focus Mode** | Max positions reached → re-scan open positions untuk amend TP/SL |
| 7 | **Telegram-First Control** | Semua kontrol dari inline keyboard menu — tidak perlu CLI |
| 8 | **Dry Run + Live** | Dry run balance virtual + live mode dengan uang sungguhan |
| 9 | **Ed25519 Support** | Binance API dengan Ed25519 signature (lebih aman dari HMAC-SHA256) |
| 10 | **PM2 Process Manager** | Bot running sebagai PM2 service — auto-restart, logs, management |
| 11 | **Zero Credentials in Git** | `.env` tidak pernah masuk Git — API keys aman |

---

## 🏗️ Arsitektur

```
┌─────────────────────────────────────────────────────────────┐
│                     TELEGRAM BOT                             │
│  MenuRouter (12 pages: main, status, monitor, wallet, dll)  │
│  Text input handlers: API key, secret, LLM key, funds       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                     AUTO TRADER                               │
│  Scan cycle (15s default)                                    │
│  ├── MTF Analyzer (15m/1h/4h) → score                        │
│  ├── 6 Market Scanners (parallel)                           │
│  ├── 11 Strategies (YAML hot-reload)                        │
│  └── Risk Engine (10-layer pre-trade check)                 │
│       ├── RiskGuard (balance, positions, regime)            │
│       ├── KellySizer (dynamic position sizing)              │
│       ├── VaR/CVaR (portfolio risk)                          │
│       ├── StressTest (5 scenarios)                           │
│       └── Volatility Regime (low/normal/high/extreme)        │
└────────────────────────┬────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          ↓                              ↓
┌─────────────────────┐      ┌─────────────────────┐
│  BINANCE FUTURES    │      │  HYPERLIQUID         │
│  Ed25519 / HMAC     │      │  (coming soon)      │
│  Real balance       │      │                     │
└─────────────────────┘      └─────────────────────┘
```

---

## 🧩 Komponen Inti

### AutoTrader (scan cycle 15s default)
- Loop utama: MTF analysis → scanners → strategies → risk check → execute
- `_sync_risk_state()` every cycle (not just on trade)
- Consume `_risk_action` dari Telegram (kill/resume buttons)
- MTF bypass: score ≥ 80 langsung execute tanpa LLM call
- Focus mode: max positions reached → `_focus_open_positions()` untuk amend

### MTF Analyzer (Multi-Timeframe)
3 timeframe analysis per symbol:
- **15m** — entry timing
- **1h** — medium trend
- **4h** — long trend

Signal: `bullish` / `bearish` / `sideway` / `conflicting`

### 6 Market Scanners (public API — no key needed)
| Scanner | Data Source | Fungsi |
|---------|-------------|--------|
| `whale` | OHLCV 15m/1h | Volume spike detection |
| `liquidation` | Orderbook depth | Liquidated positions detection |
| `orderbook` | Depth data | Order book imbalance |
| `volume_profile` | Klines | POC + volume nodes |
| `funding` | Funding rate API | Funding rate anomaly |
| `smc` | OHLCV + orderbook | Smart Money Concept |

---

## ⚙️ Persiapan & Instalasi

### Requirements
- Python 3.12+
- PM2 (process manager)
- Binance Futures account dengan API key

### Setup

```bash
# Clone
git clone https://github.com/kiozhu/trador.git
cd trador

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
nano .env  # isi TELEGRAM_BOT_TOKEN, BINANCE_API_KEY, BINANCE_API_SECRET

# Start dengan PM2
pm2 start "python3 -m src.main" --name trador
pm2 logs trador --watch   # monitor logs
```

### PM2 Commands
```bash
pm2 start "python3 -m src.main" --name trador   # Start
pm2 restart trador                                 # Restart
pm2 stop trador                                    # Stop
pm2 logs trador                                    # View logs
pm2 delete trador                                  # Remove
pm2 show trador                                    # Status detail
```

### Environment Variables (.env)
```
TELEGRAM_BOT_TOKEN=...          # Dari @BotFather
BINANCE_API_KEY=...             # Binance API Key (Ed25519 atau HMAC-SHA256)
BINANCE_API_SECRET=...          # Binance API Secret
LLM_API_KEY=...                # MiniMax API Key (untuk LLM mode)
LLM_BASE_URL=https://api.minimax.io  # LLM endpoint
TELEGRAM_CHAT_ID=...            # Chat ID kamu
TERMINAL_ENV=local              # local/docker/ssh/singularity
```

---

## 🔐 Setup Credentials via Telegram

Bot menyediakan menu untuk input credentials langsung dari Telegram (tidak perlu edit file):

### 1. Input API Key
```
👛 Wallet → Input API Key → ketik API key kamu
```
- Simpan ke `memory/state.json` + `.env`
- Klik 🔄 Reload Engine setelah input

### 2. Input API Secret
```
👛 Wallet → Input API Secret → ketik API secret kamu
```
- Support Ed25519 (format: `-----BEGIN PRIVATE KEY-----...`) dan HMAC-SHA256 (plain hex)
- Auto-detect format berdasarkan secret pattern

### 3. Test Connection
```
👛 Wallet → 🧪 Test Connection
```
- Verifikasi credentials dengan fetch balance dari exchange

### 4. Setup LLM (optional)
```
🤖 Smart → Input LLM Key → ketik MiniMax API key
🤖 Smart → Input Base URL → ketik endpoint (default: https://api.minimax.io)
```
- LLM digunakan untuk smart position sizing (bukan untuk decision taking)
- MTF override: score ≥ 80 auto-execute tanpa LLM (lebih murah)

---

## 📱 Menu Telegram

### Quick Actions
|| Tombol | Fungsi |
|--------|--------|
| 🟢 Start | Aktifkan auto trading |
| 🔴 Stop | Stop semua trading, cancel orders |
| 🔴 Close All (Real) | Emergency close ALL positions + cancel ALL orders (live mode) |
| ⏸️ Stop+Hold | Stop trading tapi jaga posisi terbuka |

### Pages (navigate via `page:name` buttons)
| Page | Fungsi |
|------|--------|
| 🏠 Main | Dashboard utama |
| 📊 Status | Balance, PnL, win rate, active strategies |
| 📋 Positions | Semua posisi terbuka |
| 📜 History | Log trade dengan filter |
| ⚙️ Strategy | Toggle 11 strategi ON/OFF |
| 📡 Monitor | Status scanner + regime |
| 🔧 Settings | Interval, max positions, daily loss limit |
| 👛 Wallet | API key/secret, test connection, reload engine |
| 🛡️ Risk Engine | Volatility, Kelly, VaR, stress test, kill/resume |
| 🔴 Mode | Switch Dry Run / Live |
| 🤖 Smart | LLM key + base URL |
| ❓ Help | Bantuan |

### Navigasi
```
🏠 Main
├── [📊 Status]   → page:status
├── [📋 Positions] → page:positions
├── [📡 Monitor] → page:monitor
├── [⚙️ Strategy] → page:strategy
├── [🔧 Settings] → page:settings
├── [👛 Wallet] → page:wallet
├── [🛡️ Risk Engine] → page:risk
├── [🔴 Mode] → mode:live / mode:dry_run
├── [🤖 Smart] → page:smart
└── [❓ Help] → page:help
```

### Perintah CLI
| Command | Fungsi |
|---------|--------|
| `/start` | Start bot, show main menu |
| `/stop` | Stop trading |
| `/newdryrun [balance]` | Reset dry run balance |
| `/status` | Quick status |
| `/help` | Help |

---

## 📈 Strategi Trading

Default: semua 11 strategi **AKTIF**. Tap untuk toggle ON/OFF.

| ID | Nama | Deskripsi |
|----|------|-----------|
| `whale_rider` | Whale Rider | Ride large wallet orders via funding rate anomalies |
| `funding_arbitrage` | Funding Arbitrage | Long/short funding rate spread capture |
| `grid_hunter` | Grid Hunter | Grid orders di sideways market |
| `scalp_rapid` | Scalp Rapid | Quick scalp di high-volume spikes |
| `swing_stealth` | Swing Stealth | Swing trade dengan stealth orders |
| `breakout_pro` | Breakout Pro | Breakout dari range/S&D zones |
| `fvg_catcher` | FVG Catcher | Fair Value Gap reversal detection |
| `liquidation_hunter` | Liquidation Hunter | Order book liquidity hunting |
| `orderblock_hunter` | Order Block Hunter | Order block detection + trade |
| `liquidity_sweep` | Liquidity Sweep | Liquidity pools sweep exploitation |
| `momentum_ema` | Momentum EMA Crossover | EMA crossover untuk momentum entry |

### Edit Strategy Tanpa Restart
Strategy files di `strategies/*.json` bisa diedit langsung — StrategyLoader auto-reload setiap perubahan (hot-reload).

### Parameter Strategy (per strategy JSON)
```json
{
  "enabled": true,
  "leverage": 10,
  "position_size": 0.10,
  "stop_loss_pct": 1.5,
  "take_profit_pct": 3.0,
  "min_score": 65,
  "max_daily_trades": 5
}
```

---

## 🛡️ Risk Engine

### 1. RiskGuard — Pre-Trade Validation (10 Layer)

Setiap order lewat 10 check sebelum eksekusi:

| Layer | Check | Action if Fail |
|-------|-------|----------------|
| L01 | trading_enabled flag | Block |
| L02 | Daily loss limit | Block + circuit breaker |
| L03 | Max concurrent positions | Block |
| L04 | Symbol whitelist/blacklist | Block |
| L05 | Balance floor ($100 min) | Block all trades |
| L06 | Kelly size validation | Block |
| L07 | Volatility regime | Block/extreme only |
| L08 | Position size ≤ 20% | Block |
| L09 | Leverage ≤ 20x | Block |
| L10 | Trade timing interval | Block |

**Kill/Resume**: Settings → 🛡️ Risk Engine → 🛑 Kill Switch / ▶️ Resume Trading

### 2. KellySizer — Dynamic Position Sizing

Kelly Criterion dengan 8 adjustment factors:

| Factor | Penjelasan |
|--------|------------|
| `win_rate` | Win rate dari trade history |
| `avg_win` | Average win ($) |
| `avg_loss` | Average loss ($) |
| `kelly_fraction` | Kelly fraction (default 0.5 = half-Kelly) |
| `max_kelly_pct` | Maximum Kelly% (default 20%) |
| `win_streak` | Current win streak (bonus) |
| `loss_streak` | Current loss streak (penalty) |
| `confidence` | Data sufficiency (0-1) |

### 3. VaR/CVaR — Portfolio Risk

- `var_95` — Value at Risk 95% (max expected loss 1 hari)
- `cvar_95` — Conditional VaR (average loss given breach)
- Updated setiap scan cycle

### 4. Volatility Regime

4 regime: `low` / `normal` / `high` / `extreme`
- Regime di-detect dari ATR + historical volatility
- Extreme regime: RiskGuard block semua trades

### 5. Stress Test

5 scenario untuk simulate worst-case:

| Scenario | Deskripsi |
|----------|-----------|
| 🔥 Flash Crash | Harga drop 15% dalam 1 jam |
| 📉 Black Swan | Harga drop 30% dalam 1 hari |
| 🌊 High Vol | Volatilitas 3x normal |
| 📰 News Gap | Gap down 10% overnight |
| 🔄 Sideway Chop | Whipsaw 5x dalam 1 hari |

Output: estimated loss ($), severity emoji, recommendations.

### Risk Engine UI
```
🛡️ Risk Engine

📊 Volatility: [NORMAL]  size: 1.0x
📈 Kelly: 15.2%  confidence: 72%
📉 VaR (95%): $85.20
📅 Daily PnL: +$12.50
💼 Positions: 3 open

🛑 Kill Switch    ▶️ Resume Trading
💪 Stress Test    🔄 Reset Daily
```

---

## 🔄 Mode Trading

### Dry Run (Simulasi)
- Balance virtual: configurable (default $250)
- Semua order simulate (tidak ada real execution)
- Reset: Balance page → 🔄 Reset Dry Run → masukkan amount

### Live (Real Money)
- Balance sync dari Binance Futures API
- Order real dieksekusi
- ⚠️ HIGH RISK — hanya gunakan uang yang siap kehilangan

**Mode switch**: Main menu → 🔴 Mode → pilih

### Balance Floor
- L05_BALANCE_FLOOR default: $100
- Jika balance < $100, semua trades di-block
- Bisa di-tune di Risk Config page

---

## ⚠️ Persiapan Live Money

### Checklist sebelum live:
- [ ] Minimal 20+ dry-run trades dengan win rate > 50%
- [ ] Profitability proven — dry-run balance consistently growing
- [ ] API key tested via Wallet → 🧪 Test Connection
- [ ] Risk parameters tuned sesuai comfort
- [ ] Balance cukup (minimal $100 di account)

### Current Track Record
```
Mode: LIVE (real money at risk)
Balance: ~$12.95 USDT free
Open positions: 0 (all closed via emergency stop)
Trading: enabled
```

**Status**: Bot stable — emergency stop tested and working ✅

---

## 🔧 Troubleshooting

### Bot tidak started
```bash
# Cek process
pm2 status

# Ceck logs
pm2 logs trador --lines 50

# Restart
pm2 restart trador
```

### "pending_input" tidak respons
- Pastikan klik tombol "Input API Key" / "Input API Secret" / "Input LLM Key" TERLEBIH DAHULU
- Setelah klik, baru ketik teks
- Jika masih tidak respons, restart bot: `pm2 restart trador`

### Wallet connection failed
1. Cek API Key + Secret benar
2. Pastikan Futures enabled di Binance
3. Gunakan 🧪 Test Connection di Wallet page
4. Jika Ed25519 — pastikan format secret benar (`-----BEGIN PRIVATE KEY-----...`)

### Scanner tidak jalan
- Scanner berjalan otomatis saat trading enabled
- Cek Monitor page untuk status
- Semua scanner pakai public API — tidak butuh API key

### Bot auto-restart terus
```bash
pm2 logs trador --lines 100 | grep -i error
```
Cek error yang muncul dan laporkan.

### Balance tidak update
- Pastikan wallet connected (Wallet page)
- Refresh dengan klik Balance di menu
- Di live mode, balance sync dari exchange API

### Strategy tidak sync dengan yang dicentang
- Status page membaca dari `StrategyLoader.list_active_ids()`
- Jika tidak sync,: `pm2 restart trador`

---

## 📁 Struktur Folder

```
trador/
├── .env                  # Credentials (JANGAN COMMIT!)
├── .env.example          # Template
├── .gitignore
├── requirements.txt
├── README.md             # Dokumen utama (INI)
├── SPEC.md               # Technical specification
├── src/
│   ├── main.py           # Entry point + Trador class
│   ├── trading/
│   │   ├── engine.py     # TradingEngine (ccxt)
│   │   ├── auto_trader.py # Scan cycle + execution
│   │   ├── risk_guard.py  # 10-layer pre-trade validation
│   │   ├── kelly_sizer.py # Dynamic Kelly criterion sizing
│   │   ├── var_calc.py    # VaR/CVaR calculator
│   │   ├── obi_analyzer.py # Order flow imbalance
│   │   ├── stress_test.py # 5 scenario stress testing
│   │   ├── mtf_analyzer.py # Multi-timeframe analysis
│   │   ├── strategies.py  # Strategy scoring engine
│   │   ├── rolling_buffer.py # Rolling trade stats
│   │   ├── position_manager.py
│   │   └── signals.py
│   ├── scanners/
│   │   ├── whale_scanner.py
│   │   ├── liquidation_scanner.py
│   │   ├── orderbook_scanner.py
│   │   ├── volume_profile_scanner.py
│   │   ├── funding_scanner.py
│   │   └── smc_scanner.py
│   ├── strategy/
│   │   └── loader.py     # StrategyLoader (hot-reload YAML)
│   ├── tg_bot/
│   │   ├── menu/
│   │   │   ├── __init__.py   # MenuRouter + _handle_text_input
│   │   │   └── pages/        # 12 page classes
│   │   └── handlers/         # Quick actions, pnl, positions
│   ├── memory/
│   │   ├── state.py      # StateManager (atomic write)
│   │   ├── trade_log.py  # TradeLog
│   │   └── performance.py
│   ├── llm/
│   │   └── scorer.py     # LLM-based position scoring
│   └── utils/
│       └── logger.py
├── strategies/           # Strategy JSON files (hot-reload)
│   ├── whale_rider.json
│   ├── funding_arbitrage.json
│   └── ... (11 files)
├── memory/               # Runtime data (per-machine)
│   ├── state.json        # Bot state (positions, mode, credentials)
│   ├── trade_history.json # Trade log
│   └── rolling_stats.json # Rolling performance stats
├── shared/               # Hermes Comm (JSON reports)
├── logs/
│   └── trador.log
└── backtest_results/
    └── *.png, *.json
```

---

## 📌 Command Reference

| Command | Fungsi |
|---------|--------|
| `/start` | Start bot, show main menu |
| `/stop` | Stop trading |
| `/newdryrun [balance]` | Reset dry run dengan balance tertentu |
| `/status` | Show quick status |
| `/menu` | Show main menu |
| `/help` | Show help |

---

**Last updated:** June 2026
**Version:** v4 (with MTF override + Focus mode + Ed25519 support)