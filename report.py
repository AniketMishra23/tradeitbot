# report.py — Terminal (stdout) signal report formatter
# Prints colour-coded six-perspective reports and watchlist scan tables.

from confluence import ConfluenceResult

_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_CYAN   = "\033[96m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"

_PERSP_ORDER = [
    ("technical",    "1. Technical"),
    ("fundamental",  "2. Fundamental"),
    ("macro",        "3. Macro"),
    ("sentiment",    "4. Sentiment"),
    ("quantitative", "5. Quantitative"),
    ("risk",         "6. Risk Mgmt"),
]


def _col(text: str, colour: str) -> str:
    return f"{colour}{text}{_RESET}"


def _dir_col(text: str, direction: str) -> str:
    if direction == "BULLISH": return _col(text, _GREEN)
    if direction == "BEARISH": return _col(text, _RED)
    return _col(text, _YELLOW)


def _verdict_col(verdict: str) -> str:
    if verdict == "BUY":      return _col(f" {verdict} ", _GREEN + _BOLD)
    if verdict == "SELL":     return _col(f" {verdict} ", _RED + _BOLD)
    if verdict == "NO TRADE": return _col(f" {verdict} ", _RED)
    return _col(f" {verdict} ", _YELLOW)


def _conf_col(conf: str) -> str:
    if conf == "HIGH":   return _col(conf, _GREEN)
    if conf == "MEDIUM": return _col(conf, _YELLOW)
    return _col(conf, _RED)


def print_report(result: ConfluenceResult) -> None:
    """Print a full six-perspective signal report to stdout with ANSI colours."""
    sep  = "=" * 70
    thin = "-" * 70

    print(f"\n{_col(sep, _BOLD)}")
    print(
        f"  {_col('SIGNAL REPORT', _BOLD + _CYAN)}  |  "
        f"{_col(result.ticker, _CYAN + _BOLD)}  |  "
        f"Overall confidence: {_conf_col(result.overall_confidence)}"
    )
    print(_col(sep, _BOLD))

    # Six-perspective table
    print(f"\n  {_col('SIX PERSPECTIVES', _BOLD)}\n")
    print(f"  {'Perspective':<16} {'Signal':<10} {'Conf':<8}  Key point")
    print(f"  {thin}")
    for key, label in _PERSP_ORDER:
        p = result.perspectives.get(key)
        if not p:
            print(f"  {label:<16} {'N/A':<10} {'N/A':<8}  —")
            continue
        sig_str   = _dir_col(f"{p.signal:<8}", p.signal)
        conf_str  = _conf_col(f"{p.confidence:<8}")
        top       = p.points[0] if p.points else "—"
        top_short = (top[:52] + "…") if len(top) > 52 else top
        print(f"  {label:<16} {sig_str}  {conf_str}  {top_short}")

    # Bull vs Bear adversarial step
    print(f"\n  {thin}")
    print(f"\n  {_col('BULL CASE', _GREEN + _BOLD)}")
    print(f"    {result.bull_case}")
    print(f"\n  {_col('BEAR CASE', _RED + _BOLD)}")
    print(f"    {result.bear_case}")
    print(f"\n  {_col('WINNER →', _BOLD)} {result.winning_case}")

    # Recommendation
    print(f"\n  {thin}")
    print(f"\n  Recommendation  :  {_verdict_col(result.final_verdict)}")

    # Trade levels (only for actionable BUY/SELL)
    if result.final_verdict in ("BUY", "SELL") and result.best_entry:
        print(f"  Entry zone      :  ₹{result.best_entry:,.2f}")
        print(f"  Stop loss       :  ₹{result.best_stop:,.2f}  (1.5× ATR)")
        print(f"  Target 1 (2R)   :  ₹{result.best_target_1:,.2f}")
        print(f"  Target 2 (3R)   :  ₹{result.best_target_2:,.2f}")
        if result.position_size:
            print(f"\n  Position size   :  {result.position_size} shares")
            print(f"  Position value  :  ₹{result.position_value:,.2f}")
            print(f"  Max risk        :  ₹{result.risk_amount:,.2f}  (1% capital rule)")

    # Warnings / risk veto notes
    if result.notes:
        print(f"\n  {thin}")
        for note in result.notes:
            print(f"  {_col('⚠', _YELLOW)}  {note}")

    # Top 3 mind-changers
    print(f"\n  {thin}")
    print("  Top 3 things that would change this view:")
    for i, mc in enumerate(result.mind_changers[:3], 1):
        print(f"    {i}. {mc}")

    # Per-perspective detail
    print(f"\n  {thin}")
    print(f"  {_col('PERSPECTIVE DETAIL', _BOLD)}\n")
    for key, label in _PERSP_ORDER:
        p = result.perspectives.get(key)
        if not p:
            continue
        print(f"  {_col(label, _BOLD)}  —  {_dir_col(p.signal, p.signal)}  ({_conf_col(p.confidence)})")
        for pt in p.points:
            print(f"    • {pt}")
        print()

    # Caveat
    print(f"  {thin}")
    print(
        f"  {_col('⚠', _YELLOW)}  This is analysis, not a guarantee. Markets can behave "
        "contrary to any signal.\n     A human must review and execute every trade."
    )
    print(f"{_col(sep, _BOLD)}\n")


def format_signal_table(results: list[ConfluenceResult]) -> None:
    """Print a compact multi-ticker comparison table (used for watchlist scans)."""
    sep  = "=" * 80
    thin = "-" * 80
    print(f"\n{sep}")
    print("  WATCHLIST SCAN — SIX-PERSPECTIVE SUMMARY")
    print(sep)
    print(f"  {'Ticker':<20} {'Direction':<10} {'Confluence':<12} {'Verdict':<12} {'Conf':<8} {'Entry':>10}")
    print(f"  {thin}")
    for r in results:
        dir_s  = _dir_col(f"{r.overall_direction:<8}", r.overall_direction)
        verd_s = _verdict_col(f"{r.final_verdict}")
        conf_s = _conf_col(r.overall_confidence)
        entry  = f"₹{r.best_entry:>9,.2f}" if r.best_entry else f"{'—':>10}"
        print(f"  {r.ticker:<20}  {dir_s}  {r.confluence_level:<12}  {verd_s:<12}  {conf_s:<8}  {entry}")
    print(f"{sep}\n")
