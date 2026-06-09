# Trador — Automated Crypto Futures Trading Bot

Bot trading crypto futures otomatis — dikontrol penuh via Telegram. Didukung 11 strategi, 6 scanners market, backtesting, dan Smart Mode dengan LLM.

> **Trador = BODY (eksekutor).** Dieksekusi persis. **Hermes = CONTROLLER** yang menganalisa hasil dan memberi saran. Jangan pernah ada credentials di committed code.

---

## ✨ Kelebihan Sistem

| # | Kelebihan | Penjelasan |
|---|-----------|------------|
| 1 | **11 Strategi Auto** | Semua strategi berjalan otomatis — whale rider, funding arbitrage, grid hunter, scalp rapid, swing stealth, breakout pro, fvg catcher, liquidation hunter, orderblock hunter, liquidity sweep, momentum EMA |
| 2 | **6 Scanner Real-time** | Whale, liquidation, orderbook, volume profile, funding rate, SMC — semua dapat data dari public API (gratis, tanpa API key) |
| 3 | **6 Exch +1 Wallet** | Binance Futures + Hyperliquid. Tidak ada Bybit/OKX. Hyperliquid tanpa wallet address — hanya API key + secret |
| 4 | **Hermes Comm Layer** | Communication via JSON files — Trador write reports, Hermes baca + analise + write suggestions. Pemisahan peran sempurna: Hermes passive only |
| 5 | **Smart Mode + LLM** | LLM-driven position sizing. Input API key LLM → validasi → konfirmasi. Cycle interval dengan deskripsi. Daily loss limit dalam dollar (bukan %) |
| 6 | **Dry Run + Live** | Dry run balance $100 (bukan $50k). Live balance sync dari wallet API. Tidak ada input manual untuk live |
| 7 | **Inline Keyboard Menu** | Semua menu pakai InlineKeyboardMarkup — trojan-style callback, tidak pakai ReplyKeyboardMarkup. Emoji di kiri tombol |
| 8 | **A-Z Coin Filter** | Symbol pool dari Binance Futures real data (50 coins). Filter huruf A-Z langsung dari keyboard, tidak perlu text input |
| 9 | **Backtesting** | Equity curve + drawdown chart + Sharpe/Sortino/Max Drawdown metrics |
| 10 | **Zero Credentials in Git** | `.env` selalu unstaged sebelum commit. Tidak ada API key/secret/token di Git history |

---

## 📋 Daftar Isi

