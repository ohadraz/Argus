from __future__ import annotations


def mitigate(hypothesis: str) -> str:
    """Stub mitigation (spec §7.3) - no real reversible action, no MCP call
    (design.md Non-Goals). Always reports the hypothesis `confirmed`."""
    return "confirmed"
