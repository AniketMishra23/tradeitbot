"""Quant / Stats Engine — quantitative perspective (Python, no LLM)."""

from __future__ import annotations

from agents.schema import AgentOutput, DataBundle

AGENT_META = {
    "name":        "quant_engine",
    "perspective": "quantitative",
    "phase":       2,
}


def run(data: DataBundle) -> AgentOutput:
    """Compute statistical metrics and return a quantitative perspective."""
    points: list[str] = []
    bull_q = bear_q = 0

    daily = data.timeframes.get("daily")
    v = (daily.latest if daily else None) or {}

    bb_pct = v.get("bb_pct")
    if bb_pct is not None:
        if bb_pct < 0.20:
            bull_q += 1
            points.append(
                f"BB%B {bb_pct:.2f} — price at lower band, statistically oversold, "
                f"mean-reversion edge"
            )
        elif bb_pct > 0.80:
            bear_q += 1
            points.append(
                f"BB%B {bb_pct:.2f} — price at upper band, statistically extended, "
                f"reversion risk"
            )
        else:
            points.append(f"BB%B {bb_pct:.2f} — within normal range, no mean-reversion edge")

    atr   = v.get("atr")
    close = v.get("close")
    if atr is not None and close is not None and close > 0:
        atr_pct = (atr / close) * 100
        regime = "high" if atr_pct > 3 else ("moderate" if atr_pct > 1.5 else "low")
        points.append(
            f"ATR {atr:.2f} ({atr_pct:.1f}% of price) — {regime} volatility regime"
        )

    tf_directions = [
        tf_data.signal.direction
        for tf_data in data.timeframes.values()
        if tf_data is not None
    ]
    bull_tfs = tf_directions.count("BULLISH")
    bear_tfs = tf_directions.count("BEARISH")
    total_tfs = len(tf_directions)
    points.append(
        f"Timeframe alignment: {bull_tfs} bullish / {bear_tfs} bearish "
        f"out of {total_tfs} valid timeframes"
    )
    if max(bull_tfs, bear_tfs, 0) >= 3:
        if bull_tfs > bear_tfs:
            bull_q += 1
        else:
            bear_q += 1

    vol_ratio = v.get("vol_ratio")
    if vol_ratio is not None:
        if vol_ratio >= 2.0:
            points.append(f"Volume z-score proxy: {vol_ratio:.1f}x average — very high participation")
        elif vol_ratio >= 1.5:
            points.append(f"Volume z-score proxy: {vol_ratio:.1f}x average — above-normal activity")
        else:
            points.append(f"Volume z-score proxy: {vol_ratio:.1f}x average — quiet session")

    if bull_q > bear_q:
        signal = "BULLISH"
    elif bear_q > bull_q:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"

    confidence = "MEDIUM" if (bb_pct is not None or atr is not None) else "LOW"

    return AgentOutput(
        agent_name="quant_engine",
        perspective="quantitative",
        signal=signal,
        confidence=confidence,
        points=points,
        key_observation=points[0] if points else "",
    )
