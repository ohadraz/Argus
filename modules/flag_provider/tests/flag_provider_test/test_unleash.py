"""The feature-flag provider as Unleash serves it, said in Argus's own values.

The one suite in Argus that knows Unleash's wire shape. The read tier, the write
tier and Mitigation are tested against the port, so what is pinned here is the
whole of what they rely on: which route each question goes to under which of the
two credentials, how each answer is read, and which failures mean the provider
could not be asked at all.

Four surfaces, and they fail differently. Evaluation says which flags are on now,
and an outage there must never read as "none is". The admin read of one flag says
what the provider itself holds for it, dated by the provider's own clock - which
is what a change is planned over, since evaluation is a cache and says nothing of
when. The event log says what changed, in which direction and by whom - which
current state cannot, since a flag switched off into an incident evaluates exactly
like one off for a year. And the admin toggle changes a flag, and is not done
until evaluation agrees: Unleash accepts the write before the change reaches
evaluation, and a caller trusting the write would judge a service nothing had yet
been done to.

The provider is a `MockTransport` rather than a stubbed function, so what is
asserted is the request as it would leave the process: method, path and the
credential it carries.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx2
import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    dont_care_sleep,
    one_record_was_logged,
    the_answer_was,
)
from core import to_iso
from core.models import FlagChange, FlagState, FlagUndo
from flag_provider import FlagProviderUnavailable, FlagWriteFailed
from flag_provider.unleash import (
    Unleash,
    UnleashFrontend,
    UnleashFrontendSettings,
    UnleashSettings,
)

DONT_CARE_BASE_URL = "http://flags.invalid"
SOME_FRONTEND_TOKEN = "default:production.some-frontend-token"
SOME_ADMIN_TOKEN = "*:*.some-admin-token"
SOME_PROJECT = "kuki-project"
SOME_ENVIRONMENT = "production"
SOME_OTHER_ENVIRONMENT = "development"
# The name the provider records Argus's own writes under.
SOME_ARGUS_ACTOR = "Shuki Tuki"
SOME_HUMAN = "admin"
# No name configured: Argus and its operators share one credential, and the
# provider cannot tell their changes apart.
NO_ACTOR = ""

SOME_FLAG = "monthly-spend-feature"
SOME_OTHER_FLAG = "recommendations-v2"

# The routes, as a real Unleash spells them.
THE_EVALUATION = "/api/frontend"
THE_EVENTS = "/api/admin/events"

# The provider's own names for the two events that change what a service
# evaluates, spelled out rather than imported: this file is what pins them.
ENABLED_EVENT = "feature-environment-enabled"
DISABLED_EVENT = "feature-environment-disabled"

GET = "GET"
POST = "POST"

SINCE = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
BEFORE_THE_WINDOW = SINCE - timedelta(minutes=28, seconds=52.119)
INSIDE_THE_WINDOW = SINCE + timedelta(minutes=4, seconds=38.033)
LATER_IN_THE_WINDOW = SINCE + timedelta(minutes=9, seconds=12.581)

# The provider's own time on its answer to an admin read. Whole seconds, since a
# `Date` header carries no finer.
SOME_READ_AT = datetime(2026, 9, 6, 17, 37, tzinfo=UTC)
# The same moment in the asctime format RFC 9110 (5.6.7) has a recipient accept,
# which names no zone - every HTTP date being GMT.
SOME_READ_AT_IN_ASCTIME = "Sun Sep  6 17:37:00 2026"

# What a refused connection says of itself, which is the tail of every message a
# failure to reach the provider carries.
REFUSED = "connection refused"


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


# One answer to one request, built fresh each time it is asked for - or raising,
# for a provider that never answered.
_Answer = Callable[[], httpx2.Response]


@dataclass
class _Provider:
    """Unleash's routes, answering what each case set and recording what was asked.

    A route given several answers gives them in turn and then repeats the last,
    which is how a provider that catches up after some reads is staged. A route
    nobody set answers 404, so a request sent somewhere it should not go fails
    the case rather than being quietly answered.
    """

    answers: dict[tuple[str, str], list[_Answer]] = field(default_factory=dict)
    asked: list[httpx2.Request] = field(default_factory=list)

    def answering(self, method: str, path: str, *answers: _Answer) -> _Provider:
        self.answers[(method, path)] = list(answers)
        return self

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.asked.append(request)
        queued = self.answers.get((request.method, request.url.path))

        if not queued:
            return httpx2.Response(404)

        answer = queued.pop(0) if len(queued) > 1 else queued[0]

        return answer()

    def requests_to(self, method: str, path: str) -> list[httpx2.Request]:
        return [
            request for request in self.asked
            if (request.method, request.url.path) == (method, path)
        ]


def _evaluating(*flags: str) -> _Answer:
    """Evaluation as Unleash answers it: the flags that evaluate true, and only
    those - a flag that is off is absent rather than present and false."""
    return lambda: httpx2.Response(200, json={
        "toggles": [_a_toggle(flag) for flag in flags]
    })


def _evaluating_toggles(*toggles: dict[str, Any]) -> _Answer:
    return lambda: httpx2.Response(200, json={"toggles": list(toggles)})


def _recording(*events: dict[str, Any]) -> _Answer:
    """The event log as Unleash answers it: newest first, the whole log."""
    return lambda: httpx2.Response(200, json={
        "version": 1, "events": list(events), "totalEvents": len(events)
    })


def _holding(flag: str,
             environments: dict[str, bool],
             dated: str | None = format_datetime(SOME_READ_AT, usegmt=True)) -> _Answer:
    """One feature as the admin API answers for it - its `featureSchema`, with
    each environment the flag can be used in and whether it is on there - and the
    `Date` header the answer was sent with, or none."""
    headers = {} if dated is None else {"Date": dated}

    return lambda: httpx2.Response(200, json={
        "name": flag,
        "project": SOME_PROJECT,
        "type": "release",
        "stale": False,
        "environments": [
            {"name": environment, "enabled": enabled, "type": "production",
             "sortOrder": 1, "strategies": []}
            for environment, enabled in environments.items()
        ]
    }, headers=headers)


def _accepting(dated: str | None = None) -> _Answer:
    """The admin toggle taking the write, with the `Date` header it was sent
    with - or none."""
    headers = {} if dated is None else {"Date": dated}

    return lambda: httpx2.Response(200, json={}, headers=headers)


def _answering_status(status: int) -> _Answer:
    return lambda: httpx2.Response(status, json={"error": "dont-care"})


def _answering_text(text: str) -> _Answer:
    return lambda: httpx2.Response(200, text=text)


def _failing_with(error: Exception) -> _Answer:
    def answer() -> httpx2.Response:
        raise error

    return answer


def _the_feature(flag: str) -> str:
    return f"/api/admin/projects/{SOME_PROJECT}/features/{flag}"


def _the_toggle_of(flag: str, enabled: bool) -> str:
    return f"{_the_feature(flag)}/environments/{SOME_ENVIRONMENT}/{'on' if enabled else 'off'}"


def _a_toggle(name: str, enabled: bool = True) -> dict[str, Any]:
    return {"name": name, "enabled": enabled, "variant": {"name": "disabled"}}


def _an_event(event_type: str,
              flag: str | None,
              at: datetime,
              created_by: str | None = "dont-care-actor",
              environment: str = SOME_ENVIRONMENT,
              event_id: int = 11) -> dict[str, Any]:
    """One row of the provider's event log, in its own wire shape. A row with no
    author has no `createdBy` at all."""
    event: dict[str, Any] = {
        "id": event_id,
        "type": event_type,
        "createdAt": _as_the_provider_dates(at),
        "featureName": flag,
        "project": SOME_PROJECT,
        "environment": environment
    }

    if created_by is not None:
        event["createdBy"] = created_by

    return event


def _an_enabling_of(flag: str,
                    at: datetime,
                    created_by: str | None = "dont-care-actor",
                    environment: str = SOME_ENVIRONMENT,
                    event_id: int = 11) -> dict[str, Any]:
    return _an_event(ENABLED_EVENT, flag, at, created_by, environment, event_id)


def _a_disabling_of(flag: str,
                    at: datetime,
                    created_by: str | None = "dont-care-actor",
                    environment: str = SOME_ENVIRONMENT,
                    event_id: int = 11) -> dict[str, Any]:
    return _an_event(DISABLED_EVENT, flag, at, created_by, environment, event_id)


def _as_the_provider_dates(moment: datetime) -> str:
    """A moment as the event log spells it: milliseconds, and `Z` for UTC."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _settings(actor: str = SOME_ARGUS_ACTOR,
              environment: str = SOME_ENVIRONMENT) -> UnleashSettings:
    """Every field named, so a developer's own environment reaches no case."""
    return UnleashSettings(
        base_url=DONT_CARE_BASE_URL,
        frontend_token=SOME_FRONTEND_TOKEN,
        admin_token=SOME_ADMIN_TOKEN,
        project=SOME_PROJECT,
        environment=environment,
        actor=actor
    )


