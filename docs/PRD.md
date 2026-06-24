# Product Requirements Document (PRD)

## Trade It — Multi-Agent Global Market Signal Platform

| Field | Value |
|---|---|
| **Product** | Trade It |
| **Author** | Aniket Mishra |
| **Date** | 2026-06-22 |
| **Version** | 1.0 |
| **Status** | Draft |

---

## 1. Product Vision

Transform Trade It from a monolithic signal pipeline into a **multi-agent analytical platform** where specialised agents collaborate to produce deeper, more accurate, and better-explained trading signals — while keeping the same simple Telegram and CLI experience users already know.

---

## 2. Goals and Non-Goals

### Goals

| # | Goal |
|---|---|
| G-1 | Each of the six CLAUDE.md perspectives is owned by a dedicated, specialised agent that can reason deeply about its domain. |
| G-2 | Agents run in parallel where they have no data dependency, reducing wall-clock latency. |
| G-3 | A Devil's Advocate agent challenges the majority view before the Chief Strategist makes the final call — implementing the adversarial step as a first-class agent. |
| G-4 | The system is extensible: adding a new agent (e.g., Sector Specialist) requires only a new file, not changes to existing code. |
| G-5 | Signal explanations become richer because each agent provides its own narrative, which the Chief Strategist weaves into the final output. |
| G-6 | The existing user experience is preserved — same commands, same output format, same Telegram inline buttons. |

### Non-Goals

| # | Non-Goal |
|---|---|
| NG-1 | Building a general-purpose agent framework — this is purpose-built for trading analysis. |
| NG-2 | Supporting agent-to-agent negotiation or debate loops — agents run once, Devil's Advocate challenges once, Chief Strategist decides once. |
| NG-3 | Real-time price streaming or live order execution. |
| NG-4 | User-facing agent selection or configuration — the user just types a ticker; the system decides which agents to run. |

---

## 3. User Personas

### 3.1 Aniket (Primary — Developer & Trader)

- Deakin University student, active retail trader focused on Indian NSE and global markets.
- Uses the bot daily to screen stocks and generate trade ideas.
- Wants deeper analysis per perspective — not just a score, but a narrative explanation.
- Cares about risk management and capital preservation.
- Runs the bot on a local machine; uses Telegram on mobile.

### 3.2 Peer Trader (Secondary)

- A friend or study-group member who Aniket has shared the bot with.
- Uses Telegram commands only — never touches the code.
- Wants clear, jargon-light explanations of signals.
- Needs to understand *why* a stock is rated BUY or SELL, not just the verdict.

---

## 4. Product Architecture

### 4.1 Agent Types

**Markdown Agents (LLM-driven)**
- Defined as `.md` files in an `agents/` directory.
- Each file contains the agent's role, instructions, input/output schema, and few-shot examples.
- At runtime, the orchestrator loads the markdown, injects the data context, and sends it to the configured AI provider (Groq or Gemini).
- Suited for: interpretation, narrative, reasoning, ambiguity handling.

**Python Agents (Computation-driven)**
- Defined as `.py` files in the `agents/` directory.
- Each file exports a standard function (e.g., `run(data: dict) -> AgentOutput`) that computes exact numbers.
- No LLM call needed — pure computation.
- Suited for: indicator math, position sizing, risk arithmetic, data fetching.

### 4.2 Agent Roster

```
agents/
  data_scout.py              # Fetches OHLCV, fundamentals, news
  technical_analyst.md        # Chart analysis, EMA/RSI/MACD interpretation
  fundamentalist.md           # Valuation, earnings, balance sheet
  macro_strategist.md         # Economic regime, sector context
  sentiment_analyst.md        # News tone, market mood narrative
  quant_engine.py             # Statistical computations (BB%, z-scores, vol regime)
  risk_manager.py             # Position sizing, stops, targets, risk veto
  devils_advocate.md          # Argues against the consensus
  chief_strategist.md         # Synthesises all views into final verdict
```

### 4.3 Orchestration Flow

