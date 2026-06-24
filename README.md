# Trade It — Multi-Agent Global Market Signal Platform

A multi-agent trading signal analysis platform that generates structured trade
recommendations for any stock, crypto, or index worldwide using a six-perspective
analytical framework (Technical, Fundamental, Macro, Sentiment, Quantitative, Risk).

Trade It is a personal research and decision-support tool. It does not predict
markets, guarantee returns, or constitute financial advice. **A human must review
and execute every trade.**

---

# Part 1 — User Guide

This part covers everything you need to run the bot and use it day to day. No
coding knowledge required beyond following the setup steps once.

## What it does

- Analyses any Yahoo Finance ticker: Indian NSE/BSE, US stocks, crypto, ASX, LSE, TSE, and more
- Runs a **four-timeframe** signal (15 min, 1 hour, daily, weekly) with weighted confluence voting
- Evaluates **six analytical perspectives**: Charts, Financials, Big Picture, News, Stats, Risk
- Provides entry zone, stop loss (1.5× ATR), and two targets (2R and 3R)
- Explains signals in plain English via Groq (llama-3.3-70b) or Gemini 2.0 Flash
- Runs fully in Telegram with inline buttons, a persistent keyboard, and a `/scan` watchlist sweep

## Quick start

```bash
# 1. Clone and enter the project
cd Trade_bot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up environment variables
cp .env.example .env
# Edit .env and fill in your keys (see below)

# 4. Run the bot
python telegram_bot.py

# Optional: run the CLI analyser (no Telegram needed)
python main.py HAL
python main.py AAPL
python main.py BTC
```

## Environment variables (`.env`)

