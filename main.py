# main.py — CLI entry point for Trade It (terminal / paper-trading mode)
#
# Usage:
#   python main.py                        # scan every ticker in WATCHLIST
#   python main.py HAL.NS                 # single ticker — full detail report
#   python main.py HAL.NS TCS.NS LT.NS   # multiple tickers — summary + BUY/SELL details

import sys
from data_fetcher import fetch_all_timeframes, fetch_fundamentals, clear_cache
from indicators import compute_all, latest_values
from signal_engine import generate_signal
from confluence import compute_confluence
from report import print_report, format_signal_table
from config import WATCHLIST

# Sentiment is optional — bot degrades gracefully if transformers/vaderSentiment not installed
try:
    from sentiment import fetch_news_sentiment, clear_sentiment_cache
    _SENTIMENT_AVAILABLE = True
except ImportError:
    _SENTIMENT_AVAILABLE = False
    print("[main] Sentiment dependencies not found — news scoring disabled.")


def analyse_ticker(ticker: str):
    """Run the full six-perspective pipeline for one ticker. Returns ConfluenceResult or None."""
    print(f"\nFetching data for {ticker}...")
    raw_data = fetch_all_timeframes(ticker)

    signals = {}
    for tf_name, df in raw_data.items():
        if df is None:
            signals[tf_name] = None
            continue
        enriched = compute_all(df)
        vals     = latest_values(enriched)
        signals[tf_name] = generate_signal(tf_name, vals)

    fundamentals   = fetch_fundamentals(ticker)
    news_sentiment = None
    if _SENTIMENT_AVAILABLE:
        print(f"  Fetching news for {ticker}...")
        news_sentiment = fetch_news_sentiment(ticker)

    return compute_confluence(ticker, signals, fundamentals, news_sentiment)


def main() -> None:
    tickers = sys.argv[1:] if len(sys.argv) > 1 else list(WATCHLIST.values())

    results = []
    for ticker in tickers:
        result = analyse_ticker(ticker)
        if result:
            results.append(result)
            if len(tickers) == 1:
                print_report(result)

    if len(tickers) > 1:
        format_signal_table(results)
        actionable = [r for r in results if r.final_verdict in ("BUY", "SELL")]
        if actionable:
            print(f"\n{'='*68}")
            print(f"  DETAILED REPORTS — {len(actionable)} Actionable Signal(s)")
            print(f"{'='*68}")
            for r in actionable:
                print_report(r)
        else:
            print("\n  No actionable BUY/SELL signals found.")

    clear_cache()
    if _SENTIMENT_AVAILABLE:
        clear_sentiment_cache()


if __name__ == "__main__":
    main()
