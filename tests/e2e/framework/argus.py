from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx
import psycopg
from agent_postmortem.prompting import SUBMIT_TOOL_NAME
from argus_core.config import get_settings
from argus_core.models.incident_status import IncidentStatus
from argus_core.replay import CallType
from argus_testkit import Assertion, all_of
from orchestrator.repository import hypotheses, incidents, postmortems, replay, timeline

"""Talking to a running Argus stack, and asserting on what it did.

Shared by every e2e test rather than restated in each: an assertion about
"the incident this webhook call created" is the same assertion whichever
scenario is driving it, and two copies drift the moment one is fixed.

Everything here takes the webhook's `httpx.Response`, because that is what a
`Scenario`'s `when` produces and the only handle a test has on the incident
Argus created for it.
"""

ARGUS_WEB_BASE_URL = "http://localhost:8000"
TARGET_SERVICE_BASE_URL = "http://localhost:8080"
DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"
ANTHROPIC_DOUBLE_BASE_URL = "http://localhost:8091"

WEBHOOK_PATH = "/webhooks/alerts"

REQUEST_TIMEOUT_SECONDS = 10.0

# An investigation is bounded by `investigation_max_seconds`, but the budget is
# only consulted between turns - a model call already in flight runs to
# completion past it. So the wall-clock worst case is that bound plus one call,
# each one adaptive thinking at high effort. Argus answers in seconds when it is
# confident on the first pass; this is what "the investigation ran out of time"
# looks like, not the expected duration.
GENEROUS_MODEL_CALL_SECONDS = 90
INVESTIGATION_TIMEOUT_SECONDS = int(
    get_settings().investigation_max_seconds + GENEROUS_MODEL_CALL_SECONDS
)
MITIGATION_TIMEOUT_SECONDS = (
    INVESTIGATION_TIMEOUT_SECONDS
    + get_settings().mitigation_verification_timeout_seconds
)

# A walk tries its candidates one at a time, and each one waits out the
# verification window before it can be called refuted - so an incident Argus
# does not solve on its first guess costs several of those windows, not one.
#
# Sized for a single round's worth of candidates rather than for the worst case
# the settings permit (every round, every candidate), which would be forty
# minutes of a suite sitting on a failure before reporting it. A run that
# somehow exceeds this is a slow failure either way; a bound nobody waits for is
# not a safety net.
WALK_TIMEOUT_SECONDS = int(
    INVESTIGATION_TIMEOUT_SECONDS
    + get_settings().investigation_max_candidates
    * get_settings().mitigation_verification_timeout_seconds
)

# The recordings that answer for the model, by the names they are stored under
# in modules/anthropic_double/recordings/.
RECORDED_FLAG_TOGGLE = "feature-flag-toggle"
RECORDED_BAD_DEPLOYMENT = "bad-deployment"
RECORDED_FALLBACK_DISABLED = "fallback-disabled"
RECORDED_ABSENCE_OF_EVIDENCE = "no-evidence"
RECORDED_FLAG_TOGGLE_RED_HERRING = "flag-toggle-red-herring"
RECORDED_FLAG_TOGGLE_UNCORROBORATED = "flag-toggle-uncorroborated"


# Not arbitrary! the Target Service names itself in its own log
THE_SERVICE_NAME = "io-shop"


def argus_is_triggered_with_alert(
    payload: dict[str, Any]
) -> Callable[[], httpx.Response]:
    """Fires the alert, and waits for everything it starts.

    The wait is the whole incident, not a round trip: the webhook runs the graph
    in-process and answers only once it has finished. That used to mean one
    investigation, and it now means the walk - every candidate tried, each with
    its own verification window, and a fresh investigation between rounds. So
    this waits on the walk's budget rather than the investigation's; waiting on
    the shorter one fails the *client* while Argus is still working, which reads
    like a hung stack and is not one.
    """
    def step() -> httpx.Response:
        return httpx.post(
            f"{ARGUS_WEB_BASE_URL}{WEBHOOK_PATH}",
            json=payload,
            timeout=WALK_TIMEOUT_SECONDS,
        )

    return step


