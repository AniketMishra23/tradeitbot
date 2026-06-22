# main.py — CLI entry point for Trade It (terminal / paper-trading mode)
#
# Usage:
#   python main.py                        # scan every ticker in WATCHLIST
#   python main.py HAL.NS                 # single ticker — full detail report
#   python main.py HAL.NS TCS.NS LT.NS   # multiple tickers — summary + BUY/SELL details

import sys
from src.report import print_report, format_signal_table
from src.config import WATCHLIST


def analyse_ticker(ticker: str):
    """Run the multi-agent pipeline for one ticker. Returns ConfluenceResult or None."""
    print(f"\nAnalysing {ticker} (multi-agent pipeline)...")
    try:
        from orchestrator import analyse_sync
        return analyse_sync(ticker, include_sentiment=True)
    except (ImportError, RuntimeError) as e:
        print(f"[main] Orchestrator unavailable ({e}), using legacy pipeline")
        return _analyse_ticker_legacy(ticker)
    except ValueError:
        print(f"[main] No data found for {ticker}")
        return None


def _analyse_ticker_legacy(ticker: str):
    """Legacy fallback — the original monolithic pipeline."""
    from src.data_fetcher import fetch_all_timeframes, fetch_fundamentals
    from src.indicators import compute_all, latest_values
    from src.signal_engine import generate_signal
    from src.confluence import compute_confluence

    try:
        from src.sentiment import fetch_news_sentiment
        _sentiment_ok = True
    except ImportError:
        _sentiment_ok = False

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
    if _sentiment_ok:
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


if __name__ == "__main__":
    main()