def _unleash_over(provider: _Provider,
                  actor: str = SOME_ARGUS_ACTOR,
                  environment: str = SOME_ENVIRONMENT) -> Unleash:
    """The write adapter, reaching only `provider` and never sleeping.

    The host does not resolve, so a request that escaped the transport would fail
    as a connection error rather than reach anything real.
    """
    return Unleash(
        _settings(actor=actor, environment=environment),
        transport=httpx2.MockTransport(provider),
        sleep=dont_care_sleep
    )


def _frontend_over(provider: _Provider) -> UnleashFrontend:
    return UnleashFrontend(
        UnleashFrontendSettings(base_url=DONT_CARE_BASE_URL,
                                frontend_token=SOME_FRONTEND_TOKEN),
        transport=httpx2.MockTransport(provider)
    )


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_frontend_asks_with_the_evaluation_credential() -> None:
    # The read tier holds the evaluation token and no other. If this call ever
    # started authenticating with something that could change a flag, the tier
    # split would be a comment rather than a property of the process.
    provider = _Provider().answering(GET, THE_EVALUATION, _evaluating())

    Scenario() \
        .given(frontend := _frontend_over(provider)) \
        .when(lambda: frontend.enabled()) \
        .then(lambda _: _every_request_to_carried(
            provider, GET, THE_EVALUATION, SOME_FRONTEND_TOKEN
        ))


@pytest.mark.unit
def test_the_frontend_settings_have_nowhere_to_put_the_admin_credential() -> None:
    # The read tier is incapable of mutation rather than disinclined (spec §13),
    # and a type that cannot name the credential is how it stays true on the day
    # somebody puts one in the environment.
    Scenario() \
        .when(lambda: set(UnleashFrontendSettings.model_fields)) \
        .then(the_answer_was({"base_url", "frontend_token"}))


@pytest.mark.unit
def test_a_flag_is_set_with_the_admin_credential() -> None:
    # The write tier exists to hold this one. A change authenticating with the
    # evaluation credential fails against a real provider.
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, False), _accepting()) \
        .answering(GET, THE_EVALUATION, _evaluating())

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.set(SOME_FLAG, False)) \
        .then(lambda _: _every_request_to_carried(
            provider, POST, _the_toggle_of(SOME_FLAG, False), SOME_ADMIN_TOKEN
        ))


@pytest.mark.unit
def test_a_flag_set_is_confirmed_with_the_evaluation_credential() -> None:
    # Confirmed as the service sees it: the evaluation the Target Service reads
    # is answered to the evaluation credential.
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, False), _accepting()) \
        .answering(GET, THE_EVALUATION, _evaluating())

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.set(SOME_FLAG, False)) \
        .then(lambda _: _every_request_to_carried(
            provider, GET, THE_EVALUATION, SOME_FRONTEND_TOKEN
        ))


@pytest.mark.unit
def test_the_history_is_read_with_the_admin_credential() -> None:
    # The provider serves its event log to admin tokens alone, which is why the
    # audit lives in the write tier at all.
    provider = _Provider().answering(GET, THE_EVENTS, _recording())

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.changes_since(SINCE)) \
        .then(lambda _: _every_request_to_carried(
            provider, GET, THE_EVENTS, SOME_ADMIN_TOKEN
        ))


@pytest.mark.unit
def test_a_flags_state_is_read_with_the_admin_credential() -> None:
    # The admin API answers admin tokens alone, which is why the read a change
    # is planned over lives in the write tier.
    provider = _Provider().answering(
        GET, _the_feature(SOME_FLAG), _holding(SOME_FLAG, {SOME_ENVIRONMENT: True})
    )

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.state_of(SOME_FLAG)) \
        .then(lambda _: _every_request_to_carried(
            provider, GET, _the_feature(SOME_FLAG), SOME_ADMIN_TOKEN
        ))


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_enabled_flag_is_reported() -> None:
    provider = _Provider().answering(GET, THE_EVALUATION, _evaluating(SOME_FLAG))

    Scenario() \
        .given(frontend := _frontend_over(provider)) \
        .when(lambda: frontend.enabled()) \
        .then(the_answer_was([SOME_FLAG]))