| Variable | Required | Where to get it |
|---|---|---|
| `BOT_TOKEN` | Yes | [@BotFather](https://t.me/BotFather) on Telegram |
| `GROQ_API_KEY` | Recommended | [console.groq.com](https://console.groq.com) — free tier available |
| `GEMINI_API_KEY` | Fallback | [ai.google.dev](https://ai.google.dev) — free tier available |

If neither AI key is set, signal generation still works but the Explain/Chat
features are disabled.

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

You can also just type a ticker directly — e.g. `HAL`, `AAPL`, `BTC` — to get a
signal instantly.

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

## How signals work

### Four timeframes, weighted voting

| Timeframe | Weight | Role |
|---|---|---|
| Weekly | 3 | Macro trend anchor |
| Daily | 2 | Primary signal timeframe |
| 1 hour | 1 | Entry timing |
| 15 min | 1 | Intraday precision |

A final direction (BULLISH / BEARISH / NEUTRAL) is determined by the weighted
sum. Confluence level is STRONG → MODERATE → WEAK → CONFLICTED based on how many
timeframes agree.

### Six analytical perspectives

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

If the calculated position value exceeds 25% of capital, the final verdict is
forced to **NO TRADE** regardless of how bullish the other five perspectives are.

## News sentiment

Headlines are scored by a three-tier fallback chain:

1. **FinBERT** (`ProsusAI/finbert`) — finance-tuned BERT, most accurate; loaded lazily on first use (~30 s startup)
2. **VADER** (`vaderSentiment`) — fast, decent on short news text
3. **Keyword** — built-in bull/bear word sets; always available, no dependencies

Each headline gets a `[-1, +1]` score. The aggregated score uses
confidence-weighted averaging. A ±0.15 dead-band avoids flip-flopping on mixed
news. News sentiment is skipped during full watchlist scans to keep per-ticker
latency low.

Install optional sentiment backends for higher-quality news analysis:

```bash
pip install vaderSentiment
pip install transformers torch   # ~2 GB download; FinBERT loads on first use
```

## Performance

| Metric | Target |
|---|---|
| Single-ticker analysis (full multi-agent) | < 30 seconds |
| Single-ticker analysis (Python-only, scan mode) | < 10 seconds |
| Full 20-ticker watchlist scan | < 3 minutes |

## Limitations and notes

- **Yahoo Finance data**: yfinance is unofficial and can return 403 errors under heavy load or from cloud/VPN IPs. Run the bot on a local machine or residential IP for best results.
- **Indian stocks**: fundamental data coverage (P/E, ROE, D/E) is limited for .NS tickers on Yahoo Finance. Agents will note when data is unavailable.
- **Watchlist persistence**: `/add` and `/remove` changes are in-memory only and reset when the bot restarts. Edit `WATCHLIST` in `src/config.py` to make changes permanent.
- **FinBERT startup**: the first call to the News sentiment backend downloads and loads ~400 MB of model weights. Subsequent calls are fast (model stays in memory).
- **Multi-agent trade-off**: LLM agents add latency (~30 seconds for full analysis) but provide deeper reasoning. The `/scan` command uses Python-only agents (no LLM calls) for faster watchlist sweeps.
- **Not financial advice**: this tool is for analytical structuring only. All trade decisions must be reviewed and executed by a human.

---

# Part 2 — Developer Guide

This part covers the architecture, code layout, and configuration for anyone
extending or maintaining the codebase.

## Multi-agent architecture

```
Phase 1: Data Scout (fetches OHLCV, fundamentals, news)
    │
    ├── [Technical Analyst]     ─┐
    ├── [Fundamentalist]          │ Phase 2: Parallel Analysis
    ├── [Macro Strategist]        │ (6 LLM agents + 2 Python agents)
    ├── [Sentiment Analyst]       │
    ├── [Sector Specialist]       │
    ├── [Event Watcher]           │
    ├── [Quant Engine]           ─┤
    └── [Risk Manager]          ─┘
    │
    ├── [Devil's Advocate]      ─── Phase 3: Adversarial Challenge
    │
    └── [Chief Strategist]      ─── Phase 4: Synthesis & Final Verdict
        │
        └── [Trade Journal]     ─── Phase 5: Logging (fire-and-forget)
```

- `orchestrator.py` runs the 5-phase pipeline and falls back to the legacy
  Python-only pipeline (`src/confluence.py`) at any phase where an LLM agent
  fails, times out, or returns malformed output.
- `agents/__init__.py` auto-discovers agents at startup by scanning `agents/`
  for `.md` files (`# Agent:` heading) and `.py` files exposing `AGENT_META` +
  `run()`. No manual registration needed — drop in a new file and it's picked up.

### Agent roster

#### Core analyst agents

| Agent | Type | Perspective | Role |
|---|---|---|---|
| `data_scout` | Python | Data | Fetches OHLCV, fundamentals, news for all other agents |
| `technical_analyst` | LLM | Technical | Chart patterns, EMA/RSI/MACD interpretation |
| `fundamentalist` | LLM | Fundamental | P/E, ROE, D/E, earnings growth, valuation |
| `macro_strategist` | LLM | Macro | Sector context, 52W positioning, regime analysis |
| `sentiment_analyst` | LLM | Sentiment | News narrative, mood, headline distribution |
| `quant_engine` | Python | Quantitative | BB%B, ATR regime, TF alignment |
| `risk_manager` | Python | Risk | Stops, targets, position sizing, risk veto |

#### Optional specialty agents

| Agent | Type | Role |
|---|---|---|
| `sector_specialist` | LLM | Compares stock vs sector peers |
| `event_watcher` | LLM | Flags earnings, dividends, macro events |
| `devils_advocate` | LLM | Argues against the consensus before final verdict |
| `chief_strategist` | LLM | Synthesizes all views into final BUY/SELL/HOLD/NO TRADE |
| `trade_journal` | Python | Logs signals to `trade_journal.json` |

### Adding a new LLM agent

1. Create `agents/your_agent.md` with a `# Agent: Your Agent` heading, `##
   Perspective`, `## Phase`, `## Output Schema` (JSON), and `## Instructions`
   sections (see `agents/technical_analyst.md` for the template).
2. If the agent needs a specific data slice, add a case to
   `_serialise_data_for_agent()` in `agents/runner.py`.
3. Add an entry to `AGENT_AI_CONFIG` in `src/config.py` to choose its provider.
4. The orchestrator picks it up automatically via `discover_agents()` — no
   other wiring required.

### Adding a new Python agent

Create `agents/your_agent.py` exposing:

```python
AGENT_META = {"name": "your_agent", "perspective": "...", "phase": 2}

def run(data: DataBundle) -> AgentOutput:
    ...
```

## Project structure

```
Trade_bot/
├── agents/                # Multi-agent modules
│   ├── __init__.py        # Agent discovery
│   ├── schema.py           # Data models (DataBundle, AgentOutput, CounterArgument)
│   ├── runner.py            # LLM execution engine
│   ├── data_scout.py        # Phase 1 — data collection
│   ├── technical_analyst.md
│   ├── fundamentalist.md
│   ├── macro_strategist.md
│   ├── sentiment_analyst.md
│   ├── quant_engine.py
│   ├── risk_manager.py
│   ├── sector_specialist.md (optional)
│   ├── event_watcher.md (optional)
│   ├── devils_advocate.md
│   ├── chief_strategist.md
│   └── trade_journal.py
├── src/                    # Core pipeline (importable package)
│   ├── __init__.py
│   ├── config.py            # RISK, INDICATORS, TIMEFRAMES, WATCHLIST, AGENT_AI_CONFIG
│   ├── data_fetcher.py      # yfinance OHLCV + fundamentals
│   ├── indicators.py        # Technical indicator calculations
│   ├── signal_engine.py     # Per-timeframe scoring
│   ├── confluence.py        # Legacy/fallback pipeline + six-perspective assessment
│   ├── sentiment.py         # News sentiment pipeline (FinBERT/VADER/keyword)
│   ├── chat_engine.py       # AI chat via Groq / Gemini
│   └── report.py            # CLI report formatter
├── orchestrator.py          # 5-phase multi-agent pipeline coordinator
├── ticker_utils.py          # Shared ticker resolution utilities
├── telegram_bot.py          # Telegram bot — uses orchestrator with fallback
├── main.py                  # CLI entry point
├── .env.example              # Environment template
├── docs/                     # Documentation (BRD, PRD, TRD)
├── requirements.txt
└── README.md
```

## Configuration (`src/config.py`)

### Risk parameters

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

Capital and risk % can also be changed at runtime via `/setcapital` and
`/setrisk` without restarting the bot.

### Agent configuration

```python
AGENT_AI_CONFIG = {
    "technical_analyst":  {"provider": "groq"},
    "fundamentalist":     {"provider": "groq"},
    "macro_strategist":   {"provider": "groq"},
    "sentiment_analyst":  {"provider": "groq"},
    "devils_advocate":    {"provider": "groq"},
    "chief_strategist":   {"provider": "groq"},
}

AGENT_TIMEOUTS = {
    "python":   10,
    "markdown": 30,
}
```

The default watchlist covers 20 NSE tickers across Defence, Energy, Infra,
Pharma, IT, Banks, Auto, and Tech. Use `/add` and `/remove` in Telegram to
change it during a session, or edit `WATCHLIST` in `src/config.py` for a
permanent change.

## Dependencies

```
python-telegram-bot
yfinance
pandas
numpy
python-dotenv
requests
groq                    # via chat_engine.py HTTP calls — no SDK required
google-generativeai     # likewise — chat_engine.py calls the REST API directly
vaderSentiment          # optional — VADER sentiment backend
transformers            # optional — FinBERT sentiment backend
torch                   # optional — required by transformers/FinBERT
```

See `requirements.txt` for pinned versions.

## Testing changes locally

```bash
# Single-ticker, full multi-agent pipeline
python main.py HAL.NS

# Multiple tickers — summary table + detail for actionable signals
python main.py HAL.NS TCS.NS LT.NS

# Telegram bot (requires BOT_TOKEN in .env)
python telegram_bot.py
```

If `orchestrator.py` raises `ImportError` or `RuntimeError` (e.g. an agent
module fails to import), both `main.py` and `telegram_bot.py` fall back
automatically to the legacy pipeline in `src/confluence.py` — useful for
isolating whether a bug is in the agent layer or the underlying data/indicator
logic.

## Hard rules enforced in code

These map directly to `CLAUDE.md` and are enforced even if an LLM agent
ignores them:

- **Risk veto overrides everything** — `orchestrator.py::_build_confluence_result`
  forces `final_verdict = "NO TRADE"` if `risk_manager` sets `veto=True`, regardless
  of what the Chief Strategist concluded.
- **No invented data** — agents are instructed to mark confidence LOW and say
  so explicitly when data is missing, never to fabricate figures.
- **No order execution** — the codebase only ever produces a recommendation;
  there is no broker/exchange integration. A human reviews and executes every
  trade.

---

## Disclaimer

Trade It is a personal research tool. It does not predict markets, guarantee
returns, or constitute financial advice. Always do your own research. A human
must review and execute every trade.
