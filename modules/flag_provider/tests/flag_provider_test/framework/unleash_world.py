"""An Unleash server, in-process, serving one `ProviderState` in Unleash's own shapes.

The port's suite runs both Unleash adapters against this through their
`transport` seam, beside the in-memory double built from the same seed. So this
answers every route the adapters ask, in the shapes `test_unleash.py` pins on
the wire, and it keeps state: a toggle is applied to what the next read is
answered with, and recorded in the history the next search finds - or the
adapter would be answering questions about a provider that never changed.

Behaviours of Unleash's that `test_unleash.py` does not pin, because the adapter
only reads their answer or never meets them there:
- A toggle that moves nothing records nothing: Unleash stores the event only
  `if (updatedEnvironmentStatus > 0)` (`unprotectedUpdateEnabled`,
  src/lib/features/feature-toggle/feature-toggle-service.ts).
- A toggle is recorded under the name of the token that made it: the event's
  `createdBy` is the audit user's name, which for an admin token is its
  `token_name`.
- A flag the provider does not hold is refused, read or toggled, with a 404.
- The event search answers newest first - `created_at` and then `id`, both
  descending, whatever is asked - with `total`, the count of every event its
  filters match, beside the page (`searchEvents`,
  src/lib/features/events/event-store.ts). A filter is an operator and its
  values, `IS:<value>` or `IS_ANY_OF:<value>,<value>` - the two read here; a
  filter written any other way fails the case rather than being answered as
  Unleash might. An `offset` that is not
  above 0 is 0, and a `limit` outside 1 to 1000 is 50 (`normalizeQueryParams`,
  src/lib/features/feature-search/search-utils.ts).
- The older event route answers the 100 newest events and no more
  (`getEvents`, src/lib/features/events/event-store.ts, `.limit(100)`), so an
  adapter that fell back to it would lose a change behind 100 newer ones.

Evaluation lags a write, as Unleash's does - the frontend API answers from a
cache the write reaches later. Staged here as the first look after a write
still seeing the old state and the second seeing the new, so the adapter's
wait is exercised; never, where the seed says evaluation does not follow.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any, Final

import httpx2
from core import parse_iso
from flag_provider.unleash import (
    DATE_HEADER,
    DISABLED_EVENT,
    ENABLED_EVENT,
    ENVIRONMENT_ENABLED,
    ENVIRONMENT_NAME,
    EVENT_CREATED_AT,
    EVENT_CREATED_BY,
    EVENT_ENVIRONMENT,
    EVENT_FLAG,
    EVENT_ID,
    EVENT_TYPE,
    EVENTS,
    FEATURE_ENVIRONMENTS,
    TOGGLE_ENABLED,
    TOGGLE_NAME,
    TOGGLES,
    UnleashFrontendSettings,
    UnleashSettings,
)
from flag_provider_double import ProviderState, RecordedToggle

# Where the stand-in is addressed. Nothing listens there: the transport answers.
_BASE_URL: Final = "http://unleash.invalid"
_PROJECT: Final = "default"
_FRONTEND_TOKEN: Final = "default:production.some-frontend-token"
_ADMIN_TOKEN: Final = "*:*.some-admin-token"

# An environment the provider holds every flag in beside the one asked about,
# listed first in the admin read of a flag and holding the opposite state - so
# an adapter reading the wrong one shows.
_ANOTHER_ENVIRONMENT: Final = "development"

# The routes, as a real Unleash spells them.
_EVALUATION: Final = "/api/frontend"
_EVENT_LOG: Final = "/api/admin/events"
_EVENT_SEARCH: Final = "/api/admin/search/events"
_FEATURE: Final = re.compile(
    r"^/api/admin/projects/(?P<project>[^/]+)/features/(?P<flag>[^/]+)"
    r"(?:/environments/(?P<environment>[^/]+)/(?P<state>on|off))?$"
)

# The event search's query, and the field of its answer that counts every
# event matched.
_TYPE: Final = "type"
_ENVIRONMENT: Final = "environment"
_OFFSET: Final = "offset"
_LIMIT: Final = "limit"
_TOTAL: Final = "total"
_FILTER: Final = re.compile(r"^(?P<operator>IS|IS_ANY_OF):(?P<values>.+)$")
_LIMIT_DEFAULT: Final = 50
_LIMIT_MOST: Final = 1000

# How many of the newest events the older event route answers with.
_THE_NEWEST_THE_LOG_ANSWERS: Final = 100

_OK: Final = 200
_NOT_FOUND: Final = 404


def unleash_settings(state: ProviderState, argus_actor: str | None) -> UnleashSettings:
    """The write adapter's settings, addressing this stand-in in the seed's
    environment, and recognising `argus_actor` as Argus's - none, where it is
    `None`. Every field named, so a developer's own environment reaches no
    case."""
    return UnleashSettings(
        base_url=_BASE_URL,
        frontend_token=_FRONTEND_TOKEN,
        admin_token=_ADMIN_TOKEN,
        project=_PROJECT,
        environment=state.environment,
        actor=argus_actor or ""
    )


def unleash_frontend_settings() -> UnleashFrontendSettings:
    """The read adapter's settings, addressing this stand-in."""
    return UnleashFrontendSettings(base_url=_BASE_URL, frontend_token=_FRONTEND_TOKEN)


