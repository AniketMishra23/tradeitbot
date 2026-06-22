# Business Requirements Document (BRD)

## Trade It — Multi-Agent Global Market Signal Platform

| Field | Value |
|---|---|
| **Project** | Trade It v2 — Multi-Agent Architecture |
| **Author** | Aniket Mishra |
| **Date** | 2026-06-22 |
| **Version** | 1.0 |
| **Status** | Draft |

---

## 1. Executive Summary

Trade It is a trading signal analysis platform that currently delivers multi-timeframe, six-perspective trade recommendations via Telegram and CLI. The platform analyses any Yahoo Finance ticker — Indian NSE/BSE, US stocks, crypto, ASX, LSE, TSE, and more — using technical indicators, fundamental data, news sentiment, and risk management rules.

The next evolution is a **multi-agent architecture** where each analytical perspective is handled by a dedicated, specialised agent. This will improve signal quality, enable parallel analysis, allow independent agent upgrades, and create a modular system where new analytical capabilities can be added without disrupting existing ones.

---

## 2. Business Objectives

| # | Objective | Success Metric |
|---|---|---|
| BO-1 | Improve signal accuracy by deepening each analytical perspective | Measured by back-testing win rate improvement over current single-pipeline approach |
| BO-2 | Reduce analysis latency through parallel agent execution | Target: full analysis in under 30 seconds (current: 15–60s sequential) |
| BO-3 | Enable independent upgrades to each analytical domain without system-wide regression | Each agent deployable/testable in isolation |
| BO-4 | Support extensibility — new analytical agents (sector specialist, event watcher) can be added with zero changes to existing agents | Plugin-style agent registration |
| BO-5 | Maintain the existing Telegram and CLI user experience — no breaking changes to end-user commands | All existing commands continue to work identically |
| BO-6 | Preserve the CLAUDE.md analytical framework as the governing standard for all agents | Six perspectives, adversarial step, risk veto, data discipline — all enforced |

---

## 3. Stakeholders

| Stakeholder | Role | Interest |
|---|---|---|
| End user (trader) | Consumes signals via Telegram/CLI | Faster, more accurate, better-explained signals |
| Developer (Aniket) | Builds and maintains the platform | Clean architecture, easy to extend and debug |
| AI providers (Groq, Gemini) | Supply LLM inference for markdown agents | API usage stays within free-tier or budget constraints |
| Yahoo Finance | Data source for OHLCV, fundamentals, news | Rate limits and data availability govern what agents can fetch |

---

## 4. Business Context

### 4.1 Current State

The platform runs a monolithic pipeline: one function fetches data, computes indicators, scores signals, evaluates six perspectives, runs the adversarial step, and produces a verdict. This works but has limitations:

- **Tight coupling**: changing the fundamental analysis logic risks breaking technical analysis.
- **Sequential execution**: sentiment scoring (especially FinBERT) blocks the entire pipeline.
- **Single-depth analysis**: each perspective gets one pass — no ability to "think deeper" on a particular angle.
- **No specialisation**: the same system prompt handles all reasoning, from chart patterns to balance sheet analysis.

### 4.2 Desired Future State

A multi-agent system where:

- Each agent owns exactly one analytical perspective.
- Agents run in parallel where possible.
- A Chief Strategist agent synthesises all outputs into a final verdict.
- A Devil's Advocate agent challenges the emerging consensus before the final call.
- Python agents handle computation (quant, risk, data fetching); markdown/LLM agents handle reasoning (technical, fundamental, macro, sentiment analysis).
- New agents can be added by dropping a markdown file or Python module into the agents directory.

---

## 5. Scope

### 5.1 In Scope

| # | Requirement |
|---|---|
| S-1 | Multi-agent architecture with 9 core agents (see Section 6) |
| S-2 | Agent orchestration layer that routes data and collects outputs |
| S-3 | Markdown-based agent definitions for LLM-driven reasoning agents |
| S-4 | Python-based agents for computation-heavy tasks (quant, risk, data) |
| S-5 | Parallel execution of independent agents |
| S-6 | Chief Strategist agent that produces the final ConfluenceResult |
| S-7 | Devil's Advocate agent that argues against majority consensus |
| S-8 | Backward-compatible Telegram and CLI interfaces |
| S-9 | Configuration for AI provider per agent (Groq, Gemini, local) |

