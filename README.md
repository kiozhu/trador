# Trador — Bot Trading Crypto Futures Otomatis

Bot trading crypto futures dengan kontrol penuh via **Telegram**. Didesain untuk traders yang ingin automasi penuh tapi tetap bisa intervene kapan saja. Tidak ada black box — semua logic visible, semua keputusan bisa di-audit.

> ⚠️ **Status: DRY RUN ONLY** — Bot ini BELUM siap untuk live money. Track record dry-run belum membuktikan profitabilitas. Baca bagian "Persiapan Live Money" sebelum berpikir untuk menggunakan uang sungguhan.

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
11. [Backtesting](#-backtesting)
12. [Persiapan Live Money](#-persiapan-live-money)
13. [Troubleshooting](#-troubleshooting)
14. [Struktur Folder](#-struktur-folder)

---

## ✅ Kelebihan Sistem

| # | Kelebihan | Penjelasan |
|---|-----------|------------|
| 1 | **11 Strategi Auto** | whale_rider, funding_arbitrage, scalp_rapid, swing_stealth, breakout_pro, fvg_catcher, liquidation_hunter, orderblock_hunter, liquidity_sweep, momentum_ema, grid_hunter |
| 2 | **6 Scanner Real-time** | whale, liquidation, orderbook, volume_profile, funding, smc — semua dari public API Binance (gratis, tanpa API key) |
| 3 | **Risk Engine Terintegrasi** | RiskGuard, Kelly Sizing, VaR/CVaR, Order Flow Imbalance, Volatility Regime, Stress Test, Daily Loss Circuit Breaker |
| 4 | **MTF Multi-Timeframe** | Analisa 3 timeframe (15m/1h/4h) sebelum entry — konfirmasi trend sebelum buka posisi |
| 5 | **LLM Smart Mode** | Position sizing yang driven oleh AI — cocok untuk yang mau automasi cerdas |
| 6 | **Hermes Self-Improve** | Cron job otomatis yang analisa trade history → edit strategy YAML langsung |
| 7 | **Telegram-First Control** | Semua kontrol dari inline keyboard menu — tidak perlu CLI, tidak perlu SSH |
| 8 | **Dry Run + Live** | Dry run dengan balance virtual $100 — sebelum pakai uang sungguhan |
| 9 | **Backtesting** | Equity curve + drawdown + Sharpe/Sortino/MaxDD dari data historis |
| 10 | **Zero Credentials in Git** | `.env` tidak pernah masuk Git — API keys aman |

---

## 🏗️ Arsitektur

```
┌─────────────────────────────────────────────────────────────┐
│                     TELEGRAM BOT                             │
│  InlineKeyboardMenu (12 pages: main, status, balance, dll)  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                     TRADING ENGINE                          │
│                                                              │
│  ┌──────────────┐   ┌──────────────────┐   ┌───────────┐     │
│  │ AUTO TRADER  │   │  6 MARKET        │   │  RISK     │     │
│  │ (scan cycle) │──→│  SCANNERS        │   │  ENGINE   │     │
│  └──────┬───────┘   └──────────────────┘   │           │     │
│         │                                     │• RiskGuard│    │
│         │         ┌──────────────────┐      │• Kelly    │    │
│         └────────→│  11 STRATEGIES   │      │• VaR/CVaR │    │
│                   │  (YAML hot-reload)│      │• OBI      │    │
│                   └──────────────────┘      │• Stress   │    │
│                                             │• Daily LB │    │
│                   ┌──────────────────┐      └───────────┘    │
│                   │  MTF ANALYZER    │                      │
│                   │  (15m/1h/4h)     │                      │
│                   └──────────────────┘                      │
└────────────────────────────┬──────────────────────────────┘
                             │
          ┌──────────────────┴──────────────────┐
          ↓                                       ↓
┌─────────────────────┐              ┌─────────────────────┐
│  BINANCE FUTURES    │              │   HYPERLIQUID       │
│  (ccxt)             │              │   (ccxt)            │
│  • API Key + Secret │              │   • API Key + Secret│
│  • Real balance    │              │   • No wallet addr   │
└─────────────────────┘              └─────────────────────┘
```

---

## 🧩 Komponen Inti

### Auto Trader (scan cycle 15s)
- Loop utama: fetch prices → run scanners → run strategies → score → filter risk → execute
- Sync `_risk_state` ke state.json setiap cycle (bukan hanya saat trade)
- Consume `_risk_action` dari Telegram (kill/resume)
- MTF bypass: score ≥ 80 langsung execute tanpa LLM

### 6 Market Scanners
| Scanner | Sumber Data | Fungsi |
|---------|-------------|--------|
| `whale` | Public Binance OHLCV | Detect large wallet activity via volume spikes |
| `liquidation` | Public Binance orderbook | Liquidated positions detection |
| `orderbook` | Public Binance depth | Order book imbalance analysis |
| `volume_profile` | Public Binance klines | Volume profile + POC detection |
| `funding` | Public Binance funding rate | Funding rate anomaly detection |
| `smc` | Public Binance OHLCV + orderbook | Smart Money Concept signals |

### 11 Strategi (YAML hot-reload)
Semua strategi dalam `strategies/*.json` — edit langsung tanpa restart bot. StrategyLoader auto-reload setiap perubahan.

### Risk Engine (5 komponen)
- **RiskGuard** — pre-trade validation (10-layer), circuit breaker, kill/resume switch
- **KellySizer** — dynamic position sizing berdasarkan win rate + Kelly criterion
- **VaRCalc** — Value at Risk + Conditional VaR untuk portfolio risk
- **OBIAnalyzer** — Order Flow Imbalance untuk eksekusi quality
- **StressTest** — 5 scenario (flash crash, black swan, dll.) dengan estimated loss + rekomendasi

### MTF Analyzer
Analisa 3 timeframe (15m/1h/4h) secara parallel. Score ≥ 80 langsung execute (bypass LLM reasoning). Sideway detection + bounce detection untuk avoid false breakouts.

---

## 🔧 Persiapan & Instalasi

### Requirements
- Python 3.10+
- Telegram Bot Token (dari @BotFather)
- API Key + Secret Binance Futures **ATAU** Hyperliquid (hanya untuk live mode)
- Hermes Agent (opsional — untuk Smart Mode + self-improve cron job)

### Instalasi

```bash
# 1. Clone repo
git clone https://github.com/kiozhu/trador.git
cd trador

# 2. Install dependencies
pip install -r requirements.txt

# 3. Setup environment
cp .env.example .env
nano .env   # isi BOT_TOKEN, ADMIN_CHAT_ID, API keys (jika ada)

# 4. Jalankan (mode module flag WAJIB)
python3 -m src.main
```

### Cara Kerja Python Path
Trador pakai module flag (`-m src.main`) karena `src/` ada di root. Kalau pakai `python3 src/main.py` akan error import.

### Jalankan di Background
```bash
# Cara 1: nohup (cek process manual)
nohup python3 -m src.main > logs/trador.log 2>&1 &

# Cara 2: dari start script (double-spawn fix untuk Hermes)
bash charon2/start.sh
```

### Cek Bot Alive
```bash
pgrep -f "python3 -m src.main"
ps aux | grep "python3 -m src.main" | grep -v grep | wc -l
```

---

## ⚙️ Konfigurasi

Edit file `.env`:

```bash
# === Telegram ===
BOT_TOKEN=*** Token dari @BotFather
ADMIN_CHAT_ID=       # Numeric chat ID kamu (dari @userinfobot)

# === Exchange ===
EXCHANGE=binance     # "binance" atau "hyperliquid"
TESTNET_MODE=false   # true untuk Binance Testnet

# === API Keys (hanya untuk live mode) ===
# Binance Futures: API Key + Secret
# Hyperliquid: API Key + Secret (TIDAK perlu wallet address)

# === LLM (opsional — untuk Smart Mode) ===
LLM_PROVIDER=openrouter
LLM_API_KEY=
LLM_MODEL=anthropic/claude-sonnet-4

> ⚠️ **JANGAN pernah commit `.env` ke Git.** File ini sudah di `.gitignore`.

---

## 📱 Menu Telegram

Navigasi: `page:NAMAPAGE` (contoh: `page:status`, `page:settings`)

### 12 Halaman Menu

| Halaman | Fungsi |
|---------|--------|
| 🏠 Main | Dashboard utama — semua navigasi di sini |
| 📊 Status | Mode, balance, open positions, win rate 24h, LLM on/off |
| 💰 Balance | Dry run balance / live balance dari exchange |
| 📋 Positions | Semua posisi terbuka (symbol, direction, size, PnL, TP/SL) |
| 📜 History | Log trade dengan pagination, filter, delete |
| ⚙️ Strategy | Toggle 11 strategi ON/OFF |
| 📡 Monitor | Status scanner + strategi aktif |
| 🔧 Settings | Cycle interval, max orders, max positions, daily loss limit |
| 👛 Wallet | Input API Key + Secret, test connection |
| 🔴 Mode | Pilih Dry Run / Live |
| 🤖 Smart | Aktifkan LLM Smart Mode |
| ❓ Help | bantuan |

### Navigasi

```
🏠 Main
├── [📊 Status]   → page:status
├── [⚙️ Strategy] → page:strategy
├── [⚡ Quick]    → page:quick
├── [💰 Balance] → page:balance
├── [📡 Monitor] → page:monitor
├── [🔧 Settings] → page:settings
└── [❓ Help]    → page:help
```

### Perintah CLI

| Command | Fungsi |
|---------|--------|
| `/start` | Start bot, show main menu |
| `/stop` | Stop trading |
| `/newdryrun [balance]` | Reset dry run dengan balance tertentu |
| `/status` | Quick status |
| `/balance` | Show balance page |

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
Strategy files di `strategies/*.json` bisa diedit langsung — StrategyLoader auto-reload setiap perubahan (hot-reload). Tidak perlu restart bot.

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

## 🔍 6 Scanner Market

Semua scanner pakai **public API Binance** — tidak butuh API key. Berjalan parallel di setiap scan cycle.

| Scanner | Data Source | Fungsi |
|---------|-------------|--------|
| `whale` | OHLCV 15m/1h | Volume spike detection — identify large player activity |
| `liquidation` | Orderbook depth | Detect recent liquidations di price level |
| `orderbook` | Depth data | Order book imbalance — buy/sell pressure |
| `volume_profile` | Klines | POC (Point of Control) + volume nodes |
| `funding` | Funding rate API | Funding rate anomaly vs spot vs perp spread |
| `smc` | OHLCV + orderbook | Smart Money Concept — order blocks, FVG, liquidity sweep |

### MTF Scanner
MTF Analyzer run di setiap scan cycle untuk 3 timeframe (15m/1h/4h):
- **Bullish**: semua timeframe searah
- **Bearish**: semua timeframe berlawanan
- **Conflicting**: timeframe不一致 → skip (no trade)

---

## 🛡️ Risk Engine

Risk engine terdiri dari 5 komponen yang bekerja sama untuk proteksi portfolio.

### 1. RiskGuard — Pre-Trade Validation

10-layer check sebelum setiap order:
1. trading_enabled flag check
2. Daily loss limit check
3. Max concurrent positions check
4. Symbol whitelist/blacklist
5. Volatility regime check
6. Kelly size validation
7. Balance sufficiency check
8. Position size check (≤20% per trade)
9. Leverage check (≤20x)
10. Order timing (min interval between trades)

**Circuit Breaker:** Jika daily loss hit limit, `trading_enabled=False` sampai next day reset.

**Kill/Resume:** Telegram UI → Settings → 🛡️ Risk Engine → 🛑 Kill Switch / ▶️ Resume Trading.

### 2. KellySizer — Dynamic Position Sizing

Kelly Criterion dengan 8 adjustment factors:

| Factor | Penjelasan |
|--------|------------|
| `win_rate` | Win rate dari trade history |
| `avg_win` | Average win amount ($) |
| `avg_loss` | Average loss amount ($) |
| `kelly_fraction` | Kelly fraction (default 0.5 = half-Kelly) |
| `max_kelly_pct` | Maximum Kelly% (default 20%) |
| `win_streak` | Current win streak (bonus) |
| `loss_streak` | Current loss streak (penalty) |
| `confidence` | Historical data sufficiency (0-1) |

Output: `current_kelly` (0-20% dari balance) dan `confidence` (0-1).

### 3. VaRCalc — Value at Risk

Portfolio risk metrics:

| Metric | Penjelasan |
|--------|------------|
| `var_95` | Value at Risk 95% — max expected loss dalam 1 hari |
| `cvar_95` | Conditional VaR — average loss GIVEN breach |
| `worst_case` | Worst single position loss |
| `portfolio_exposure` | Total exposure across all positions |

Updated setiap scan cycle dari trade history + current positions.

### 4. OBIAnalyzer — Order Flow Imbalance

Analisa order flow dari orderbook depth untuk eksekusi quality:

| Signal | Penjelasan |
|--------|------------|
| `bid_ask_imbalance` | Buy/sell pressure ratio |
| `price_impact` | Estimated price impact |
| `order_book_depth` | Liquidity depth |
| `execution_quality` | Estimated fill quality |

Digunakan untuk reject poor execution pada saat high volatility.

### 5. StressTest — Scenario Testing

5 scenario untuk simulate worst-case losses:

| Scenario | Deskripsi |
|----------|-----------|
| 🔥 Flash Crash | Harga drop 15% dalam 1 jam |
| 📉 Black Swan | Harga drop 30% dalam 1 hari |
| 🌊 High Vol | Volatilitas 3x normal |
| 📰 News Gap | Gap down 10% overnight |
| 🔄 Sideway Chop | Whipsaw 5x dalam 1 hari |

Setiap scenario output:
- Estimated loss ($)
- Severity (🟢 Low / 🟡 Medium / 🟠 High / 🔴 Critical)
- Recommendations (action items)

### Risk Engine UI (Settings → 🛡️ Risk Engine)

Halaman Telegram khusus untuk monitoring risk:

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
- Balance virtual: $100 default
- Tidak ada order real — semua simulate
- Cocok untuk testing strategi + verify bot behavior
- Reset balance: Balance page → 🔄 Reset Dry Run → $100

### Live (Real)
- Balance sync dari exchange API (Binance Futures / Hyperliquid)
- Order real dieksekusi
- ⚠️ Risk tinggi — gunakan uang yang siap kehilangan

**Mode switch:** Main menu → 🔴 Mode → pilih Dry Run / Live

---

## 📊 Backtesting

```bash
cd /home/ubuntu/trador
python3 -m src.backtesting.run --strategy whale_rider --symbol BTCUSDT --interval 1h --days 30
```

**Output:**
- Equity curve PNG
- Trade markers di chart
- Drawdown fill
- Sharpe Ratio, Sortino Ratio, Max Drawdown

---

## ⚠️ Persiapan Live Money

**BOT INI BELUM SIAP UNTUK LIVE MONEY.**

### Checklist sebelum live:

- [ ] **Minimal 20+ dry-run trades** dengan win rate > 50%
- [ ] **Profitability proven** — dry-run balance consistently growing
- [ ] **API key tested** — rate limit, order execution latency, slippage verified
- [ ] **Risk parameters tuned** — daily loss limit, max position size, leverage sesuai comfort
- [ ] **MTF analysis verified** — false breakout rate rendah di live conditions

### Current Dry Run Track Record:
- ❌ 6/6 losing trades (100% loss rate)
- ❌ Balance $100 → $96 (negative return)
- ❌ API key belum tested di real execution

### Kapan boleh mulai live:
Hanya setelah dry-run menunjukkan win rate > 50% dan positive return minimal 30 trades.

---

## 🔧 Troubleshooting

### Bot tidak started
```bash
# Cek process
pgrep -f "python3 -m src.main"

# Ceck logs
tail -30 logs/trador.log

# Restart
pkill -f "python3 -m src.main" && python3 -m src.main
```

### "Message is not modified" di logs
Normal — bot mencoba render halaman yang isinya sama. Sudah di-handle gracefully, tidak mempengaruhi fungsi.

### Wallet connection failed
1. Cek API Key + Secret benar
2. Pastikan Futures enabled untuk Binance
3. Hyperliquid: hanya API Key + Secret, tidak perlu wallet address
4. Cek network connectivity dari server

### Scanner tidak jalan
- Scanner berjalan otomatis saat trading enabled
- Cek Monitor page untuk status scanner
- Semua scanner pakai public API — tidak butuh API key

### Balance tidak update di Live mode
- Pastikan wallet connected (Wallet page)
- Balance sync dari exchange API setiap kali halaman dibuka
- Refresh dengan klik Balance di menu

### Strategy tidak sync dengan yang dicentang
- Status page membaca dari `StrategyLoader.list_active_ids()` — source of truth
- Jika tidak sync, restart bot

### Bot terminated (exit code 143)
- SIGTERM — bot menerima kill signal, bukan crash
- Restart: `python3 -m src.main`
- Check logs untuk verify clean startup

---

## 📁 Struktur Folder

```
trador/
├── .env                  # Credentials (JANGAN COMMIT!)
├── .env.example          # Template
├── requirements.txt
├── README.md             # Dokumen utama (INI)
├── SPEC.md               # Technical specification
├── src/
│   ├── main.py           # Entry point
│   ├── trading/
│   │   ├── auto_trader.py   # Scan cycle + execution
│   │   ├── engine.py        # Core engine
│   │   ├── risk_guard.py    # Pre-trade validation (520 lines)
│   │   ├── kelly_sizer.py   # Dynamic position sizing (389 lines)
│   │   ├── var_calc.py      # VaR/CVaR calculator (259 lines)
│   │   ├── obi_analyzer.py  # Order flow imbalance (284 lines)
│   │   ├── stress_test.py   # Scenario tester (408 lines)
│   │   ├── mtf_analyzer.py  # Multi-timeframe (396 lines)
│   │   ├── strategies.py    # Strategy scoring (466 lines)
│   │   ├── rolling_buffer.py # Rolling stats (342 lines)
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
│   │   └── loader.py     # StrategyLoader — hot-reload
│   ├── tg_bot/
│   │   ├── menu/
│   │   │   ├── __init__.py   # MenuRouter + all handlers
│   │   │   └── pages/        # 12 page classes
│   │   └── handlers/         # Legacy handlers
│   ├── memory/
│   │   ├── state.py      # StateManager
│   │   ├── trade_log.py  # TradeLog
│   │   └── performance.py
│   ├── llm/
│   │   └── scorer.py
│   ├── backtesting/
│   │   └── run.py
│   └── utils/
│       └── logger.py
├── strategies/           # Strategy JSON files (hot-reload)
│   ├── whale_rider.json
│   ├── funding_arbitrage.json
│   └── ...
├── memory/               # Runtime data (per-machine)
│   ├── state.json
│   ├── trade_history.json
│   └── performance.json
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
| `/newdryrun [balance]` | Start dry run dengan balance tertentu |
| `/status` | Show quick status |
| `/balance` | Show balance page |
| `/help` | Show help |

---

**Last updated:** June 2026
**Version:** v3 (with integrated Risk Engine)
**Status:** DRY RUN ONLY — Not ready for live money