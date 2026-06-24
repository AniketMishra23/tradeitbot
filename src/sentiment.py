"""News sentiment engine: FinBERT -> VADER -> keyword fallback chain, aggregated into SentimentResult."""

from __future__ import annotations

import time
import datetime
from dataclasses import dataclass, field
from typing import Optional

import yfinance as yf

# Lazy-loaded backends — imported only when first needed to avoid hard dependencies
_finbert_pipeline = None
_vader_analyzer   = None


@dataclass
class ScoredHeadline:
    """A single news headline with its sentiment score."""
    title:       str
    publisher:   str
    published:   str     # human-readable datetime string (e.g. "2026-06-14 09:30")
    raw_score:   float   # [-1.0, +1.0] — negative = negative sentiment, positive = positive
    label:       str     # "POSITIVE" | "NEGATIVE" | "NEUTRAL"
    confidence:  float   # model probability for the winning label [0.0 .. 1.0]
    backend:     str     # "finbert" | "vader" | "keyword"


@dataclass
class SentimentResult:
    """Aggregated sentiment across all scored headlines for one ticker."""
    ticker:        str
    signal:        str           # "POSITIVE" | "NEGATIVE" | "NEUTRAL"
    confidence:    str           # "HIGH" | "MEDIUM" | "LOW"
    score:         float         # weighted average raw_score across all headlines [-1.0, +1.0]
    article_count: int           # number of articles successfully scored
    headlines:     list[ScoredHeadline] = field(default_factory=list)
    backend:       str = "unknown"
    error:         Optional[str] = None  # populated if news fetch or scoring failed


# Avoids re-fetching news on repeated calls within 30 minutes
_SENTIMENT_CACHE: dict[str, tuple[float, SentimentResult]] = {}
_CACHE_TTL_SECONDS = 1800


def _load_finbert():
    """
    Load the FinBERT classification pipeline on first call and cache it globally.
    Returns the pipeline on success, or None if transformers/torch are not installed.
    """
    global _finbert_pipeline
    if _finbert_pipeline is not None:
        return _finbert_pipeline

    try:
        from transformers import pipeline as hf_pipeline
        print("[sentiment] Loading FinBERT model (first run — may take ~30s)...")
        _finbert_pipeline = hf_pipeline(
            task="text-classification",
            model="ProsusAI/finbert",
            top_k=None,       # return probabilities for all 3 classes, not just the winner
            truncation=True,
            max_length=512,
        )
        print("[sentiment] FinBERT loaded successfully.")
        return _finbert_pipeline
    except Exception as e:
        print(f"[sentiment] FinBERT unavailable: {e}")
        return None


def _score_with_finbert(headlines: list[str]) -> list[tuple[float, str, float]] | None:
    """
    Score a list of headline strings with FinBERT.

    Returns list of (raw_score, label, confidence) tuples, or None on failure.
      raw_score : +1.0 = fully positive, -1.0 = fully negative, 0.0 = neutral
      label     : "POSITIVE" | "NEGATIVE" | "NEUTRAL"
      confidence: probability of the winning class [0.0 .. 1.0]
    """
    pipe = _load_finbert()
    if pipe is None:
        return None

    try:
        results = pipe(headlines, batch_size=8)
        scored = []
        for result in results:
            # Each result is a list of dicts: [{"label": "positive", "score": 0.9}, ...]
            probs = {r["label"].lower(): r["score"] for r in result}
            pos = probs.get("positive", 0.0)
            neg = probs.get("negative", 0.0)
            neu = probs.get("neutral",  0.0)

            raw_score = pos - neg   # maps the 3-class output to a single [-1, +1] axis
            max_prob  = max(pos, neg, neu)

            if pos == max_prob:
                label, confidence = "POSITIVE", pos
            elif neg == max_prob:
                label, confidence = "NEGATIVE", neg
            else:
                label, confidence = "NEUTRAL",  neu

            scored.append((raw_score, label, confidence))
        return scored
    except Exception as e:
        print(f"[sentiment] FinBERT scoring error: {e}")
        return None


def _load_vader():
    """
    Load the VADER SentimentIntensityAnalyzer on first call and cache it globally.
    Returns the analyzer on success, or None if vaderSentiment is not installed.
    """
    global _vader_analyzer
    if _vader_analyzer is not None:
        return _vader_analyzer
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _vader_analyzer = SentimentIntensityAnalyzer()
        print("[sentiment] VADER loaded as fallback sentiment backend.")
        return _vader_analyzer
    except Exception as e:
        print(f"[sentiment] VADER unavailable: {e}")
        return None


