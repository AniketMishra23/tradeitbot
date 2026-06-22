# signal_engine.py — Per-timeframe signal scoring
#
# Takes indicator values from indicators.latest_values() and produces a
# TimeframeSignal with direction, confidence, entry zone, stop, and targets.
#
# Scoring rules (each adds ±1 bull/bear point):
#   1. EMA stack alignment  (full stack = ±2, partial = ±1)
#   2. RSI zone             (oversold/overbought/neutral)
#   3. MACD histogram       (direction + crossovers)
#   4. Bollinger Band %     (near lower/upper band)
#   5. Volume ratio         (amplifies dominant direction if >1.5×)
#
# Confidence thresholds:
#   HIGH   : score ratio ≥ 0.75 and ≥ 4 total signals
#   MEDIUM : score ratio ≥ 0.60
#   LOW    : everything else

from dataclasses import dataclass, field
from .config import RISK


@dataclass
class TimeframeSignal:
    timeframe:   str
    direction:   str              # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence:  str              # "HIGH" | "MEDIUM" | "LOW"
    entry_low:   float | None = None
    entry_high:  float | None = None
    stop_loss:   float | None = None
    target_1:    float | None = None
    target_2:    float | None = None
    risk_reward: float | None = None   # R:R ratio to target_1
    reasoning:   list[str] = field(default_factory=list)
    raw:         dict = field(default_factory=dict)


def _score_indicators(v: dict) -> tuple[int, int, list[str]]:
    """Score indicator values and return (bull_points, bear_points, reasons)."""
    bull, bear, reasons = 0, 0, []

    c, e20, e50, e200 = v.get("close"), v.get("ema20"), v.get("ema50"), v.get("ema200")

    # 1. EMA stack
    if c and e20 and e50 and e200:
        if c > e20 > e50 > e200:
            bull += 2; reasons.append("Price above EMA20 > EMA50 > EMA200 (full bullish stack)")
        elif c < e20 < e50 < e200:
            bear += 2; reasons.append("Price below EMA20 < EMA50 < EMA200 (full bearish stack)")
        elif c > e20 > e50:
            bull += 1; reasons.append("Price above EMA20 > EMA50 (partial bullish trend)")
        elif c < e20 < e50:
            bear += 1; reasons.append("Price below EMA20 < EMA50 (partial bearish trend)")
        else:
            reasons.append("EMA stack mixed — no clear trend bias")
    elif c and e20 and e50:
        if c > e20 > e50:
            bull += 1; reasons.append("Price > EMA20 > EMA50 (EMA200 unavailable)")
        elif c < e20 < e50:
            bear += 1; reasons.append("Price < EMA20 < EMA50 (EMA200 unavailable)")

    # 2. RSI
    rsi = v.get("rsi")
    if rsi is not None:
        lo, hi = RISK["rsi_oversold"], RISK["rsi_overbought"]
        nl, nh = RISK["rsi_neutral_low"], RISK["rsi_neutral_high"]
        if rsi < lo:
            bull += 1; reasons.append(f"RSI {rsi:.1f} oversold (<{lo}) — potential bounce")
        elif rsi > hi:
            bear += 1; reasons.append(f"RSI {rsi:.1f} overbought (>{hi}) — potential pullback")
        elif nl < rsi < nh:
            reasons.append(f"RSI {rsi:.1f} neutral ({nl}–{nh})")
        elif rsi >= nh:
            bull += 1; reasons.append(f"RSI {rsi:.1f} in bullish zone (above neutral)")
        else:
            bear += 1; reasons.append(f"RSI {rsi:.1f} in bearish zone (below neutral)")

    # 3. MACD histogram direction + crossovers
    hist, prev_hist = v.get("macd_hist"), v.get("prev_macd_hist")
    macd, sig       = v.get("macd"), v.get("macd_sig")
    if hist is not None and prev_hist is not None:
        if hist > 0 and hist > prev_hist:
            bull += 1; reasons.append("MACD histogram positive and rising — bullish momentum")
        elif hist < 0 and hist < prev_hist:
            bear += 1; reasons.append("MACD histogram negative and falling — bearish momentum")
        elif hist > 0 and macd and sig and macd > sig:
            reasons.append("MACD above signal but histogram losing steam — watch for fade")
        elif hist < 0 and macd and sig and macd < sig:
            reasons.append("MACD below signal — weak momentum")
    if macd and sig and hist and prev_hist:
        if prev_hist < 0 and hist > 0:
            bull += 1; reasons.append("MACD bullish crossover this bar")
        elif prev_hist > 0 and hist < 0:
            bear += 1; reasons.append("MACD bearish crossover this bar")

    # 4. Bollinger Band position
    bb_pct = v.get("bb_pct")
    if bb_pct is not None:
        if bb_pct < 0.2:
            bull += 1; reasons.append(f"Price near lower Bollinger Band (BB%={bb_pct:.2f}) — mean-reversion setup")
        elif bb_pct > 0.8:
            bear += 1; reasons.append(f"Price near upper Bollinger Band (BB%={bb_pct:.2f}) — extended, reversion risk")

    # 5. Volume confirmation (amplifies dominant direction)
    vol = v.get("vol_ratio")
    if vol is not None:
        if vol >= RISK["volume_spike_ratio"]:
            reasons.append(f"Volume {vol:.1f}× average — strong participation confirms move")
            if bull > bear:   bull += 1
            elif bear > bull: bear += 1
        else:
            reasons.append(f"Volume {vol:.1f}× average — below threshold, lower conviction")

    return bull, bear, reasons


