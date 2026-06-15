# data_fetcher.py — Yahoo Finance OHLCV + fundamentals fetcher
# All downloads are cached in-memory for the duration of one analysis run.
# Call clear_cache() after each run to free memory.

import yfinance as yf
import pandas as pd
from config import TIMEFRAMES

_CACHE: dict = {}


def _cache_key(ticker: str, interval: str, period: str) -> tuple:
    return (ticker.upper(), interval, period)


def fetch_ohlcv(
    ticker: str,
    interval: str,
    period: str,
    min_bars: int = 50,
    use_cache: bool = True,
) -> pd.DataFrame | None:
    """
    Download OHLCV data from Yahoo Finance for one ticker/interval/period.

    Returns a DataFrame with [Open, High, Low, Close, Volume],
    or None if data is unavailable or has fewer than min_bars rows.
    """
    key = _cache_key(ticker, interval, period)
    if use_cache and key in _CACHE:
        return _CACHE[key]

    try:
        raw = yf.download(ticker, interval=interval, period=period, progress=False, auto_adjust=True)
    except Exception as e:
        print(f"[data_fetcher] Download error for {ticker} ({interval}): {e}")
        return None

    if raw is None or raw.empty:
        print(f"[data_fetcher] No data for {ticker} ({interval}/{period})")
        return None

    # Flatten MultiIndex columns that newer yfinance versions sometimes produce
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in raw.columns]
    df   = raw[cols].dropna()

    if len(df) < min_bars:
        print(f"[data_fetcher] Only {len(df)} bars for {ticker} ({interval}), need {min_bars} — skipping.")
        return None

    if use_cache:
        _CACHE[key] = df
    return df


def fetch_all_timeframes(ticker: str, timeframes: dict | None = None) -> dict[str, pd.DataFrame | None]:
    """
    Fetch OHLCV across all configured timeframes for one ticker.
    Returns {timeframe_name: DataFrame or None}.
    """
    if timeframes is None:
        timeframes = TIMEFRAMES

    result = {}
    for tf_name, tf_cfg in timeframes.items():
        df = fetch_ohlcv(ticker, tf_cfg["interval"], tf_cfg["period"], tf_cfg["bars"])
        result[tf_name] = df
        status = f"{len(df)} bars" if df is not None else "UNAVAILABLE"
        print(f"  [{tf_name:8s}] {ticker}: {status}")
    return result


def get_current_price(ticker: str) -> float | None:
    """Return the latest closing price for a ticker (uses daily data)."""
    df = fetch_ohlcv(ticker, interval="1d", period="5d", min_bars=1)
    if df is None or df.empty:
        return None
    return float(df["Close"].iloc[-1])


def fetch_fundamentals(ticker: str) -> dict:
    """
    Fetch key fundamental metrics from yfinance Ticker.info.

    Returns a flat dict — all values may be None. Yahoo Finance coverage
    varies by market (Indian .NS stocks have limited fundamental data).
    """
    try:
        info = yf.Ticker(ticker).info
        return {
            "pe_trailing":     info.get("trailingPE"),
            "pe_forward":      info.get("forwardPE"),
            "price_to_book":   info.get("priceToBook"),
            "roe":             info.get("returnOnEquity"),
            "debt_to_equity":  info.get("debtToEquity"),
            "earnings_growth": info.get("earningsGrowth"),
            "revenue_growth":  info.get("revenueGrowth"),
            "dividend_yield":  info.get("dividendYield"),
            "market_cap":      info.get("marketCap"),
            "week52_high":     info.get("fiftyTwoWeekHigh"),
            "week52_low":      info.get("fiftyTwoWeekLow"),
            "sector":          info.get("sector"),
            "industry":        info.get("industry"),
            "short_name":      info.get("shortName"),
        }
    except Exception as e:
        print(f"[data_fetcher] Fundamentals error for {ticker}: {e}")
        return {}


def clear_cache() -> None:
    """Clear the in-memory OHLCV cache. Call after each analysis run."""
    _CACHE.clear()
