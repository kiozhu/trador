# Trador

Crypto futures trading bot — independent, Telegram-controlled, Hermes-aware.

**Trador is the BODY.** It follows its strategy exactly. Hermes is the CONTROLLER that modifies Trador's strategy files. Trador does NOT think — it executes. LLM only scores execution quality, never changes strategy.

---

## Quick Start

```bash
#1. Clone
git clone git@github.com:kiozhu/trador.git
cd trador

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your Binance API keys, Telegram token, MiniMax API key

# 4. Run
python src/main.py
```

---

## Architecture

```
Trador
├── Telegram Bot (reply keyboard) ← user controls here
├── Trading Engine (ccxt → Binance Futures)
├── Strategy Config (JSON files, hot-reload)
├── Memory System (trade history, performance)
├── LLM Scorer (execution quality only)
└── Hermes Comm (file-based JSON reports/suggestions)
```

**Hermes** = supervisor that can modify Trador's strategy files. **Trador** = executor that reads strategy and trades.

**Memory & Role Separation:**
- Hermes: fokus analisis hasil trade, belajar dari error, ubah strategy JSON. GA BISA akses memory Trador atau LLM scorer Trador.
- Trador: fokus eksekusi, enforce hard limits, LLM scorer sendiri. GA BISA ubah strategy sendiri atau interpretasi bebas dari Hermes suggestion.

---

## Folder Structure

```
trador/
├── .env                    # Environment config
├── src/
│   ├── main.py            # Entry point
│   ├── telegram/          # Telegram bot
│   ├── trading/           # Trading engine
│   ├── strategy/           # Strategy loader/watcher
│   ├── memory/             # Trade history, performance
│   ├── llm/                # LLM execution scorer
│   └── comm/               # Hermes file communication
├── strategies/             # Strategy JSON files
├── shared/                 # Hermes communication
│   ├── trador_reports/     # → Hermes reads
│   └── hermes_suggestions/ # ← Hermes writes
└── memory/                 # Trador's own memory
```

---

## Strategy Files

Strategies are JSON files in `strategies/`. Edit them directly or via Telegram bot.

Example (`strategies/momentum_ema.json`):
```json
{
  "id": "momentum_ema",
  "name": "Momentum EMA Crossover",
  "indicators": {
    "ema_fast": 20,
    "ema_slow": 50,
    "adx_threshold": 25
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
    "max_hold_minutes": 30
  }
}
```

---

## Telegram Commands

| Button | Function |
|--------|----------|
| 📊 Status | Show bot status + open positions |
| 📈 Positions | View all open positions |
| ⚙️ Strategi | Switch strategy / adjust parameters |
| 📋 History | Recent trade history |
| 🚀 Start | Enable trading |
| 🛑 Stop | Disable trading |
| 💰 Balance | Show account balance |
| ❓ Help | Show help |

---

## Hermes Communication

Trador writes reports to `shared/trador_reports/`:
- `status.json` — current state (every 30s)
- `trades.json` — trade results (after each trade)
- `metrics.json` — performance metrics (hourly)

Trador reads suggestions from `shared/hermes_suggestions/pending/`:
- Hermes writes strategy adjustment JSON here
- Trador validates, applies if valid, moves to `processed/`

---

## Tech Stack

- **Telegram Bot:** python-telegram-bot v22+ (async)
- **Exchange:** ccxt (Binance Futures)
- **Strategy:** JSON files + watchdog hot-reload
- **LLM:** MiniMax API
- **Process Manager:** systemd

---

## Development

```bash
# Install dev dependencies
pip install -r requirements.txt

# Run
python src/main.py

# Lint
ruff check src/

# Test
pytest tests/
```
