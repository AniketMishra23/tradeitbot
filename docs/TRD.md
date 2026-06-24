# Technical Requirements Document (TRD)

## Trade It — Multi-Agent Architecture

| Field | Value |
|---|---|
| **Project** | Trade It — Multi-Agent Architecture |
| **Author** | Aniket Mishra |
| **Date** | 2026-06-22 |
| **Version** | 1.0 |
| **Status** | Draft |

---

## 1. System Overview

### 1.1 Current Architecture

```
telegram_bot.py / main.py
        │
        ▼
   run_signal()                          # Monolithic pipeline
        │
        ├── fetch_all_timeframes()       # data_fetcher.py
        ├── compute_all() + latest_values()  # indicators.py
        ├── generate_signal()            # signal_engine.py  (per timeframe)
        ├── fetch_fundamentals()         # data_fetcher.py
        ├── fetch_news_sentiment()       # sentiment.py
        └── compute_confluence()         # confluence.py  (6 perspectives + adversarial)
              │
              └── ConfluenceResult
```

### 1.2 Target Architecture

```
telegram_bot.py / main.py
        │
        ▼
   orchestrator.py
        │
        ├── Phase 1: data_scout.py
        │       ├── data_fetcher.fetch_all_timeframes()
        │       ├── indicators.compute_all() + latest_values()
        │       ├── signal_engine.generate_signal()
        │       ├── data_fetcher.fetch_fundamentals()
        │       └── sentiment.fetch_news_sentiment()
        │       → DataBundle
        │
        ├── Phase 2: parallel execution
        │       ├── technical_analyst.md   → AgentOutput
        │       ├── fundamentalist.md      → AgentOutput
        │       ├── macro_strategist.md    → AgentOutput
        │       ├── sentiment_analyst.md   → AgentOutput
        │       ├── quant_engine.py        → AgentOutput
        │       └── risk_manager.py        → AgentOutput
        │
        ├── Phase 3: devils_advocate.md    → CounterArgument
        │
        └── Phase 4: chief_strategist.md   → ConfluenceResult
```

---

## 2. Directory Structure

```
Trade_bot/
├── agents/                          # NEW — all agent definitions
│   ├── __init__.py                  # Agent discovery + registry
│   ├── schema.py                    # DataBundle, AgentOutput, CounterArgument dataclasses
│   ├── runner.py                    # LLM agent runner (loads .md, calls AI, parses output)
│   │
│   ├── data_scout.py                # Phase 1: data collection
│   ├── technical_analyst.md         # Phase 2: LLM agent
│   ├── fundamentalist.md            # Phase 2: LLM agent
│   ├── macro_strategist.md          # Phase 2: LLM agent
│   ├── sentiment_analyst.md         # Phase 2: LLM agent
│   ├── quant_engine.py              # Phase 2: Python agent
│   ├── risk_manager.py              # Phase 2: Python agent
│   ├── devils_advocate.md           # Phase 3: LLM agent
│   └── chief_strategist.md          # Phase 4: LLM agent
│
├── orchestrator.py                  # NEW — agent orchestration + parallel execution
│
├── config.py                        # Existing — add AGENT_AI_CONFIG
├── data_fetcher.py                  # Existing — no changes
├── indicators.py                    # Existing — no changes
├── signal_engine.py                 # Existing — no changes
├── sentiment.py                     # Existing — no changes
├── confluence.py                    # Existing — kept for scan-mode fallback
├── chat_engine.py                   # Existing — add multi-provider support
├── report.py                        # Existing — no changes
├── telegram_bot.py                  # Existing — swap run_signal() to use orchestrator
├── main.py                          # Existing — swap to use orchestrator
├── requirements.txt                 # Existing — no new dependencies
│
├── docs/
│   ├── BRD.md
│   ├── PRD.md
│   └── TRD.md
│
├── CLAUDE.md                        # Existing — governing analytical framework
├── README.md                        # Existing — update for multi-agent architecture
└── .env                             # Existing — API keys
```

---

## 3. Data Models

### 3.1 DataBundle

Produced by the Data Scout. Passed to all Phase 2 agents.