### 5.2 Out of Scope (v2.0)

| # | Item | Rationale |
|---|---|---|
| OS-1 | Live order execution | CLAUDE.md hard rule: output recommendations only |
| OS-2 | Real-time streaming price feeds | Yahoo Finance is batch; live feeds require a broker API |
| OS-3 | Multi-user authentication / user accounts | Current Telegram per-user state is sufficient |
| OS-4 | Paid AI providers (OpenAI, Anthropic API) | Stick to free-tier Groq/Gemini for now |
| OS-5 | Mobile app or web dashboard | Telegram is the primary interface |
| OS-6 | Historical back-testing engine | Future phase; requires trade journal agent first |

---

## 6. Agent Roster — Business Requirements

### 6.1 Core Analyst Agents (Markdown — LLM-Driven)

| Agent | Business Need | Input | Output |
|---|---|---|---|
| **Technical Analyst** | Deep chart analysis beyond simple indicator scores — pattern recognition, support/resistance, trend narrative | OHLCV data, computed indicators | Directional signal, confidence, key chart observations |
| **Fundamentalist** | Evaluate whether the stock is fairly valued using financial ratios and earnings quality | Fundamental data from yfinance | Valuation signal, confidence, key financial observations |
| **Macro Strategist** | Contextualise the trade within the broader economic regime — currently a gap (always NEUTRAL/LOW) | Sector, market cap, 52W range, external macro context if available | Macro signal, confidence, regime assessment |
| **Sentiment Analyst** | Interpret news tone and market mood beyond raw scores — narrative analysis | Scored headlines from sentiment engine, volume data, 52W positioning | Sentiment signal, confidence, narrative summary |
| **Devil's Advocate** | Prevent confirmation bias by arguing against the emerging consensus | All other agent outputs | Strongest counter-argument, risk factors the group missed |
| **Chief Strategist** | Make the final call by weighing all perspectives — the decision-maker | All agent outputs | Final verdict (BUY/SELL/HOLD/NO TRADE), trade plan, confidence, mind-changers |

### 6.2 Computation Agents (Python)

| Agent | Business Need | Input | Output |
|---|---|---|---|
| **Quant / Stats Engine** | Exact statistical computations — Bollinger %B, z-scores, volatility regime, correlations | OHLCV data | Quantitative signal, confidence, computed stats |
| **Risk Manager** | Position sizing, stop-loss calculation, risk veto enforcement, capital checks | Current price, ATR, capital config | Risk signal, confidence, position size, stop/targets, veto decision |
| **Data Scout** | Centralised data fetching — OHLCV, fundamentals, news — so no agent hits Yahoo Finance independently | Ticker symbol, timeframe config | Raw data bundle distributed to all other agents |

---

## 7. Business Rules

| # | Rule | Source |
|---|---|---|
| BR-1 | The Risk Manager agent can veto any trade recommendation. If position value exceeds 25% of capital, verdict MUST be NO TRADE. | CLAUDE.md — Risk Management Veto |
| BR-2 | No agent may invent prices, figures, or news. If data is missing, the agent must say so explicitly and note how it affects confidence. | CLAUDE.md — Data Discipline |
| BR-3 | No agent may present any conclusion as certain. All outputs are analysis, not predictions. | CLAUDE.md — Hard Rules |
| BR-4 | The system must never place or execute an order. Output recommendations only. | CLAUDE.md — Hard Rules |
| BR-5 | Default to paper-trading / simulation unless the human explicitly states otherwise. | CLAUDE.md — Hard Rules |
| BR-6 | All six CLAUDE.md perspectives must be evaluated before any final conclusion. | CLAUDE.md — Mandatory Perspectives |
| BR-7 | The adversarial step (bull case vs bear case) must run before the final verdict. | CLAUDE.md — Adversarial Step |
| BR-8 | All existing Telegram commands must continue to work without changes to user-facing syntax. | Backward compatibility requirement |

---

## 8. Constraints