def incident_id_from(response: httpx.Response) -> str:
    incident_id = response.json().get("incident_id")

    if not incident_id:
        raise AssertionError(f"No incident_id in response: [{response.text}].")

    return str(incident_id)


def argus_returns_status(expected_status: int | HttpStatus) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        if response.status_code != expected_status:
            raise AssertionError(
                f"Expected status [{expected_status}], but got [{response.status_code}]."
            )

        return True

    return assertion


def about_the_hypothesis(
    *hypothesis_assertions: Assertion[Any]
) -> Assertion[httpx.Response]:
    """Adapts assertions about a `Hypothesis` to the webhook response a
    scenario ends with, so the domain assertions in `tests/framework` stay
    shared with the eval and integration tiers rather than being restated
    against a database row here.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            hypothesis = hypotheses.get_latest_by_incident(conn, incident_id)

        if hypothesis is None:
            raise AssertionError(f"No hypothesis found for incident [{incident_id}].")

        return all_of(*hypothesis_assertions)(hypothesis)

    return assertion


def argus_ended_with_status(expected_status: IncidentStatus) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != expected_status:
            raise AssertionError(
                f"Expected incident [{incident_id}] to be [{expected_status}], "
                f"got [{incident.status}]."
            )

        return True

    return assertion


def argus_went_through_statuses(*expected: IncidentStatus) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            events = timeline.get_timeline_events(conn, incident_id)

        actual = [event.to_status for event in events]

        if actual != list(expected):
            raise AssertionError(
                f"Expected status transitions {[str(status) for status in expected]}, "
                f"got {actual}."
            )

        return True

    return assertion


def argus_registered_an_incident_for_the_alert(
    alert_payload: dict[str, Any]
) -> Assertion[httpx.Response]:
    """The alert reached the database in Argus's own shape.

    The absent `labels` key is the point: a vendor's nesting must not survive
    past the webhook adapter (spec §7.9, §25).
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)
        alert = alert_payload["alerts"][0]

        with psycopg.connect(DATABASE_URL) as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        alert_in_db = incident.alert_payload
        expected_service = alert["labels"]["service"]
        actual_service = alert_in_db["service"]
        expected_alert_name = alert["labels"]["alertname"]
        actual_alert_name = alert_in_db["alert_name"]

        if actual_service != expected_service:
            raise AssertionError(
                f"Expected service [{expected_service!r}], got [{actual_service!r}]."
            )

        if actual_alert_name != expected_alert_name:
            raise AssertionError(
                f"Expected alert_name [{expected_alert_name!r}], got [{actual_alert_name!r}]."
            )

        if "labels" in alert_in_db:
            raise AssertionError(
                f"Expected alert_payload to not leak Grafana's raw 'labels' "
                f"nesting: [{alert_in_db!r}]."
            )

        return True

    return assertion


def argus_created_a_postmortem_for_the_incident() -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            postmortem = postmortems.get_by_incident(conn, incident_id)

        if postmortem is None:
            raise AssertionError(f"No postmortem exists for incident [{incident_id}].")

        # What separates a real postmortem from the stub that stood here: prose
        # the model wrote about this incident, and a token count only the
        # replay log could have supplied.
        if not postmortem.root_cause or not postmortem.executive_summary:
            raise AssertionError(
                f"Postmortem for [{incident_id}] carries no prose: "
                f"root cause [{postmortem.root_cause!r}], "
                f"summary [{postmortem.executive_summary!r}].")

        if postmortem.tokens_spent is None:
            raise AssertionError(
                f"Postmortem for [{incident_id}] reports no tokens spent, so nothing "
                f"counted what the incident cost.")

        spent_before_the_postmortem = _tokens_spent_excluding_postmortem(incident_id)

        if postmortem.tokens_spent != spent_before_the_postmortem:
            raise AssertionError(
                f"Postmortem for [{incident_id}] reports [{postmortem.tokens_spent}] "
                f"tokens spent, and its replay log adds up to "
                f"[{spent_before_the_postmortem}].")

        return True

    return assertion


