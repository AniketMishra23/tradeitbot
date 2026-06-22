"""Data Scout agent — centralised data collection for all other agents."""

from __future__ import annotations

from agents.schema import DataBundle, TickerMeta, TimeframeData
from data_fetcher import fetch_all_timeframes, fetch_fundamentals, clear_cache
from indicators import compute_all, latest_values
from signal_engine import generate_signal
from ticker_utils import resolve_ticker, ticker_currency, market_label

try:
    from sentiment import fetch_news_sentiment
    _SENTIMENT_OK = True
except ImportError:
    _SENTIMENT_OK = False

AGENT_META = {
    "name":        "data_scout",
    "perspective": "data",
    "phase":       1,
}


def run(ticker_raw: str, include_sentiment: bool = True) -> DataBundle | None:
    """
    Fetch OHLCV, fundamentals, and news for a ticker.

    Returns DataBundle on success, None if ticker has no data on any timeframe.
    """
    resolved = resolve_ticker(ticker_raw)

    raw_data     = fetch_all_timeframes(resolved)
    fetch_errors: list[str] = []

    if all(df is None for df in raw_data.values()):
        clear_cache()
        return None

    timeframes: dict[str, TimeframeData | None] = {}
    for tf_name, df in raw_data.items():
        if df is None:
            timeframes[tf_name] = None
            continue
        enriched = compute_all(df)
        vals     = latest_values(enriched)
        sig      = generate_signal(tf_name, vals)
        timeframes[tf_name] = TimeframeData(
            name=tf_name,
            ohlcv=df,
            indicators=enriched,
            latest=vals,
            signal=sig,
        )

    fundamentals = fetch_fundamentals(resolved)

    sentiment = None
    if include_sentiment and _SENTIMENT_OK:
        try:
            sentiment = fetch_news_sentiment(resolved)
        except Exception as e:
            fetch_errors.append(f"Sentiment fetch failed: {e}")

    current_price = None
    daily = timeframes.get("daily")
    if daily:
        current_price = daily.latest.get("close")
    if current_price is None:
        for tf_data in timeframes.values():
            if tf_data:
                current_price = tf_data.latest.get("close")
                break

    meta = TickerMeta(
        raw_input=ticker_raw,
        resolved=resolved,
        currency=ticker_currency(resolved),
        market=market_label(resolved),
    )

    clear_cache()

    return DataBundle(
        ticker_meta=meta,
        timeframes=timeframes,
        fundamentals=fundamentals,
        sentiment=sentiment,
        current_price=current_price,
        fetch_errors=fetch_errors,
    )
