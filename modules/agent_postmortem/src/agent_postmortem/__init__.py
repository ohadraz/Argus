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
        "customer_loss_estimate_usd": None,
        "engineer_minutes": None,
        "tokens_spent": None,
        "assumptions": ["stub - no real evidence gathered"],
        "executive_summary": STUB_EXECUTIVE_SUMMARY,
        "checklist_complete": False,
    }
