"""Trade Journal agent — logs each signal to a local JSON-lines file.

Fire-and-forget: the orchestrator swallows any exception from this agent
so a write failure never affects the signal output.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

AGENT_META = {
    "name":        "trade_journal",
    "perspective": "journal",
    "phase":       5,
}

_JOURNAL_PATH = Path(__file__).resolve().parent.parent / "trade_journal.json"


def run(result) -> None:
    """Append one JSON-lines entry to trade_journal.json."""
    entry = {
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "ticker":        result.ticker,
        "verdict":       result.final_verdict,
        "direction":     result.overall_direction,
        "confidence":    result.overall_confidence,
        "confluence":    result.confluence_level,
        "entry":         result.best_entry,
        "stop":          result.best_stop,
        "target_1":      result.best_target_1,
        "target_2":      result.best_target_2,
        "position_size": result.position_size,
        "bull_case":     result.bull_case[:200] if result.bull_case else "",
        "bear_case":     result.bear_case[:200] if result.bear_case else "",
    }

    # Append mode creates the file if it doesn't exist
    with open(_JOURNAL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