def generate_signal(timeframe: str, v: dict) -> TimeframeSignal:
    """
    Produce a TimeframeSignal from indicator values for one timeframe.

    Parameters
    ----------
    timeframe : timeframe key, e.g. "daily"
    v         : dict from indicators.latest_values()
    """
    if not v:
        return TimeframeSignal(
            timeframe=timeframe, direction="NEUTRAL", confidence="LOW",
            reasoning=["No indicator data available."],
        )

    bull, bear, reasons = _score_indicators(v)
    total = bull + bear

    if bull > bear:
        direction, score_ratio = "BULLISH", bull / max(total, 1)
    elif bear > bull:
        direction, score_ratio = "BEARISH", bear / max(total, 1)
    else:
        direction, score_ratio = "NEUTRAL", 0.5

    if direction == "NEUTRAL" or total < 2:   confidence = "LOW"
    elif score_ratio >= 0.75 and total >= 4:  confidence = "HIGH"
    elif score_ratio >= 0.60:                 confidence = "MEDIUM"
    else:                                     confidence = "LOW"

    close, atr, e20 = v.get("close"), v.get("atr"), v.get("ema20")
    entry_low = entry_high = stop_loss = target_1 = target_2 = rr_actual = None

    if close and atr:
        atr_sl = RISK["atr_sl_multiplier"] * atr

        if direction == "BULLISH":
            entry_high = round(close, 2)
            entry_low  = round(e20, 2) if (e20 and e20 < close) else round(close * 0.995, 2)
            entry_mid  = (entry_low + entry_high) / 2
            stop_loss  = round(entry_mid - atr_sl, 2)
            risk       = entry_mid - stop_loss
            target_1   = round(entry_mid + RISK["rr_target_1"] * risk, 2)
            target_2   = round(entry_mid + RISK["rr_target_2"] * risk, 2)
            rr_actual  = round((target_1 - entry_mid) / max(risk, 0.001), 2)

        elif direction == "BEARISH":
            entry_low  = round(close, 2)
            entry_high = round(e20, 2) if (e20 and e20 > close) else round(close * 1.005, 2)
            entry_mid  = (entry_low + entry_high) / 2
            stop_loss  = round(entry_mid + atr_sl, 2)
            risk       = stop_loss - entry_mid
            target_1   = round(entry_mid - RISK["rr_target_1"] * risk, 2)
            target_2   = round(entry_mid - RISK["rr_target_2"] * risk, 2)
            rr_actual  = round((entry_mid - target_1) / max(risk, 0.001), 2)

    reasons.append(f"[Score: Bull={bull}, Bear={bear}, Total={total}]")

    return TimeframeSignal(
        timeframe=timeframe, direction=direction, confidence=confidence,
        entry_low=entry_low, entry_high=entry_high, stop_loss=stop_loss,
        target_1=target_1, target_2=target_2, risk_reward=rr_actual,
        reasoning=reasons, raw=v,
    )