```python
# agents/schema.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

@dataclass
class TickerMeta:
    raw_input:   str             # What the user typed ("HAL", "AAPL", "BTC")
    resolved:    str             # Yahoo Finance ticker ("HAL.NS", "AAPL", "BTC-USD")
    currency:    str             # Display currency symbol ("Rs.", "$", "A$")
    market:      str             # Market label ("NSE", "US", "Crypto")

@dataclass
class TimeframeData:
    name:       str              # "15min" | "1hour" | "daily" | "weekly"
    ohlcv:      pd.DataFrame     # Raw OHLCV
    indicators: pd.DataFrame     # OHLCV + computed indicators
    latest:     dict             # indicators.latest_values() — flat dict of most recent bar
    signal:     object           # signal_engine.TimeframeSignal

@dataclass
class DataBundle:
    ticker_meta:     TickerMeta
    timeframes:      dict[str, TimeframeData | None]  # keyed by timeframe name
    fundamentals:    dict                              # from data_fetcher.fetch_fundamentals()
    sentiment:       object | None                     # sentiment.SentimentResult or None
    current_price:   float | None
    fetch_errors:    list[str] = field(default_factory=list)  # non-fatal issues during data collection
```

### 3.2 AgentOutput

Standard output for all analyst agents (Phase 2).

```python
@dataclass
class AgentOutput:
    agent_name:     str          # "technical_analyst", "fundamentalist", etc.
    perspective:    str          # "technical", "fundamental", "macro", "sentiment", "quantitative", "risk"
    signal:         str          # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence:     str          # "HIGH" | "MEDIUM" | "LOW"
    points:         list[str]    # Key observations (shown in final report)
    key_observation: str = ""    # One-sentence summary
    missing_data:   list[str] = field(default_factory=list)  # Data the agent needed but didn't have
    extra:          dict = field(default_factory=dict)  # Agent-specific additional fields

    # Risk Manager specific (populated only by risk_manager.py)
    entry:          float | None = None
    stop_loss:      float | None = None
    target_1:       float | None = None
    target_2:       float | None = None
    position_size:  int | None   = None
    position_value: float | None = None
    risk_amount:    float | None = None
    risk_reward:    float | None = None
    veto:           bool = False
    veto_reason:    str | None = None
```

### 3.3 CounterArgument

Output from the Devil's Advocate agent (Phase 3).

```python
@dataclass
class CounterArgument:
    counter_direction:     str          # Opposite of the majority
    argument:              str          # The strongest case against
    risks_underweighted:   list[str]    # What other agents are missing
    invalidation_condition: str         # "I'm wrong if..."
    confidence_in_counter: str          # "HIGH" | "MEDIUM" | "LOW"
```

### 3.4 ConfluenceResult (Existing — Preserved)

The existing `ConfluenceResult` in `confluence.py` remains the final output object. The Chief Strategist agent produces data that maps directly onto this dataclass. No changes to its fields.

---

## 4. Agent Discovery and Registration

### 4.1 Auto-Discovery

```python
# agents/__init__.py

import os
import importlib
from pathlib import Path

AGENT_DIR = Path(__file__).parent

def discover_agents() -> dict:
    """
    Scan the agents/ directory and return a registry of all agents.

    Returns {agent_name: AgentMeta} where AgentMeta contains:
      - name: str
      - type: "markdown" | "python"
      - perspective: str (one of the 6 CLAUDE.md perspectives, or "adversarial", "synthesis")
      - phase: int (1=data, 2=analysis, 3=adversarial, 4=synthesis)
      - path: Path to the agent file
      - run_fn: callable (for Python agents)
    """
    registry = {}

    for f in AGENT_DIR.iterdir():
        if f.suffix == ".md" and f.stem not in ("README",):
            meta = _parse_markdown_meta(f)
            if meta:
                registry[meta["name"]] = meta

        elif f.suffix == ".py" and f.stem not in ("__init__", "schema", "runner"):
            mod = importlib.import_module(f"agents.{f.stem}")
            if hasattr(mod, "AGENT_META") and hasattr(mod, "run"):
                meta = mod.AGENT_META.copy()
                meta["type"] = "python"
                meta["path"] = f
                meta["run_fn"] = mod.run
                registry[meta["name"]] = meta

    return registry
```