def _score_with_vader(headlines: list[str]) -> list[tuple[float, str, float]] | None:
    """
    Score headlines with VADER's compound score.

    Returns list of (raw_score, label, confidence) tuples, or None if VADER unavailable.
    VADER compound score is already in [-1, +1]; threshold ±0.05 separates neutral.
    """
    analyzer = _load_vader()
    if analyzer is None:
        return None

    scored = []
    for text in headlines:
        vs       = analyzer.polarity_scores(text)
        compound = vs["compound"]

        if compound >= 0.05:
            label      = "POSITIVE"
            # Linear rescale so compound=0.05 → confidence=0.525, compound=1.0 → 1.0
            confidence = (compound + 1) / 2
        elif compound <= -0.05:
            label      = "NEGATIVE"
            confidence = (-compound + 1) / 2
        else:
            label      = "NEUTRAL"
            # Near-zero compound → high neutral confidence; shrinks fast toward edges
            confidence = max(0.0, 1 - abs(compound) * 10)

        scored.append((compound, label, min(1.0, confidence)))
    return scored


# Word sets for the zero-dependency keyword fallback
_BULL_WORDS = {
    "surge", "rally", "gain", "rise", "climb", "beat", "record", "profit",
    "growth", "upgrade", "bullish", "strong", "outperform", "buy", "positive",
    "breakout", "high", "jump", "soar", "expand", "dividend", "buyback",
}
_BEAR_WORDS = {
    "fall", "drop", "plunge", "loss", "miss", "decline", "cut", "downgrade",
    "bearish", "weak", "underperform", "sell", "negative", "crash", "low",
    "slump", "layoff", "recall", "lawsuit", "investigate", "fraud", "default",
}


def _score_with_keywords(headlines: list[str]) -> list[tuple[float, str, float]]:
    """
    Ultra-lightweight keyword scorer — used when both FinBERT and VADER are unavailable.
    Counts bull/bear word hits in each headline to assign a directional label.
    Always returns a list (never None) — guaranteed fallback.
    """
    scored = []
    for text in headlines:
        words = set(text.lower().split())
        bull  = len(words & _BULL_WORDS)
        bear  = len(words & _BEAR_WORDS)
        total = bull + bear

        if total == 0:
            scored.append((0.0, "NEUTRAL", 0.5))
        elif bull > bear:
            s = bull / total
            scored.append((s, "POSITIVE", 0.5 + s * 0.3))
        else:
            s = bear / total
            scored.append((-s, "NEGATIVE", 0.5 + s * 0.3))
    return scored


def _fetch_yfinance_news(ticker: str, max_articles: int = 20) -> list[dict]:
    """
    Fetch recent news from Yahoo Finance using yfinance.Ticker.news.

    Returns a list of dicts with keys: title, publisher, published.
    Returns an empty list on any failure — never raises.
    """
    try:
        items = yf.Ticker(ticker).news
        if not items:
            return []

        results = []
        for item in items[:max_articles]:
            # yfinance returns Unix timestamps; convert to human-readable string
            ts  = item.get("providerPublishTime", 0)
            pub = (
                datetime.datetime.fromtimestamp(ts).strftime("%d %b")
                if ts else ""
            )

            # yfinance >= 0.2.x may wrap content inside a nested "content" dict
            content   = item.get("content", {}) or {}
            title     = (content.get("title") or item.get("title") or "").strip()
            publisher = (
                content.get("provider", {}).get("displayName", "")
                or item.get("publisher", "")
            ).strip()

            if title:
                results.append({
                    "title":     title,
                    "publisher": publisher or "Yahoo Finance",
                    "published": pub,
                })
        return results

    except Exception as e:
        print(f"[sentiment] yfinance news fetch error for {ticker}: {e}")
        return []


