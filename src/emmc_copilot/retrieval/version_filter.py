"""Version detection and ChromaDB filter building for eMMC spec retrieval.

Canonical version strings (as stored in chunk metadata):
    "5.1"  → JESD84-B51
    "5.0"  → JESD84-B50
    "4.51" → JESD84-B451
"""

from __future__ import annotations

import re
from typing import Any

# Each entry: (regex pattern, canonical version string)
# Patterns are tried in order; first match wins for each version.
_PATTERNS: list[tuple[str, str]] = [
    (r"\b5\.1\b|[Bb]51\b|JESD84-B51\b", "5.1"),
    (r"\b5\.0\b|[Bb]50\b|JESD84-B50\b", "5.0"),
    (r"\b4\.51\b|\b4\.5\b|[Bb]451\b|JESD84-B451\b", "4.51"),
]

# Default version when the user does not mention any
DEFAULT_VERSION = "5.1"


def detect_versions(query: str) -> list[str]:
    """Extract eMMC version mentions from *query*.

    Returns a deduplicated list of canonical version strings in the order they
    appear, or an empty list if no version is mentioned.

    Examples::

        detect_versions("eMMC 5.1 CACHE_CTRL")          → ["5.1"]
        detect_versions("比较 4.51 和 5.0 的 BKOPS_EN") → ["4.51", "5.0"]
        detect_versions("what is boot partition size")   → []
        detect_versions("[B451 §7.4.87 p.207]")         → ["4.51"]
    """
    seen: list[str] = []
    for pattern, version in _PATTERNS:
        if re.search(pattern, query, re.IGNORECASE) and version not in seen:
            seen.append(version)
    return seen


def build_version_where(versions: list[str]) -> dict[str, Any]:
    """Build a ChromaDB metadata ``where`` dict for *versions*.

    Single version  → ``{"version": "5.1"}``
    Multiple        → ``{"version": {"$in": ["4.51", "5.0"]}}``
    """
    if len(versions) == 1:
        return {"version": versions[0]}
    return {"version": {"$in": versions}}