@pytest.mark.unit
def test_every_enabled_flag_is_reported_in_the_order_the_provider_lists_them() -> None:
    # Not alphabetical, so an adapter that sorted would be caught.
    provider = _Provider().answering(
        GET, THE_EVALUATION, _evaluating(SOME_OTHER_FLAG, SOME_FLAG)
    )

    Scenario() \
        .given(frontend := _frontend_over(provider)) \
        .when(lambda: frontend.enabled()) \
        .then(the_answer_was([SOME_OTHER_FLAG, SOME_FLAG]))


@pytest.mark.unit
def test_a_flag_the_provider_does_not_mention_is_not_enabled() -> None:
    # The provider answers with the flags that evaluate true; one that is off is
    # absent rather than present and false. A reader that looked for
    # `enabled: false` would find nothing and report every flag as on.
    provider = _Provider().answering(GET, THE_EVALUATION, _evaluating())

    Scenario() \
        .given(frontend := _frontend_over(provider)) \
        .when(lambda: frontend.enabled()) \
        .then(the_answer_was([]))


@pytest.mark.unit
def test_a_flag_reported_as_not_enabled_is_not_reported() -> None:
    # Honoured where it appears: a provider that started reporting disabled
    # toggles would otherwise have every one of them read as on - a healthy
    # environment turned into a flag Mitigation reverts.
    provider = _Provider().answering(
        GET, THE_EVALUATION, _evaluating_toggles(_a_toggle(SOME_FLAG, enabled=False))
    )

    Scenario() \
        .given(frontend := _frontend_over(provider)) \
        .when(lambda: frontend.enabled()) \
        .then(the_answer_was([]))


@pytest.mark.unit
def test_the_write_adapter_reads_what_is_enabled_as_the_frontend_does() -> None:
    # It is a reads port too, and confirms its own writes by the same reading.
    provider = _Provider().answering(GET, THE_EVALUATION, _evaluating(SOME_FLAG))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.enabled()) \
        .then(all_of(
            the_answer_was([SOME_FLAG]),
            lambda _: _every_request_to_carried(
                provider, GET, THE_EVALUATION, SOME_FRONTEND_TOKEN
            )
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "answer",
    [
        _failing_with(httpx2.ConnectError(REFUSED)),
        _answering_status(401),
        _answering_status(503),
        _answering_text("<html>login</html>")
    ],
    ids=["unreachable", "refused the credential", "down", "not json"]
)
def test_a_provider_that_could_not_be_asked_is_unavailable_rather_than_nothing_enabled(
    answer: _Answer
) -> None:
    # "Could not ask" and "nothing is on" are opposite facts. Mitigation reads
    # this to decide which flag to revert; an outage reported as an empty list
    # would look like an environment with no flag to revert at all.
    provider = _Provider().answering(GET, THE_EVALUATION, answer)

    Scenario() \
        .given(frontend := _frontend_over(provider)) \
        .when(attempting(lambda: frontend.enabled())) \
        .then(an_error_was_raised(FlagProviderUnavailable))


@pytest.mark.unit
def test_an_unavailable_provider_says_where_it_was_asked() -> None:
    # Today's words, kept: they are what a walk's record says of the outage.
    provider = _Provider().answering(
        GET, THE_EVALUATION, _failing_with(httpx2.ConnectError(REFUSED))
    )

    Scenario() \
        .given(frontend := _frontend_over(provider)) \
        .when(attempting(lambda: frontend.enabled())) \
        .then(_it_said(
            f"could not read flag state from [{DONT_CARE_BASE_URL}{THE_EVALUATION}]: "
            f"{REFUSED}"
        ))


# ---------------------------------------------------------------------------
# A flag's state, as the provider holds it
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
def test_a_flags_state_is_read_as_the_provider_holds_it_and_dated_by_its_own_clock(
    enabled: bool
) -> None:
    # Both directions, since a change is planned from whichever the flag is in.
    # Dated by the answer's own `Date`, not this process's clock: the history a
    # change is later made over is stamped by the provider, and two clocks
    # compared hide whatever they disagree by.
    provider = _Provider().answering(
        GET, _the_feature(SOME_FLAG),
        _holding(SOME_FLAG, {SOME_ENVIRONMENT: enabled},
                 dated=format_datetime(SOME_READ_AT, usegmt=True))
    )

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.state_of(SOME_FLAG)) \
        .then(the_answer_was(FlagState(enabled=enabled, read_at=SOME_READ_AT)))


@pytest.mark.unit
def test_a_date_naming_no_zone_is_read_as_utc() -> None:
    # Every HTTP date is GMT, and the asctime format is the one that does not
    # say so. Read in this process's zone it would move with the machine; read
    # as no moment, a provider answering in it could never be planned over.
    provider = _Provider().answering(
        GET, _the_feature(SOME_FLAG),
        _holding(SOME_FLAG, {SOME_ENVIRONMENT: True}, dated=SOME_READ_AT_IN_ASCTIME)
    )

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.state_of(SOME_FLAG).read_at) \
        .then(the_answer_was(SOME_READ_AT))


@pytest.mark.unit
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
def test_a_flags_state_is_read_in_the_configured_environment_alone(enabled: bool) -> None:
    # The answer lists every environment the flag can be used in, and the one
    # listed first is not the one asked about. A flag read in an environment
    # nobody is looking at is a change planned from the wrong state.
    provider = _Provider().answering(
        GET, _the_feature(SOME_FLAG),
        _holding(SOME_FLAG, {SOME_OTHER_ENVIRONMENT: not enabled, SOME_ENVIRONMENT: enabled})
    )

    Scenario() \
        .given(unleash := _unleash_over(provider, environment=SOME_ENVIRONMENT)) \
        .when(lambda: unleash.state_of(SOME_FLAG).enabled) \
        .then(the_answer_was(enabled))