def fetch_news_sentiment(
    ticker:       str,
    max_articles: int  = 20,
    use_cache:    bool = True,
) -> SentimentResult:
    """
    Fetch recent news headlines for `ticker` and return aggregated sentiment.

    Backend priority (auto-selected, first available wins):
      1. FinBERT  — finance-tuned BERT, highest accuracy
      2. VADER    — fast, decent on news headlines
      3. Keyword  — built-in, always available

    Parameters
    ----------
    ticker       : Yahoo Finance ticker, e.g. "HAL.NS" or "AAPL"
    max_articles : maximum number of headlines to score (default 20)
    use_cache    : return cached result if fetched within the last 30 minutes

    Returns
    -------
    SentimentResult with signal, confidence, score, and per-headline detail.
    On failure (no news found, network error), returns a NEUTRAL / LOW result
    with the error field populated — never raises.
    """
    ticker = ticker.upper()

    if use_cache and ticker in _SENTIMENT_CACHE:
        cached_ts, cached_result = _SENTIMENT_CACHE[ticker]
        if time.time() - cached_ts < _CACHE_TTL_SECONDS:
            print(f"[sentiment] Using cached sentiment for {ticker}")
            return cached_result

    raw_news = _fetch_yfinance_news(ticker, max_articles)
    if not raw_news:
        result = SentimentResult(
            ticker        = ticker,
            signal        = "NEUTRAL",
            confidence    = "LOW",
            score         = 0.0,
            article_count = 0,
            backend       = "none",
            error         = "No news articles found via Yahoo Finance for this ticker.",
        )
        _SENTIMENT_CACHE[ticker] = (time.time(), result)
        return result

    headlines = [item["title"] for item in raw_news]

    # Try backends in priority order; keyword scorer always succeeds
    raw_scores = _score_with_finbert(headlines)
    if raw_scores is not None:
        backend = "finbert"
    else:
        raw_scores = _score_with_vader(headlines)
        if raw_scores is not None:
            backend = "vader"
        else:
            raw_scores = _score_with_keywords(headlines)
            backend    = "keyword"

    scored_headlines = []
    for i, (raw_score, label, conf) in enumerate(raw_scores):
        item = raw_news[i]
        scored_headlines.append(ScoredHeadline(
            title      = item["title"],
            publisher  = item["publisher"],
            published  = item["published"],
            raw_score  = round(raw_score, 4),
            label      = label,
            confidence = round(conf, 4),
            backend    = backend,
        ))

    # Weight each headline by its model confidence so high-certainty scores dominate
    total_weight = sum(h.confidence for h in scored_headlines)
    if total_weight > 0:
        agg_score = sum(h.raw_score * h.confidence for h in scored_headlines) / total_weight
    else:
        agg_score = sum(h.raw_score for h in scored_headlines) / len(scored_headlines)

    agg_score = round(max(-1.0, min(1.0, agg_score)), 4)

    # ±0.15 dead-band avoids flip-flopping on mildly mixed news
    if agg_score >= 0.15:
        signal = "POSITIVE"
    elif agg_score <= -0.15:
        signal = "NEGATIVE"
    else:
        signal = "NEUTRAL"

    # Confidence reflects both label dominance and average model certainty;
    # requires n >= 5 for HIGH to prevent a single strong headline from inflating it
    n             = len(scored_headlines)
    pos_count     = sum(1 for h in scored_headlines if h.label == "POSITIVE")
    neg_count     = sum(1 for h in scored_headlines if h.label == "NEGATIVE")
    neutral_count = sum(1 for h in scored_headlines if h.label == "NEUTRAL")
    dominant      = max(pos_count, neg_count, neutral_count) / n
    avg_conf      = sum(h.confidence for h in scored_headlines) / n

    if dominant >= 0.70 and avg_conf >= 0.70 and n >= 5:
        confidence = "HIGH"
    elif dominant >= 0.55 and n >= 3:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    result = SentimentResult(
        ticker        = ticker,
        signal        = signal,
        confidence    = confidence,
        score         = agg_score,
        article_count = n,
        headlines     = scored_headlines,
        backend       = backend,
    )

    _SENTIMENT_CACHE[ticker] = (time.time(), result)

    print(
        f"[sentiment] {ticker}: {signal} ({confidence}) | "
        f"positive={pos_count} negative={neg_count} neutral={neutral_count} | "
        f"backend={backend} | n={n}"
    )
    return result


def clear_sentiment_cache() -> None:
    """Clear the in-session sentiment cache (called between scan runs)."""
    _SENTIMENT_CACHE.clear()
    print("[sentiment] Cache cleared.")


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"\nSentiment test for {ticker}")
    print("=" * 50)

    result = fetch_news_sentiment(ticker, max_articles=10)

    print(f"\nSignal     : {result.signal}")
    print(f"Confidence : {result.confidence}")
    print(f"Backend    : {result.backend}")
    print(f"Articles   : {result.article_count}")
    if result.error:
        print(f"Error      : {result.error}")

    if result.headlines:
        print("\nHeadlines scored:")
        for h in result.headlines:
            icon = "+" if h.label == "POSITIVE" else ("-" if h.label == "NEGATIVE" else "=")
            print(f"  {icon} [{h.label:<8}] {h.title[:80]}")
