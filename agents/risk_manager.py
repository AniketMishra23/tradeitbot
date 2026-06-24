"""Risk Manager agent — position sizing, stops, targets, risk veto (Python, no LLM)."""

from __future__ import annotations

from agents.schema import AgentOutput, DataBundle
from src.config import RISK

AGENT_META = {
    "name":        "risk_manager",
    "perspective": "risk",
    "phase":       2,
}

# Weekly/daily timeframes carry more weight for positional trade sizing
TF_WEIGHT = {"weekly": 3, "daily": 2, "1hour": 1, "15min": 1}


def run(data: DataBundle) -> AgentOutput:
    """Compute risk assessment with entry/stop/targets and veto check."""
    points: list[str] = []
    bull_r = bear_r = 0

    # Weighted vote across timeframes to determine overall direction
    bull_w = bear_w = neutral_w = 0
    for tf_name, tf_data in data.timeframes.items():
        w = TF_WEIGHT.get(tf_name, 1)
        if tf_data is None or tf_data.signal.direction == "NEUTRAL":
            neutral_w += w
        elif tf_data.signal.direction == "BULLISH":
            bull_w += w
        else:
            bear_w += w

    if bull_w > bear_w:
        overall_direction = "BULLISH"
    elif bear_w > bull_w:
        overall_direction = "BEARISH"
    else:
        overall_direction = "NEUTRAL"

    # Find anchor signal for trade levels
    level_priority = ["daily", "1hour", "15min", "weekly"]
    anchor = None
    for tf in level_priority:
        tf_data = data.timeframes.get(tf)
        if (
            tf_data is not None
            and tf_data.signal.direction == overall_direction
            and tf_data.signal.stop_loss is not None
        ):
            anchor = tf_data.signal
            break

    entry = anchor.entry_high if anchor else None
    stop  = anchor.stop_loss  if anchor else None
    t1    = anchor.target_1   if anchor else None
    t2    = anchor.target_2   if anchor else None

    # Position sizing
    position_size = position_value = risk_amount = rr = None
    if entry and stop:
        risk_per_share = abs(entry - stop)
        if risk_per_share > 0:
            capital      = RISK["capital"]
            max_risk_rs  = capital * RISK["risk_pct_per_trade"]
            position_size  = max(1, int(max_risk_rs / risk_per_share))
            position_value = round(position_size * entry, 2)
            risk_amount    = round(position_size * risk_per_share, 2)

    # R:R evaluation
    if entry and stop and t1:
        raw_risk   = abs(entry - stop)
        raw_reward = abs(t1 - entry)
        rr = round(raw_reward / raw_risk, 2) if raw_risk > 0 else 0
        rr_ok = rr >= 2.0
        points.append(
            f"R:R = {rr:.1f}:1 — "
            f"{'acceptable (meets 2:1 minimum)' if rr_ok else 'below ideal 2:1 minimum'}"
        )
        if rr_ok:
            bull_r += 1
        else:
            bear_r += 1

    # Position as % of capital
    if position_value and risk_amount:
        cap      = RISK["capital"]
        pos_pct  = (position_value / cap) * 100
        risk_pct = (risk_amount / cap) * 100
        points.append(
            f"Position = {pos_pct:.1f}% of capital | "
            f"Capital at risk = {risk_pct:.2f}% (rule: {RISK['risk_pct_per_trade']*100:.1f}%)"
        )
        if pos_pct <= 25:
            bull_r += 1
        else:
            bear_r += 2

    # ATR-based stop description
    atr = None
    daily = data.timeframes.get("daily")
    if daily:
        atr = daily.latest.get("atr")
    if atr and entry and stop:
        atr_sl_dist = abs(entry - stop)
        points.append(
            f"Stop = {RISK['atr_sl_multiplier']}x ATR below/above entry "
            f"({atr_sl_dist:.2f} pts — gives price room to breathe)"
        )

    # Risk veto
    veto = False
    veto_reason = None
    if position_value and position_value > RISK["capital"] * RISK["max_position_pct"]:
        veto = True
        veto_reason = (
            f"RISK VETO: position {data.ticker_meta.currency}{position_value:,.0f} "
            f"exceeds 25% of capital. Increase capital or reduce risk_pct."
        )
        bear_r += 2
        points.append(veto_reason)

    if not entry:
        points.append("Cannot compute risk levels — no entry price available.")

    if bull_r > bear_r:
        signal = "BULLISH"
    elif bear_r > bull_r:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"

    confidence = "HIGH" if entry else "LOW"

    return AgentOutput(
        agent_name="risk_manager",
        perspective="risk",
        signal=signal,
        confidence=confidence,
        points=points,
        key_observation=points[0] if points else "",
        entry=entry,
        stop_loss=stop,
        target_1=t1,
        target_2=t2,
        position_size=position_size,
        position_value=position_value,
        risk_amount=risk_amount,
        risk_reward=rr,
        veto=veto,
        veto_reason=veto_reason,
    )
