from __future__ import annotations

from collections.abc import Callable

from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from read_mcp_client import get_log_lines

STUB_CONFIDENCE = 0.9

LogFetcher = Callable[[], list[str]]


def _fetch_logs() -> list[str]:
    return get_log_lines()


def investigate(
    alert: Alert, incident_id: str, fetch_logs: LogFetcher = _fetch_logs
) -> Hypothesis:
    """Reads the Target Service's current logs and determines a cause via
    deterministic keyword matching (spec §7.2, §9 - no ReAct loop, no real
    LLM call yet).

    Returns a `Hypothesis` rather than a tuple: the cause, the confidence and
    the evidence are one verdict, and the model refuses to hold a cause
    without a confidence or the reverse. `incident_id` is taken because a
    hypothesis belongs to an incident and carries that from the moment it is
    formed.

    `fetch_logs` defaults to a real call through `read_mcp_client`; the seam
    exists so tests can inject a stub instead of hitting a real service.
    """
    logs = fetch_logs()
    cause_type = _determine_cause(logs)

    if cause_type == CauseType.FEATURE_FLAG_TOGGLE:
        return Hypothesis(
            incident_id=incident_id,
            summary=(
                f"feature flag toggle: {alert.alert_name} on {alert.service} "
                "correlates with a recent flag change"
            ),
            cause_type=cause_type,
            confidence=STUB_CONFIDENCE,
            supporting_evidence=logs,
        )

    # No recognizable cause. This must carry no confidence at all - the model
    # refuses to hold one without a cause, and that refusal is the point: the
    # old code returned a fabricated hypothesis at a fixed 0.9 here, which is
    # exactly the "confident about nothing" answer §9 forbids.
    return Hypothesis(
        incident_id=incident_id,
        summary=(
            f"no cause determined for {alert.alert_name} on {alert.service} "
            "from the evidence retrieved"
        ),
        cause_type=None,
        confidence=None,
        supporting_evidence=logs,
    )


def _determine_cause(logs: list[str]) -> CauseType | None:
    """Requires the flag-toggled-on event to appear *before* the first error
    in log order - an error that precedes any toggle can't have been caused
    by it, so presence alone isn't enough to attribute the cause."""
    toggle_index = _first_index_matching(logs, "feature flag", "toggled")
    error_index = _first_index_matching(logs, "error")

    if toggle_index is not None and error_index is not None and toggle_index < error_index:
        return CauseType.FEATURE_FLAG_TOGGLE

    return None


def _first_index_matching(logs: list[str], *phrases: str) -> int | None:
    for index, line in enumerate(logs):
        lowered = line.lower()
        if all(phrase in lowered for phrase in phrases):
            return index

    return None