```
Phase 1: DATA COLLECTION
  [Data Scout]
    ├── Fetches OHLCV for 4 timeframes
    ├── Fetches fundamentals
    └── Fetches news headlines + sentiment scores
    → Produces: DataBundle

Phase 2: PARALLEL ANALYSIS (all agents run concurrently)
  [Technical Analyst]     ← DataBundle.indicators     → TechOutput
  [Fundamentalist]        ← DataBundle.fundamentals   → FundOutput
  [Macro Strategist]      ← DataBundle.macro_context  → MacroOutput
  [Sentiment Analyst]     ← DataBundle.sentiment      → SentOutput
  [Quant Engine]          ← DataBundle.indicators     → QuantOutput
  [Risk Manager]          ← DataBundle.price + config → RiskOutput

Phase 3: ADVERSARIAL CHALLENGE
  [Devil's Advocate]      ← All Phase 2 outputs       → CounterArgument

Phase 4: SYNTHESIS
  [Chief Strategist]      ← All Phase 2 + Phase 3     → ConfluenceResult
```

---

## 5. Feature Specifications

### F-1: Agent Definition Format (Markdown)

Each markdown agent file follows a standard structure:

```markdown
# Agent: [Name]

## Role
[One-paragraph description of what this agent does]

## Perspective
[Which of the 6 CLAUDE.md perspectives this agent owns]

## Input
[Structured description of what data this agent receives]

## Output Schema
[Exact fields the agent must return — signal, confidence, points]

## Instructions
[Detailed instructions for how to analyse the data]

## Rules
[Hard constraints — data discipline, uncertainty acknowledgment, etc.]

## Examples
[1-2 few-shot examples showing input → output]
```

**Acceptance criteria:**
- The orchestrator can parse any `.md` file in `agents/` that follows this format.
- The output schema is enforced — if the LLM returns non-conforming output, it retries once.
- Missing required sections in the markdown cause a validation error at startup.

---

### F-2: Agent Definition Format (Python)

Each Python agent file exports:

```python
from agents.schema import AgentOutput, DataBundle

AGENT_META = {
    "name": "risk_manager",
    "perspective": "risk",
    "type": "python",
}

def run(data: DataBundle, config: dict) -> AgentOutput:
    """Compute risk assessment. Returns AgentOutput with signal, confidence, points."""
    ...
```

**Acceptance criteria:**
- Any `.py` file in `agents/` with `AGENT_META` and a `run()` function is auto-discovered.
- Python agents never call an LLM — they return computed results only.
- Python agents complete in under 1 second.

---

### F-3: Orchestrator

The orchestrator is the central coordinator that:

1. Discovers all agents in `agents/`.
2. Runs the Data Scout to collect all raw data.
3. Dispatches data to each analyst agent in parallel.
4. Collects outputs and validates them against the expected schema.
5. Runs the Devil's Advocate with all analyst outputs as context.
6. Runs the Chief Strategist with all outputs to produce the final verdict.
7. Returns a `ConfluenceResult` (same object as today — backward compatible).

**Acceptance criteria:**
- Adding a new `.md` or `.py` agent to `agents/` automatically includes it in the pipeline — no orchestrator changes needed.
- If an agent fails or times out (10s for Python, 30s for LLM), the orchestrator logs the error and continues with the remaining agents. The Chief Strategist notes the missing perspective.
- Agent execution order respects dependencies: Data Scout first, then parallel analysts, then Devil's Advocate, then Chief Strategist.

---

### F-4: Data Scout Agent

**Type:** Python

**Responsibility:** Single point of data acquisition. No other agent fetches from external sources.

**Produces a `DataBundle` containing:**

| Field | Source | Content |
|---|---|---|
| `ohlcv` | yfinance | OHLCV DataFrames for all 4 timeframes |
| `indicators` | indicators.py | Computed indicators (EMA, RSI, MACD, ATR, BB, volume ratio) per timeframe |
| `timeframe_signals` | signal_engine.py | Pre-scored TimeframeSignal per timeframe (existing scoring logic) |
| `fundamentals` | yfinance Ticker.info | P/E, ROE, D/E, earnings growth, sector, 52W range, market cap |
| `news_headlines` | yfinance Ticker.news | Raw headline list with publisher and date |
| `sentiment_scores` | sentiment.py | SentimentResult with per-headline scores |
| `current_price` | From daily OHLCV | Latest closing price |
| `ticker_meta` | resolve_ticker() | Resolved ticker, currency, market label |