### 4.2 Markdown Metadata Extraction

The first section of each markdown agent file is parsed for metadata:

```markdown
# Agent: Technical Analyst

## Role
...

## Perspective
technical

## Phase
2
```

The parser extracts `name`, `perspective`, and `phase` from the headings. The rest of the file is the prompt template.

---

## 5. Orchestrator

### 5.1 Core Logic

```python
# orchestrator.py

import asyncio
from agents import discover_agents
from agents.schema import DataBundle, AgentOutput, CounterArgument
from agents.runner import run_markdown_agent
from confluence import ConfluenceResult

AGENT_REGISTRY = discover_agents()


async def analyse(ticker: str, include_sentiment: bool = True) -> ConfluenceResult:
    """
    Run the full multi-agent pipeline for one ticker.

    Phases:
      1. Data Scout (sync in thread)
      2. Parallel analysts (LLM + Python, concurrent)
      3. Devil's Advocate (LLM, sequential)
      4. Chief Strategist (LLM, sequential)

    Returns ConfluenceResult — same object as the current pipeline.
    """

    # Phase 1: Data collection
    data_scout = AGENT_REGISTRY["data_scout"]
    data_bundle: DataBundle = await asyncio.to_thread(
        data_scout["run_fn"], ticker, include_sentiment
    )

    if data_bundle is None:
        raise ValueError(ticker)

    # Phase 2: Parallel analysis
    phase_2_agents = {
        name: meta for name, meta in AGENT_REGISTRY.items()
        if meta.get("phase") == 2
    }

    async def run_agent(name, meta):
        try:
            if meta["type"] == "python":
                return await asyncio.to_thread(meta["run_fn"], data_bundle)
            else:
                return await asyncio.wait_for(
                    run_markdown_agent(meta, data_bundle),
                    timeout=30,
                )
        except Exception as e:
            return AgentOutput(
                agent_name=name,
                perspective=meta.get("perspective", "unknown"),
                signal="NEUTRAL",
                confidence="LOW",
                points=[f"Agent error: {e}"],
            )

    tasks = [run_agent(name, meta) for name, meta in phase_2_agents.items()]
    phase_2_outputs: list[AgentOutput] = await asyncio.gather(*tasks)

    # Phase 3: Devil's Advocate
    da_meta = AGENT_REGISTRY.get("devils_advocate")
    counter: CounterArgument | None = None
    if da_meta:
        try:
            counter = await asyncio.wait_for(
                run_markdown_agent(da_meta, data_bundle, phase_2_outputs),
                timeout=30,
            )
        except Exception:
            counter = None

    # Phase 4: Chief Strategist
    cs_meta = AGENT_REGISTRY.get("chief_strategist")
    result: ConfluenceResult = await asyncio.wait_for(
        run_markdown_agent(cs_meta, data_bundle, phase_2_outputs, counter),
        timeout=30,
    )

    return result
```

### 5.2 Scan Mode Fallback

```python
async def analyse_scan(ticker: str) -> ConfluenceResult:
    """
    Lightweight Python-only analysis for watchlist scans.
    Skips all LLM agents. Uses existing signal_engine + confluence pipeline.
    """
    data_scout = AGENT_REGISTRY["data_scout"]
    data_bundle = await asyncio.to_thread(data_scout["run_fn"], ticker, False)

    if data_bundle is None:
        raise ValueError(ticker)

    # Run only Python agents
    quant_output = AGENT_REGISTRY["quant_engine"]["run_fn"](data_bundle)
    risk_output  = AGENT_REGISTRY["risk_manager"]["run_fn"](data_bundle)

    # Use existing confluence.compute_confluence() for the rest
    from confluence import compute_confluence
    return compute_confluence(
        ticker=data_bundle.ticker_meta.resolved,
        signals={tf.name: tf.signal for tf in data_bundle.timeframes.values() if tf},
        fundamentals=data_bundle.fundamentals,
        news_sentiment=data_bundle.sentiment,
    )
```

---

## 6. LLM Agent Runner

### 6.1 Markdown Prompt Construction