@pytest.mark.unit
def test_a_flags_state_is_never_read_from_the_evaluation() -> None:
    # Evaluation is a cache, and says neither what the provider holds nor when.
    # Staged to disagree, so an adapter that read it would answer on.
    provider = _Provider() \
        .answering(GET, _the_feature(SOME_FLAG), _holding(SOME_FLAG, {SOME_ENVIRONMENT: False})) \
        .answering(GET, THE_EVALUATION, _evaluating(SOME_FLAG))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.state_of(SOME_FLAG).enabled) \
        .then(all_of(
            the_answer_was(False),
            lambda _: _it_was_asked_once(provider, GET, _the_feature(SOME_FLAG)),
            lambda _: _evaluation_was_read(provider, times=0)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("dated", [None, "the day before yesterday"],
                         ids=["no date", "an unreadable date"])
def test_a_flags_state_the_provider_did_not_date_is_unavailable(dated: str | None) -> None:
    # Not dated by this process instead: the date is what the change is later
    # made over, and a read with no time of the provider's own cannot be
    # compared with its history.
    provider = _Provider().answering(
        GET, _the_feature(SOME_FLAG), _holding(SOME_FLAG, {SOME_ENVIRONMENT: True}, dated=dated)
    )

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(attempting(lambda: unleash.state_of(SOME_FLAG))) \
        .then(an_error_was_raised(FlagProviderUnavailable))


@pytest.mark.unit
@pytest.mark.parametrize(
    "answer",
    [
        _failing_with(httpx2.ConnectError(REFUSED)),
        _answering_status(401),
        _answering_status(404),
        _answering_status(503),
        _answering_text("<html>login</html>"),
        _holding(SOME_FLAG, {SOME_OTHER_ENVIRONMENT: True})
    ],
    ids=["unreachable", "refused the credential", "no such flag", "down", "not json",
         "not in the configured environment"]
)
def test_a_flags_state_the_provider_could_not_give_is_unavailable(answer: _Answer) -> None:
    # Never a state: a flag read as off because nothing was read is a change
    # planned from a state the flag was never in.
    provider = _Provider().answering(GET, _the_feature(SOME_FLAG), answer)

    Scenario() \
        .given(unleash := _unleash_over(provider, environment=SOME_ENVIRONMENT)) \
        .when(attempting(lambda: unleash.state_of(SOME_FLAG))) \
        .then(an_error_was_raised(FlagProviderUnavailable))


@pytest.mark.unit
def test_an_unreadable_flag_state_says_which_flag_and_where_it_was_asked() -> None:
    provider = _Provider().answering(
        GET, _the_feature(SOME_FLAG), _failing_with(httpx2.ConnectError(REFUSED))
    )

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(attempting(lambda: unleash.state_of(SOME_FLAG))) \
        .then(_it_said(
            f"could not read flag [{SOME_FLAG}] at "
            f"[{DONT_CARE_BASE_URL}{_the_feature(SOME_FLAG)}]: {REFUSED}"
        ))


# ---------------------------------------------------------------------------
# Setting a flag
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
def test_setting_a_flag_addresses_it_in_the_configured_environment(enabled: bool) -> None:
    # Both directions, because an incident can be caused by a flag being
    # withdrawn - a fallback disabled - and an agent that could only turn flags
    # off could not mitigate it.
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, enabled), _accepting()) \
        .answering(GET, THE_EVALUATION, _evaluating(*([SOME_FLAG] if enabled else [])))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.set(SOME_FLAG, enabled)) \
        .then(lambda _: _it_was_asked_once(provider, POST, _the_toggle_of(SOME_FLAG, enabled)))


@pytest.mark.unit
def test_setting_a_flag_off_returns_only_once_it_evaluates_off() -> None:
    # A toggle is not instantly visible through evaluation. Returning before it
    # is would hand Mitigation a window in which it reads the old value and
    # refutes a hypothesis that was right. Two stale answers and then the new
    # one: fewer reads returned early, more kept asking after it caught up.
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, False), _accepting()) \
        .answering(GET, THE_EVALUATION,
                   _evaluating(SOME_FLAG), _evaluating(SOME_FLAG), _evaluating())

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.set(SOME_FLAG, False)) \
        .then(lambda _: _evaluation_was_read(provider, times=3))


@pytest.mark.unit
def test_setting_a_flag_on_returns_only_once_it_evaluates_on() -> None:
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, True), _accepting()) \
        .answering(GET, THE_EVALUATION, _evaluating(), _evaluating(), _evaluating(SOME_FLAG))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.set(SOME_FLAG, True)) \
        .then(lambda _: _evaluation_was_read(provider, times=3))


@pytest.mark.unit
def test_switching_a_flag_off_records_that_it_had_been_on_where_it_was_set() -> None:
    # The undo names the state to restore, not the call that would restore it,
    # and the environment it was changed in - a flag restored in an environment
    # nobody touched leaves the incident's own as the mitigation left it.
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, False), _accepting()) \
        .answering(GET, THE_EVALUATION, _evaluating())

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.set(SOME_FLAG, False)) \
        .then(the_answer_was(FlagUndo(
            flag=SOME_FLAG, was_enabled=True, environment=SOME_ENVIRONMENT, written_at=None
        )))


@pytest.mark.unit
def test_switching_a_flag_on_records_that_it_had_been_off() -> None:
    # The undo of a mitigation that undid a switch-off. Recording `was_enabled`
    # as true here would have the undo leave the flag in the state that caused
    # the incident.
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, True), _accepting()) \
        .answering(GET, THE_EVALUATION, _evaluating(SOME_FLAG))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.set(SOME_FLAG, True).was_enabled) \
        .then(the_answer_was(False))


@pytest.mark.unit
def test_the_undo_is_dated_by_the_providers_own_clock() -> None:
    # An undo asks the provider what changed *since* Argus wrote, and a time
    # taken from Argus's own clock would be compared against the provider's.
    # The write's own response carries the provider's.
    some_moment_the_provider_recorded = datetime(2026, 9, 6, 17, 38, tzinfo=UTC)
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, False), _accepting(
            dated=format_datetime(some_moment_the_provider_recorded, usegmt=True)
        )) \
        .answering(GET, THE_EVALUATION, _evaluating())

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.set(SOME_FLAG, False).written_at) \
        .then(the_answer_was(some_moment_the_provider_recorded))


@pytest.mark.unit
@pytest.mark.parametrize("dated", [None, "the day before yesterday"],
                         ids=["no date", "an unreadable date"])
def test_a_write_the_provider_did_not_date_leaves_the_moment_absent(dated: str | None) -> None:
    # Absent rather than filled in from this process's clock, which would be
    # wrong by whatever the two clocks disagree by. An undo can say it could not
    # establish the state, which is one of its answers.
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, False), _accepting(dated=dated)) \
        .answering(GET, THE_EVALUATION, _evaluating())

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.set(SOME_FLAG, False).written_at) \
        .then(the_answer_was(None))


