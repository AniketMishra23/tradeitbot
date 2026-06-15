"""Multi-timeframe confluence engine implementing the CLAUDE.md six-perspective analytical framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from signal_engine import TimeframeSignal
from config import RISK, TIMEFRAMES

try:
    from sentiment import SentimentResult   # type: ignore[assignment]
except ImportError:
    SentimentResult = None  # type: ignore[assignment,misc]


# Weekly and daily carry more weight than intraday for positional trades.
TF_WEIGHT = {
    "weekly": 3,
    "daily":  2,
    "1hour":  1,
    "15min":  1,
}


@dataclass
class Perspective:
    signal:     str          # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence: str          # "HIGH" | "MEDIUM" | "LOW"
    points:     list[str] = field(default_factory=list)


@dataclass
class ConfluenceResult:
    ticker:             str
    overall_direction:  str          # "BULLISH" | "BEARISH" | "NEUTRAL"
    confluence_score:   int          # raw count of agreeing timeframes
    confluence_level:   str          # "STRONG" | "MODERATE" | "WEAK" | "CONFLICTED"
    final_verdict:      str          # "BUY" | "SELL" | "HOLD" | "NO TRADE"
    timeframe_signals:  dict         # {tf_name: TimeframeSignal}
    best_entry:         float | None = None
    best_stop:          float | None = None
    best_target_1:      float | None = None
    best_target_2:      float | None = None
    position_size:      int | None   = None
    position_value:     float | None = None
    risk_amount:        float | None = None
    top_reasons:        list[str] = field(default_factory=list)
    notes:              list[str] = field(default_factory=list)
    perspectives:       dict = field(default_factory=dict)   # {name: Perspective}
    bull_case:          str  = ""
    bear_case:          str  = ""
    winning_case:       str  = ""
    mind_changers:      list[str] = field(default_factory=list)
    overall_confidence: str  = "LOW"


def _assess_perspectives(
    timeframe_signals:  dict,
    overall_direction:  str,
    confluence_level:   str,
    final_verdict:      str,
    best_entry:         float | None,
    best_stop:          float | None,
    best_target_1:      float | None,
    position_value:     float | None,
    risk_amount:        float | None,
    notes:              list[str],
    fundamentals:       dict,
    news_sentiment:     Optional[SentimentResult] = None,
) -> dict:
    """
    Evaluate all six CLAUDE.md perspectives and return assessment results.

    Only uses data actually retrieved — never invents prices or ratios. Where
    data is missing, marks confidence LOW and says so explicitly.

    Returns a dict with keys: "technical", "fundamental", "macro", "sentiment",
    "quantitative", "risk" (each a Perspective), plus "bull_case", "bear_case",
    "winning_case", "mind_changers", and "overall_confidence".
    """
    f   = fundamentals or {}
    # Daily signal carries the richest single-timeframe indicator snapshot.
    daily_sig  = timeframe_signals.get("daily")
    weekly_sig = timeframe_signals.get("weekly")
    v          = (daily_sig.raw  if daily_sig  else {}) or {}

    # --- 1. TECHNICAL ---
    tech_points = []
    bull_t = bear_t = 0

    close = v.get("close")
    e20   = v.get("ema20")
    e50   = v.get("ema50")
    e200  = v.get("ema200")

    if close and e20 and e50 and e200:
        if close > e20 > e50 > e200:
            bull_t += 2
            tech_points.append("Full EMA stack aligned bullish (Price > EMA20 > EMA50 > EMA200)")
        elif close < e20 < e50 < e200:
            bear_t += 2
            tech_points.append("Full EMA stack aligned bearish (Price < EMA20 < EMA50 < EMA200)")
        elif close > e20 > e50:
            bull_t += 1
            tech_points.append("Price above EMA20 and EMA50 — short/medium trend bullish")
        elif close < e20 < e50:
            bear_t += 1
            tech_points.append("Price below EMA20 and EMA50 — short/medium trend bearish")
        else:
            tech_points.append("EMA stack mixed — no clean trend alignment")

    rsi = v.get("rsi")
    if rsi:
        if rsi > 70:
            bear_t += 1
            tech_points.append(f"RSI {rsi:.1f} — overbought, momentum stretched")
        elif rsi < 30:
            bull_t += 1
            tech_points.append(f"RSI {rsi:.1f} — oversold, potential mean reversion")
        elif rsi >= 55:
            bull_t += 1
            tech_points.append(f"RSI {rsi:.1f} — bullish momentum zone")
        elif rsi <= 45:
            bear_t += 1
            tech_points.append(f"RSI {rsi:.1f} — bearish momentum zone")
        else:
            tech_points.append(f"RSI {rsi:.1f} — neutral zone (45–55)")

    macd_h = v.get("macd_hist")
    prev_h = v.get("prev_macd_hist")
    if macd_h is not None and prev_h is not None:
        if macd_h > 0 and macd_h > prev_h:
            bull_t += 1
            tech_points.append("MACD histogram positive and rising — momentum accelerating")
        elif macd_h < 0 and macd_h < prev_h:
            bear_t += 1
            tech_points.append("MACD histogram negative and falling — momentum deteriorating")
        elif prev_h < 0 < macd_h:
            bull_t += 1
            tech_points.append("MACD bullish crossover — histogram flipped positive")
        elif prev_h > 0 > macd_h:
            bear_t += 1
            tech_points.append("MACD bearish crossover — histogram flipped negative")

    agreeing = sum(1 for s in timeframe_signals.values()
                   if s and s.direction == overall_direction)
    total_valid = sum(1 for s in timeframe_signals.values() if s)
    tech_points.append(
        f"{agreeing}/{total_valid} timeframes aligned {overall_direction} "
        f"(confluence: {confluence_level})"
    )

    tech_signal = overall_direction
    tech_conf   = {"STRONG": "HIGH", "MODERATE": "MEDIUM",
                   "WEAK": "LOW", "CONFLICTED": "LOW"}.get(confluence_level, "LOW")

    tech = Perspective(signal=tech_signal, confidence=tech_conf, points=tech_points)

    # --- 2. FUNDAMENTAL ---
    # Only uses what yfinance actually returned; missing fields are stated explicitly.
    fund_points = []
    bull_f = bear_f = 0
    fund_data_count = 0

    pe = f.get("pe_trailing")
    if pe and pe > 0:
        fund_data_count += 1
        if pe < 20:
            bull_f += 1
            fund_points.append(f"P/E {pe:.1f}x — reasonable valuation (below 20x)")
        elif pe > 40:
            bear_f += 1
            fund_points.append(f"P/E {pe:.1f}x — premium valuation (above 40x)")
        else:
            fund_points.append(f"P/E {pe:.1f}x — fair value range (20–40x)")
    else:
        fund_points.append("P/E: not available from Yahoo Finance for this ticker")

    roe = f.get("roe")
    if roe is not None:
        fund_data_count += 1
        roe_pct = roe * 100
        if roe_pct > 15:
            bull_f += 1
            fund_points.append(f"ROE {roe_pct:.1f}% — strong capital efficiency (above 15%)")
        elif roe_pct < 8:
            bear_f += 1
            fund_points.append(f"ROE {roe_pct:.1f}% — weak returns on equity (below 8%)")
        else:
            fund_points.append(f"ROE {roe_pct:.1f}% — acceptable (8–15%)")
    else:
        fund_points.append("ROE: not available")

    de = f.get("debt_to_equity")
    if de is not None:
        fund_data_count += 1
        # yfinance returns D/E as a percentage in some cases (e.g. 50 means 0.5x)
        if de < 50:
            bull_f += 1
            fund_points.append(f"D/E {de/100:.2f}x — low leverage (healthy balance sheet)")
        elif de > 150:
            bear_f += 1
            fund_points.append(f"D/E {de/100:.2f}x — high leverage (elevated financial risk)")
        else:
            fund_points.append(f"D/E {de/100:.2f}x — moderate leverage")
    else:
        fund_points.append("D/E: not available")

    eg = f.get("earnings_growth")
    if eg is not None:
        fund_data_count += 1
        eg_pct = eg * 100
        if eg_pct > 15:
            bull_f += 1
            fund_points.append(f"Earnings growth {eg_pct:.1f}% YoY — strong momentum")
        elif eg_pct < 0:
            bear_f += 1
            fund_points.append(f"Earnings growth {eg_pct:.1f}% YoY — declining earnings")
        else:
            fund_points.append(f"Earnings growth {eg_pct:.1f}% YoY — modest growth")
    else:
        fund_points.append("Earnings growth: not available")

    sector = f.get("sector") or f.get("industry")
    if sector:
        fund_points.append(f"Sector: {sector}")

    if fund_data_count == 0:
        fund_points = [
            "I do not have fundamental data for this ticker from Yahoo Finance.",
            "Verify P/E, ROE, D/E, earnings on Screener.in or Equitymaster before trading.",
        ]
        fund_signal = "NEUTRAL"
        fund_conf   = "LOW"
    else:
        fund_signal = ("BULLISH" if bull_f > bear_f
                       else "BEARISH" if bear_f > bull_f else "NEUTRAL")
        fund_conf   = ("HIGH" if abs(bull_f - bear_f) >= 2 and fund_data_count >= 3
                       else "MEDIUM" if abs(bull_f - bear_f) >= 1 else "LOW")

    fund = Perspective(signal=fund_signal, confidence=fund_conf, points=fund_points)

    # --- 3. MACRO ---
    # No live macro feed is connected; state this explicitly per CLAUDE.md data discipline.
    macro = Perspective(
        signal="NEUTRAL",
        confidence="LOW",
        points=[
            "I do not have live macro data (no feed connected).",
            "Verify before trading: RBI/Fed policy direction, Nifty 50 trend, "
            "sector rotation signals, global risk sentiment (DXY, VIX).",
        ],
    )

    # --- 4. SENTIMENT & NEWS ---
    sent_points = []
    bull_s = bear_s = 0

    if news_sentiment is not None and news_sentiment.article_count > 0:
        ns = news_sentiment
        mood_map = {"POSITIVE": "Mostly positive 🟢", "NEGATIVE": "Mostly negative 🔴", "NEUTRAL": "Mixed / neutral 🟡"}
        mood = mood_map.get(ns.signal, ns.signal)
        sent_points.append(
            f"News mood: {mood} ({ns.article_count} articles)"
        )
        pos_n     = sum(1 for h in ns.headlines if h.label == "POSITIVE")
        neg_n     = sum(1 for h in ns.headlines if h.label == "NEGATIVE")
        neutral_n = sum(1 for h in ns.headlines if h.label == "NEUTRAL")
        sent_points.append(
            f"  {pos_n} good news  /  {neg_n} bad news  /  {neutral_n} neutral"
        )

        # Show top 3 most impactful headlines sorted by model confidence.
        sorted_hl = sorted(ns.headlines, key=lambda h: h.confidence, reverse=True)
        for h in sorted_hl[:3]:
            icon = "📈" if h.label == "POSITIVE" else ("📉" if h.label == "NEGATIVE" else "➡️")
            date_str = f"  ({h.published})" if h.published else ""
            sent_points.append(
                f"  {icon} {h.title[:75]}"
                f"  — {h.publisher}{date_str}"
            )

        if ns.signal == "POSITIVE":
            bull_s += 2 if ns.confidence == "HIGH" else 1
        elif ns.signal == "NEGATIVE":
            bear_s += 2 if ns.confidence == "HIGH" else 1
    elif news_sentiment is not None and news_sentiment.error:
        sent_points.append(
            f"News sentiment: {news_sentiment.error}"
        )
    else:
        sent_points.append(
            "I do not have news sentiment data. "
            "Call fetch_news_sentiment(ticker) and pass result to compute_confluence()."
        )

    if rsi:
        if rsi > 70:
            bear_s += 1
            sent_points.append(f"Momentum (RSI {rsi:.0f}) — stock looks overbought, may pull back")
        elif rsi < 30:
            bull_s += 1
            sent_points.append(f"Momentum (RSI {rsi:.0f}) — stock looks oversold, may bounce")
        else:
            sent_points.append(f"Momentum (RSI {rsi:.0f}) — in a normal range, no extreme reading")

    vol_ratio = v.get("vol_ratio")
    if vol_ratio:
        if vol_ratio >= 1.5:
            sent_points.append(
                f"Trading volume — {vol_ratio:.1f}x higher than usual, strong interest"
            )
            if overall_direction == "BULLISH":
                bull_s += 1
            elif overall_direction == "BEARISH":
                bear_s += 1
        else:
            sent_points.append(
                f"Trading volume — quiet ({vol_ratio:.1f}x average), not many people trading it right now"
            )

    # 52W positioning used as a fear/greed proxy.
    w52h = f.get("week52_high")
    w52l = f.get("week52_low")
    if close and w52h and w52l and w52h > w52l:
        pct_from_low = (close - w52l) / (w52h - w52l)
        if pct_from_low < 0.25:
            bull_s += 1
            sent_points.append(
                f"Price at {pct_from_low:.0%} of 52W range — near lows, contrarian opportunity"
            )
        elif pct_from_low > 0.75:
            bear_s += 1
            sent_points.append(
                f"Price at {pct_from_low:.0%} of 52W range — near highs, momentum extended"
            )
        else:
            sent_points.append(
                f"Price at {pct_from_low:.0%} of 52W range — mid-range, balanced sentiment"
            )
    else:
        sent_points.append("52W range: not available — cannot assess 52W positioning")

    sent_signal = ("BULLISH" if bull_s > bear_s
                   else "BEARISH" if bear_s > bull_s else "NEUTRAL")

    # Inherit model confidence when we have enough FinBERT/VADER articles.
    if news_sentiment is not None and news_sentiment.article_count >= 5:
        sent_conf = news_sentiment.confidence
    elif rsi or vol_ratio:
        sent_conf = "MEDIUM"
    else:
        sent_conf = "LOW"

    sentiment = Perspective(signal=sent_signal, confidence=sent_conf, points=sent_points)

    # --- 5. QUANTITATIVE ---
    quant_points = []
    bull_q = bear_q = 0

    bb_pct = v.get("bb_pct")
    if bb_pct is not None:
        if bb_pct < 0.20:
            bull_q += 1
            quant_points.append(
                f"BB%B {bb_pct:.2f} — price at lower band, statistically oversold, "
                f"mean-reversion edge"
            )
        elif bb_pct > 0.80:
            bear_q += 1
            quant_points.append(
                f"BB%B {bb_pct:.2f} — price at upper band, statistically extended, "
                f"reversion risk"
            )
        else:
            quant_points.append(f"BB%B {bb_pct:.2f} — within normal range, no mean-reversion edge")

    atr = v.get("atr")
    if atr and close:
        atr_pct = (atr / close) * 100
        regime = ("high" if atr_pct > 3 else "moderate" if atr_pct > 1.5 else "low")
        quant_points.append(
            f"ATR {atr:.2f} ({atr_pct:.1f}% of price) — {regime} volatility regime"
        )

    tf_directions = [s.direction for s in timeframe_signals.values() if s]
    bull_tfs = tf_directions.count("BULLISH")
    bear_tfs = tf_directions.count("BEARISH")
    quant_points.append(
        f"Timeframe alignment: {bull_tfs} bullish / {bear_tfs} bearish "
        f"out of {len(tf_directions)} valid timeframes"
    )
    if max(bull_tfs, bear_tfs) >= 3:
        if bull_tfs > bear_tfs:
            bull_q += 1
        else:
            bear_q += 1

    quant_signal = ("BULLISH" if bull_q > bear_q
                    else "BEARISH" if bear_q > bull_q else "NEUTRAL")
    quant_conf   = "MEDIUM" if bb_pct is not None or atr else "LOW"

    quantitative = Perspective(signal=quant_signal, confidence=quant_conf, points=quant_points)

    # --- 6. RISK MANAGEMENT ---
    # This perspective can veto all others per CLAUDE.md.
    risk_points = []
    bull_r = bear_r = 0

    if best_entry and best_stop and best_target_1:
        raw_risk = abs(best_entry - best_stop)
        raw_reward = abs(best_target_1 - best_entry)
        rr = raw_reward / raw_risk if raw_risk > 0 else 0
        rr_ok = rr >= 2.0
        risk_points.append(
            f"R:R = {rr:.1f}:1 — "
            f"{'acceptable (meets 2:1 minimum)' if rr_ok else 'below ideal 2:1 minimum'}"
        )
        if rr_ok:
            bull_r += 1
        else:
            bear_r += 1

    if position_value and risk_amount:
        cap = RISK["capital"]
        pos_pct  = (position_value / cap) * 100
        risk_pct = (risk_amount / cap) * 100
        risk_points.append(
            f"Position = {pos_pct:.1f}% of capital | "
            f"Capital at risk = {risk_pct:.2f}% (rule: {RISK['risk_pct_per_trade']*100:.1f}%)"
        )
        if pos_pct <= 25:
            bull_r += 1
        else:
            bear_r += 2   # oversized position; veto message is already in notes

    if atr and best_entry:
        atr_sl_dist = abs(best_entry - best_stop) if best_stop else 0
        risk_points.append(
            f"Stop = {RISK['atr_sl_multiplier']}x ATR below/above entry "
            f"({atr_sl_dist:.2f} pts — gives price room to breathe)"
        )

    veto_active = any("RISK VETO" in n for n in notes)
    if veto_active:
        bear_r += 2
        risk_points.append("RISK VETO ACTIVE — position too large relative to capital.")

    if not best_entry:
        risk_points.append("Cannot compute risk levels — no entry price available.")
        risk_signal = "NEUTRAL"
        risk_conf   = "LOW"
    else:
        risk_signal = "BULLISH" if bull_r > bear_r else ("BEARISH" if bear_r > bull_r else "NEUTRAL")
        risk_conf   = "HIGH"

    risk = Perspective(signal=risk_signal, confidence=risk_conf, points=risk_points)

    # --- ADVERSARIAL STEP ---
    all_persp = {
        "technical":    tech,
        "fundamental":  fund,
        "macro":        macro,
        "sentiment":    sentiment,
        "quantitative": quantitative,
        "risk":         risk,
    }

    bull_evidence = []
    bear_evidence = []
    for name, p in all_persp.items():
        if p.signal == "BULLISH" and p.confidence in ("HIGH", "MEDIUM"):
            bull_evidence.append(f"{name.title()}: {p.points[0]}" if p.points else name.title())
        elif p.signal == "BEARISH" and p.confidence in ("HIGH", "MEDIUM"):
            bear_evidence.append(f"{name.title()}: {p.points[0]}" if p.points else name.title())

    bull_case = (
        "Strong bull evidence: " + "; ".join(bull_evidence[:3]) + "."
        if bull_evidence
        else "No strong bullish evidence with medium/high confidence."
    )
    bear_case = (
        "Key bear risks: " + "; ".join(bear_evidence[:3]) + "."
        if bear_evidence
        else "No strong bearish evidence with medium/high confidence."
    )

    # Weighted score: HIGH confidence counts double.
    bull_score = sum(
        2 if p.confidence == "HIGH" else 1
        for p in all_persp.values() if p.signal == "BULLISH"
    )
    bear_score = sum(
        2 if p.confidence == "HIGH" else 1
        for p in all_persp.values() if p.signal == "BEARISH"
    )

    if veto_active:
        winning_case = "BEAR case wins — RISK VETO overrides all other signals."
    elif bull_score > bear_score:
        winning_case = (
            f"BULL case wins — supported by {bull_score} weighted points vs "
            f"{bear_score} for bears. Weight of evidence favours the long."
        )
    elif bear_score > bull_score:
        winning_case = (
            f"BEAR case wins — supported by {bear_score} weighted points vs "
            f"{bull_score} for bulls. Weight of evidence favours caution."
        )
    else:
        winning_case = (
            "Cases are evenly balanced — no clear edge. "
            "Consider waiting for a higher-conviction setup."
        )

    # Top 3 things that would change the current directional view.
    if overall_direction == "BULLISH":
        mind_changers = [
            "Price closes below the daily EMA50 — medium-term trend structure breaks.",
            "RSI drops back below 40 on the daily — bullish momentum confirmed lost.",
            "Broader market (Nifty 50 / S&P 500) breaks key support, removing macro tailwind.",
        ]
    elif overall_direction == "BEARISH":
        mind_changers = [
            "Price closes above daily EMA20 with above-average volume — bearish structure invalidated.",
            "RSI recovers above 55 — bearish momentum fading, potential trend reversal.",
            "Strong earnings surprise or major positive catalyst reverses fundamental picture.",
        ]
    else:
        mind_changers = [
            "A confirmed close above daily EMA20 with expanding volume would flip to bullish.",
            "A break below daily EMA50 with bearish MACD crossover would flip to bearish.",
            "Sustained above-average volume in either direction would resolve the indecision.",
        ]

    high_count   = sum(1 for p in all_persp.values() if p.confidence == "HIGH")
    medium_count = sum(1 for p in all_persp.values() if p.confidence == "MEDIUM")

    if high_count >= 3:
        overall_confidence = "HIGH"
    elif high_count >= 1 or medium_count >= 3:
        overall_confidence = "MEDIUM"
    else:
        overall_confidence = "LOW"

    return {
        "technical":    tech,
        "fundamental":  fund,
        "macro":        macro,
        "sentiment":    sentiment,
        "quantitative": quantitative,
        "risk":         risk,
        "bull_case":    bull_case,
        "bear_case":    bear_case,
        "winning_case": winning_case,
        "mind_changers": mind_changers,
        "overall_confidence": overall_confidence,
    }


def compute_confluence(
    ticker:          str,
    signals:         dict[str, TimeframeSignal],
    fundamentals:    dict | None = None,
    news_sentiment:  "Optional[SentimentResult]" = None,
) -> ConfluenceResult:
    """
    Aggregate per-timeframe signals into a final trade verdict, then run the
    six CLAUDE.md perspectives and adversarial bull/bear step.

    Parameters
    ----------
    ticker         : Yahoo Finance ticker symbol (display only)
    signals        : {timeframe_name: TimeframeSignal | None} from signal_engine
    fundamentals   : dict from data_fetcher.fetch_fundamentals(), or None
    news_sentiment : SentimentResult from sentiment.fetch_news_sentiment(), or None.
                     When provided, wired into perspective #4 with full headline detail.
    """
    fundamentals = fundamentals or {}
    notes        = []
    top_reasons  = []

    # --- 1. Weighted directional vote ---
    bull_weight = bear_weight = neutral_weight = 0
    for tf_name, sig in signals.items():
        w = TF_WEIGHT.get(tf_name, 1)
        if sig is None or sig.direction == "NEUTRAL":
            neutral_weight += w
        elif sig.direction == "BULLISH":
            bull_weight += w
        elif sig.direction == "BEARISH":
            bear_weight += w

    total_weight = bull_weight + bear_weight + neutral_weight

    if bull_weight > bear_weight:
        overall_direction = "BULLISH"
        dominant_weight   = bull_weight
    elif bear_weight > bull_weight:
        overall_direction = "BEARISH"
        dominant_weight   = bear_weight
    else:
        overall_direction = "NEUTRAL"
        dominant_weight   = neutral_weight

    # --- 2. Confluence score (unweighted count) ---
    agreeing      = sum(1 for s in signals.values()
                        if s is not None and s.direction == overall_direction)
    total_valid   = sum(1 for s in signals.values() if s is not None)
    confluence_score = agreeing

    # --- 3. Confluence level ---
    min_conf = RISK["confluence_min"]
    ratio    = dominant_weight / max(total_weight, 1)

    if agreeing >= min_conf and ratio >= 0.70:
        confluence_level = "STRONG"
    elif agreeing >= 2 and ratio >= 0.55:
        confluence_level = "MODERATE"
    elif agreeing >= 1 and overall_direction != "NEUTRAL":
        confluence_level = "WEAK"
    else:
        confluence_level = "CONFLICTED"

    # --- 4. Anchor signal for trade levels ---
    # Daily preferred; fall back to intraday. Weekly is deprioritised because its
    # levels are too wide for practical stop placement on most trade sizes.
    level_priority = ["daily", "1hour", "15min", "weekly"]
    anchor_signal  = None
    for tf in level_priority:
        s = signals.get(tf)
        if s and s.direction == overall_direction and s.stop_loss is not None:
            anchor_signal = s
            break

    best_entry = anchor_signal.entry_high if anchor_signal else None
    best_stop  = anchor_signal.stop_loss  if anchor_signal else None
    best_t1    = anchor_signal.target_1   if anchor_signal else None
    best_t2    = anchor_signal.target_2   if anchor_signal else None

    # --- 5. Position sizing ---
    position_size = position_value = risk_amount = None
    if best_entry and best_stop:
        risk_per_share = abs(best_entry - best_stop)
        if risk_per_share > 0:
            capital        = RISK["capital"]
            risk_pct       = RISK["risk_pct_per_trade"]
            max_risk_rs    = capital * risk_pct
            position_size  = max(1, int(max_risk_rs / risk_per_share))
            position_value = round(position_size * best_entry, 2)
            risk_amount    = round(position_size * risk_per_share, 2)

    # --- 6. Final verdict ---
    if confluence_level == "CONFLICTED":
        final_verdict = "NO TRADE"
        notes.append("Timeframes are conflicted — no edge, no trade.")
    elif confluence_level == "WEAK" and overall_direction == "NEUTRAL":
        final_verdict = "HOLD"
        notes.append("Weak neutral signal — hold existing, no new entry.")
    elif overall_direction == "BULLISH":
        final_verdict = "BUY" if confluence_level in ("STRONG", "MODERATE") else "HOLD"
        if final_verdict == "HOLD":
            notes.append("Bullish but only 1 timeframe confirms — wait for more alignment.")
    elif overall_direction == "BEARISH":
        final_verdict = "SELL" if confluence_level in ("STRONG", "MODERATE") else "HOLD"
        if final_verdict == "HOLD":
            notes.append("Bearish but only 1 timeframe confirms — no short yet.")
    else:
        final_verdict = "HOLD"

    # --- 7. Top reasoning ---
    for tf_name in ["daily", "weekly", "1hour", "15min"]:
        sig = signals.get(tf_name)
        if sig and sig.reasoning:
            for r in sig.reasoning:
                if "[Score:" not in r:
                    top_reasons.append(f"[{tf_name}] {r}")
                if len(top_reasons) >= 6:
                    break
        if len(top_reasons) >= 6:
            break

    # --- 8. Risk veto ---
    # CLAUDE.md: risk perspective overrides positive signals when position exceeds 25% of capital.
    if position_value and position_value > RISK["capital"] * 0.25:
        original = final_verdict
        final_verdict = "NO TRADE"
        notes.append(
            f"RISK VETO: position ₹{position_value:,.0f} exceeds 25% of capital. "
            f"Increase capital or reduce risk_pct in config.py. [Original: {original}]"
        )

    # --- 9. Six-perspective assessment ---
    persp_data = _assess_perspectives(
        timeframe_signals  = signals,
        overall_direction  = overall_direction,
        confluence_level   = confluence_level,
        final_verdict      = final_verdict,
        best_entry         = best_entry,
        best_stop          = best_stop,
        best_target_1      = best_t1,
        position_value     = position_value,
        risk_amount        = risk_amount,
        notes              = notes,
        fundamentals       = fundamentals,
        news_sentiment     = news_sentiment,
    )

    perspectives = {k: v for k, v in persp_data.items()
                    if isinstance(v, Perspective)}

    return ConfluenceResult(
        ticker             = ticker,
        overall_direction  = overall_direction,
        confluence_score   = confluence_score,
        confluence_level   = confluence_level,
        final_verdict      = final_verdict,
        timeframe_signals  = signals,
        best_entry         = best_entry,
        best_stop          = best_stop,
        best_target_1      = best_t1,
        best_target_2      = best_t2,
        position_size      = position_size,
        position_value     = position_value,
        risk_amount        = risk_amount,
        top_reasons        = top_reasons,
        notes              = notes,
        perspectives       = perspectives,
        bull_case          = persp_data["bull_case"],
        bear_case          = persp_data["bear_case"],
        winning_case       = persp_data["winning_case"],
        mind_changers      = persp_data["mind_changers"],
        overall_confidence = persp_data["overall_confidence"],
    )
