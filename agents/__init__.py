"""Agent auto-discovery — scans agents/ for .md and .py definitions."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

AGENT_DIR = Path(__file__).parent

_SKIP_PY = {"__init__", "schema", "runner"}


def _parse_markdown_meta(path: Path) -> dict | None:
    """Extract agent metadata from a markdown file's headings."""
    text = path.read_text(encoding="utf-8")

    name_match = re.search(r"^#\s+Agent:\s*(.+)", text, re.MULTILINE)
    if not name_match:
        return None

    raw_name = name_match.group(1).strip()
    slug = re.sub(r"[^a-z0-9]+", "_", raw_name.lower()).strip("_")

    perspective = ""
    persp_match = re.search(r"^##\s+Perspective\s*\n+(.+)", text, re.MULTILINE)
    if persp_match:
        perspective = persp_match.group(1).strip().lower()

    phase = 2
    phase_match = re.search(r"^##\s+Phase\s*\n+(\d+)", text, re.MULTILINE)
    if phase_match:
        phase = int(phase_match.group(1))

    return {
        "name":        slug,
        "display_name": raw_name,
        "type":        "markdown",
        "perspective": perspective,
        "phase":       phase,
        "path":        path,
        "run_fn":      None,
    }


def discover_agents() -> dict:
    """
    Scan agents/ and return {agent_name: meta_dict}.

    Markdown agents: identified by '# Agent:' heading.
    Python agents:   identified by AGENT_META dict + run() callable.
    """
    registry: dict = {}

    for f in sorted(AGENT_DIR.iterdir()):
        if f.suffix == ".md":
            meta = _parse_markdown_meta(f)
            if meta:
                registry[meta["name"]] = meta

        elif f.suffix == ".py" and f.stem not in _SKIP_PY:
            try:
                mod = importlib.import_module(f"agents.{f.stem}")
            except Exception:
                # Skip agents with missing dependencies (e.g. sentiment not installed)
                continue
            if hasattr(mod, "AGENT_META") and hasattr(mod, "run"):
                meta = dict(mod.AGENT_META)
                meta["type"] = "python"
                meta["path"] = f
                meta["run_fn"] = mod.run
                registry[meta["name"]] = meta

    return registry
