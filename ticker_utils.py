"""Ticker resolution and market display utilities.

Extracted from telegram_bot.py to break a circular dependency:
agents/data_scout.py needs resolve_ticker() but must not import telegram_bot.py.
"""

_CRYPTO_SYMBOLS = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX",
    "DOT", "MATIC", "LTC", "LINK", "UNI", "ATOM", "NEAR", "SHIB",
    "TRX", "TON", "SUI", "APT", "OP", "ARB", "FTM", "INJ", "SEI",
}

_KNOWN_SUFFIXES = (
    ".NS", ".BO", ".AX", ".L", ".T", ".HK", ".SI", ".TO", ".DE", ".PA",
)

_ALIASES = {
    "HDFC":         "HDFCBANK.NS",
    "HDFCBANK":     "HDFCBANK.NS",
    "BAJAJFINANCE": "BAJFINANCE.NS",
    "M&M":          "M&M.NS",
    "MAHINDRA":     "M&M.NS",
}


def resolve_ticker(raw: str) -> str:
    """Convert user-typed symbol into a Yahoo Finance ticker."""
    t = raw.upper().strip()
    if t in _ALIASES:
        return _ALIASES[t]
    if any(t.endswith(s) for s in _KNOWN_SUFFIXES):
        return t
    if "-" in t:
        return t
    if t in _CRYPTO_SYMBOLS:
        return f"{t}-USD"
    return f"{t}.NS"


def ticker_currency(ticker: str) -> str:
    """Return the display currency symbol for a ticker."""
    t = ticker.upper()
    if t.endswith(".NS") or t.endswith(".BO"):
        return "Rs."
    if t.endswith(".AX"):
        return "A$"
    if t.endswith(".L"):
        return "£"
    if t.endswith(".T"):
        return "¥"
    if t.endswith(".HK"):
        return "HK$"
    if "-USD" in t or "-USDT" in t or t.split("-")[0] in _CRYPTO_SYMBOLS:
        return "$"
    return "$"


def market_label(ticker: str) -> str:
    """Short human-readable market name."""
    t = ticker.upper()
    if t.endswith(".NS"):
        return "NSE 🇮🇳"
    if t.endswith(".BO"):
        return "BSE 🇮🇳"
    if t.endswith(".AX"):
        return "ASX 🇦🇺"
    if t.endswith(".L"):
        return "LSE 🇬🇧"
    if t.endswith(".T"):
        return "TSE 🇯🇵"
    if t.endswith(".HK"):
        return "HKEX 🇭🇰"
    if "-USD" in t or "-USDT" in t:
        return "Crypto ₿"
    return "US 🇺🇸"
