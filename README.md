# Trade It — Global Market Signal Bot

A Telegram bot that generates multi-timeframe trading signals for any stock, crypto, or index worldwide using a six-perspective analytical framework.

---

## What it does

- Analyses any Yahoo Finance ticker: Indian NSE/BSE, US stocks, crypto, ASX, LSE, TSE, and more
- Runs a **four-timeframe** signal (15 min, 1 hour, daily, weekly) with weighted confluence voting
- Evaluates **six analytical perspectives** per the CLAUDE.md framework: Charts, Financials, Big Picture, News, Stats, Risk
- Provides entry zone, stop loss (1.5× ATR), and two targets (2R and 3R)
- Explains signals in plain English via Groq (llama-3.3-70b) or Gemini 2.0 Flash
- Runs fully in Telegram with inline buttons, a persistent keyboard, and a `/scan` watchlist sweep

---

## Quick start

```bash
# 1. Clone and enter the project
cd Trade_bot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up environment variables
cp .env.example .env
# Edit .env and fill in your keys (see Keys section below)

# 4. Run the bot
python telegram_bot.py

# Optional: run the CLI analyser (no Telegram needed)
python main.py HAL
python main.py AAPL
python main.py BTC
```

---

## Environment variables (`.env`)

| Variable | Required | Where to get it |
|---|---|---|
| `BOT_TOKEN` | Yes | [@BotFather](https://t.me/BotFather) on Telegram |
| `GROQ_API_KEY` | Recommended | [console.groq.com](https://console.groq.com) — free tier available |
| `GEMINI_API_KEY` | Fallback | [ai.google.dev](https://ai.google.dev) — free tier available |

If neither AI key is set, signal generation still works but the Explain button is disabled.

---

## Telegram commands

| Command | Description |
|---|---|
| `/analyse TICKER` | Full signal for any stock or crypto |
| `/scan` | Scan the whole watchlist for BUY/SELL signals |
| `/explain` | Plain-English explanation of the last signal (AI) |
| `/watchlist` | View the current scan watchlist |
| `/add TICKER` | Add a ticker to the watchlist (in-memory, resets on restart) |
| `/remove TICKER` | Remove a ticker from the watchlist |
| `/setcapital AMOUNT` | Set your trading capital for position sizing |
| `/setrisk PCT` | Set max risk per trade as a percentage (e.g. `1.5`) |
| `/chat` | Enter AI chat mode for free-form trading questions |
| `/done` | Exit chat mode |
| `/cancel` | Cancel any running fetch |
| `/help` | Full command reference |

You can also just type a ticker directly — e.g. `HAL`, `AAPL`, `BTC` — to get a signal instantly.

---

## Supported markets

| Market | Format | Examples |
|---|---|---|
| Indian NSE | `TICKER` or `TICKER.NS` | `HAL`, `TCS.NS`, `HDFCBANK` |
| Indian BSE | `TICKER.BO` | `RELIANCE.BO` |
| US stocks | `TICKER` (no suffix) | `AAPL`, `NVDA`, `TSLA` |
| Crypto | `SYMBOL` or `SYMBOL-USD` | `BTC`, `ETH`, `SOL-USD` |
| Australian ASX | `TICKER.AX` | `CBA.AX`, `BHP.AX` |
| UK LSE | `TICKER.L` | `HSBA.L`, `BP.L` |
| Japanese TSE | `TICKER.T` | `7203.T` |
| Hong Kong | `TICKER.HK` | `0700.HK` |

**Known aliases** (resolved automatically):

| You type | Resolves to | Why |
|---|---|---|
| `HDFC` | `HDFCBANK.NS` | HDFC Ltd merged into HDFC Bank in 2023; HDFC.NS is delisted |
| `HDFCBANK` | `HDFCBANK.NS` | Common shorthand |
| `BAJAJFINANCE` | `BAJFINANCE.NS` | Yahoo Finance ticker differs from display name |
| `M&M` or `MAHINDRA` | `M&M.NS` | Ampersand variant |

---

## How signals work

### Four timeframes, weighted voting

| Timeframe | Weight | Role |
|---|---|---|
| Weekly | 3 | Macro trend anchor |
| Daily | 2 | Primary signal timeframe |
| 1 hour | 1 | Entry timing |
| 15 min | 1 | Intraday precision |

A final direction (BULLISH / BEARISH / NEUTRAL) is determined by the weighted sum. Confluence level is STRONG → MODERATE → WEAK → CONFLICTED based on how many timeframes agree.

### Per-timeframe scoring (5 rules, ±1 or ±2 each)

1. **EMA stack** — Price vs EMA20 vs EMA50 vs EMA200 (full alignment = ±2, partial = ±1)
2. **RSI** — Oversold (<30) or overbought (>70) zones score ±1; neutral zones score 0
3. **MACD histogram** — Direction and crossovers score ±1 each
4. **Bollinger Band %** — Near lower band (<0.2) or upper band (>0.8) scores ±1
5. **Volume ratio** — If volume is >1.5× the 20-bar average, it amplifies the dominant side (+1)

Confidence: HIGH if score ratio ≥ 0.75 and ≥ 4 total signal points; MEDIUM if ≥ 0.60; LOW otherwise.

### Six analytical perspectives (CLAUDE.md framework)

| Perspective | Data used |
|---|---|
| **Charts** | EMA stack, RSI, MACD, multi-timeframe confluence |
| **Financials** | P/E, ROE, D/E ratio, earnings/revenue growth, P/B (yfinance) |
| **Big Picture** | Sector, 52-week range, market cap, macroeconomic context |
| **News** | FinBERT → VADER → keyword fallback; top headlines scored and aggregated |
| **Stats** | Bollinger Band %, volume, risk-reward ratio, mean-reversion signals |
| **Risk** | ATR-based stop, position size vs capital, risk veto if >25% capital |

### Trade levels

- **Entry zone**: current price to EMA20 (bull) or EMA20 to current price (bear)
- **Stop loss**: entry midpoint ± 1.5× ATR
- **Target 1**: 2R from entry mid (take partial profit)
- **Target 2**: 3R from entry mid (let the rest run)
- **Position size**: `(capital × risk%) ÷ (entry - stop)`, rounded to whole shares

### Risk veto

If the calculated position value exceeds 25% of capital, the final verdict is forced to **NO TRADE** regardless of how bullish the other five perspectives are.

---

## News sentiment

Headlines are scored by a three-tier fallback chain:

1. **FinBERT** (`ProsusAI/finbert`) — finance-tuned BERT, most accurate; loaded lazily on first use (~30 s startup)
2. **VADER** (`vaderSentiment`) — fast, decent on short news text
3. **Keyword** — built-in bull/bear word sets; always available, no dependencies

Each headline gets a `[-1, +1]` score. The aggregated score uses confidence-weighted averaging. A ±0.15 dead-band avoids flip-flopping on mixed news.

News sentiment is skipped during full watchlist scans to keep per-ticker latency low.

---

## Project structure

```
Trade_bot/
├── telegram_bot.py   # Telegram bot — command handlers, message router, inline buttons
├── main.py           # CLI entry point for single-ticker analysis (no Telegram needed)
├── confluence.py     # Six-perspective evaluator + multi-timeframe confluence verdict
├── signal_engine.py  # Per-timeframe scoring → TimeframeSignal
├── indicators.py     # Technical indicator calculations (EMA, RSI, MACD, ATR, BB, volume)
├── data_fetcher.py   # yfinance OHLCV + fundamentals downloader with in-memory cache
├── sentiment.py      # News sentiment pipeline (FinBERT / VADER / keyword)
├── chat_engine.py    # AI chat via Groq (primary) / Gemini (fallback)
├── report.py         # CLI terminal report formatter (ANSI colours)
├── config.py         # RISK parameters, INDICATORS config, TIMEFRAMES, WATCHLIST
├── .env.example      # Template for environment variables
└── requirements.txt  # Python dependencies
```

---

## Configuration (`config.py`)

Key settings you can change:

```python
RISK = {
    "capital":            100_000,   # trading capital in Rs. (or your currency)
    "risk_pct_per_trade": 0.01,      # 1% risk per trade
    "atr_sl_multiplier":  1.5,       # stop loss = 1.5× ATR
    "rr_target_1":        2.0,       # Target 1 = 2R
    "rr_target_2":        3.0,       # Target 2 = 3R
    "max_position_pct":   0.25,      # veto any trade requiring > 25% of capital
}
```

Capital and risk % can also be changed at runtime via `/setcapital` and `/setrisk` without restarting the bot.

The default watchlist covers 20 NSE tickers across Defence, Energy, Infra, Pharma, IT, Banks, Auto, and Tech. Use `/add` and `/remove` in Telegram to change it during a session.

---

## Dependencies

```
python-telegram-bot
yfinance
pandas
numpy
python-dotenv
groq
google-generativeai
vaderSentiment          # optional — VADER sentiment backend
transformers            # optional — FinBERT sentiment backend
torch                   # optional — required by transformers/FinBERT
```

Install optional sentiment backends for higher-quality news analysis:

```bash
pip install vaderSentiment
pip install transformers torch   # ~2 GB download; FinBERT loads on first use
```

---

## Limitations and notes

- **Yahoo Finance data**: yfinance is unofficial and can return 403 errors under heavy load or from cloud/VPN IPs. Run the bot on a local machine or residential IP for best results.
- **Indian stocks**: fundamental data coverage (P/E, ROE, D/E) is limited for .NS tickers on Yahoo Finance. The Financials perspective will note when data is unavailable.
- **Watchlist persistence**: `/add` and `/remove` changes are in-memory only and reset when the bot restarts. Edit `WATCHLIST` in `config.py` to make changes permanent.
- **FinBERT startup**: the first call to the News sentiment backend downloads and loads ~400 MB of model weights. Subsequent calls are fast (model stays in memory).
- **Not financial advice**: this tool is for analytical structuring only. All trade decisions must be reviewed and executed by a human.

---

## Disclaimer

Trade It is a personal research tool. It does not predict markets, guarantee returns, or constitute financial advice. Always do your own research. A human must review and execute every trade.
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    