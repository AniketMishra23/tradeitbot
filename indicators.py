# indicators.py — Technical indicator calculations (pure pandas/numpy, no TA-Lib)
#
# All functions accept a DataFrame with [Open, High, Low, Close, Volume] columns
# and return a new DataFrame with indicator columns appended.
# Use compute_all() to add every indicator at once, then latest_values() to
# extract the most recent bar as a flat dict for signal_engine.py.

import pandas as pd
import numpy as np
from config import INDICATORS as CFG


def add_ema(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA-20, EMA-50, and EMA-200 columns."""
    df = df.copy()
    df["ema20"]  = df["Close"].ewm(span=CFG["ema_fast"],  adjust=False).mean()
    df["ema50"]  = df["Close"].ewm(span=CFG["ema_mid"],   adjust=False).mean()
    df["ema200"] = df["Close"].ewm(span=CFG["ema_slow"],  adjust=False).mean()
    return df


def add_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """Add RSI-14 using Wilder's smoothing (EWM with com=period-1)."""
    df     = df.copy()
    period = CFG["rsi_period"]
    delta  = df["Close"].diff()
    gain   = delta.clip(lower=0)
    loss   = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def add_macd(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add MACD line, signal line, and histogram.
    macd_hist > 0 and rising  → bullish momentum.
    macd_hist < 0 and falling → bearish momentum.
    """
    df     = df.copy()
    fast   = df["Close"].ewm(span=CFG["macd_fast"],   adjust=False).mean()
    slow   = df["Close"].ewm(span=CFG["macd_slow"],   adjust=False).mean()
    macd   = fast - slow
    signal = macd.ewm(span=CFG["macd_signal"], adjust=False).mean()
    df["macd"]      = macd
    df["macd_sig"]  = signal
    df["macd_hist"] = macd - signal
    return df


def add_atr(df: pd.DataFrame) -> pd.DataFrame:
    """Add ATR-14 (Average True Range). Used to size stop losses."""
    df     = df.copy()
    period = CFG["atr_period"]
    high_low   = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close  = (df["Low"]  - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.ewm(com=period - 1, min_periods=period).mean()
    return df


def add_bollinger_bands(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add Bollinger Bands (20-period SMA ± 2 std) and bb_pct.
    bb_pct = 0 means price is at the lower band; 1 means at the upper band.
    """
    df     = df.copy()
    period = CFG["bb_period"]
    std    = CFG["bb_std"]
    sma    = df["Close"].rolling(period).mean()
    sigma  = df["Close"].rolling(period).std()
    df["bb_upper"] = sma + std * sigma
    df["bb_lower"] = sma - std * sigma
    df["bb_mid"]   = sma
    band_width     = df["bb_upper"] - df["bb_lower"]
    df["bb_pct"]   = (df["Close"] - df["bb_lower"]) / band_width.replace(0, np.nan)
    return df


def add_volume_ratio(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add vol_ratio = current volume ÷ 20-bar rolling average.
    Values above 1.5 indicate above-average participation (confirms a move).
    """
    df = df.copy()
    ma = df["Volume"].rolling(CFG["volume_ma"]).mean()
    df["vol_ratio"] = df["Volume"] / ma.replace(0, np.nan)
    return df


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all indicators and return an enriched DataFrame."""
    df = add_ema(df)
    df = add_rsi(df)
    df = add_macd(df)
    df = add_atr(df)
    df = add_bollinger_bands(df)
    df = add_volume_ratio(df)
    return df


def latest_values(df: pd.DataFrame) -> dict:
    """
    Extract the most recent bar's indicator values as a flat dict.
    Also includes the previous bar for crossover detection (prev_macd_hist).
    Returns an empty dict if fewer than 2 rows exist.
    """
    if df is None or len(df) < 2:
        return {}

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    def safe(series, key):
        val = series.get(key, np.nan)
        return float(val) if not pd.isna(val) else None

    return {
        "close":          float(curr["Close"]),
        "high":           float(curr["High"]),
        "low":            float(curr["Low"]),
        "open":           float(curr["Open"]),
        "ema20":          safe(curr, "ema20"),
        "ema50":          safe(curr, "ema50"),
        "ema200":         safe(curr, "ema200"),
        "rsi":            safe(curr, "rsi"),
        "macd":           safe(curr, "macd"),
        "macd_sig":       safe(curr, "macd_sig"),
        "macd_hist":      safe(curr, "macd_hist"),
        "prev_macd_hist": safe(prev, "macd_hist"),
        "atr":            safe(curr, "atr"),
        "bb_upper":       safe(curr, "bb_upper"),
        "bb_lower":       safe(curr, "bb_lower"),
        "bb_pct":         safe(curr, "bb_pct"),
        "vol_ratio":      safe(curr, "vol_ratio"),
    }