```python
# agents/runner.py

import json
from pathlib import Path
from chat_engine import chat_with_provider
from agents.schema import AgentOutput, DataBundle


def _build_prompt(agent_path: Path, data_bundle: DataBundle,
                  extra_context: str = "") -> str:
    """
    Load the markdown agent definition and inject data as structured context.

    The prompt sent to the LLM is:
      [Agent markdown — role, instructions, output schema, examples]
      ---
      [DATA CONTEXT]
      {serialised data relevant to this agent}
      ---
      [EXTRA CONTEXT]  (if any — e.g., other agent outputs for Devil's Advocate)
      ---
      Produce your analysis now. Return ONLY valid JSON matching the output schema.
    """
    template = agent_path.read_text(encoding="utf-8")

    # Serialise relevant data sections based on agent perspective
    data_json = _serialise_data_for_agent(agent_path.stem, data_bundle)

    prompt = (
        f"{template}\n\n"
        f"---\n"
        f"## DATA CONTEXT\n"
        f"```json\n{data_json}\n```\n"
    )

    if extra_context:
        prompt += (
            f"\n---\n"
            f"## ADDITIONAL CONTEXT\n"
            f"{extra_context}\n"
        )

    prompt += (
        f"\n---\n"
        f"Produce your analysis now. Return ONLY valid JSON matching the Output Schema above. "
        f"No markdown, no commentary outside the JSON."
    )

    return prompt


def _serialise_data_for_agent(agent_stem: str, data: DataBundle) -> str:
    """
    Return a JSON string containing only the data fields relevant to the agent.
    Prevents sending the entire DataBundle to every agent (reduces token usage).
    """
    # Map agent stem to its required data fields
    AGENT_DATA_MAP = {
        "technical_analyst": ["indicators", "timeframe_signals", "current_price"],
        "fundamentalist":    ["fundamentals"],
        "macro_strategist":  ["fundamentals_macro_subset", "ticker_meta"],
        "sentiment_analyst": ["sentiment", "indicators_subset", "fundamentals_52w"],
        "devils_advocate":   [],  # Gets other agent outputs via extra_context
        "chief_strategist":  [],  # Gets everything via extra_context
    }

    fields = AGENT_DATA_MAP.get(agent_stem, [])
    subset = {}

    if "indicators" in fields:
        for tf_name, tf_data in data.timeframes.items():
            if tf_data:
                subset[f"indicators_{tf_name}"] = tf_data.latest

    if "timeframe_signals" in fields:
        for tf_name, tf_data in data.timeframes.items():
            if tf_data and tf_data.signal:
                sig = tf_data.signal
                subset[f"signal_{tf_name}"] = {
                    "direction": sig.direction,
                    "confidence": sig.confidence,
                    "risk_reward": sig.risk_reward,
                    "reasoning": sig.reasoning,
                }

    if "fundamentals" in fields:
        subset["fundamentals"] = data.fundamentals

    if "fundamentals_macro_subset" in fields:
        f = data.fundamentals or {}
        subset["macro_context"] = {
            "sector": f.get("sector"),
            "industry": f.get("industry"),
            "market_cap": f.get("market_cap"),
            "week52_high": f.get("week52_high"),
            "week52_low": f.get("week52_low"),
        }

    if "sentiment" in fields and data.sentiment:
        s = data.sentiment
        subset["sentiment"] = {
            "signal": s.signal,
            "confidence": s.confidence,
            "score": s.score,
            "article_count": s.article_count,
            "headlines": [
                {"title": h.title, "label": h.label, "confidence": h.confidence,
                 "publisher": h.publisher, "published": h.published}
                for h in (s.headlines or [])
            ],
        }

    if "current_price" in fields:
        subset["current_price"] = data.current_price

    if "ticker_meta" in fields:
        subset["ticker"] = {
            "symbol": data.ticker_meta.resolved,
            "market": data.ticker_meta.market,
            "currency": data.ticker_meta.currency,
        }

    return json.dumps(subset, indent=2, default=str)
```

### 6.2 LLM Call and Response Parsing