@pytest.mark.unit
@pytest.mark.parametrize(
    "answer",
    [_failing_with(httpx2.ConnectError(REFUSED)), _answering_status(400),
     _answering_status(503)],
    ids=["never sent", "rejected", "not handled"]
)
def test_a_write_the_provider_never_took_is_known_not_applied(answer: _Answer) -> None:
    # Nothing was sent, or what was sent was read and refused: the flag is as it
    # was, and the failure says so.
    provider = _Provider().answering(POST, _the_toggle_of(SOME_FLAG, False), answer)

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(attempting(lambda: unleash.set(SOME_FLAG, False))) \
        .then(_it_failed_the_write(known_not_applied=True, left_behind=None))


@pytest.mark.unit
@pytest.mark.parametrize(
    "answer",
    [_failing_with(httpx2.ReadTimeout("timed out")), _answering_status(500)],
    ids=["timed out", "faulted"]
)
def test_a_write_whose_answer_was_lost_is_not_said_to_have_changed_nothing(
    answer: _Answer
) -> None:
    # The provider may have flipped it. A failure saying it left nothing would
    # have the record say the flag is as it was.
    provider = _Provider().answering(POST, _the_toggle_of(SOME_FLAG, False), answer)

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(attempting(lambda: unleash.set(SOME_FLAG, False))) \
        .then(_it_failed_the_write(known_not_applied=False, left_behind=None))


@pytest.mark.unit
def test_a_write_that_never_left_says_what_it_was_and_where() -> None:
    provider = _Provider().answering(
        POST, _the_toggle_of(SOME_FLAG, False), _failing_with(httpx2.ConnectError(REFUSED))
    )

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(attempting(lambda: unleash.set(SOME_FLAG, False))) \
        .then(_it_said(
            f"could not set flag [{SOME_FLAG}] off at "
            f"[{DONT_CARE_BASE_URL}{_the_toggle_of(SOME_FLAG, False)}]: {REFUSED}"
        ))


@pytest.mark.unit
def test_a_write_accepted_and_never_seen_in_effect_carries_what_puts_it_back() -> None:
    # The provider took the change, so the flag is flipped whatever evaluation
    # says yet - and recorded nowhere else, it is a flag no withdrawal would put
    # back.
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, False), _accepting()) \
        .answering(GET, THE_EVALUATION, _evaluating(SOME_FLAG))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(attempting(lambda: unleash.set(SOME_FLAG, False))) \
        .then(all_of(
            _it_failed_the_write(known_not_applied=False, left_behind=FlagUndo(
                flag=SOME_FLAG, was_enabled=True, environment=SOME_ENVIRONMENT,
                written_at=None
            )),
            _it_said(f"flag [{SOME_FLAG}] was accepted as off but still evaluates on")
        ))


@pytest.mark.unit
def test_a_write_accepted_and_then_unconfirmable_carries_what_puts_it_back() -> None:
    # The same change taken, and the evaluation read gone with it.
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, False), _accepting()) \
        .answering(GET, THE_EVALUATION, _failing_with(httpx2.ConnectError(REFUSED)))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(attempting(lambda: unleash.set(SOME_FLAG, False))) \
        .then(all_of(
            _it_failed_the_write(known_not_applied=False, left_behind=FlagUndo(
                flag=SOME_FLAG, was_enabled=True, environment=SOME_ENVIRONMENT,
                written_at=None
            )),
            _it_began(f"could not confirm flag [{SOME_FLAG}] is off: ")
        ))


@pytest.mark.unit
def test_a_write_the_provider_did_not_date_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The undo this leaves can only answer that it could not establish the
    # state, and whoever reads that answer later needs to know why.
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, False), _accepting()) \
        .answering(GET, THE_EVALUATION, _evaluating())

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.set(SOME_FLAG, False)) \
        .then(one_record_was_logged(caplog, "flag_provider.unleash", logging.WARNING,
                                    "provider gave no write time",
                                    values={"flag": SOME_FLAG}))


@pytest.mark.unit
def test_a_write_the_provider_dated_unreadably_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The same undo, for a different reason - and the header it could not read
    # is the one thing that says which.
    some_unreadable_date = "the day before yesterday"
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, False),
                   _accepting(dated=some_unreadable_date)) \
        .answering(GET, THE_EVALUATION, _evaluating())

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.set(SOME_FLAG, False)) \
        .then(one_record_was_logged(caplog, "flag_provider.unleash", logging.WARNING,
                                    "provider gave no write time",
                                    values={"flag": SOME_FLAG, "date": some_unreadable_date}))


@pytest.mark.unit
def test_a_flag_that_never_evaluates_as_set_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Not the failure of a provider that refused: the write was taken, and
    # should the provider catch up later, production ends up in a state Argus
    # reported it had not reached.
    provider = _Provider() \
        .answering(POST, _the_toggle_of(SOME_FLAG, False), _accepting()) \
        .answering(GET, THE_EVALUATION, _evaluating(SOME_FLAG))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(attempting(lambda: unleash.set(SOME_FLAG, False))) \
        .then(one_record_was_logged(caplog, "flag_provider.unleash", logging.WARNING,
                                    "flag accepted but not evaluating",
                                    values={"flag": SOME_FLAG, "enabled": False}))


# ---------------------------------------------------------------------------
# What changed
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_change_is_read_as_the_provider_recorded_it() -> None:
    # Every field at once: the flag, the state it was changed *to*, when, by
    # whom, and whether that was Argus. A reader that found the right flag and
    # read its direction backwards is the failure this exists to prevent.
    provider = _Provider().answering(GET, THE_EVENTS, _recording(
        _an_enabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, created_by=SOME_HUMAN)
    ))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.changes_since(SINCE)) \
        .then(the_answer_was([FlagChange(
            flag=SOME_FLAG,
            enabled=True,
            occurred_at=to_iso(INSIDE_THE_WINDOW),
            actor=SOME_HUMAN,
            made_by_argus=False
        )]))


@pytest.mark.unit
def test_a_flag_that_was_switched_off_is_reported_as_disabled() -> None:
    # The case current state cannot answer. A flag switched off into an incident
    # is off now, and so is every flag that has been off for a year - only the
    # history tells the two apart, and only it carries the direction.
    provider = _Provider().answering(GET, THE_EVENTS, _recording(
        _a_disabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW)
    ))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: _what_changed(unleash.changes_since(SINCE))) \
        .then(the_answer_was([(SOME_FLAG, False)]))