def the_model_answers_from(recording: str) -> Callable[[], bool]:
    """A `given` step naming the stored answers the model gives for this case.

    The counterpart to seeding the Target Service's scenario: one says what the
    service did, the other says what the model said about it. Both are
    stand-ins, so both are arranged in the test rather than one being supplied
    invisibly by a fixture - and a case wanting a mismatched pair (a deploy
    scenario the model finds nothing in) can write one.

    Answers, plural, because one incident is several calls. A walk investigates,
    has its first candidate refuted, and investigates again carrying that
    refutation - and the real model answers those differently, which is the
    whole reason a second candidate is ever reached. A single answer repeated
    made the replayed run re-derive its first verdict, refuse to act twice on
    the same subject, and escalate: the free suite reported a pass on a walk
    that had never walked. Recording already captures the set - `name`,
    `name-2`, `name-3` - so the answers were always there to serve; nothing
    served them in order.

    Every answer is served once, in order. Nothing repeats: the postmortem's
    answer sits behind the verdict, and a seed that answered twice would park
    at the head of the queue and hand the verdict to the call that comes after
    it. A replay that wants more answers than were recorded therefore runs the
    queue dry and fails saying so, rather than quietly re-deriving the walk it
    already took.

    Resets first, because a seed from an earlier case answers until it is
    cleared, and a test whose verdict came from the previous test's recording
    is worse than a failing one.

    Against `nox -s e2e` this seeds a double nothing is pointed at, and is
    harmlessly ignored - which is what lets one set of cases serve both the
    paid path and the replayed one.
    """
    def step() -> bool:
        with httpx.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
            control.post("/double-control/reset").raise_for_status()

            for answered_once in _the_answers_recorded_for(recording, control):
                control.post(
                    "/double-control/seed",
                    json={"recording": answered_once, "repeat": 1},
                ).raise_for_status()

        return True

    return step


def _the_answers_recorded_for(recording: str, control: httpx.Client) -> list[str]:
    """Every stored answer belonging to one incident, in the order it was given.

    Asked of the double rather than the filesystem: the recordings belong to it,
    and a test reaching into another package's directory to list them would be
    a second opinion about what is available.

    A name with no numbered siblings answers as itself, which is every case that
    resolves on its first verdict - so this changes nothing for them.
    """
    state = control.get("/double-control/state")
    state.raise_for_status()

    belonging = [
        name
        for name in state.json().get("available_recordings", [])
        if name == recording or _is_a_later_answer_of(name, recording)
    ]

    return sorted(belonging, key=_the_order_it_was_answered_in) or [recording]


def _is_a_later_answer_of(name: str, recording: str) -> bool:
    """Whether `name` is one of `recording`'s numbered continuations.

    The digits are checked, not just the prefix: two recordings can share a
    stem, and a case seeded with somebody else's answer fails in a way nobody
    reads as a naming collision.
    """
    return name.startswith(f"{recording}-") and name[len(recording) + 1:].isdigit()


def _the_order_it_was_answered_in(name: str) -> int:
    """The call this answer came back from - the bare name being the first.

    Numeric, because sorting these as text puts a tenth answer before a second.
    """
    _, _, suffix = name.rpartition("-")

    return int(suffix) if suffix.isdigit() else 1


def _tokens_spent_excluding_postmortem(incident_id: str) -> int:
    """Every token the incident spent up to the moment it was written up.

    The postmortem's own calls are left out, and have to be: it counts what
    the incident cost before asking the model to describe it, so its own
    conversation is not part of the figure it reports. Which calls those are is
    read from the tools each request offered - an incident that never reached a
    model at all then adds up to nothing, which is a measurement rather than a
    gap.
    """
    with psycopg.connect(DATABASE_URL) as conn:
        entries = replay.get_by_incident(conn, incident_id)

    return sum(
        entry.response.get("input_tokens", 0)
        + entry.response.get("output_tokens", 0)
        + entry.response.get("cache_read_tokens", 0)
        + entry.response.get("cache_write_tokens", 0)
        for entry in entries
        if entry.call_type == CallType.LLM and not _asked_for_a_postmortem(entry.request)
    )


def _asked_for_a_postmortem(request: dict[str, Any]) -> bool:
    return any(tool.get("name") == SUBMIT_TOOL_NAME
               for tool in request.get("tools", []))
