"""What the flag provider recorded as having changed (spec §7.3, §16).

A read, in the write server. That placement is not an oversight: the provider
issues no credential that can read its change history without also being able to
change a flag - asked with the evaluation token, the history endpoints answer
`403 invalid token: expected a different token type for this endpoint` - so
putting this on `argus-read-mcp` would hand the read tier a mutation-capable
secret and dissolve the guarantee the tier split exists to make. The write server
already holds that credential, and a read inside a process that can already write
is strictly less capability than it has.

Why a history at all, rather than reading which flags are currently on: a flag
causes an incident by *changing*, in either direction, and current state cannot
see one of those directions. A flag switched off into an incident is off now, and
so is every flag that has been off for a year - evaluation cannot tell them
apart. The history can, and it carries the direction the mitigating action has to
reverse.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from argus_core.config import Settings, get_settings
from argus_core.models.flag_change import FlagChange
from argus_core.timestamps import parse_iso, to_iso

HttpGet = Callable[..., httpx.Response]

REQUEST_TIMEOUT_SECONDS = 10.0

EVENTS_PATH = "/api/admin/events"

# The provider's own names for the two events that change what a service
# evaluates. Everything else in its log - features created, strategies added,
# tokens issued - left evaluation where it was, and so is not a change to undo.
_ENABLED_EVENT = "feature-environment-enabled"
_DISABLED_EVENT = "feature-environment-disabled"


class FlagHistoryUnavailable(Exception):
    """The provider's change history could not be read.

    Raised rather than returning an empty history, because "nothing changed" is
    a conclusion Mitigation acts on - it escalates, having nothing to revert. An
    outage reported as an empty history would look like a quiet environment, and
    the incident would be filed under the wrong reason.
    """


def recent_flag_changes(
    since: str,
    settings: Settings | None = None,
    get: HttpGet = httpx.get,
) -> list[FlagChange]:
    """The flag toggles recorded in the configured environment since `since`,
    oldest first.

    Ordered oldest-first although the provider answers newest-first, matching
    every other windowed read in Argus. Callers ask which change was *latest*,
    and having one direction decided here rather than at each call site is what
    stops two of them disagreeing about which end of the list that is.

    The window is applied here rather than by the provider: its events endpoint
    ignores a row limit and answers with the whole log. Correct at any size and
    cheap at the scale this runs at; a real deployment would want the provider's
    own filtering, and this adapter is the one place that changes.
    """
    resolved = settings if settings is not None else get_settings()
    url = f"{resolved.unleash_base_url}{EVENTS_PATH}"

    try:
        response = get(
            url,
            headers={"Authorization": resolved.unleash_admin_token},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
    except Exception as error:
        raise FlagHistoryUnavailable(
            f"could not read flag history at [{url}]: {error}"
        ) from error

    window_start = parse_iso(since)
    toggles = [
        event
        for event in body.get("events", [])
        if _is_a_toggle_of_this_environment(event, resolved.unleash_environment)
        and parse_iso(event["createdAt"]) >= window_start
    ]

    return [_as_flag_change(event) for event in sorted(toggles, key=_recorded_order)]


def _recorded_order(event: dict[str, Any]) -> int:
    """The provider's own insertion sequence for a log row.

    Ordering on the timestamp instead would leave two changes tied whenever they
    land in the same second - it records to the second - and a flag switched on
    and straight back off does exactly that. A stable sort then keeps the order
    the provider listed them in, which is newest first, so "the latest change"
    becomes the earliest one and the flag gets reverted the wrong way. The event
    id is the sequence actually recorded and it does not tie. It stays inside
    this adapter: `FlagChange` is vendor-neutral and carries no provider id.
    """
    return int(event["id"])


def _is_a_toggle_of_this_environment(event: dict[str, Any], environment: str) -> bool:
    return (
        event.get("type") in (_ENABLED_EVENT, _DISABLED_EVENT)
        and event.get("environment") == environment
        and event.get("featureName") is not None
    )


def _as_flag_change(event: dict[str, Any]) -> FlagChange:
    """One log row in the provider's shape, as the vendor-neutral fact it
    records. Deterministic mapping, never a model: a hallucinated toggle is a
    write to the wrong flag."""
    return FlagChange(
        flag=event["featureName"],
        enabled=event["type"] == _ENABLED_EVENT,
        occurred_at=to_iso(parse_iso(event["createdAt"])),
        actor=event.get("createdBy"),
    )