@pytest.mark.unit
def test_changes_before_the_window_are_not_reported() -> None:
    # The window is applied here rather than by the provider, whose events
    # endpoint ignores a row limit and answers with the whole log.
    provider = _Provider().answering(GET, THE_EVENTS, _recording(
        _an_enabling_of(SOME_FLAG, at=BEFORE_THE_WINDOW)
    ))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.changes_since(SINCE)) \
        .then(the_answer_was([]))


@pytest.mark.unit
def test_a_change_at_the_very_moment_asked_from_is_reported() -> None:
    # At or after: a resumed walk asks from the moment it claimed an action, and
    # a change it made that same instant is the one it is asking about.
    provider = _Provider().answering(GET, THE_EVENTS, _recording(
        _an_enabling_of(SOME_FLAG, at=SINCE)
    ))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: _what_changed(unleash.changes_since(SINCE))) \
        .then(the_answer_was([(SOME_FLAG, True)]))


@pytest.mark.unit
def test_changes_in_another_environment_are_not_reported() -> None:
    # One Target Service maps to one environment. A flag toggled in staging did
    # not cause the incident in production, and reverting it would change an
    # environment nobody was looking at.
    provider = _Provider().answering(GET, THE_EVENTS, _recording(
        _an_enabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, environment=SOME_OTHER_ENVIRONMENT)
    ))

    Scenario() \
        .given(unleash := _unleash_over(provider, environment=SOME_ENVIRONMENT)) \
        .when(lambda: unleash.changes_since(SINCE)) \
        .then(the_answer_was([]))


@pytest.mark.unit
def test_events_that_are_not_flag_toggles_are_not_reported() -> None:
    # The log records everything the provider does to itself - features
    # created, strategies added, tokens issued. None of them changed what the
    # service evaluates, so none of them is a change to undo.
    provider = _Provider().answering(GET, THE_EVENTS, _recording(
        _an_event("feature-created", SOME_FLAG, at=INSIDE_THE_WINDOW),
        _an_event("feature-strategy-add", SOME_FLAG, at=INSIDE_THE_WINDOW),
        _an_event("api-token-created", None, at=INSIDE_THE_WINDOW)
    ))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.changes_since(SINCE)) \
        .then(the_answer_was([]))


@pytest.mark.unit
def test_changes_are_reported_oldest_first() -> None:
    # The provider answers newest first. Callers ask which change was *latest*,
    # and every other windowed read in Argus runs in time order.
    provider = _Provider().answering(GET, THE_EVENTS, _recording(
        _a_disabling_of(SOME_FLAG, at=LATER_IN_THE_WINDOW, event_id=12),
        _an_enabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, event_id=11)
    ))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: _what_changed(unleash.changes_since(SINCE))) \
        .then(the_answer_was([(SOME_FLAG, True), (SOME_FLAG, False)]))


@pytest.mark.unit
def test_two_changes_within_the_same_second_keep_the_order_they_happened_in() -> None:
    # Timestamps tie within a second, and a flag switched on and straight back
    # off does exactly that. A stable sort on the time keeps the provider's
    # newest-first order, so "the latest change" becomes the earliest and the
    # flag is reverted the wrong way. The provider's event ids do not tie.
    the_same_second = INSIDE_THE_WINDOW
    provider = _Provider().answering(GET, THE_EVENTS, _recording(
        _a_disabling_of(SOME_FLAG, at=the_same_second, event_id=13),
        _an_enabling_of(SOME_FLAG, at=the_same_second, event_id=12)
    ))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: _what_changed(unleash.changes_since(SINCE))) \
        .then(the_answer_was([(SOME_FLAG, True), (SOME_FLAG, False)]))


@pytest.mark.unit
@pytest.mark.parametrize(
    "answer",
    [_failing_with(httpx2.ConnectError(REFUSED)), _answering_status(403),
     _answering_text("<html>login</html>")],
    ids=["unreachable", "refused the credential", "not json"]
)
def test_a_history_that_could_not_be_read_is_unavailable_rather_than_empty(
    answer: _Answer
) -> None:
    # "Nothing changed" is a conclusion Mitigation acts on - it escalates. An
    # outage read as an empty history would look like an environment with
    # nothing to revert, which is a different incident entirely.
    provider = _Provider().answering(GET, THE_EVENTS, answer)

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(attempting(lambda: unleash.changes_since(SINCE))) \
        .then(an_error_was_raised(FlagProviderUnavailable))


@pytest.mark.unit
def test_an_unreadable_history_says_where_it_was_asked() -> None:
    provider = _Provider().answering(
        GET, THE_EVENTS, _failing_with(httpx2.ConnectError(REFUSED))
    )

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(attempting(lambda: unleash.changes_since(SINCE))) \
        .then(_it_said(
            f"could not read flag history at [{DONT_CARE_BASE_URL}{THE_EVENTS}]: {REFUSED}"
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("recorded", "expected"),
    [
        ([], []),
        ([_an_enabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, created_by=SOME_HUMAN)],
         [(SOME_FLAG, True)])
    ],
    ids=["nothing changed", "somebody changed it"]
)
def test_the_history_is_read_where_no_actor_is_configured(
    recorded: list[dict[str, Any]], expected: list[tuple[str, bool]]
) -> None:
    # Whose a change was is a question about each change, not about the read.
    # The write tier makes a change over this one read, and a flag nobody moved
    # since the plan is writable whoever Argus writes as: a history refused
    # before it was read, where Argus and its operators share a credential,
    # would hold back every write in that deployment.
    provider = _Provider().answering(GET, THE_EVENTS, _recording(*recorded))

    Scenario() \
        .given(unleash := _unleash_over(provider, actor=NO_ACTOR)) \
        .when(lambda: _what_changed(unleash.changes_since(SINCE))) \
        .then(all_of(
            the_answer_was(expected),
            lambda _: _it_was_asked_once(provider, GET, THE_EVENTS)
        ))


