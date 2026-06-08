# Trador

Bot trading crypto futures otomatis — sangat dibagus jika digunakan bersama Hermes agen yang bisa belajar dari kesalahan dan terus memperbaiki diri, dikontrol via Telegram.

**Trador = BODY (eksekutor).** Ikuti strategi persis. **Hermes = CONTROLLER** yang bisa modify strategy files. LLM hanya scoring kualitas eksekusi, tidak pernah ubah strategi.

> Kalau Hermes jatuh, Trador tetap jalan. Hercules tetap makan.

---

## 📋 Daftar Isi

1. [Ringkasan](#-ringkasan)
2. [Persyaratan](#-persyaratan)
3. [Instalasi](#-instalasi)
4. [Konfigurasi](#-konfigurasi)
5. [Menu Telegram](#-menu-telegram)
6. [Strategi](#-strategi)
7. [Scanners](#-scanners)
8. [Mode Trading](#-mode-trading)
9. [Direction](#-direction)
10. [Wallet Connect](#-wallet-connect)
11. [PnL Chart](#-pnl-chart)
12. [Smart Mode](#-smart-mode)
13. [Quick Actions](#-quick-actions)
14. [Hermes Integration](#-hermes-integration)
15. [Role Separation](#-role-separation)
16. [Struktur Folder](#-struktur-folder)
17. [API Endpoints](#-api-endpoints)
18. [Troubleshooting](#-troubleshooting)

---

## 🔰 Ringkasan

```
Trador
├── Telegram Bot      ← kontrol di sini
├── Trading Engine    ← ccxt → Binance Futures
├── Strategy Config   ← JSON files, hot-reload
├── Memory System     ← trade history, performance
├── Scanners         ← market data real-time
├── LLM Scorer       ← scoring kualitas eksekusi
└── Hermes Comm      ← file-based JSON reports/suggestions
```

**Fitur utama:**
- 11 strategi trading
- 6 scanner market real-time (liquidation, orderbook, whales, funding rate, volume profile, SMC)
- Live Mode / Dry Run Mode
- Long / Short / Both direction
- Wallet connect ke Binance, Bybit, OKX
- PnL chart (24h / 7d / 30d / all)
- Smart Mode — auto switch strategi terbaik
- Telegram control panel lengkap
- Berdiri sendiri tanpa Hermes

---

## ✅ Persyaratan

- **Python 3.10+**
- **Node.js 18+** (untuk بعض dependencies)
- **Binance Futures account** (atau testnet)
- **Telegram Bot Token** — dari @BotFather
- **MiniMax API Key** — untuk LLM scorer (opsional)

---

## 🚀 Instalasi

```bash
# 1. Clone
git clone git@github.com:kiozhu/trador.git
cd trador

# 2. Virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Setup environment
cp .env.example .env
```

---

## ⚙️ Konfigurasi

Edit file `.env`:

```env
# ── Telegram Bot ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# ── Exchange API (Binance Futures) ────────────────────────────
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
TESTNET=false                    # true = testnet, false = real

# ── Exchange API (Bybit) ─────────────────────────────────────
BYBIT_API_KEY=your_bybit_api_key
BYBIT_API_SECRET=your_bybit_api_secret

# ── Exchange API (OKX) ───────────────────────────────────────
OKX_API_KEY=your_okx_api_key
OKX_API_SECRET=your_okx_api_secret
OKX_PASSPHRASE=your_okx_passphrase

# ── LLM Scorer (MiniMax) ─────────────────────────────────────
MINIMAX_API_KEY=your_minimax_api_key

# ── Misc ─────────────────────────────────────────────────────
LOG_LEVEL=INFO
```

### Cara dapat API Key Binance Futures

1. Login ke [binance.com](https://www.binance.com)
2. Go to **Dashboard → API Management**
3. Buat API Key baru — centang **Enable Futures**
4. Simpan `API Key` dan `Secret Key`
5. **PENTING:** Set IP whitelist (kosongkan untuk allow all, atau isi IP server)
6. **PENTING:** Aktifkan **Enable Spot & Margin Trading** jika perlu

> ⚠️ Jangan pernah share API Secret kamu. Simpan di `.env` yang sudah di-`.gitignore`.

---

## 📱 Menu Telegram

Setelah bot jalan, kirim `/start` di Telegram. Menu utama:

```
┌─────────────────────────────────────────┐
│ ⚡ Quick Actions  │  📈 Positions      │
│ ⚙️ Strategi       │  📋 History        │
│ 🚀 Start          │  🛑 Stop           │
│ 💰 Balance        │  🧠 Smart Mode    │
│ 📊 PnL Chart      │  🔗 Wallet         │
│ 🎮 Mode           │  📐 Direction      │
│ ❓ Help                                │
└─────────────────────────────────────────┘
```

### Detail Menu

| Button | Fungsi |
|--------|--------|
| **⚡ Quick Actions** | View Orders, Cancel All, Close All, Avg Entry, Scan Market |
| **📈 Positions** | Lihat semua posisi terbuka |
| **⚙️ Strategi** | Pilih strategi, adjust parameter |
| **📋 History** | Riwayat trade terakhir |
| **🚀 Start** | Aktifkan trading |
| **🛑 Stop** | Hentikan trading |
| **💰 Balance** | Lihat saldo account |
| **🧠 Smart Mode** | Auto switch strategi terbaik berdasarkan performance |
| **📊 PnL Chart** | Chart PnL (24h / 7d / 30d / All) |
| **🔗 Wallet** | Connect ke exchange (Binance / Bybit / OKX) |
| **🎮 Mode** | Switch Live / Dry Run |
| **📐 Direction** | Set Long / Short / Both |
| **❓ Help** | Panduan penggunaan |

---

## 📊 Strategi

11 strategi tersedia. Semua menggunakan prinsip: **TP kecil tapi sering, bukan TP besar yang jarang tercapai.**

### Prinsip Trading

```
❌ GREEDY TP
├── TP 100% → jarang tercapai
├── Akhirnya kena SL
└── 1 trade = wipe out

✅ CONSISTENT TP  
├── TP 10-15%
├── High frequency trading
├── Compounding
└── 1000x small wins > 1 big loss
```

### Leverage Math

```
Dengan leverage, SL/TP dalam % adalah % HARGA, bukan % MARGIN.
 
Contoh: BTC $100,000, leverage 10x, entry LONG
- Harga turun 0.5% → $99,500
- Loss = 0.5% × 10 = 5% dari margin

Jadi:
- SL -1% di price = -10% margin (10x leverage) — TOO TIGHT
- SL -2% di price = -20% margin — LANGSUNG WIPED
- Max margin loss yang aman: 15-20%
- SL = Max_margin_loss / Leverage
```

### Daftar Strategi

#### 1. Scalp Rapid ⚡⚡⚡
```
TP: 2% (price) | SL: 1.5% (price) | Leverage: 10x
Signal: EMA9/21 crossover + RSI + Volume spike
Frequency: SANGAT TINGGI — scalping cepat
Max hold: 5 menit
```

#### 2. Liquidation Hunter ⚡⚡⚡⚡
```
TP: 2% (price) | SL: 1.5% (price) | Leverage: 10x
Signal: Liquidation cascade dari Binance WebSocket
Frequency: SANGAT TINGGI
Entry: Setelah liquidation wave terdeteksi
- Short cascade (BUY liquidations) → go LONG
- Long cascade (SELL liquidations) → go SHORT
Max hold: 3 menit
```

#### 3. Momentum EMA ⚡⚡
```
TP: 3% (price) | SL: 2% (price) | Leverage: 5x
Signal: EMA20/50 crossover + ADX filter + RSI
Frequency: TINGGI
Max hold: 15 menit
```

#### 4. Grid Hunter ⚡⚡
```
TP: 2% (price) | SL: 1.5% (price) | Leverage: 5x
Signal: Bollinger Bands range bound
Frequency: TINGGI — buy low sell high di range
Cocok: Market sideways
Max hold: 15 menit
```

#### 5. Breakout Pro ⚡⚡
```
TP: 4% (price) | SL: 2% (price) | Leverage: 5x
Signal: Breakout consolidation + volume confirmation
Frequency: SEDANG
Max hold: 20 menit
```

#### 6. Swing Stealth ⚡
```
TP: 5% (price) | SL: 3% (price) | Leverage: 3x
Signal: EMA50/200 trend following + ADX
Frequency: RENDAH — swing trade
Max hold: 2 jam
```

#### 7. Order Block Hunter (SMC) ⚡⚡
```
TP: 4% (price) | SL: 2% (price) | Leverage: 5x
Signal: Order Block reclaim (institutional zones)
Source: Smart Money Concepts
Frequency: SEDANG
Max hold: 30 menit
```

#### 8. FVG Catcher (SMC) ⚡⚡⚡
```
TP: 3% (price) | SL: 1.5% (price) | Leverage: 8x
Signal: Fair Value Gap fill
Source: Smart Money Concepts — 3-candle imbalance
Frequency: TINGGI
Max hold: 10 menit
```

#### 9. Liquidity Sweep (SMC) ⚡⚡⚡
```
TP: 2.5% (price) | SL: 1% (price) | Leverage: 10x
Signal: Liquidity sweep reversal (stop hunt)
Source: Smart Money Concepts
Frequency: TINGGI — reversal after stop hunt
Max hold: 5 menit
```

#### 10. Funding Arbitrage 💰
```
TP: 2% (price) | SL: 4% (price) | Leverage: 3x
Signal: Funding rate edge
Source: Binance funding rate monitoring
Entry: Lawan arah funding rate tinggi
Max hold: 8 jam
Target: Collect funding payments
```

#### 11. Whale Rider 🐋
```
TP: 2.5% (price) | SL: 1% (price) | Leverage: 10x
Signal: Whale activity (large trades > $50K)
Source: DexScreener + Binance WS
Frequency: TINGGI
Max hold: 5 menit
```

### Setup Strategy via Telegram

```
⚙️ Strategi → Pilih strategi → Inline keyboard:
├── ✅ Active (aktifkan)
├── 📝 Parameters (adjust SL/TP/lev)
├── 📈 Performance (win rate, avg PnL)
└── 🧠 Smart Select (Hermes pilih terbaik)
```

---

## 🔍 Scanners

6 scanner market real-time. Semua **GRATIS, no API key** (kecuali kalau butuh private data).

### 1. Liquidation Scanner 🔥
```
Source: wss://fstream.binance.com/stream?streams=<symbol>@forceOrder
Data: Real-time forced liquidations (no API key)
Logic: Group liquidation events into price clusters
Signal: Cluster > $50K = potential cascade
Update: Real-time
```

### 2. Orderbook / Wall Scanner 📊
```
Source: wss://fstream.binance.com/stream?streams=<symbol>@depth20@100ms
Data: Orderbook depth 20 levels, 100ms update
Logic: Wall = level > 5x rolling average size
Signal: Large wall appear/disappear
Update: 100ms (very fast)
```

### 3. Whale Scanner 🐋
```
Source: 
  - Binance WS: <symbol>@trade (large trades > $50K)
  - DexScreener API: https://api.dexscreener.com/dex/v1/trades
Data: Large trades di Solana + Binance futures
Logic: Cluster whale trades by symbol/side
Signal: Cluster confirmed = follow whale direction
Update: Real-time + 10s polling DexScreener
```

### 4. Funding Rate Scanner 💰
```
Source:
  - REST: https://fapi.binance.com/fapi/v1/premiumIndex
  - WS: wss://fstream.binance.com/stream?streams=!premiumIndex@arr
Data: Funding rate per symbol, 8h interval
Logic: Funding rate > threshold = edge opportunity
Signal: High funding = trade opposite direction
Update: Real-time via WebSocket
```

### 5. Volume Profile Scanner 📈
```
Source: https://api.binance.com/api/v3/klines (REST, no API key)
Data: OHLCV candles
Logic:
  - POC (Point of Control): Price level dengan volume tertinggi
  - VAH (Value Area High): Batas atas 70% volume
  - VAL (Value Area Low): Batas bawah 70% volume
Signal: Price return ke POC = high probability entry
Update: Per request (on-demand)
```

### 6. SMC Scanner 🎯
```
Source: https://api.binance.com/api/v3/klines (REST, no API key)
Data: OHLCV candles 15m/1h
Features:
  - Order Blocks: Institutional zones dari candle bodies/wicks
  - Fair Value Gaps: 3-candle imbalance
  - Liquidity Sweeps: Stop hunt detection (price sweeps high/low)
  - Market Structure: Swing highs/lows, BOS (Break of Structure)
  - BTC Master Filter: Block trades vs BTC trend
Signal: confluence 3+ factors
Update: Per request (on-demand)
```

---

## 🎮 Mode Trading

### Live Mode 🔴
- Real money trading
- Butuh wallet connect ke exchange
- Semua order menggunakan dana nyata

### Dry Run Mode 🟡
- Simulasi trading
- Tidak butuh wallet connect
- Aman untuk testing strategi

### Switch Mode via Telegram

```
🎮 Mode → Pilih:
├── 🔴 LIVE
└── 🟡 DRY RUN

Konfirmasi:
"Switch ke LIVE mode? Pastikan wallet sudah connect."
[✅ Ya, switch] [❌ Batal]
```

---

## 📐 Direction

Atur arah trading:

| Direction | Fungsi |
|-----------|--------|
| **📈 LONG** | Profit saat harga naik |
| **📉 SHORT** | Profit saat harga turun |
| **🔄 BOTH** |双向 — profit kedua arah (recommended) |

```
📐 Direction → Pilih:
├── 📈 LONG
├── 📉 SHORT
└── 🔄 BOTH
```

> 💡 **Rekomendasi: BOTH.** Future trading bisa profit naik DAN turun. Yang penting analisa + strategi, bukan arah market.

---

## 🔗 Wallet Connect

Connect ke exchange untuk Live Mode:

```
🔗 Wallet → Pilih Exchange:
├── 🟣 Binance Futures
├── 🔵 Bybit Unified
└── 🟠 OKX

→ Masukkan API Key + Secret
→ Test connection
→ Show balance
→ Wallet connected ✅
```

**Data yang dibutuhkan:**
- Binance: `BINANCE_API_KEY` + `BINANCE_API_SECRET`
- Bybit: `BYBIT_API_KEY` + `BYBIT_API_SECRET`
- OKX: `OKX_API_KEY` + `OKX_API_SECRET` + Passphrase

**Yang TIDAK dibutuhkan:**
- Seed phrase (itu untuk DeFi/MetaMask, bukan CEX)
- Withdrawal permission (cukup trading permission)

---

## 📈 PnL Chart

Visualisasi performance:

```
📊 PnL Chart → Pilih Periode:
├── ⏱️ 24 Jam
├── 📅 7 Hari
├── 🗓️ 30 Hari
├── ♾️  Semua
└── 📋 Text Summary

Chart: Dark-themed line chart
- Cumulative PnL over time
- Win/lose color green/red
- Shows: Mode, Direction, Strategy, Final PnL
```

Text Summary juga tersedia:
- Total trades
- Win rate
- Wins / Losses count
- Total PnL
- Recent 5 trades

---

## 🧠 Smart Mode

Mode otomatis — bot switch ke strategi terbaik berdasarkan performance:

```
🧠 Smart Mode → Panel:
├── 🤖 Auto Trading: ON/OFF
├── 🧠 Hermes Passive: ON/OFF
├── 📈 Best Strategy: [strategy_name]
├── 🔄 Force Scan
├── 🧪 Simulate Signal
└── 📊 Performance Dashboard
```

**Auto Trading ON:** Bot auto switch strategi terbaik tanpa konfirmasi.

**Hermes Passive ON:** Hermes hanya scoring, tidak auto-apply suggestions.

---

## ⚡ Quick Actions

Aksi cepat tanpa masuk menu:

```
⚡ Quick Actions → Pilih:
├── 📋 View Orders
├── 🗑️ Cancel All (konfirmasi)
├── 🔻 Close All (konfirmasi)
├── 📊 Avg Entry
└── 🔍 Scan Market
```

**Cancel All:** Batalkan semua open orders. Konfirmasi diperlukan.

**Close All:** Tutup semua posisi. Konfirmasi diperlukan.

---

## 🤖 Hermes Integration

Trador dan Hermes berkomunikasi via file-based JSON.

### Trador → Hermes (Reports)

```
shared/trador_reports/
├── status.json       # Current state (every 30s)
├── trades.json       # Trade results (after each trade)
├── metrics.json      # Performance metrics (hourly)
└── alerts.json       # Error/warning alerts
```

### Hermes → Trador (Suggestions)

```
shared/hermes_suggestions/
├── pending/          # ← Hermes writes di sini
│   └── suggestion_<timestamp>.json
└── processed/        # → Trador move ke sini setelah diproses
```

### Suggestion Format

```json
{
  "id": "sug_001",
  "timestamp": 1750000000,
  "type": "strategy_adjust",
  "data": {
    "strategy_id": "scalp_rapid",
    "changes": {
      "risk.sl_percent": -1.0,
      "risk.tp_percent": 2.5
    },
    "reason": "Win rate menurun 10% dalam 1 jam terakhir"
  }
}
```

### Trador Hard Limits

Trador **MENOLAK** suggestion kalau:

1. **Expired** — suggestion older than 5 minutes
2. **Cooling off** — another suggestion for same strategy < 10 min ago
3. **Risk violation:**
   - `leverage > 20`
   - `sl_percent > 5` (price terms)
   - `size_value > 20%` of balance
   - `max_open > 5`

---

## 🔀 Role Separation

**PRINSIP UTAMA:**

```
Hermes = CONTROLLER (strategy)
Trador = EXECUTOR (execution)
LLM    = SCORER (execution quality only)
```

| Siapa | Fungsi | BISA apa | TIDAK BISA apa |
|-------|--------|----------|----------------|
| **Hermes** | Analisa, strategi | Baca reports, ubah strategy JSON | Eksekusi trade, akses exchange |
| **Trador** | Eksekusi | Trade sesuai strategy, enforce limits | Ubah strategy sendiri |
| **LLM** | Scoring | Score execution quality | Ubah strategi |

**Memory Separation:**

```
Hermes memory ← tidak pernah menyentuh memory Trador
Trador memory ← tidak pernah dibaca Hermes
Komunikasi ← hanya via shared/ folder (JSON files only)
```

**Kenapa pisah?**

```
Kalau Hermes error → Trador tetap jalan
Kalau Trador error → Hermes tetap bisa analisa
Tidak ada single point of failure
```

---

## 📁 Struktur Folder

```
trador/
├── .env                        # API keys, tokens
├── .env.example                # Template
├── README.md                   # Dokumen ini
├── SPEC.md                     # Technical specification
├── requirements.txt            # Python dependencies
│
├── src/
│   ├── main.py                # Entry point
│   │
│   ├── tg_bot/                # Telegram bot
│   │   ├── keyboards.py       # Reply/Inline keyboards
│   │   └── handlers/
│   │       ├── menu.py        # Status, balance, help
│   │       ├── positions.py    # View positions
│   │       ├── trades.py       # Trade history
│   │       ├── strategy.py     # Strategy management
│   │       ├── smart_mode.py   # Smart Mode panel
│   │       ├── quick_actions.py # Quick actions
│   │       ├── wallet.py       # Wallet/mode/direction
│   │       ├── pnl.py          # PnL chart
│   │       └── pnl_chart.py    # Chart generator
│   │
│   ├── trading/               # Trading engine
│   │   ├── engine.py         # ccxt wrapper
│   │   ├── signals.py        # Signal generation
│   │   └── position_manager.py # Position tracking
│   │
│   ├── scanners/              # Market data scanners
│   │   ├── liquidation_scanner.py   # Liquidation WS
│   │   ├── orderbook_scanner.py     # Orderbook walls
│   │   ├── whale_scanner.py          # Whale trades
│   │   ├── funding_scanner.py        # Funding rate
│   │   ├── volume_profile_scanner.py # POC/VAH/VAL
│   │   └── smc_scanner.py            # SMC indicators
│   │
│   ├── strategy/              # Strategy management
│   │   ├── loader.py         # Load strategy JSONs
│   │   ├── validator.py      # Validate strategy config
│   │   └── watcher.py        # Hot-reload on file change
│   │
│   ├── memory/                # Trador's memory
│   │   ├── state.py          # State manager
│   │   ├── trade_log.py      # Trade history
│   │   └── performance.py    # Performance metrics
│   │
│   ├── comm/                  # Hermes communication
│   │   ├── reporter.py       # Write reports → Hermes
│   │   └── reader.py        # Read suggestions ← Hermes
│   │
│   ├── llm/                  # LLM scorer
│   │   └── scorer.py        # Score execution quality
│   │
│   └── utils/
│       ├── logger.py         # Logging
│       └── helpers.py        # Helpers
│
├── strategies/                # Strategy JSON files
│   ├── scalp_rapid.json
│   ├── liquidation_hunter.json
│   ├── momentum_ema.json
│   ├── grid_hunter.json
│   ├── breakout_pro.json
│   ├── swing_stealth.json
│   ├── orderblock_hunter.json
│   ├── fvg_catcher.json
│   ├── liquidity_sweep.json
│   ├── funding_arbitrage.json
│   └── whale_rider.json
│
├── shared/                    # Hermes communication (file-based)
│   ├── trador_reports/       # → Hermes reads
│   └── hermes_suggestions/   # ← Hermes writes
│
├── memory/                    # Trador persistent memory
│   ├── state.json            # Current state
│   ├── trades.json           # Trade history
│   └── performance.json      # Metrics
│
└── logs/                      # Log files
    └── trador.log
```

---

## 🌐 API Endpoints

### Binance Futures (Public — No API Key)

| Endpoint | Method | Fungsi |
|----------|--------|--------|
| `/fapi/v1/klines` | GET | OHLCV candles |
| `/fapi/v1/premiumIndex` | GET | Funding rate |
| `/fapi/v1/forceOrder` | GET | Recent liquidations |
| `/fapi/v1/openInterest` | GET | Open interest |

### Binance Futures (Requires API Key)

| Endpoint | Method | Fungsi |
|----------|--------|--------|
| `/fapi/v1/account` | GET | Account info |
| `/fapi/v1/positionRisk` | GET | Position info |
| `/fapi/v1/order` | POST | Place order |
| `/fapi/v1/order` | DELETE | Cancel order |

### WebSocket Streams (Public)

| Stream | URL | Fungsi |
|--------|-----|--------|
| Trade | `wss://fstream.binance.com/stream?streams=<sym>@trade` | Real-time trades |
| Force Order | `wss://fstream.binance.com/stream?streams=<sym>@forceOrder` | Liquidations |
| Depth | `wss://fstream.binance.com/stream?streams=<sym>@depth20@100ms` | Orderbook |
| Premium Index | `wss://fstream.binance.com/stream?streams=!premiumIndex@arr` | All funding rates |

### External APIs (Free)

| API | URL | Fungsi |
|-----|-----|--------|
| DexScreener | `https://api.dexscreener.com/dex/v1/trades` | Whale trades (Solana) |

---

## 🔧 Troubleshooting

### Bot tidak merespond

```bash
# Check bot token
cat .env | grep TELEGRAM_BOT_TOKEN

# Check bot logs
tail -f logs/trador.log

# Restart bot
python src/main.py
```

### API Key error

```bash
# Verify API key
python -c "import ccxt; e=ccxt.binance({'apiKey':'KEY','secret':'SECRET'}); print(e.fetch_balance())"
```

### WebSocket disconnect

Scanner auto-reconnect setiap 5 detik. Kalau sering disconnect:
- Check internet stability
- Kurangi jumlah symbol yang di-monitor
- Check firewall tidak blokir port 443

### Position tidak terbuka

```bash
# Check leverage setting
# Verify margin cukup
# Check SL/TP tidak terlalu ketat
# Verify dry run vs live mode
```

### Hermes suggestions tidak diproses

```bash
# Check file permissions
ls -la shared/hermes_suggestions/pending/

# Check suggestion format
cat shared/hermes_suggestions/pending/*.json | python -m json.tool
```

---

## 📜 Lisensi

MIT License. Use at your own risk. Trading crypto futures involves substantial risk of loss.

---

## ⚠️ Disclaimer

Ini adalah software experimental. Gunakan dengan bijak.

- **Backtest dulu** sebelum live trading
- **Mulai dengan nominal kecil**
- **Pahami risk management**
- **Jangan trade dengan uang yang kamu tidak mampu kehilangan**

作者: Trador — crypto futures trading bot