**Acceptance criteria:**
- DataBundle is the single source of truth — all agents receive their data from it.
- Caching works as today — one fetch per ticker per run.
- If sentiment dependencies are missing, `sentiment_scores` is None and the Sentiment Analyst receives a note saying so.

---

### F-5: Technical Analyst Agent

**Type:** Markdown (LLM)

**Perspective:** Technical (CLAUDE.md #1)

**Input:** `DataBundle.indicators`, `DataBundle.timeframe_signals`

**Analyses:**
- EMA stack alignment across timeframes.
- RSI momentum — oversold/overbought zones, divergences.
- MACD histogram direction, crossovers, momentum acceleration/deceleration.
- Multi-timeframe confluence — do the charts agree?
- Key support/resistance levels derived from EMA20, EMA50, EMA200, Bollinger Bands.
- Volume confirmation — is the move backed by participation?

**Output:**
```json
{
  "signal": "BULLISH | BEARISH | NEUTRAL",
  "confidence": "HIGH | MEDIUM | LOW",
  "points": ["EMA stack fully aligned bullish...", "RSI at 62 — bullish zone...", ...],
  "support_levels": [4520.0, 4480.0],
  "resistance_levels": [4620.0, 4700.0],
  "key_observation": "One-sentence summary of the chart picture"
}
```

---

### F-6: Fundamentalist Agent

**Type:** Markdown (LLM)

**Perspective:** Fundamental (CLAUDE.md #2)

**Input:** `DataBundle.fundamentals`

**Analyses:**
- Valuation: P/E relative to sector and historical norms.
- Profitability: ROE quality — is it driven by leverage or genuine returns?
- Balance sheet health: D/E ratio, interest coverage.
- Growth trajectory: earnings and revenue growth trends.
- Dividend policy (if applicable).
- Explicitly states which data points are missing and how that affects confidence.

**Output:**
```json
{
  "signal": "BULLISH | BEARISH | NEUTRAL",
  "confidence": "HIGH | MEDIUM | LOW",
  "points": ["P/E 18.5x — below sector average of 24x...", ...],
  "missing_data": ["ROE", "earnings_growth"],
  "key_observation": "One-sentence valuation summary"
}
```

---

### F-7: Macro Strategist Agent

**Type:** Markdown (LLM)

**Perspective:** Macro (CLAUDE.md #3)

**Input:** `DataBundle.fundamentals.sector`, `DataBundle.fundamentals.market_cap`, `DataBundle.fundamentals.week52_high/low`, ticker market suffix

**Analyses:**
- Sector context — is this sector in favour given the current economic regime?
- 52-week positioning — is the stock near highs or lows relative to its range?
- Market cap context — large-cap stability vs small-cap volatility.
- Explicitly notes that no live macro feed is connected and lists what external data the user should verify (RBI/Fed policy, Nifty/S&P trend, DXY, VIX).

**Output:**
```json
{
  "signal": "BULLISH | BEARISH | NEUTRAL",
  "confidence": "HIGH | MEDIUM | LOW",
  "points": ["Defence sector has government tailwind...", ...],
  "missing_data": ["live_interest_rates", "vix", "dxy"],
  "verify_before_trading": ["RBI policy stance", "Nifty 50 trend", "Global risk sentiment"],
  "key_observation": "One-sentence macro context"
}
```

---

### F-8: Sentiment Analyst Agent

**Type:** Markdown (LLM)

**Perspective:** Sentiment & News (CLAUDE.md #4)

**Input:** `DataBundle.sentiment_scores`, `DataBundle.indicators.vol_ratio`, `DataBundle.fundamentals.week52_high/low`

**Analyses:**
- News narrative — what story are the headlines telling? Is it a one-off event or a trend?
- Model-scored sentiment distribution — how many positive vs negative vs neutral?
- Volume as a sentiment proxy — high volume confirms strong interest.
- 52-week positioning as a fear/greed indicator.
- Whether the sentiment is likely to persist or is reactionary (e.g., one earnings miss vs structural decline).

**Output:**
```json
{
  "signal": "BULLISH | BEARISH | NEUTRAL",
  "confidence": "HIGH | MEDIUM | LOW",
  "points": ["News mood: 7 positive / 2 negative / 3 neutral...", ...],
  "top_headlines": [{"title": "...", "impact": "positive", "publisher": "..."}],
  "key_observation": "One-sentence mood summary"
}
```

---

### F-9: Quant / Stats Engine Agent

**Type:** Python

**Perspective:** Quantitative (CLAUDE.md #5)

**Computes:**
- Bollinger Band %B interpretation (mean-reversion edge detection).
- ATR as percentage of price (volatility regime: low / moderate / high).
- Timeframe alignment score (how many of 4 timeframes agree).
- Volume z-score relative to 20-bar average.

**Output:** Same `AgentOutput` schema with signal, confidence, and computed points.

---

### F-10: Risk Manager Agent

**Type:** Python

**Perspective:** Risk Management (CLAUDE.md #6)

**Computes:**
- Entry zone: current price to EMA20 (bull) or EMA20 to current price (bear).
- Stop loss: entry midpoint +/- 1.5x ATR.
- Target 1: 2R from entry mid. Target 2: 3R from entry mid.
- Position size: `(capital x risk%) / risk_per_share`, rounded to whole shares.
- Risk/reward ratio.
- Position value as percentage of capital.
- **Risk veto check**: if position value > 25% of capital, sets `veto = True`.

**Output:**
```json
{
  "signal": "BULLISH | BEARISH | NEUTRAL",
  "confidence": "HIGH",
  "points": ["R:R = 2.1:1 — meets 2:1 minimum...", ...],
  "entry": 4550.0,
  "stop_loss": 4480.0,
  "target_1": 4690.0,
  "target_2": 4760.0,
  "position_size": 22,
  "position_value": 100100.0,
  "risk_amount": 1540.0,
  "veto": false,
  "veto_reason": null
}
```

---

### F-11: Devil's Advocate Agent

**Type:** Markdown (LLM)

**Input:** All Phase 2 agent outputs, including the emerging directional consensus.

**Role:** Forced contrarian. This agent MUST argue against the majority view, even if the evidence strongly supports it.

**Analyses:**
- What is the strongest case against the current consensus?
- What risks or data gaps are the other agents underweighting?
- What historical pattern or scenario would invalidate the current setup?
- What is the "I'm wrong if..." condition?

**Output:**
```json
{
  "counter_direction": "BULLISH | BEARISH",
  "argument": "The strongest case against the current view is...",
  "risks_underweighted": ["Earnings announcement in 3 days...", ...],
  "invalidation_condition": "If price closes below EMA50 with volume...",
  "confidence_in_counter": "LOW | MEDIUM | HIGH"
}
```

---

### F-12: Chief Strategist Agent

**Type:** Markdown (LLM)

**Input:** All Phase 2 outputs + Devil's Advocate output.

**Role:** The final decision-maker. Weighs all perspectives, respects the risk veto, and produces the `ConfluenceResult`.

**Responsibilities:**
- Count and weigh perspective signals (bullish/bearish/neutral with confidence).
- Write the bull case and bear case summaries.
- Declare which case wins and why.
- Produce the final verdict: BUY / SELL / HOLD / NO TRADE.
- If Risk Manager set `veto = True`, verdict MUST be NO TRADE regardless.
- Set overall confidence based on perspective agreement.
- Produce the top 3 mind-changers.

**Output:** A complete `ConfluenceResult`-compatible structure.

---

### F-13: Scan Mode (Watchlist)

During `/scan`, to stay within AI rate limits:

- Data Scout runs for each ticker.
- Python agents (Quant, Risk Manager) run normally.
- LLM agents are **skipped** — the system uses the existing Python-based scoring from `signal_engine.py` and `confluence.py` as a fast path.
- News sentiment is also skipped (current behaviour).

This produces a scan that is fast (Python-only) while single-ticker `/analyse` gets the full multi-agent deep analysis.

---

## 6. Output Format

The final output format remains identical to the current Telegram HTML format:

1. Six-perspective summary table (signal + confidence per perspective).
2. Latest news (top scored headlines).
3. Bull case vs bear case — which wins.
4. Recommendation: BUY / SELL / HOLD / NO TRADE.
5. Trade levels: entry, stop, targets, position size.
6. Overall confidence + 3 mind-changers.
7. Caveat.

Each inline button (Explain, Refresh, All Timeframes, Set Alert) continues to work.

---

## 7. Performance Requirements

| Metric | Target |
|---|---|
| Single-ticker analysis (full multi-agent) | < 30 seconds |
| Single-ticker analysis (Python-only, scan mode) | < 10 seconds |
| Full 20-ticker watchlist scan (Python-only) | < 3 minutes |
| Agent timeout (Python) | 10 seconds |
| Agent timeout (LLM) | 30 seconds |
| Memory usage (idle) | < 200 MB |
| Memory usage (with FinBERT loaded) | < 800 MB |

---

## 8. Error Handling

| Scenario | Behaviour |
|---|---|
| LLM agent returns unparseable output | Retry once with a stricter prompt. If still fails, mark perspective as NEUTRAL/LOW with note "Agent failed to produce structured output." |
| LLM agent times out (>30s) | Mark perspective as NEUTRAL/LOW with note "Agent timed out." |
| Python agent throws exception | Log error, mark perspective as NEUTRAL/LOW with note. |
| Data Scout cannot fetch any data | Abort analysis, return "Symbol not found" error (current behaviour). |
| Data Scout fetches partial data (e.g., no fundamentals) | Continue with available data. Agents that need missing data report it in their output. |
| AI rate limit hit | Fall back to Python-only analysis; note "AI analysis unavailable — showing indicator-based signal only." |

---

## 9. Configuration

### Per-Agent AI Provider Override

```python
# In config or agent metadata
AGENT_AI_CONFIG = {
    "technical_analyst":  {"provider": "groq",   "model": "llama-3.3-70b-versatile"},
    "fundamentalist":     {"provider": "gemini", "model": "gemini-2.0-flash"},
    "macro_strategist":   {"provider": "groq",   "model": "llama-3.3-70b-versatile"},
    "sentiment_analyst":  {"provider": "groq",   "model": "llama-3.3-70b-versatile"},
    "devils_advocate":    {"provider": "groq",   "model": "llama-3.3-70b-versatile"},
    "chief_strategist":   {"provider": "groq",   "model": "llama-3.3-70b-versatile"},
}
```

This allows mixing providers — e.g., use Gemini for fundamentals (longer context for balance sheet data) and Groq for everything else (faster).

---

## 10. Future Enhancements

| # | Enhancement | Description |
|---|---|---|
| FE-1 | Sector Specialist Agent | Compares the stock against sector peers and sector ETF trends. |
| FE-2 | Event Watcher Agent | Flags upcoming earnings, ex-dividend dates, central bank meetings, IPO lock-up expiries. |
| FE-3 | Trade Journal Agent | Logs past signals and actual outcomes; tracks hit rate over time. |
| FE-4 | Agent Debate Mode | Allow Devil's Advocate and the majority view to go back-and-forth for 2-3 rounds before final verdict. |
| FE-5 | User-Selected Depth | `/analyse HAL deep` runs all LLM agents; `/analyse HAL quick` uses Python-only. |
| FE-6 | Custom Agent Upload | Users can add their own markdown agent files via Telegram. |
| FE-7 | Live Macro Feed | Connect to a macro data source (e.g., FRED API) so the Macro Strategist has real data. |
| FE-8 | Multi-Ticker Correlation Agent | Analyses portfolio-level correlations and concentration risk. |

---

## 11. Release Plan

| Phase | Scope | Timeline |
|---|---|---|
| **Phase 1: Foundation** | Agent schema, orchestrator, Data Scout, Risk Manager (Python) | Week 1–2 |
| **Phase 2: Core Analysts** | Technical Analyst, Fundamentalist, Quant Engine (markdown + Python) | Week 3–4 |
| **Phase 3: Full Framework** | Macro Strategist, Sentiment Analyst, Devil's Advocate, Chief Strategist | Week 5–6 |
| **Phase 4: Integration** | Wire into Telegram bot, backward-compat testing, scan mode fallback | Week 7 |
| **Phase 5: Polish** | Performance tuning, error handling, documentation, agent prompt tuning | Week 8 |