class UnleashWorld:
    """One Unleash server holding `state`, answering the requests a
    `MockTransport` hands it, recording and dating by `clock`.

    `unreachable` stands up a server nothing reaches: every request fails as a
    refused connection, before a byte of it was sent.
    """

    def __init__(self,
                 state: ProviderState,
                 *,
                 clock: Callable[[], datetime],
                 unreachable: bool = False) -> None:
        assert state.environment != _ANOTHER_ENVIRONMENT, \
            f"the seed's environment is the one the stand-in holds beside it [{state.environment}]"

        self._environment = state.environment
        self._held = dict(state.flags)
        self._evaluated = dict(state.flags)
        self._evaluation_follows = state.evaluation_follows
        self._stale_looks = 0
        self._signed_in_as = state.signed_in_as
        self._clock = clock
        self._unreachable = unreachable
        self._events: list[dict[str, Any]] = []

        for toggle in state.history:
            self._record(toggle)

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if self._unreachable:
            raise httpx2.ConnectError("connection refused", request=request)

        path = request.url.path
        method = request.method

        if path == _EVALUATION and method == "GET":
            return self._evaluation()
        if path == _EVENT_SEARCH and method == "GET":
            return self._search(dict(request.url.params))
        if path == _EVENT_LOG and method == "GET":
            return self._answer(_OK, {"version": 1,
                                      EVENTS: self._newest_first(self._events)
                                      [:_THE_NEWEST_THE_LOG_ANSWERS],
                                      "totalEvents": len(self._events)})

        routed = _FEATURE.match(path)

        if routed is None or routed["project"] != _PROJECT or routed["flag"] not in self._held:
            return self._answer(_NOT_FOUND, {})

        if routed["state"] is None and method == "GET":
            return self._feature(routed["flag"])
        if (routed["state"] is not None and method == "POST"
                and routed["environment"] == self._environment):
            return self._toggle(routed["flag"], routed["state"] == "on")

        return self._answer(_NOT_FOUND, {})

    def _evaluation(self) -> httpx2.Response:
        """The flags evaluating true, in the order the provider lists them - a
        look behind a write still seeing what was evaluated before it."""
        if self._stale_looks > 0:
            self._stale_looks -= 1
        elif self._evaluation_follows:
            self._evaluated = dict(self._held)

        return self._answer(_OK, {TOGGLES: [
            {TOGGLE_NAME: flag, TOGGLE_ENABLED: True,
             "variant": {"name": "disabled", "enabled": False}}
            for flag, on in self._evaluated.items() if on
        ]})

    def _feature(self, flag: str) -> httpx2.Response:
        """The admin read of one flag: every environment it is in, the one not
        asked about first, dated by the answer's `Date`."""
        held = self._held[flag]

        return self._answer(_OK, {
            "name": flag,
            "project": _PROJECT,
            "type": "release",
            "stale": False,
            FEATURE_ENVIRONMENTS: [
                {ENVIRONMENT_NAME: _ANOTHER_ENVIRONMENT, ENVIRONMENT_ENABLED: not held},
                {ENVIRONMENT_NAME: self._environment, ENVIRONMENT_ENABLED: held}
            ]
        })

    def _toggle(self, flag: str, enabled: bool) -> httpx2.Response:
        if self._held[flag] != enabled:
            self._held[flag] = enabled
            self._record(RecordedToggle(flag=flag, enabled=enabled, occurred_at=self._clock(),
                                        actor=self._signed_in_as))
            self._stale_looks = 1

        return self._answer(_OK, {})

    def _search(self, query: dict[str, str]) -> httpx2.Response:
        matched = self._events

        for field, name in ((_TYPE, EVENT_TYPE), (_ENVIRONMENT, EVENT_ENVIRONMENT)):
            if field not in query:
                continue

            asked = _FILTER.match(query[field])

            # The stand-in's own failure, not an answer of Unleash's: what Unleash
            # says of a filter it cannot read is not pinned anywhere.
            if asked is None:
                raise AssertionError(
                    f"The stand-in reads [{field}] only as IS or IS_ANY_OF, and was asked "
                    f"[{query[field]}]."
                )

            values = asked["values"].split(",")
            matched = [event for event in matched if event.get(name) in values]

        offset = _a_number(query.get(_OFFSET))
        limit = _a_number(query.get(_LIMIT))
        offset = int(offset) if offset is not None and offset > 0 else 0
        limit = int(limit) if limit is not None and 0 < limit <= _LIMIT_MOST else _LIMIT_DEFAULT

        return self._answer(_OK, {EVENTS: self._newest_first(matched)[offset:offset + limit],
                                  _TOTAL: len(matched)})

    def _record(self, toggle: RecordedToggle) -> None:
        """`toggle` as a row of the provider's log, numbered after the last."""
        self._events.append({
            EVENT_ID: len(self._events) + 1,
            EVENT_TYPE: ENABLED_EVENT if toggle.enabled else DISABLED_EVENT,
            EVENT_CREATED_AT: _as_the_provider_dates(toggle.occurred_at),
            EVENT_CREATED_BY: toggle.actor,
            EVENT_FLAG: toggle.flag,
            "project": _PROJECT,
            EVENT_ENVIRONMENT: self._environment
        })

    def _newest_first(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(events,
                      key=lambda event: (parse_iso(event[EVENT_CREATED_AT]), event[EVENT_ID]),
                      reverse=True)

    def _answer(self, status: int, body: Any) -> httpx2.Response:
        return httpx2.Response(status, json=body,
                               headers={DATE_HEADER: format_datetime(self._now(), usegmt=True)})

    def _now(self) -> datetime:
        return self._clock().astimezone(UTC).replace(microsecond=0)


def _a_number(text: str | None) -> float | None:
    """`text` read as JavaScript's `Number` reads a query value, `None` where it
    reads none."""
    if text is None:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def _as_the_provider_dates(moment: datetime) -> str:
    """A moment as the event log spells it: milliseconds, and `Z` for UTC."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
