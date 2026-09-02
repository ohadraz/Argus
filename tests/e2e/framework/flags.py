from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import psycopg
from argus_core.anomaly import has_recovered_since
from argus_core.config import get_settings
from argus_core.models.metrics import MetricBucket
from argus_testkit import Assertion

from tests.e2e.framework.argus import REQUEST_TIMEOUT_SECONDS, TARGET_SERVICE_BASE_URL

"""Asserting on the world Argus acted on, and putting that world back.

An incident that reached `resolved` proves the graph ran; it does not prove
anything changed. These read the flag provider and the Target Service directly,
so a mitigation that reported success without turning a flag off, or turned one
off without the service recovering, fails here rather than passing quietly.

Everything takes the webhook's `httpx.Response` for the same reason the rest of
the e2e framework does - it is what a `Scenario`'s `when` produces - even where
the assertion does not need it.
"""

# The provider's own database, published by the Target Environment's compose
# file. Reached directly because the provider offers no other way back to a
# clean world - see `the_flag_provider_forgot_every_change`.
FLAG_PROVIDER_DATABASE_URL = "postgresql://unleash:unleash@localhost:5433/unleash"

# The credential these cases write flags with, and deliberately *not* the one
# `Settings.unleash_admin_token` holds. That one is Argus's, and the provider
# records the author of every change: a case staging a flag change with Argus's
# credential would be staging something Argus attributes to itself and filters
# out of its own evidence. Everything here plays a human - the operator who
# toggled the flag, the colleague who changed an unrelated one - so it writes
# under the human's credential, which is the shop's.
THE_HUMANS_ADMIN_TOKEN = "*:*.argus-demo-admin-token"

# The one flag the Target Service brings into existence for itself, mirroring
# its `UNLEASH_FLAG`. Every other flag in the provider was put there by a case -
# either directly, or by seeding a scenario that stages its own flag - and is
# this suite's to remove again.
THE_DEMO_FLAG = "monthly-spend-feature"


# The provider's table of recorded changes, and the event types that record a
# flag being switched. Internal to the provider, which is why they are named
# once, here: the compose file pins the provider's version and says to
# re-verify on a bump, and this is one of the things that verifies.
_EVENTS_TABLE = "events"
_TOGGLE_EVENT_TYPES = ("feature-environment-enabled", "feature-environment-disabled")


def the_flag_provider_reports(flag: str, enabled: bool) -> Assertion[Any]:
    """Read over the provider's evaluation API, which is what the Target
    Service itself reads - so this asserts what the service sees, not merely
    what the provider's admin side recorded."""
    def assertion(_result: Any) -> bool:
        evaluating = flags_evaluating_true()

        if (flag in evaluating) is not enabled:
            raise AssertionError(
                f"Expected flag [{flag}] to be "
                f"{'enabled' if enabled else 'disabled'}, "
                f"but the provider evaluates {sorted(evaluating)}."
            )

        return True

    return assertion


def the_service_returned_to_baseline() -> Assertion[Any]:
    """The service's most recent completed minute sits at its own baseline.

    Judged with the same departure rule the Investigator uses to find an onset
    and Mitigation uses to form a verdict, rather than a threshold invented
    here - a test that disagreed with the system about what a healthy minute is
    would be measuring something nothing else measures.
    """
    def assertion(_result: Any) -> bool:
        buckets = _target_service_metrics()

        if not buckets:
            raise AssertionError("The Target Service reported no metrics at all.")

        the_latest_minute = buckets[-1].bucket_id

        if not has_recovered_since(buckets, the_latest_minute):
            raise AssertionError(
                f"The Target Service's minute [{the_latest_minute}] still departs "
                f"from its baseline: error rate [{buckets[-1].error_rate}], "
                f"p95 [{buckets[-1].p95_ms}ms]."
            )

        return True

    return assertion


def another_flag_was_toggled_on(flag: str) -> Callable[[], bool]:
    """Arranges a second, unrelated flag change in the window.

    It never touches the Target Service - it exists only so the provider
    reports two changed flags, which is the state in which Mitigation must
    refuse to guess.

    Written as a human, like everything else here. A change Argus is recorded
    as having made is one Argus discounts as its own, so staging this with
    Argus's credential would stage no ambiguity at all - and the case would
    pass while testing nothing.
    """
    def step() -> bool:
        _create_flag_if_absent(flag)

        return switch_flag(flag, enabled=True)

    return step


