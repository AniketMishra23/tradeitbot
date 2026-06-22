# config.py — Central configuration for Trade It
# Edit this file to change your watchlist, timeframes, and risk parameters.
# All other modules import from here — no need to touch them for routine changes.

# ---------------------------------------------------------------------------
# Watchlist
# Key   : display name shown in scan results
# Value : Yahoo Finance ticker (NSE = .NS, BSE = .BO)
# Note  : Users can also add/remove tickers at runtime via /add and /remove
#         in Telegram — those changes are in-memory and reset on bot restart.
# ---------------------------------------------------------------------------
WATCHLIST = {
    # Defence & Aerospace
    "HAL":            "HAL.NS",
    "BEL":            "BEL.NS",
    "Mazagon Dock":   "MAZDOCK.NS",

    # Renewable Energy
    "Tata Power":     "TATAPOWER.NS",

    # Infrastructure & Capital Goods
    "L&T":            "LT.NS",
    "ABB India":      "ABB.NS",
    "IRB Infra":      "IRB.NS",

    # Pharmaceuticals
    "Sun Pharma":     "SUNPHARMA.NS",
    "Divi's Lab":     "DIVISLAB.NS",
    "Cipla":          "CIPLA.NS",

    # IT & AI Services
    "TCS":            "TCS.NS",
    "Infosys":        "INFY.NS",
    "HCL Tech":       "HCLTECH.NS",

    # Private Banks & NBFCs
    "HDFC Bank":      "HDFCBANK.NS",
    "ICICI Bank":     "ICICIBANK.NS",
    "Bajaj Finance":  "BAJFINANCE.NS",

    # Automobiles & EVs
    "Maruti":         "MARUTI.NS",
    "M&M":            "M&M.NS",
    "Tata Motors":    "TATAMOTORS.NS",

    # Internet & Tech
    "Naukri":         "NAUKRI.NS",
}

# ---------------------------------------------------------------------------
# Timeframes
# Four timeframes are analysed per ticker and voted on with different weights:
#   weekly=3, daily=2, 1hour=1, 15min=1
# Sub-daily intervals (15m, 1h) are limited to the last 60 days by Yahoo Finance.
# ---------------------------------------------------------------------------
TIMEFRAMES = {
    "15min": {
        "interval": "15m",
        "period":   "5d",
        "label":    "15-Minute (Intraday)",
        "bars":     100,    # minimum candles required for indicator warmup
    },
    "1hour": {
        "interval": "1h",
        "period":   "30d",
        "label":    "1-Hour (Intraday)",
        "bars":     60,
    },
    "daily": {
        "interval": "1d",
        "period":   "1y",
        "label":    "Daily (Swing / Positional)",
        "bars":     200,
    },
    "weekly": {
        "interval": "1wk",
        "period":   "5y",
        "label":    "Weekly (Positional / Trend)",
        "bars":     100,
    },
}

# ---------------------------------------------------------------------------
# Risk & Signal Parameters
# ---------------------------------------------------------------------------
RISK = {
    "atr_sl_multiplier":    1.5,    # stop loss = entry ± (1.5 × ATR)
    "rr_target_1":          2.0,    # first target at 2R
    "rr_target_2":          3.0,    # second target at 3R

    "rsi_oversold":         35,     # RSI below this → oversold (bullish lean)
    "rsi_overbought":       65,     # RSI above this → overbought (bearish lean)
    "rsi_neutral_low":      40,
    "rsi_neutral_high":     60,

    "volume_spike_ratio":   1.5,    # volume must be 1.5× average to confirm a move

    "confluence_min":       3,      # timeframes that must agree for STRONG confluence

    "capital":              100_000,    # trading capital in ₹ (change to your actual amount)
    "risk_pct_per_trade":   0.01,       # 1% of capital at risk per trade
    "max_position_pct":     0.25,       # risk veto: refuse any trade needing > 25% of capital
}

# ---------------------------------------------------------------------------
# Indicator Periods
# ---------------------------------------------------------------------------
INDICATORS = {
    "ema_fast":     20,
    "ema_mid":      50,
    "ema_slow":     200,
    "rsi_period":   14,
    "macd_fast":    12,
    "macd_slow":    26,
    "macd_signal":  9,
    "atr_period":   14,
    "bb_period":    20,
    "bb_std":       2,
    "volume_ma":    20,
}

# ---------------------------------------------------------------------------
# Multi-Agent Configuration
# ---------------------------------------------------------------------------
AGENT_AI_CONFIG = {
    "technical_analyst":  {"provider": "groq"},
    "fundamentalist":     {"provider": "groq"},
    "macro_strategist":   {"provider": "groq"},
    "sentiment_analyst":  {"provider": "groq"},
    "sector_specialist":  {"provider": "groq"},
    "event_watcher":      {"provider": "groq"},
    "devils_advocate":    {"provider": "groq"},
    "chief_strategist":   {"provider": "groq"},
}

AGENT_TIMEOUTS = {
    "python":   10,
    "markdown": 30,
}
