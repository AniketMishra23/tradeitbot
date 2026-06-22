"""Multi-agent orchestrator — 5-phase pipeline producing ConfluenceResult."""

from __future__ import annotations

import asyncio
import logging

from agents import discover_agents
from agents.schema import AgentOutput, CounterArgument, DataBundle
from agents.runner import run_markdown_agent
from confluence import ConfluenceResult, Perspective
from config import AGENT_TIMEOUTS

log = logging.getLogger(__name__)

AGENT_REGISTRY = discover_agents()

# The 6 perspectives that map onto ConfluenceResult.perspectives
_CORE_PERSPECTIVES = {
    "technical", "fundamental", "macro", "sentiment", "quantitative", "risk",
}


# ── Public API ───────────────────────────────────────────────────────────────

def analyse_sync(ticker: str, include_sentiment: bool = True) -> ConfluenceResult:
    """Synchronous entry point — creates a new event loop in the calling thread."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(analyse(ticker, include_sentiment))
    finally:
        loop.close()


async def analyse(ticker: str, include_sentiment: bool = True) -> ConfluenceResult:
    """
    Full multi-agent analysis pipeline.

    Phase 1: Data Scout — fetch all data
    Phase 2: Parallel analysts (LLM + Python)
    Phase 3: Devil's Advocate
    Phase 4: Chief Strategist → ConfluenceResult
    Phase 5: Trade Journal (fire-and-forget)
    """
    # Phase 1: Data Collection
    data_scout = AGENT_REGISTRY.get("data_scout")
    if not data_scout:
        raise RuntimeError("data_scout agent not found in registry")

    data_bundle: DataBundle | None = await asyncio.to_thread(
        data_scout["run_fn"], ticker, include_sentiment,
    )
    if data_bundle is None:
        raise ValueError(ticker)

    log.info("Phase 1 complete: data collected for %s", data_bundle.ticker_meta.resolved)

    # Phase 2: Parallel Analysis
    phase_2_agents = {
        name: meta for name, meta in AGENT_REGISTRY.items()
        if meta.get("phase") == 2
    }

    phase_2_outputs: list[AgentOutput] = await _run_phase_2(phase_2_agents, data_bundle)
    log.info("Phase 2 complete: %d agents returned outputs", len(phase_2_outputs))

    # Phase 3: Devil's Advocate
    counter: CounterArgument | None = await _run_devils_advocate(data_bundle, phase_2_outputs)
    if counter:
        log.info("Phase 3 complete: Devil's Advocate argues %s", counter.counter_direction)

    # Phase 4: Chief Strategist
    result = await _run_chief_strategist(data_bundle, phase_2_outputs, counter)
    log.info("Phase 4 complete: verdict = %s", result.final_verdict)

    # Phase 5: Trade Journal (fire-and-forget)
    journal = AGENT_REGISTRY.get("trade_journal")
    if journal and journal.get("run_fn"):
        try:
            await asyncio.to_thread(journal["run_fn"], result)
        except Exception:
            pass

    return result


async def analyse_scan(ticker: str) -> ConfluenceResult:
    """
    Lightweight Python-only path for /scan — zero LLM calls.

    Uses existing confluence.compute_confluence() for the final result.
    """
    from confluence import compute_confluence

    data_scout = AGENT_REGISTRY.get("data_scout")
    if not data_scout:
        raise RuntimeError("data_scout agent not found in registry")

    data_bundle = await asyncio.to_thread(data_scout["run_fn"], ticker, False)
    if data_bundle is None:
        raise ValueError(ticker)

    signals = {}
    for tf_name, tf_data in data_bundle.timeframes.items():
        if tf_data is not None:
            signals[tf_name] = tf_data.signal
        else:
            signals[tf_name] = None

    return compute_confluence(
        data_bundle.ticker_meta.resolved,
        signals,
        data_bundle.fundamentals,
        data_bundle.sentiment,
    )


# ── Phase 2: Parallel Analysis ───────────────────────────────────────────────

async def _run_phase_2(
    agents: dict,
    data_bundle: DataBundle,
) -> list[AgentOutput]:
    """Run all Phase 2 agents concurrently and collect outputs."""
    timeout_py = AGENT_TIMEOUTS.get("python", 10)
    timeout_md = AGENT_TIMEOUTS.get("markdown", 30)

    async def _run_one(name: str, meta: dict) -> AgentOutput:
        timeout = timeout_py if meta["type"] == "python" else timeout_md
        try:
            if meta["type"] == "python":
                result = await asyncio.wait_for(
                    asyncio.to_thread(meta["run_fn"], data_bundle),
                    timeout=timeout,
                )
            else:
                result = await asyncio.wait_for(
                    run_markdown_agent(meta, data_bundle),
                    timeout=timeout,
                )
            if isinstance(result, AgentOutput):
                return result
            return AgentOutput(
                agent_name=name,
                perspective=meta.get("perspective", "unknown"),
                signal="NEUTRAL",
                confidence="LOW",
                points=[f"Agent {name} returned unexpected type."],
            )
        except asyncio.TimeoutError:
            log.warning("Agent %s timed out after %ds", name, timeout)
            return AgentOutput(
                agent_name=name,
                perspective=meta.get("perspective", "unknown"),
                signal="NEUTRAL",
                confidence="LOW",
                points=[f"Agent {name} timed out ({timeout}s)."],
            )
        except Exception as e:
            log.warning("Agent %s failed: %s", name, e)
            return AgentOutput(
                agent_name=name,
                perspective=meta.get("perspective", "unknown"),
                signal="NEUTRAL",
                confidence="LOW",
                points=[f"Agent {name} error: {e}"],
            )

    tasks = [_run_one(name, meta) for name, meta in agents.items()]
    return list(await asyncio.gather(*tasks))


# ── Phase 3: Devil's Advocate ────────────────────────────────────────────────

async def _run_devils_advocate(
    data_bundle: DataBundle,
    phase_2_outputs: list[AgentOutput],
) -> CounterArgument | None:
    da_meta = AGENT_REGISTRY.get("devils_advocate")
    if not da_meta:
        return None

    timeout = AGENT_TIMEOUTS.get("markdown", 30)
    try:
        result = await asyncio.wait_for(
            run_markdown_agent(da_meta, data_bundle, phase_2_outputs),
            timeout=timeout,
        )
        if isinstance(result, CounterArgument):
            return result
        return None
    except Exception as e:
        log.warning("Devil's Advocate failed: %s", e)
        return None


# ── Phase 4: Chief Strategist ────────────────────────────────────────────────

async def _run_chief_strategist(
    data_bundle: DataBundle,
    phase_2_outputs: list[AgentOutput],
    counter: CounterArgument | None,
) -> ConfluenceResult:
    """
    Run the Chief Strategist LLM agent and map output to ConfluenceResult.

    Falls back to the existing Python pipeline if the agent fails.
    """
    cs_meta = AGENT_REGISTRY.get("chief_strategist")
    if not cs_meta:
        return _fallback_confluence(data_bundle)

    timeout = AGENT_TIMEOUTS.get("markdown", 30)
    try:
        raw = await asyncio.wait_for(
            run_markdown_agent(cs_meta, data_bundle, phase_2_outputs, counter),
            timeout=timeout,
        )

        if isinstance(raw, dict):
            return _build_confluence_result(data_bundle, phase_2_outputs, counter, raw)
        else:
            log.warning("Chief Strategist returned non-dict, falling back")
            return _fallback_confluence(data_bundle)

    except Exception as e:
        log.warning("Chief Strategist failed: %s — falling back to Python pipeline", e)
        return _fallback_confluence(data_bundle)


# ── Result Builders ──────────────────────────────────────────────────────────

def _build_confluence_result(
    data_bundle: DataBundle,
    phase_2_outputs: list[AgentOutput],
    counter: CounterArgument | None,
    cs_output: dict,
) -> ConfluenceResult:
    """Map Chief Strategist JSON + Phase 2 outputs to ConfluenceResult."""

    # Build perspectives dict from Phase 2 outputs
    perspectives: dict[str, Perspective] = {}
    for output in phase_2_outputs:
        if output.perspective in _CORE_PERSPECTIVES:
            perspectives[output.perspective] = Perspective(
                signal=output.signal,
                confidence=output.confidence,
                points=output.points,
            )

    # Ensure all 6 core perspectives exist
    for p in _CORE_PERSPECTIVES:
        if p not in perspectives:
            perspectives[p] = Perspective(
                signal="NEUTRAL", confidence="LOW",
                points=[f"No agent output for {p} perspective."],
            )

    # Extract risk manager data
    risk_output = next(
        (o for o in phase_2_outputs if o.perspective == "risk"), None
    )

    best_entry  = risk_output.entry if risk_output else None
    best_stop   = risk_output.stop_loss if risk_output else None
    best_t1     = risk_output.target_1 if risk_output else None
    best_t2     = risk_output.target_2 if risk_output else None
    pos_size    = risk_output.position_size if risk_output else None
    pos_value   = risk_output.position_value if risk_output else None
    risk_amount = risk_output.risk_amount if risk_output else None

    # Build timeframe_signals dict
    tf_signals = {}
    for tf_name, tf_data in data_bundle.timeframes.items():
        tf_signals[tf_name] = tf_data.signal if tf_data else None

    # Extract fields from Chief Strategist output
    overall_direction = cs_output.get("overall_direction", "NEUTRAL")
    if overall_direction not in ("BULLISH", "BEARISH", "NEUTRAL"):
        overall_direction = "NEUTRAL"

    confluence_level = cs_output.get("confluence_level", "CONFLICTED")
    if confluence_level not in ("STRONG", "MODERATE", "WEAK", "CONFLICTED"):
        confluence_level = "CONFLICTED"

    final_verdict = cs_output.get("final_verdict", "HOLD")
    if final_verdict not in ("BUY", "SELL", "HOLD", "NO TRADE"):
        final_verdict = "HOLD"

    overall_confidence = cs_output.get("overall_confidence", "LOW")
    if overall_confidence not in ("HIGH", "MEDIUM", "LOW"):
        overall_confidence = "LOW"

    notes = cs_output.get("notes", [])
    if isinstance(notes, str):
        notes = [notes]

    # CLAUDE.md hard rule: risk veto overrides everything, enforced even if the LLM ignored it
    if risk_output and risk_output.veto and final_verdict != "NO TRADE":
        original = final_verdict
        final_verdict = "NO TRADE"
        notes.append(
            f"RISK VETO: {risk_output.veto_reason or 'position exceeds capital limits'}. "
            f"[Original verdict: {original}]"
        )

    mind_changers = cs_output.get("mind_changers", [])
    if not mind_changers or len(mind_changers) < 3:
        mind_changers = _default_mind_changers(overall_direction)

    top_reasons = cs_output.get("top_reasons", [])
    if not top_reasons:
        for out in phase_2_outputs:
            if out.points:
                top_reasons.append(f"[{out.perspective}] {out.points[0]}")
            if len(top_reasons) >= 6:
                break

    # Sector specialist and event watcher are supplementary — fold into notes, not perspectives
    for out in phase_2_outputs:
        if out.perspective in ("sector", "events") and out.points:
            for pt in out.points[:2]:
                notes.append(f"[{out.perspective}] {pt}")

    confluence_score = cs_output.get("confluence_score", 0)

    return ConfluenceResult(
        ticker=data_bundle.ticker_meta.resolved,
        overall_direction=overall_direction,
        confluence_score=confluence_score,
        confluence_level=confluence_level,
        final_verdict=final_verdict,
        timeframe_signals=tf_signals,
        best_entry=best_entry,
        best_stop=best_stop,
        best_target_1=best_t1,
        best_target_2=best_t2,
        position_size=pos_size,
        position_value=pos_value,
        risk_amount=risk_amount,
        top_reasons=top_reasons,
        notes=notes,
        perspectives=perspectives,
        bull_case=cs_output.get("bull_case", ""),
        bear_case=cs_output.get("bear_case", ""),
        winning_case=cs_output.get("winning_case", ""),
        mind_changers=mind_changers,
        overall_confidence=overall_confidence,
    )


def _fallback_confluence(data_bundle: DataBundle) -> ConfluenceResult:
    """Fall back to the existing Python-only confluence pipeline."""
    from confluence import compute_confluence

    signals = {}
    for tf_name, tf_data in data_bundle.timeframes.items():
        signals[tf_name] = tf_data.signal if tf_data else None

    return compute_confluence(
        data_bundle.ticker_meta.resolved,
        signals,
        data_bundle.fundamentals,
        data_bundle.sentiment,
    )


def _default_mind_changers(direction: str) -> list[str]:
    if direction == "BULLISH":
        return [
            "Price closes below the daily EMA50 — medium-term trend structure breaks.",
            "RSI drops back below 40 on the daily — bullish momentum confirmed lost.",
            "Broader market index breaks key support, removing the macro tailwind.",
        ]
    elif direction == "BEARISH":
        return [
            "Price closes above daily EMA20 with above-average volume — bearish structure invalidated.",
            "RSI recovers above 55 — bearish momentum fading, potential trend reversal.",
            "Strong earnings surprise or major positive catalyst reverses the fundamental picture.",
        ]
    return [
        "A confirmed close above daily EMA20 with expanding volume would flip to bullish.",
        "A break below daily EMA50 with bearish MACD crossover would flip to bearish.",
        "Sustained above-average volume in either direction would resolve the indecision.",
    ]