def switch_flag(flag: str, enabled: bool) -> bool:
    settings = get_settings()
    response = httpx.post(
        f"{settings.unleash_base_url}"
        f"/api/admin/projects/{settings.unleash_project}"
        f"/features/{flag}/environments/{settings.unleash_environment}"
        f"/{'on' if enabled else 'off'}",
        headers={"Authorization": THE_HUMANS_ADMIN_TOKEN},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    return response.is_success


def flags_evaluating_true() -> list[str]:
    settings = get_settings()
    response = httpx.get(
        f"{settings.unleash_base_url}/api/frontend",
        headers={"Authorization": settings.unleash_frontend_token},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body: dict[str, Any] = response.json()

    return [
        toggle["name"]
        for toggle in body.get("toggles", [])
        if toggle.get("enabled", True)
    ]


def the_flag_provider_forgot_every_change() -> None:
    """Erases the record of every flag toggle, in the provider's own database.

    Teardown for any case that touched a flag - which, once Mitigation acts,
    is most of them. Mitigation identifies the flag an incident is about from
    what the provider says changed recently, so a change one case made is
    evidence the next case would reason about, and a suite whose cases inherit
    each other's history is a suite whose results depend on their order.

    Down here rather than through the API because the provider offers no other
    route: its event endpoints are read-only by design, it is an audit log, and
    deleting the flag leaves the flag's history behind and adds two entries
    saying it was deleted. Reaching past the vendor's API is a real cost, paid
    knowingly and in one place, against a disposable local fixture.
    """
    with psycopg.connect(FLAG_PROVIDER_DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {_EVENTS_TABLE} WHERE type = ANY(%s)",
                (list(_TOGGLE_EVENT_TYPES),),
            )
        connection.commit()


def every_flag_was_switched_off() -> None:
    """Leaves no flag on, whichever case turned which one on.

    Paired with forgetting the changes rather than replacing it: the history is
    what Mitigation reads, and the live state is what the Target Service reads.
    A world put back has to be right for both.
    """
    for flag in flags_evaluating_true():
        switch_flag(flag, enabled=False)


def only_the_shops_own_flag_was_left_in_the_provider() -> None:
    """Removes every flag a case brought into existence, keeping the shop's.

    The provider is shared with the demo, which shows its console to an
    audience, and a flag left behind by a test run is a flag somebody has to
    explain standing in front of one. Switching a flag off is not enough:
    off and absent look nothing alike in a list of flags.

    The shop's own flag is kept because the shop creates it at startup and
    reads it on every request - removing it would be breaking the fixture
    rather than cleaning up after a case. Everything else is a case's doing,
    including the fallback flag, which now comes into existence only when the
    scenario that stages it is seeded.

    Deletion is two calls in this provider: archiving a flag hides it, and only
    a second call against the archive removes it. Verified against the pinned
    version - re-verify on a bump, like every other admin path here.
    """
    for flag in _the_flags_the_provider_holds():
        if flag != THE_DEMO_FLAG:
            _delete_flag(flag)


def _the_flags_the_provider_holds() -> list[str]:
    """Every flag in the project, over the admin API rather than the evaluation
    one - a flag that is off still exists, and existing is the thing being
    cleaned up here."""
    settings = get_settings()
    response = httpx.get(
        f"{settings.unleash_base_url}/api/admin/projects/{settings.unleash_project}"
        f"/features",
        headers={"Authorization": THE_HUMANS_ADMIN_TOKEN},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body: dict[str, Any] = response.json()

    return [feature["name"] for feature in body.get("features", [])]


def _delete_flag(flag: str) -> None:
    settings = get_settings()
    headers = {"Authorization": THE_HUMANS_ADMIN_TOKEN}
    httpx.delete(
        f"{settings.unleash_base_url}/api/admin/projects/{settings.unleash_project}"
        f"/features/{flag}",
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    httpx.delete(
        f"{settings.unleash_base_url}/api/admin/archive/{flag}",
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def _create_flag_if_absent(flag: str) -> None:
    settings = get_settings()
    httpx.post(
        f"{settings.unleash_base_url}/api/admin/projects/{settings.unleash_project}/features",
        headers={"Authorization": THE_HUMANS_ADMIN_TOKEN},
        json={"name": flag, "type": "release"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    # A flag with no strategy never evaluates true however it is toggled, so
    # the second flag would be invisible to the very read this arranges for.
    httpx.post(
        f"{settings.unleash_base_url}/api/admin/projects/{settings.unleash_project}"
        f"/features/{flag}/environments/{settings.unleash_environment}/strategies",
        headers={"Authorization": THE_HUMANS_ADMIN_TOKEN},
        json={"name": "flexibleRollout", "parameters": {"rollout": "100"}},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def _target_service_metrics() -> list[MetricBucket]:
    response = httpx.get(
        f"{TARGET_SERVICE_BASE_URL}/metrics", timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()

    return [MetricBucket.model_validate(bucket) for bucket in response.json()]