# ---------------------------------------------------------------------------
# Whose change it was
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("created_by", "expected"),
    [
        (SOME_ARGUS_ACTOR, True),
        (SOME_ARGUS_ACTOR.upper(), True),
        (SOME_HUMAN, False),
        (None, False)
    ],
    ids=["argus", "argus in another case", "somebody else", "nobody recorded"]
)
def test_whether_argus_made_a_change_is_read_off_who_the_provider_says_made_it(
    created_by: str | None, expected: bool
) -> None:
    # Argus writes under a name of its own, so the author is what tells its own
    # revert from a human's. The case is ignored because the name is seeded in
    # one repository and compared in this one, and drift between the two would
    # switch the recognition off quietly. A change nobody is recorded for is not
    # Argus's: "the provider did not say" is not "Argus did it".
    provider = _Provider().answering(GET, THE_EVENTS, _recording(
        _an_enabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, created_by=created_by)
    ))

    Scenario() \
        .given(unleash := _unleash_over(provider, actor=SOME_ARGUS_ACTOR)) \
        .when(lambda: _whether_argus_made_each(unleash.changes_since(SINCE))) \
        .then(the_answer_was([expected]))


@pytest.mark.unit
def test_no_change_is_said_to_be_argus_own_or_not_where_no_actor_is_configured() -> None:
    # Argus and its operators sharing one credential is a real deployment, and
    # there the provider cannot tell their changes apart. `None` on every change,
    # a change under the very name Argus would have used included.
    provider = _Provider().answering(GET, THE_EVENTS, _recording(
        _a_disabling_of(SOME_FLAG, at=LATER_IN_THE_WINDOW, created_by=SOME_ARGUS_ACTOR,
                        event_id=13),
        _an_enabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, created_by=SOME_HUMAN,
                        event_id=12)
    ))

    Scenario() \
        .given(unleash := _unleash_over(provider, actor=NO_ACTOR)) \
        .when(lambda: _whether_argus_made_each(unleash.changes_since(SINCE))) \
        .then(the_answer_was([None, None]))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("recorded", "expected"),
    [
        ([_an_enabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, created_by=SOME_ARGUS_ACTOR)], True),
        ([_an_enabling_of(SOME_OTHER_FLAG, at=INSIDE_THE_WINDOW,
                          created_by=SOME_ARGUS_ACTOR)], False),
        ([_an_enabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, created_by=SOME_HUMAN)], False),
        ([_an_enabling_of(SOME_FLAG, at=BEFORE_THE_WINDOW, created_by=SOME_ARGUS_ACTOR)],
         False),
        ([], False)
    ],
    ids=["argus changed it", "argus changed another flag", "somebody else changed it",
         "argus changed it before the moment asked", "nothing changed"]
)
def test_whether_argus_changed_a_flag_since_a_moment(recorded: list[dict[str, Any]],
                                                     expected: bool) -> None:
    # The question a walk asks when it is resumed after its worker died with an
    # action claimed: did the change it was making land? Only the provider knows.
    # A human moving the same flag is not evidence Argus's change landed, and a
    # change before the claim belongs to whoever caused the incident.
    provider = _Provider().answering(GET, THE_EVENTS, _recording(*recorded))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.argus_changed_since(SOME_FLAG, SINCE)) \
        .then(_it_answered(expected))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("recorded", "expected"),
    [
        ([_an_enabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, created_by=SOME_HUMAN)], True),
        ([_an_enabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, created_by=None)], True),
        ([_an_enabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, created_by=SOME_ARGUS_ACTOR)],
         False),
        ([_an_enabling_of(SOME_OTHER_FLAG, at=INSIDE_THE_WINDOW, created_by=SOME_HUMAN)],
         False),
        ([_an_enabling_of(SOME_FLAG, at=BEFORE_THE_WINDOW, created_by=SOME_HUMAN)], False),
        ([], False)
    ],
    ids=["somebody else changed it", "nobody recorded changed it", "only argus changed it",
         "somebody else changed another flag", "somebody changed it before the moment asked",
         "nothing changed"]
)
def test_whether_anybody_else_changed_a_flag_since_a_moment(recorded: list[dict[str, Any]],
                                                            expected: bool) -> None:
    # What an undo consults before it writes: a change made after Argus's own is
    # somebody's deliberate decision, and putting the flag back would overwrite
    # it. A change nobody is recorded for counts as somebody else's - a flag left
    # as found can be put back by hand, and an overwritten decision cannot.
    provider = _Provider().answering(GET, THE_EVENTS, _recording(*recorded))

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: unleash.others_changed_since(SOME_FLAG, SINCE)) \
        .then(_it_answered(expected))


@pytest.mark.unit
@pytest.mark.parametrize("question", ["argus_changed_since", "others_changed_since"])
@pytest.mark.parametrize(
    "recorded",
    [[], [_an_enabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, created_by=SOME_HUMAN)]],
    ids=["nothing changed", "somebody changed it"]
)
def test_neither_question_is_answered_where_no_actor_is_configured(
    question: str, recorded: list[dict[str, Any]]
) -> None:
    # Nobody can say, and that includes a log with nothing in it. Told `False`,
    # a resumed walk would act again on something that may already have been
    # done; told either answer, an undo would act on a guess about whose write
    # it was looking at.
    provider = _Provider().answering(GET, THE_EVENTS, _recording(*recorded))

    Scenario() \
        .given(unleash := _unleash_over(provider, actor=NO_ACTOR)) \
        .when(lambda: getattr(unleash, question)(SOME_FLAG, SINCE)) \
        .then(_it_answered(None))


@pytest.mark.unit
@pytest.mark.parametrize("question", ["argus_changed_since", "others_changed_since"])
def test_neither_question_is_answered_where_the_history_could_not_be_read(
    question: str
) -> None:
    # Not raised: "could not ask" is an answer both callers have a move for,
    # and not `False`, which is the difference between acting again and
    # escalating - or between putting a change back and overwriting a person.
    provider = _Provider().answering(
        GET, THE_EVENTS, _failing_with(httpx2.ConnectError(REFUSED))
    )

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: getattr(unleash, question)(SOME_FLAG, SINCE)) \
        .then(_it_answered(None))