```python
async def run_markdown_agent(
    meta: dict,
    data_bundle: DataBundle,
    phase_2_outputs: list[AgentOutput] | None = None,
    counter: object | None = None,
) -> AgentOutput:
    """
    Execute a markdown-defined LLM agent.

    1. Build prompt from markdown template + serialised data.
    2. Call the configured AI provider (Groq or Gemini).
    3. Parse JSON response into AgentOutput (or CounterArgument for Devil's Advocate).
    4. On parse failure, retry once with a stricter instruction.
    """
    extra_context = ""
    if phase_2_outputs:
        outputs_json = json.dumps(
            [_agent_output_to_dict(o) for o in phase_2_outputs],
            indent=2, default=str,
        )
        extra_context += f"## Phase 2 Agent Outputs\n```json\n{outputs_json}\n```\n"

    if counter:
        counter_json = json.dumps(_counter_to_dict(counter), indent=2)
        extra_context += f"\n## Devil's Advocate\n```json\n{counter_json}\n```\n"

    prompt = _build_prompt(meta["path"], data_bundle, extra_context)

    # Determine AI provider for this agent
    from config import AGENT_AI_CONFIG
    ai_cfg = AGENT_AI_CONFIG.get(meta["name"], {})
    provider = ai_cfg.get("provider", None)  # None = use default

    # Call LLM
    response_text = await asyncio.to_thread(
        chat_with_provider, prompt, provider=provider
    )

    # Parse JSON from response
    try:
        parsed = _extract_json(response_text)
        return _dict_to_agent_output(meta["name"], meta["perspective"], parsed)
    except (json.JSONDecodeError, KeyError, ValueError):
        # Retry once with stricter instruction
        retry_prompt = (
            f"{prompt}\n\n"
            f"YOUR PREVIOUS RESPONSE WAS NOT VALID JSON. "
            f"Return ONLY a JSON object with these required fields: "
            f"signal, confidence, points, key_observation. No other text."
        )
        response_text = await asyncio.to_thread(
            chat_with_provider, retry_prompt, provider=provider
        )
        parsed = _extract_json(response_text)
        return _dict_to_agent_output(meta["name"], meta["perspective"], parsed)


def _extract_json(text: str) -> dict:
    """
    Extract a JSON object from LLM response text.
    Handles common wrapping: ```json ... ``` blocks, leading/trailing text.
    """
    # Try direct parse first
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)

    # Try extracting from code block
    import re
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1).strip())

    # Try finding first { to last }
    start = text.index("{")
    end = text.rindex("}") + 1
    return json.loads(text[start:end])
```

---

## 7. Integration Points

### 7.1 telegram_bot.py Changes

Minimal change: replace the `run_signal()` call with the orchestrator.

```python
# Before (current):
def run_signal(ticker: str, include_sentiment: bool = True) -> tuple[str, object]:
    ...
    result = compute_confluence(ticker, signals, fundamentals, news_sentiment)
    ...

# After:
def run_signal(ticker: str, include_sentiment: bool = True) -> tuple[str, object]:
    """Synchronous wrapper around the async orchestrator."""
    import asyncio
    from orchestrator import analyse, analyse_scan

    if include_sentiment:
        result = asyncio.run(analyse(ticker))
    else:
        result = asyncio.run(analyse_scan(ticker))

    return format_signal_html(result), result
```

The rest of `telegram_bot.py` (commands, callbacks, message router, HTML formatting) remains unchanged because `ConfluenceResult` is the same object.

### 7.2 main.py Changes

```python
# Before:
from confluence import compute_confluence

# After:
from orchestrator import analyse
import asyncio

def analyse_ticker(ticker: str):
    return asyncio.run(analyse(ticker))
```

### 7.3 chat_engine.py Changes

Add a provider-selectable function for the agent runner:

```python
def chat_with_provider(
    prompt: str,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """
    Send a prompt to a specific AI provider.
    If provider is None, uses the default (Groq → Gemini fallback).
    """
    provider = provider or get_provider()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    if provider == "groq":
        return _chat_groq(messages)
    elif provider == "gemini":
        return _chat_gemini(messages)
    else:
        return "No AI provider available."
```

---

## 8. Configuration Additions