| # | Constraint | Impact |
|---|---|---|
| C-1 | Yahoo Finance rate limits (unofficial API, 403 under heavy load) | Data Scout must cache aggressively; agents cannot fetch independently |
| C-2 | Free-tier AI provider limits (Groq: ~30 req/min, Gemini: 60 req/min) | At most 6 LLM agent calls per analysis; batch where possible |
| C-3 | FinBERT model is 440 MB — cold start takes ~30 seconds | Sentiment agent must lazy-load and cache the model in memory |
| C-4 | Sub-daily Yahoo Finance data limited to 60 days | 15-min and 1-hour timeframes have limited history |
| C-5 | No live macro data feed currently connected | Macro Strategist operates with limited data; must state this explicitly |
| C-6 | Indian NSE/BSE tickers have limited fundamental data on Yahoo Finance | Fundamentalist must handle missing data gracefully |

---

## 9. Assumptions

| # | Assumption |
|---|---|
| A-1 | The user has a stable internet connection for Yahoo Finance and AI API calls. |
| A-2 | Groq and/or Gemini free-tier API keys are available. |
| A-3 | The bot runs on a local machine or residential IP (not cloud/VPN) for Yahoo Finance reliability. |
| A-4 | Python 3.10+ is available. |
| A-5 | The multi-agent architecture does not require a database — in-memory state per session is sufficient. |
| A-6 | LLM agents receive structured data as context and return structured output — no tool-use or function-calling required in v2.0. |

---

## 10. Acceptance Criteria

| # | Criteria |
|---|---|
| AC-1 | Running `/analyse HAL` in Telegram produces the same output format as today, but generated by the multi-agent pipeline. |
| AC-2 | Each agent can be run and tested in isolation with sample input data. |
| AC-3 | Adding a new agent requires only a new markdown file or Python module — no changes to the orchestrator. |
| AC-4 | The Risk Manager veto overrides all other agent outputs when triggered. |
| AC-5 | The Devil's Advocate agent produces a counter-argument even when all other agents agree. |
| AC-6 | Full analysis completes within 30 seconds for a single ticker on a residential internet connection. |
| AC-7 | All six perspectives appear in the final output with signal and confidence ratings. |
| AC-8 | `/scan` continues to work and completes within 3 minutes for the default 20-ticker watchlist. |

---

## 11. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | AI provider rate limits exceeded during scan of 20 tickers (up to 120 LLM calls) | High | Scan fails or is very slow | Skip LLM agents during scans (current behaviour); use Python-only path |
| R-2 | LLM agent returns unstructured / unparseable output | Medium | Chief Strategist cannot synthesise | Define strict output schemas; validate and retry once on parse failure |
| R-3 | Yahoo Finance API becomes unreliable or introduces breaking changes | Medium | No data for any agent | Data Scout abstracts the source; can swap to another provider later |
| R-4 | Multi-agent overhead makes analysis slower than current pipeline | Low | User experience degrades | Parallel execution; skip LLM agents for scan mode; benchmark continuously |
| R-5 | Increased token usage pushes past free-tier limits | Medium | Increased cost or service interruptions | Monitor token usage; use concise prompts; fall back to Python-only mode |

---

## 12. Glossary

| Term | Definition |
|---|---|
| **Agent** | A self-contained analytical module — either a markdown prompt (LLM-driven) or a Python module (computation-driven) — that evaluates one perspective and returns a structured signal. |
| **Confluence** | The degree to which multiple timeframes and perspectives agree on a direction. |
| **Risk Veto** | A hard override that forces the verdict to NO TRADE when position sizing exceeds capital safety thresholds. |
| **Perspective** | One of six analytical angles defined in CLAUDE.md: Technical, Fundamental, Macro, Sentiment, Quantitative, Risk. |
| **Adversarial Step** | A mandatory step where the strongest bull and bear cases are compared before reaching a conclusion. |
| **OHLCV** | Open, High, Low, Close, Volume — standard price bar data. |
| **ATR** | Average True Range — a volatility measure used for stop-loss placement. |
| **Timeframe Signal** | The directional call (BULLISH/BEARISH/NEUTRAL) for one timeframe (15m, 1h, daily, weekly). |
| **ConfluenceResult** | The final output object containing the verdict, trade levels, all perspectives, and the adversarial assessment. |