@pytest.mark.unit
@pytest.mark.parametrize("question", ["argus_changed_since", "others_changed_since"])
def test_a_history_that_could_not_be_read_for_a_question_is_logged(
    question: str, caplog: pytest.LogCaptureFixture
) -> None:
    # Answered as nobody-can-say, which is right, and which loses the reason -
    # so the reason is logged here, where the failure still is.
    provider = _Provider().answering(
        GET, THE_EVENTS, _failing_with(httpx2.ConnectError(REFUSED))
    )

    Scenario() \
        .given(unleash := _unleash_over(provider)) \
        .when(lambda: getattr(unleash, question)(SOME_FLAG, SINCE)) \
        .then(one_record_was_logged(caplog, "flag_provider.unleash", logging.WARNING,
                                    "flag history could not be read",
                                    values={"flag": SOME_FLAG},
                                    failure=FlagProviderUnavailable))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_provider_is_configured_by_the_variables_it_always_was(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    # The names a deployment already sets, unchanged by the move out of the
    # kernel's `Settings` - a renamed variable is a deployment that silently
    # falls back to its defaults.
    some_base_url = "http://kuki.invalid:4242"
    some_frontend_token = "default:staging.kuki-frontend-token"
    some_admin_token = "*:*.kuki-admin-token"
    some_project = "buki-project"
    some_environment = "staging"
    some_actor = "Kuki Buki"

    Scenario() \
        .given(
            calling(lambda: monkeypatch.setenv("UNLEASH_BASE_URL", some_base_url)),
            calling(lambda: monkeypatch.setenv("UNLEASH_FRONTEND_TOKEN", some_frontend_token)),
            calling(lambda: monkeypatch.setenv("UNLEASH_ADMIN_TOKEN", some_admin_token)),
            calling(lambda: monkeypatch.setenv("UNLEASH_PROJECT", some_project)),
            calling(lambda: monkeypatch.setenv("UNLEASH_ENVIRONMENT", some_environment)),
            calling(lambda: monkeypatch.setenv("UNLEASH_ACTOR", some_actor))
        ) \
        .when(lambda: (UnleashSettings(), UnleashFrontendSettings())) \
        .then(the_answer_was((
            UnleashSettings(base_url=some_base_url,
                            frontend_token=some_frontend_token,
                            admin_token=some_admin_token,
                            project=some_project,
                            environment=some_environment,
                            actor=some_actor),
            UnleashFrontendSettings(base_url=some_base_url,
                                    frontend_token=some_frontend_token)
        )))


@pytest.mark.unit
def test_an_unconfigured_provider_is_the_demos() -> None:
    # The defaults the kernel's `Settings` declared before the settings moved,
    # spelled out because there is nothing left to derive them from. Read off
    # the declared defaults rather than off a `UnleashSettings()`, which would
    # read the developer's own environment. The admin token is empty so a
    # misconfigured write server fails loudly rather than authenticating as
    # nobody; the actor is the name the Target Environment seeds.
    the_demos_provider = "http://localhost:4242"
    the_demos_evaluation_token = "default:production.argus-demo-frontend-token"

    Scenario() \
        .when(lambda: (UnleashSettings.model_construct().model_dump(),
                       UnleashFrontendSettings.model_construct().model_dump())) \
        .then(the_answer_was((
            {
                "base_url": the_demos_provider,
                "frontend_token": the_demos_evaluation_token,
                "admin_token": "",
                "project": "default",
                "environment": "production",
                "actor": "Argus"
            },
            {
                "base_url": the_demos_provider,
                "frontend_token": the_demos_evaluation_token
            }
        )))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _what_changed(changes: list[FlagChange]) -> list[tuple[str, bool]]:
    """Which flags changed, and which way each went - the pair rather than
    either half, since the right flag read backwards is the failure that
    matters."""
    return [(change.flag, change.enabled) for change in changes]


def _whether_argus_made_each(changes: list[FlagChange]) -> list[bool | None]:
    return [change.made_by_argus for change in changes]


def _every_request_to_carried(provider: _Provider,
                              method: str,
                              path: str,
                              credential: str) -> bool:
    """That the route was asked, and asked under this credential every time.

    Read off the requests rather than inferred from the answer, because the
    stand-in answers whatever it is asked under - it is not the provider and
    does not refuse a credential.
    """
    asked = provider.requests_to(method, path)

    if not asked:
        raise AssertionError(
            f"Expected a {method} to [{path}], and the provider was asked "
            f"{[(request.method, request.url.path) for request in provider.asked]}."
        )

    carried = [request.headers.get("Authorization") for request in asked]

    if any(each != credential for each in carried):
        raise AssertionError(
            f"Expected every {method} to [{path}] to carry [{credential}], and they "
            f"carried {carried}"
        )

    return True


def _it_was_asked_once(provider: _Provider, method: str, path: str) -> bool:
    asked = provider.requests_to(method, path)

    if len(asked) != 1:
        raise AssertionError(
            f"Expected one {method} to [{path}], and the provider was asked "
            f"{[(request.method, request.url.path) for request in provider.asked]}."
        )

    return True


def _evaluation_was_read(provider: _Provider, times: int) -> bool:
    """Counted rather than "more than once", because the provider lags by a known
    number of reads: fewer means it returned early, more that it kept asking
    after the provider had caught up."""
    read = len(provider.requests_to(GET, THE_EVALUATION))

    if read != times:
        raise AssertionError(f"Expected evaluation read [{times}] times, got [{read}].")

    return True


def _it_answered(expected: bool | None) -> Assertion[bool | None]:
    """`is` rather than `==`: `None` and `False` are the whole distinction here."""
    def assertion(answer: bool | None) -> bool:
        if answer is not expected:
            raise AssertionError(f"Expected the answer [{expected}], got [{answer}].")

        return True

    return assertion


def _it_said(expected: str) -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if str(error) != expected:
            raise AssertionError(f"Expected the failure to say [{expected}], got [{error}].")

        return True

    return assertion


def _it_began(expected: str) -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if not str(error).startswith(expected):
            raise AssertionError(
                f"Expected the failure to begin [{expected}], got [{error}]."
            )

        return True

    return assertion


def _it_failed_the_write(known_not_applied: bool,
                         left_behind: FlagUndo | None) -> Assertion[Exception | None]:
    """The write's failure, and both things it says of the flag: whether the
    write is known not to have landed, and what puts it back if it did.

    Every wrong field reported together, since a failure saying it left nothing
    while carrying an undo is two mistakes and the second is the costly one.
    """
    def assertion(error: Exception | None) -> bool:
        if not isinstance(error, FlagWriteFailed):
            raise AssertionError(
                f"Expected the write to fail as FlagWriteFailed, and what was raised "
                f"was {error!r}."
            )

        wanted: dict[str, object] = {
            "known_not_applied": known_not_applied, "left_behind": left_behind
        }
        wrong = {
            name: (expected, getattr(error, name))
            for name, expected in wanted.items()
            if getattr(error, name) != expected
        }

        if wrong:
            raise AssertionError(
                f"Expected the failure to say {wanted}, and {wrong} differed "
                f"(expected, got): [{error}]."
            )

        return True

    return assertion
