from __future__ import annotations

STUB_ROOT_CAUSE = "root cause pending real analysis (walking-skeleton stub)"
STUB_EXECUTIVE_SUMMARY = (
    "Incident handled end-to-end by stub agents; no real investigation performed."
)


def write_postmortem(incident_id: str) -> dict[str, object]:
    """Stub Postmortem (spec §7.6) - placeholder content, no memory write,
    no completeness self-check (design.md Non-Goals)."""
    return {
        "root_cause": STUB_ROOT_CAUSE,
        "cost_estimate": {"amount_usd": 0, "assumptions": ["stub - no real cost model"]},
        "assumptions": ["stub - no real evidence gathered"],
        "executive_summary": STUB_EXECUTIVE_SUMMARY,
        "checklist_complete": False,
    }
