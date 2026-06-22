"""Core dataclasses for the multi-agent pipeline.

These types flow through the orchestrator:
  DataBundle     — produced by Data Scout, consumed by all Phase 2 agents
  AgentOutput    — returned by every Phase 2 analyst (LLM or Python)
  CounterArgument — returned by the Devil's Advocate (Phase 3)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from signal_engine import TimeframeSignal


@dataclass
class TickerMeta:
    """Resolved ticker info passed to every agent for display purposes."""
    raw_input: str
    resolved:  str
    currency:  str
    market:    str


@dataclass
class TimeframeData:
    """One timeframe's complete data: raw OHLCV, enriched indicators, and signal."""
    name:       str
    ohlcv:      pd.DataFrame
    indicators: pd.DataFrame
    latest:     dict              # from indicators.latest_values()
    signal:     TimeframeSignal


@dataclass
class DataBundle:
    """Complete data package produced by Data Scout and consumed by all analysts."""
    ticker_meta:   TickerMeta
    timeframes:    dict[str, TimeframeData | None]
    fundamentals:  dict
    sentiment:     Optional[object]   # SentimentResult or None (optional dependency)
    current_price: float | None
    fetch_errors:  list[str] = field(default_factory=list)


@dataclass
class AgentOutput:
    """Standard return type for all Phase 2 analyst agents."""
    agent_name:      str
    perspective:     str              # one of the 6 CLAUDE.md perspectives, or "sector"/"events"
    signal:          str              # BULLISH | BEARISH | NEUTRAL
    confidence:      str              # HIGH | MEDIUM | LOW
    points:          list[str]
    key_observation: str = ""
    missing_data:    list[str] = field(default_factory=list)
    extra:           dict = field(default_factory=dict)

    # Populated only by risk_manager — other agents leave these as defaults
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


@dataclass
class CounterArgument:
    """Output from the Devil's Advocate agent (Phase 3)."""
    counter_direction:      str
    argument:               str
    risks_underweighted:    list[str]
    invalidation_condition: str
    confidence_in_counter:  str