1. [Kelebihan](#-kelebihan-sistem)
2. [Ringkasan](#-ringkasan)
3. [Persyaratan](#-persyaratan)
4. [Instalasi](#-instalasi)
5. [Konfigurasi](#-konfigurasi)
6. [Menu Telegram](#-menu-telegram)
7. [Strategi](#-strategi)
8. [Scanners](#-scanners)
9. [Mode Trading](#-mode-trading)
10. [Wallet Connect](#-wallet-connect)
11. [Hermes Comm](#-hermes-comm-smart-mode)
12. [Backtesting](#-backtesting)
13. [FAQ](#-faq)
14. [Troubleshooting](#-troubleshooting)
15. [Struktur Folder](#-struktur-folder)

---

## 🔰 Ringkasan

```
Trador
├── Telegram Bot      ← kontrol di sini
├── Trading Engine    ← ccxt → Binance Futures / Hyperliquid
├── Strategy Config   ← YAML files, hot-reload
├── Memory System     ← trade history, performance
├── 6 Scanners        ← market data real-time
├── LLM Scorer        ← scoring kualitas eksekusi
└── Hermes Comm       ← file-based JSON reports/suggestions
```

**Fitur utama:**
- 11 strategi trading (Whale Rider, EMA Cross, MACD Reversal, RSI Extreme, dll.)
- 6 scanner market real-time (liquidation, orderbook, whales, funding rate, volume profile, SMC)
- Live Mode / Dry Run Mode
- Hyperliquid + Binance Futures support
- Backtesting dengan equity curve + drawdown
- Smart Mode: LLM-driven position sizing via Hermes passive controller

---

## 📦 Persyaratan

- Python 3.10+
- Node.js 20+ (untuk development)
- Telegram Bot Token (dari @BotFather)
- API Key + Secret dari Binance Futures ATAU Hyperliquid
- Hermes Agent (opsional — untuk Smart Mode + self-improvement)

---

## 🚀 Instalasi

```bash
# Clone repo
git clone https://github.com/kiozhu/trador.git
cd trador

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
nano .env   # isi BOT_TOKEN, ADMIN_CHAT_ID, API keys
```

### Setup Python path

```bash
# Method 1: module flag (recommended)
python3 -m src.main

# Method 2: set PYTHONPATH
export PYTHONPATH=src:$PYTHONPATH
python3 src/main.py

# Method 3: run from src/
cd src && python3 main.py
```

### Start bot

```bash
python3 -m src.main
# atau background:
nohup python3 -m src.main > logs/trador.log 2>&1 &
```

### Restart

```bash
pkill -f "python3 -m src.main"
python3 -m src.main
```

---

## ⚙️ Konfigurasi

Edit file `.env`:

```bash
BOT_TOKEN=               # Telegram bot token (dari @BotFather)
ADMIN_CHAT_ID=           # Telegram chat ID admin ( numeric ID )
EXCHANGE=binance         # "binance" atau "hyperliquid"
TESTNET_MODE=false       # true untuk testnet (Binance Testnet)
```

**API Keys:**

| Exchange | Yang Dibutuhkan | Tidak Perlu |
|----------|----------------|-------------|
| Binance Futures | API Key + Secret | Wallet address |
| Hyperliquid | API Key + Secret | Wallet address, seed phrase |

> ⚠️ **JANGAN commit .env ke Git.** File ini sudah di .gitignore.

---

## 📱 Menu Telegram

### Cara Kerja

Semua interaksi via **InlineKeyboardMarkup** (tombol di dalam message). Tidak ada ReplyKeyboard.

Format callback: `prefix:action:value`
- `page:XXX` — navigasi halaman
- `set:XXX` — ubah settings
- `action:XXX` — eksekusi trading
- `strat:XXX` — manajemen strategi

---

### Halaman Menu

#### 🏠 Main Page
```
Trador v2
[Status] [Strategy] [Quick]
[Balance] [Monitor] [Settings]
[Help]
```
Akses semua halaman. Status hijau = bot hidup.

#### 📊 Status Page
- Mode (dry_run / live)
- Balance saat ini + PnL
- Open positions count
- Win rate 24h (dari trade_log, bukan perf tracker)
- Strategi aktif + jumlah
- Wallet connected / disconnected

#### 💰 Balance Page
- **Dry Run**: Balance simulasi, reset ke $100
- **Live**: Balance dari wallet exchange (sync otomatis)
- PnL since start, PnL 24h

#### 📋 Positions Page
- Semua posisi terbuka (symbol, direction, size, entry, PnL, TP/SL)
- Tombol close per posisi

#### 📜 History Page
- Log trade dengan pagination (5 per halaman)
- Filter: ALL / DRY RUN / LIVE
- Hapus history: 7 days / 30 days / ALL

#### ⚙️ Strategy Page
- 11 strategi — tap untuk toggle ON/OFF
- Default: semua ON
- Indikator ✅ = aktif

#### 📡 Monitor Page
- Status scanner (whale, liquidation, orderbook, volume_profile, funding, smc)
- Strategi yang aktif (dari StrategyLoader)
- Cycle interval + last scan time

#### 🔧 Settings Page

| Parameter | Deskripsi | Default |
|-----------|-----------|---------|
| LLM Smart | Position sizing via Hermes LLM | OFF |
| Cycle Interval | Detik antar scan cycle | 15s |
| Max Orders/Cycle | Maksimal order per cycle | 2 |
| Max Positions | Total posisi aktif bersamaan | 5 |
| Daily Loss Limit | Maksimal loss per hari ($) | $50 |
| Symbol Pool | Coin yang di-scan | 30 coins |

##### 🪙 Symbol Pool (Coin Filter)
- Tap `🪙 Coins` → halaman coin pool
- **A-Z Letter Filter**: tap huruf untuk filter coin berdasarkan huruf awal
- **Tap coin** untuk toggle enable/disable
- Data coin: real dari Binance Futures (top 50 USDT pairs by volume)
- Fallback ke 30 coin static jika API gagal

#### 👛 Wallet Page
- Pilih exchange: Binance Futures / Hyperliquid
- Input API Key + Secret
- Test connection → konfirmasi "✅ Connected" atau "❌ Failed"

#### 🔴 Mode Page
- **Dry Run**: Simulasi, tidak perlu API key (bisa test tanpa risiko)
- **Live**: Real trading, butuh wallet connected + API keys

---

## 📈 Strategi

Default: semua 11 strategi **AKTIF**.

| ID | Nama | Deskripsi Singkat |
|----|------|-------------------|
| `whale_rider` | Whale Rider | Riding large wallet orders via funding rate anomalies |
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

---

## 🔍 Scanners

6 scanner berjalan parallel di setiap cycle:

| Scanner | Data Source | Fungsi |
|---------|-------------|--------|
| `whale` | Public Binance OHLCV | Detect whale activity |
| `liquidation` | Public Binance orderbook | Liquidated positions |
| `orderbook` | Public Binance depth | Order book imbalance |
| `volume_profile` | Public Binance klines | Volume profile analysis |
| `funding` | Public Binance funding rate | Funding rate anomalies |
| `smc` | Public Binance OHLCV + orderbook | Smart Money Concept signals |

> Semua scanner menggunakan **public API** — tidak butuh API key.

---

## 🔄 Mode Trading

### Dry Run (Simulasi)
- Balance simulated: $100 default
- Tidak ada order real
- Cocok untuk testing strategi

### Live (Real)
- Balance dari wallet exchange (Binance Futures / Hyperliquid)
- Order real被执行
- ⚠️ Risk: real money involved

---

## 👛 Wallet Connect

### Binance Futures
```
1. Buka Binance → API Management
2. Buat API Key (Futures enabled)
3. Input Key + Secret di Wallet page
4. Test Connection
```

### Hyperliquid
```
1. Buka Hyperliquid → API
2. Buat API Key
3. Input Key + Secret (no wallet address needed)
4. Test Connection
```

> Hyperliquid **tidak butuh wallet address** — hanya API key + secret.

---

## 🤖 Hermes Comm (Smart Mode)

Hermes Comm = communication layer antara **Hermes Agent** (kamu ngobrol sama aku) dan **Trador** (trading bot) via JSON files.

**Arsitektur:**
```
┌─────────────────────────────────────────────────────────┐
│  TRADOR BOT (executor body)                             │
│  • Execute trades                                       │
│  • Write reports → shared/trador_reports/               │
└──────────────────┬──────────────────────────────────────┘
                   ↓ write JSON
 shared/trador_reports/
         ├── trades.json      ← trade results
         ├── status.json      ← bot status
         └── metrics.json     ← 24h metrics
                   │ read (cron job 15 menit)
                   ↓
┌─────────────────────────────────────────────────────────┐
│  HERMES AGENT (this bot — kamu ngobrol sama aku)         │
│  • Baca reports │
│  • Analisa dengan LLM                                   │
│  • Write suggestions → shared/hermes_suggestions/ │
└──────────────────┬──────────────────────────────────────┘
                   │ Trador auto-read& apply
                   ↓
         shared/hermes_suggestions/pending/
         └── suggestion JSON files
                   │
                   ↓ (auto-processed)
         Strategy files di src/strategy/
```

**Cron Job Hermes:**
```
Name:  trador-hermes-reader
Every: 15 minutes
Task:  Baca trades.json → Analisa → Tulis suggestion
```

**Perintah managing cron job:**
```bash
# Lihat semua cron job
hermes cron list

# Lihat detail (nama, schedule, next run)
hermes cron list | grep trador

# Hapus cron job
/hermes cron remove <job_id>
```

**Yang DILAKUKAN Hermes (passive):**
- ✅ Analisa win rate per strategi
- ✅ Suggest position size adjustments
- ✅ Identify market regime patterns
- ✅ Recommend strategy params

**Yang TIDAK dilakukan Hermes:**
- ❌ Touch execution langsung
- ❌ Buka/tutup posisi
- ❌ Ganti strategy files langsung

---

## 📊 Backtesting

```bash
cd src
python3 -m backtesting.run
```

**Output:**
- Equity curve chart (PNG)
- Trade markers di chart
- Drawdown fill
- Sharpe Ratio, Sortino Ratio, Max Drawdown

**Contoh:**
```bash
python3 -m backtesting.run --strategy whale_rider --symbol BTCUSDT --interval 1h --days 30
```

---

## ❓ FAQ

### Q: Apakah 11 strategi bisa dipakai gratis?
**A:** Ya. Semua strategi menggunakan **public Binance API** (`fapi.binance.com`). Tidak butuh API key untuk scanner/strategi. API key hanya diperlukan untuk **Live trading** (buka posisi real).

### Q: max_orders_per_cycle vs max_concurrent_positions bedanya?
**A:**
- `max_orders_per_cycle` = berapa kali bot boleh **buka posisi baru** tiap cycle scan
- `max_concurrent_positions` = total **posisi aktif bersamaan** (belum ditutup/TP/SL)

Contoh: max_orders=2, max_pos=5
→ Tiap 15 detik, bot boleh buka max 2 posisi baru
→ Total tidak boleh lebih dari 5 posisi aktif

### Q: Cycle interval itu apa?
**A:** Detik antar scan cycle. Default 15s.

**Cycle flow:**
```
1. Fetch price semua coin di pool
2. Jalankan 11 strategi → score per coin
3. Top score + filter risk → buka posisi
4. Check TP/SL semua posisi terbuka
5. Sleep cycle_interval
```

Semakin kecil interval = semakin responsif tapi **lebih banyak API calls**.

### Q: Symbol pool itu apa?
**A:** Daftar coin yang di-scan tiap cycle. Default 30 coins dari Binance Futures top volume.

- Tap `🪙 Coins` di Settings untuk customize
- Filter huruf A-Z untuk find coin spesifik
- ✅ = enabled (di-scan), ❌ = disabled

### Q: Kenapa Status menunjukkan 0% Win Rate padahal sudah profit?
**A:** Win Rate dihitung langsung dari `trade_log.json` (semua trade records). Jika kosong atau tidak ada trade, Win Rate = 0%. Bukan dari `performance.json` yang tidak pernah di-update.

### Q: Bagaimana cara reset dry run balance?
**A:** Balance page → `🔄 Reset Dry Run → $100`

### Q: Live balance tidak sync?
**A:** Pastikan wallet sudah connected (Wallet page → Test Connection). Live balance diambil langsung dari exchange API, bukan dari input manual.

### Q: Bot tidak response saat diklik?
**A:** 
1. Cek bot alive: `pgrep -f "python3 -m src.main"`
2. Restart: `pkill -f "python3 -m src.main" && python3 -m src.main`
3. Cek logs: `tail -20 logs/trador.log`

### Q: Hyperliquid butuh wallet address?
**A:** Tidak. Hyperliquid hanya butuh **API Key + Secret**. Tidak ada wallet address atau seed phrase.

### Q: Daily loss limit dalam apa?
**A:** Dalam **dollar ($)** — bukan persen. Default $50/hari. Jika total PnL negatif mencapai -$50, bot akan stop trading sampai hari berikutnya.

### Q: Bagaimana cara hapus semua history?
**A:** History page → 🔽 Filter → Pilih **ALL** → 🗑️ Delete → Pilih rentang (7 days / 30 days / ALL data)

---

## 🔧 Troubleshooting

### Bot tidak started
```bash
# Cek process
pgrep -f "python3 -m src.main"

# Cek logs
tail -20 logs/trador.log

# Restart
pkill -f "python3 -m src.main"
python3 -m src.main
```

### "Message is not modified" di logs
Normal — bot mencoba render halaman yang isinya sama persis. Sudah di-handle gracefully, tidak mempengaruhi fungsi.

### Wallet connection failed
1. Cek API Key + Secret benar
2. Pastikan Futures enabled untuk Binance
3. Hyperliquid: hanya API Key + Secret, tidak perlu wallet address
4. Cek network connectivity dari server

### Balance tidak update di Live mode
- Pastikan wallet connected (Wallet page)
- Balance sync dari exchange API setiap kali halaman dibuka
- Refresh dengan klik Balance di menu

### Strategi tidak sync dengan yang dicentang
- Status page membaca dari `StrategyLoader.list_active_ids()` — source of truth
- Monitor page juga membaca dari StrategyLoader
- Jika tidak sync, restart bot: `pkill -f "python3 -m src.main" && python3 -m src.main`

### Scanner tidak jalan
- Scanner berjalan otomatis saat trading enabled
- Cek Monitor page untuk status scanner
- Semua scanner menggunakan public API — tidak butuh API key

### API rate limit
- Default cycle 15s — sudah aman untuk Binance public API
- Jika limit tercapai, bot会自动 backoff
- Hyperliquid: lebih toleran untuk rate limit

### Coin pool hanya show A-I
- Pastikan halaman coin pool di-render dengan benar
- Huruf di-split jadi 4 rows (A-G, H-N, O-U, V-Z)
- Jika ada letter tanpa coin, tampil sebagai `·` (disabled)

---

## 📁 Struktur Folder

```
trador/
├── .env                  # Credentials (JANGAN commit!)
├── .env.example          # Template
├── requirements.txt
├── README.md
├── SPEC.md
├── src/
│   ├── main.py           # Entry point
│   ├── trading/
│   │   ├── engine.py     # Core trading engine
│   │   └── auto_trader.py # 11-strategy auto trader
│   ├── scanners/
│   │   ├── whale_scanner.py
│   │   ├── liquidation_scanner.py
│   │   ├── orderbook_scanner.py
│   │   ├── volume_profile_scanner.py
│   │   ├── funding_scanner.py
│   │   └── smc_scanner.py
│   ├── strategy/
│   │   ├── loader.py     # StrategyLoader — hot-reload
│   │   └── *.yaml        # Strategy configs
│   ├── tg_bot/
│   │   ├── menu/
│   │   │   ├── __init__.py      # MenuRouter + handlers
│   │   │   ├── core.py          # MenuPage + MenuNavigator
│   │   │   └── pages/
│   │   │       ├── main_page.py
│   │   │       ├── status_page.py
│   │   │       ├── balance_page.py
│   │   │       ├── positions_page.py
│   │   │       ├── history_page.py
│   │   │       ├── strategy_page.py
│   │   │       ├── monitor_page.py
│   │   │       ├── settings_page.py
│   │   │       ├── wallet_page.py
│   │   │       ├── mode_page.py
│   │   │       ├── smart_page.py
│   │   │       ├── quick_page.py
│   │   │       └── help_page.py
│   │   └── handlers/     # Legacy handlers (deprecated)
│   ├── memory/
│   │   ├── state.py      # StateManager
│   │   ├── trade_log.py  # TradeLog
│   │   └── performance.py # PerformanceTracker
│   ├── llm/
│   │   └── scorer.py     # LLM scoring
│   ├── backtesting/
│   │   └── run.py        # Backtesting CLI
│   └── utils/
│       └── logger.py
├── memory/               # Runtime data
│   ├── state.json
│   ├── trade_history.json
│   ├── performance.json
│   ├── dry_run/
│   └── live/
├── shared/                # Hermes Comm (JSON reports/suggestions)
│   ├── trador_reports/    # ← Trador writes (trades.json, status.json)
│   └── hermes_suggestions/ # ← Hermes writes (pending/ suggestions)
│       └── pending/
├── strategies/           # Strategy YAML files
│   ├── whale_rider.yaml
│   └── ...
└── logs/
    └── trador.log
```

---

## 📌 Commands

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
**Version:** v2 (inline keyboard menu system)
