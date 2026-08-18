from __future__ import annotations

from collections.abc import Callable

import httpx
from argus_core.config import get_settings
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType

STUB_CONFIDENCE = 0.9

LogFetcher = Callable[[], list[str]]


def _fetch_logs() -> list[str]:
    settings = get_settings()
    response = httpx.get(f"{settings.target_service_url}/logs", timeout=10.0)
    response.raise_for_status()
    logs: list[str] = response.json()
    return logs


def investigate(
    alert: Alert, fetch_logs: LogFetcher = _fetch_logs
) -> tuple[str, float, CauseType | None]:
    """Reads the Target Service's current logs and determines a cause via
    deterministic keyword matching (spec §7.2, §9 - no ReAct loop, no real
    LLM call yet, per design.md Non-Goals). Falls back to the same fixed
    confidence used before this change when nothing is recognized, so the
    no-scenario-seeded happy path is unaffected. `fetch_logs` defaults to a
    real HTTP call to the Target Service; the seam exists so it can later be
    swapped for a real `logs-mcp`-backed adapter without changing this
    function's shape, and so tests can inject a stub instead of hitting a
    real service."""
    logs = fetch_logs()
    cause_type = _determine_cause(logs)

    if cause_type == CauseType.FEATURE_FLAG_TOGGLE:
        hypothesis = (
            f"feature flag toggle: {alert.alert_name} on {alert.service} "
            "correlates with a recent flag change"
        )
    else:
        hypothesis = (
            f"stub hypothesis: {alert.alert_name} on {alert.service} "
            "correlates with a recent change"
        )

    return hypothesis, STUB_CONFIDENCE, cause_type


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
