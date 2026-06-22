"""LLM agent execution engine — loads markdown agents, calls AI, parses JSON.

Each markdown agent file is a self-contained prompt template.  The runner:
  1. Reads the .md file
  2. Injects only the data slice relevant to that agent (token efficiency)
  3. Calls the configured AI provider via chat_with_provider()
  4. Parses JSON from the response (with one retry on parse failure)
  5. Returns AgentOutput, CounterArgument, or raw dict depending on the agent
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from agents.schema import AgentOutput, CounterArgument, DataBundle


_VALID_SIGNALS     = {"BULLISH", "BEARISH", "NEUTRAL"}
_VALID_CONFIDENCE  = {"HIGH", "MEDIUM", "LOW"}

# Overrides the default trading-chat system prompt with a stricter JSON-focused one
AGENT_SYSTEM_PROMPT = (
    "You are a specialised financial analyst agent. You receive structured market data "
    "and must return your analysis as valid JSON matching the Output Schema in your instructions. "
    "Use ONLY the data provided. Never invent prices or figures. "
    "If data is missing, say so and lower your confidence."
)


def _serialise_data_for_agent(agent_stem: str, data: DataBundle) -> str:
    """Return a JSON string with only the data fields relevant to this agent."""
    subset: dict = {}

    if agent_stem in ("technical_analyst",):
        for tf_name, tf_data in (data.timeframes or {}).items():
            if tf_data:
                subset[f"indicators_{tf_name}"] = tf_data.latest
                sig = tf_data.signal
                subset[f"signal_{tf_name}"] = {
                    "direction":  sig.direction,
                    "confidence": sig.confidence,
                    "risk_reward": sig.risk_reward,
                    "reasoning":  sig.reasoning,
                }
        subset["current_price"] = data.current_price

    elif agent_stem in ("fundamentalist",):
        subset["fundamentals"] = data.fundamentals

    elif agent_stem in ("macro_strategist",):
        f = data.fundamentals or {}
        subset["macro_context"] = {
            "sector":      f.get("sector"),
            "industry":    f.get("industry"),
            "market_cap":  f.get("market_cap"),
            "week52_high": f.get("week52_high"),
            "week52_low":  f.get("week52_low"),
            "short_name":  f.get("short_name"),
        }
        subset["ticker"] = {
            "symbol":   data.ticker_meta.resolved,
            "market":   data.ticker_meta.market,
            "currency": data.ticker_meta.currency,
        }
        subset["current_price"] = data.current_price

    elif agent_stem in ("sentiment_analyst",):
        if data.sentiment is not None:
            s = data.sentiment
            subset["sentiment"] = {
                "signal":        s.signal,
                "confidence":    s.confidence,
                "score":         s.score,
                "article_count": s.article_count,
                "headlines": [
                    {
                        "title":      h.title,
                        "label":      h.label,
                        "confidence": h.confidence,
                        "publisher":  h.publisher,
                        "published":  h.published,
                    }
                    for h in (s.headlines or [])
                ],
            }
        daily = (data.timeframes or {}).get("daily")
        if daily:
            subset["vol_ratio"] = daily.latest.get("vol_ratio")
        f = data.fundamentals or {}
        subset["week52_high"] = f.get("week52_high")
        subset["week52_low"]  = f.get("week52_low")
        subset["current_price"] = data.current_price

    elif agent_stem in ("sector_specialist",):
        f = data.fundamentals or {}
        subset["fundamentals"] = {
            "sector":          f.get("sector"),
            "industry":        f.get("industry"),
            "pe_trailing":     f.get("pe_trailing"),
            "roe":             f.get("roe"),
            "market_cap":      f.get("market_cap"),
            "earnings_growth": f.get("earnings_growth"),
            "revenue_growth":  f.get("revenue_growth"),
        }
        subset["ticker"] = {
            "symbol":   data.ticker_meta.resolved,
            "market":   data.ticker_meta.market,
            "currency": data.ticker_meta.currency,
        }
        subset["current_price"] = data.current_price

    elif agent_stem in ("event_watcher",):
        f = data.fundamentals or {}
        subset["fundamentals"] = {
            "sector":          f.get("sector"),
            "industry":        f.get("industry"),
            "dividend_yield":  f.get("dividend_yield"),
            "earnings_growth": f.get("earnings_growth"),
            "short_name":      f.get("short_name"),
        }
        subset["ticker"] = {
            "symbol":   data.ticker_meta.resolved,
            "market":   data.ticker_meta.market,
        }

    return json.dumps(subset, indent=2, default=str)


def _build_prompt(
    agent_path: Path,
    data_bundle: DataBundle,
    extra_context: str = "",
) -> str:
    """Assemble the full prompt from markdown template + data context."""
    template = agent_path.read_text(encoding="utf-8")

    data_json = _serialise_data_for_agent(agent_path.stem, data_bundle)

    prompt = f"{template}\n\n---\n## DATA CONTEXT\n```json\n{data_json}\n```\n"

    if extra_context:
        prompt += f"\n---\n## ADDITIONAL CONTEXT\n{extra_context}\n"

    prompt += (
        "\n---\n"
        "Produce your analysis now. Return ONLY valid JSON matching the Output Schema above. "
        "No markdown fences, no commentary outside the JSON object."
    )
    return prompt


def _extract_json(text: str) -> dict:
    """Extract a JSON object from LLM response text."""
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)

    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1).strip())

    start = text.index("{")
    end   = text.rindex("}") + 1
    return json.loads(text[start:end])


def _dict_to_agent_output(agent_name: str, perspective: str, d: dict) -> AgentOutput:
    """Map a parsed JSON dict to AgentOutput with validation."""
    signal = d.get("signal", "NEUTRAL").upper()
    if signal not in _VALID_SIGNALS:
        signal = "NEUTRAL"

    confidence = d.get("confidence", "LOW").upper()
    if confidence not in _VALID_CONFIDENCE:
        confidence = "LOW"

    points = d.get("points", [])
    if isinstance(points, str):
        points = [points]

    return AgentOutput(
        agent_name=agent_name,
        perspective=perspective,
        signal=signal,
        confidence=confidence,
        points=points,
        key_observation=d.get("key_observation", ""),
        missing_data=d.get("missing_data", []),
        extra={k: v for k, v in d.items()
               if k not in ("signal", "confidence", "points", "key_observation", "missing_data")},
    )


def _dict_to_counter(d: dict) -> CounterArgument:
    """Map a parsed JSON dict to CounterArgument."""
    return CounterArgument(
        counter_direction=d.get("counter_direction", "NEUTRAL").upper(),
        argument=d.get("argument", ""),
        risks_underweighted=d.get("risks_underweighted", []),
        invalidation_condition=d.get("invalidation_condition", ""),
        confidence_in_counter=d.get("confidence_in_counter", "LOW").upper(),
    )


def agent_output_to_dict(output: AgentOutput) -> dict:
    """Serialise AgentOutput for injection into downstream prompts."""
    d = {
        "agent":       output.agent_name,
        "perspective": output.perspective,
        "signal":      output.signal,
        "confidence":  output.confidence,
        "points":      output.points,
    }
    if output.key_observation:
        d["key_observation"] = output.key_observation
    if output.missing_data:
        d["missing_data"] = output.missing_data
    if output.veto:
        d["veto"] = True
        d["veto_reason"] = output.veto_reason
    if output.entry is not None:
        d.update({
            "entry":          output.entry,
            "stop_loss":      output.stop_loss,
            "target_1":       output.target_1,
            "target_2":       output.target_2,
            "position_size":  output.position_size,
            "position_value": output.position_value,
            "risk_amount":    output.risk_amount,
            "risk_reward":    output.risk_reward,
        })
    return d


def counter_to_dict(counter: CounterArgument) -> dict:
    """Serialise CounterArgument for injection into downstream prompts."""
    return {
        "counter_direction":      counter.counter_direction,
        "argument":               counter.argument,
        "risks_underweighted":    counter.risks_underweighted,
        "invalidation_condition": counter.invalidation_condition,
        "confidence_in_counter":  counter.confidence_in_counter,
    }


async def run_markdown_agent(
    meta: dict,
    data_bundle: DataBundle,
    phase_2_outputs: list[AgentOutput] | None = None,
    counter: CounterArgument | None = None,
) -> AgentOutput | CounterArgument | dict:
    """
    Execute a markdown-defined LLM agent.

    Returns AgentOutput for analysts, CounterArgument for devil's advocate,
    or a raw dict for the chief strategist.
    """
    from src.chat_engine import chat_with_provider
    from src.config import AGENT_AI_CONFIG

    extra_context = ""
    if phase_2_outputs:
        outputs_json = json.dumps(
            [agent_output_to_dict(o) for o in phase_2_outputs],
            indent=2, default=str,
        )
        extra_context += f"## Phase 2 Agent Outputs\n```json\n{outputs_json}\n```\n"

    if counter:
        counter_json = json.dumps(counter_to_dict(counter), indent=2)
        extra_context += f"\n## Devil's Advocate\n```json\n{counter_json}\n```\n"

    prompt = _build_prompt(meta["path"], data_bundle, extra_context)

    ai_cfg   = AGENT_AI_CONFIG.get(meta["name"], {})
    provider = ai_cfg.get("provider")

    response_text = await asyncio.to_thread(
        chat_with_provider, prompt,
        provider=provider,
        system_prompt=AGENT_SYSTEM_PROMPT,
        max_tokens=1024,
    )

    agent_name  = meta["name"]
    perspective = meta.get("perspective", "unknown")

    try:
        parsed = _extract_json(response_text)
    except (json.JSONDecodeError, ValueError):
        retry_prompt = (
            f"{prompt}\n\n"
            "YOUR PREVIOUS RESPONSE WAS NOT VALID JSON. "
            "Return ONLY a JSON object. No other text."
        )
        response_text = await asyncio.to_thread(
            chat_with_provider, retry_prompt,
            provider=provider,
            system_prompt=AGENT_SYSTEM_PROMPT,
        )
        try:
            parsed = _extract_json(response_text)
        except (json.JSONDecodeError, ValueError):
            return AgentOutput(
                agent_name=agent_name,
                perspective=perspective,
                signal="NEUTRAL",
                confidence="LOW",
                points=[f"Agent {agent_name} failed to return valid JSON after retry."],
            )

    if agent_name == "devils_advocate":
        return _dict_to_counter(parsed)

    if agent_name == "chief_strategist":
        return parsed

    return _dict_to_agent_output(agent_name, perspective, parsed)