```python
# config.py — additions for multi-agent support

# Per-agent AI provider configuration
# Keys: agent name (stem of the file in agents/)
# Values: {"provider": "groq"|"gemini", "model": "..."}
# If an agent is not listed, it uses the default provider (Groq → Gemini fallback).
AGENT_AI_CONFIG = {
    "technical_analyst":  {"provider": "groq"},
    "fundamentalist":     {"provider": "groq"},
    "macro_strategist":   {"provider": "groq"},
    "sentiment_analyst":  {"provider": "groq"},
    "devils_advocate":    {"provider": "groq"},
    "chief_strategist":   {"provider": "groq"},
}

# Agent execution timeouts (seconds)
AGENT_TIMEOUTS = {
    "python":   10,
    "markdown": 30,
}
```

---

## 9. Error Handling Strategy

### 9.1 Agent-Level Resilience

```
Agent call
    │
    ├── Success → AgentOutput
    │
    ├── Parse error → Retry once with stricter prompt
    │       ├── Success → AgentOutput
    │       └── Fail → Fallback AgentOutput (NEUTRAL/LOW, error noted)
    │
    ├── Timeout → Fallback AgentOutput (NEUTRAL/LOW, "timed out")
    │
    └── Exception → Fallback AgentOutput (NEUTRAL/LOW, error message)
```

### 9.2 System-Level Resilience

| Failure | Recovery |
|---|---|
| Data Scout returns no data on any timeframe | Raise ValueError — same as current "symbol not found" |
| All LLM agents fail (rate limit, network) | Fall back to `analyse_scan()` (Python-only path) and note in output |
| Chief Strategist fails | Use Python-based `compute_confluence()` as fallback |
| Single agent fails | Continue with remaining agents; Chief Strategist notes the gap |

### 9.3 Graceful Degradation Tiers

```
Tier 1: Full multi-agent   — all agents run (best quality)
Tier 2: Partial agents     — some LLM agents failed, others succeeded
Tier 3: Python-only        — all LLM agents failed; use existing scoring pipeline
Tier 4: No data            — Yahoo Finance down; return error to user
```

---

## 10. Token Budget and Cost Management

### 10.1 Per-Analysis Token Estimate

| Agent | Input Tokens (est.) | Output Tokens (est.) | Provider |
|---|---|---|---|
| Technical Analyst | ~800 | ~300 | Groq (free) |
| Fundamentalist | ~500 | ~300 | Groq (free) |
| Macro Strategist | ~400 | ~250 | Groq (free) |
| Sentiment Analyst | ~1200 (headlines) | ~300 | Groq (free) |
| Devil's Advocate | ~1500 (all outputs) | ~200 | Groq (free) |
| Chief Strategist | ~2000 (all outputs + counter) | ~500 | Groq (free) |
| **Total per analysis** | **~6,400** | **~1,850** | |

At Groq free tier (~30 req/min), a single analysis uses 6 LLM calls — well within limits.

### 10.2 Scan Mode

Scan uses 0 LLM calls per ticker (Python-only). 20 tickers = 0 LLM calls total.

### 10.3 Token Reduction Strategies

- Each agent receives only its relevant data slice (not the entire DataBundle).
- Serialised data uses compact JSON (no whitespace in production mode).
- Agent prompts are optimised for conciseness — instructions are precise, not verbose.
- Output is capped at structured JSON — no free-form narrative in the raw output.

---

## 11. Testing Strategy

### 11.1 Unit Tests

| Component | Test |
|---|---|
| `agents/schema.py` | DataBundle and AgentOutput creation, serialisation, validation |
| `agents/__init__.py` | Agent discovery — detects .md and .py files correctly |
| `agents/runner.py` | JSON extraction from various LLM response formats |
| `agents/quant_engine.py` | Deterministic output for known indicator inputs |
| `agents/risk_manager.py` | Position sizing math, risk veto triggering |
| `orchestrator.py` | Phase ordering, timeout handling, fallback behaviour |

### 11.2 Integration Tests

| Test | Validates |
|---|---|
| End-to-end single ticker (HAL.NS) | Full pipeline produces valid ConfluenceResult |
| Scan mode 3 tickers | Python-only path produces valid results |
| LLM agent failure simulation | System falls back gracefully to Python-only |
| Rate limit simulation | Tier 3 degradation works correctly |

### 11.3 Agent-Level Testing

Each agent can be tested in isolation:

```python
# Test a single agent with fixture data
from agents.schema import DataBundle
from agents.runner import run_markdown_agent
from agents import AGENT_REGISTRY

data = load_test_fixture("HAL_NS_20260620.json")
agent = AGENT_REGISTRY["technical_analyst"]
output = await run_markdown_agent(agent, data)

assert output.signal in ("BULLISH", "BEARISH", "NEUTRAL")
assert output.confidence in ("HIGH", "MEDIUM", "LOW")
assert len(output.points) >= 1
```

---

## 12. Deployment

### 12.1 No Infrastructure Changes

The bot continues to run as a single Python process on a local machine. No containers, no cloud deployment, no database.

```bash
# Same as today:
python telegram_bot.py

# CLI mode:
python main.py HAL
```

### 12.2 New Dependencies

None. The multi-agent architecture uses only existing dependencies:
- `asyncio` (stdlib) for parallel execution.
- `json` (stdlib) for data serialisation.
- `pathlib` (stdlib) for agent file discovery.
- `chat_engine.py` (existing) for LLM calls.

### 12.3 Migration Path

The transition is backward-compatible:

1. **Phase 1**: Build `agents/` directory with schema and orchestrator alongside existing code.
2. **Phase 2**: Wire `orchestrator.analyse()` into `telegram_bot.py`'s `run_signal()`.
3. **Phase 3**: Existing `confluence.py` becomes the scan-mode fallback.
4. **Phase 4**: Old monolithic path in `run_signal()` removed once all tests pass.

At every phase, the old path remains functional — the switchover is a single function call change.

---

## 13. Monitoring and Observability

### 13.1 Logging

Each agent logs its execution:

```
[orchestrator] Starting analysis for HAL.NS
[data_scout]   Fetched 4 timeframes, fundamentals, 12 news articles
[technical]    Completed in 2.1s — BULLISH (HIGH)
[fundamental]  Completed in 1.8s — BULLISH (MEDIUM)
[macro]        Completed in 1.5s — NEUTRAL (LOW)
[sentiment]    Completed in 2.3s — POSITIVE (MEDIUM)
[quant]        Completed in 0.02s — BULLISH (MEDIUM)
[risk]         Completed in 0.01s — BULLISH (HIGH)
[advocate]     Completed in 2.0s — counter: BEARISH (LOW)
[strategist]   Completed in 2.5s — BUY (MEDIUM confidence)
[orchestrator] Total: 8.2s (Phase 2 parallel: 2.3s)
```

### 13.2 Metrics (Logged, Not Dashboarded)

- Total analysis time (wall clock).
- Per-agent latency.
- LLM token usage per agent (if provider returns it).
- Agent failure count and type.
- Fallback tier used (1–4).

---

## 14. Security Considerations

| Concern | Mitigation |
|---|---|
| API keys in .env | `.env` is in `.gitignore`; never committed |
| LLM prompt injection via news headlines | Headlines are data-context, not instructions; agent prompts explicitly say "use only the data provided" |
| Yahoo Finance data manipulation | Out of scope — yfinance is the standard; no alternative without a broker API |
| Telegram bot token exposure | Token in `.env`, not in code |
| Agent markdown injection | Agent files are local, developer-controlled — no user-uploaded agents |

---

## 15. Performance Benchmarks (Targets)

| Metric | Before | Target |
|---|---|---|
| Single ticker (with sentiment) | 15–60s | < 30s |
| Single ticker (no sentiment) | 5–15s | < 10s |
| 20-ticker scan | 2–4 min | < 3 min (unchanged — Python-only) |
| Memory (idle) | ~100 MB | < 200 MB |
| Memory (FinBERT loaded) | ~500 MB | < 800 MB |
| LLM calls per analysis | 0 (explain only) | 6 (analyst + adversarial + strategist) |
| LLM calls per scan | 0 | 0 (Python-only fast path) |
