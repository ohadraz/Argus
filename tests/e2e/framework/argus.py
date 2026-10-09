"""Talking to a running Argus stack, and asserting on what it did.

Shared by every e2e test rather than restated in each: an assertion about
"the incident this webhook call created" is the same assertion whichever
scenario is driving it, and two copies drift the moment one is fixed.

Everything here takes the webhook's `httpx2.Response`, because that is what a
`Scenario`'s `when` produces and the only handle a test has on the incident
Argus created for it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from http import HTTPStatus as HttpStatus
from pathlib import Path
from typing import Any, Final

import httpx2
import psycopg
from agent_investigator.tools.answer import ANSWER_TOOL
from agent_investigator.tools.windows import WINDOW_END_ARG, WINDOW_START_ARG
from agent_postmortem.prompting import SUBMIT_TOOL_NAME
from anthropic_double.recordings import RECORDINGS_DIR, load
from anthropic_double.server import DEFAULT_BASE_URL as ANTHROPIC_DOUBLE_BASE_URL
from argus_core import get_settings, parse_iso, to_iso
from argus_core.events import ActionTaken, ChangesRetrieved, FixAttempted, StatusChanged
from argus_core.models import (
    ROLL_BACK_DEPLOYMENT,
    FailureMode,
    FixOutcome,
    IncidentStatus,
)
from argus_core.replay import CallType
from argus_incidents.repository import events, hypotheses, incidents, postmortems, replay
from argus_testkit import Assertion, all_of

from tests.framework.assertions import (
    some_confidence_was_given,
    the_cause_was_identified_as,
)

ARGUS_WEB_BASE_URL = "http://localhost:8000"
TARGET_SERVICE_BASE_URL = "http://localhost:8080"
DATABASE_URL = get_settings().database_url

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

# The recordings that answer for the model, by the case each one is of. What is
# on disk is this name under the prefix `stored_as` below applies - a recording
# belongs to a mode as much as to a case.
RECORDED_FLAG_TOGGLE = "feature-flag-toggle"
RECORDED_BAD_DEPLOYMENT = "bad-deployment"
RECORDED_FALLBACK_DISABLED = "fallback-disabled"
RECORDED_ABSENCE_OF_EVIDENCE = "no-evidence"
RECORDED_FLAG_TOGGLE_RED_HERRING = "flag-toggle-red-herring"
RECORDED_FLAG_TOGGLE_UNCORROBORATED = "flag-toggle-uncorroborated"
RECORDED_RESOURCE_LEAK = "resource-leak"
RECORDED_UPSTREAM_DEPENDENCY_FAILURE = "upstream-dependency-failure"
RECORDED_CACHE_MISCONFIGURED = "cache-misconfigured"
RECORDED_SLOW_CANARY_ROLLOUT = "slow-canary-rollout"
RECORDED_LARGE_CODE_FIX = "monthly-statement-panel"
RECORDED_PRICING_SERVICE_DEGRADED = "pricing-service-degraded"
RECORDED_CPU_SATURATION = "cpu-saturation"
RECORDED_AUTOSCALER_FLAPPING = "autoscaler-flapping"
RECORDED_HALF_FINISHED_ROLLOUT = "half-finished-rollout"
RECORDED_SILENT_DATA_CORRUPTION = "silent-data-corruption"
RECORDED_CONTROL_PLANE_UNREACHABLE = "control-plane-unreachable"
RECORDED_MONITORING_BLIND_SPOT = "monitoring-blind-spot"
RECORDED_MONITORING_CONFIGURATION_DRIFT = "monitoring-configuration-drift"
RECORDED_STATE_DIVERGENCE = "cache-failed-over"
RECORDED_UNDATED_STATE_DIVERGENCE = "cache-failed-over-undated"
RECORDED_DEPLOY_CAUSED_CORRUPTION = "monthly-totals-falling-behind"
RECORDED_FLAG_REVERT_LEAVES_A_FLAP = "flag-revert-leaves-a-flap"
RECORDED_OUTPUT_QUALITY_DEGRADATION = "categoriser-model-upgraded"
RECORDED_ACCELERATOR_HETEROGENEITY = "scorer-replica-rescheduled"

# Which of those walks has to come back with a patch. Declared once, here,
# because two things need it and would otherwise each keep a list: the recorder,
# which refuses to store a walk that was supposed to propose a fix and did not,
# and the grader, which would otherwise report a scenario that quietly stopped
# proposing one as having nothing to grade.
#
# A scenario is absent from this either because its cause is not in the code -
# a misconfigured cache is rolled back, not patched - or because there is no
# cause at all to find. Absence is a statement, not an oversight, which is why
# the set is spelled out rather than derived from what the corpus happens to
# hold today.
THE_RECORDINGS_THAT_MUST_CARRY_A_FIX = frozenset({
    RECORDED_FLAG_TOGGLE,
    RECORDED_RESOURCE_LEAK,
    RECORDED_MONITORING_CONFIGURATION_DRIFT,
    RECORDED_LARGE_CODE_FIX,
    RECORDED_OUTPUT_QUALITY_DEGRADATION,
    RECORDED_ACCELERATOR_HETEROGENEITY
})

# Not arbitrary! the Target Service names itself in its own log
THE_SERVICE_NAME = "io-shop"

# Anthropic's own word for a block that calls a tool, declared here rather than
# imported: it is not on any of the kernel's front doors, and
# `scripts/seed_a_rehearsal.py` spells it locally for the same reason.
TOOL_USE_TYPE: Final = "tool_use"

# The extension a set's capture instant is stored under, beside the recordings.
ANCHOR_SUFFIX: Final = ".anchor"


def stored_as(recording: str) -> str:
    """The name this run's `CODE_SEARCH` keeps `recording` under.

    A mode is not a label on a recording - it is the world the recording was
    captured in. Under `grep` the read tier registers no retrieval-by-meaning
    tool at all, so a walk captured under `both` asked questions this stack
    cannot be asked, and answers them by calling a tool that was never offered.
    The double is a queue seeded by name and never inspects the request, so it
    would serve every one of those answers and the failure would read as an
    agent bug.

    Read from settings rather than taken as an argument, because nothing in a
    case chooses it: the session that brought this stack up set `CODE_SEARCH`,
    and the index pass, the read tier, the worker and this process all answer
    to that one setting.
    """
    return f"{get_settings().code_search.value}-{recording}"


def argus_is_triggered_with_alert(
    payload: dict[str, Any]
) -> Callable[[], httpx2.Response]:
    """Fires the alert, and waits for everything it starts.

    The wait is the whole incident, not a round trip: the webhook runs the graph
    in-process and answers only once it has finished. That used to mean one
    investigation, and it now means the walk - every candidate tried, each with
    its own verification window, and a fresh investigation between rounds. So
    this waits on the walk's budget rather than the investigation's; waiting on
    the shorter one fails the *client* while Argus is still working, which reads
    like a hung stack and is not one.

    The payload goes out naming the rule the staged scenario trips, as Grafana's
    webhook names the rule that fired. Asked of the shop when the alert is sent
    rather than written into the case: which rule a scenario trips is the
    fixture's to say, and a uid copied here would be a second copy of it.
    """
    def step() -> httpx2.Response:
        return httpx2.post(
            f"{ARGUS_WEB_BASE_URL}{WEBHOOK_PATH}",
            json=_naming_the_staged_rule(payload),
            timeout=WALK_TIMEOUT_SECONDS,
        )

    return step


def _naming_the_staged_rule(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload with every alert in it linking to the staged scenario's rule,
    or the payload as it is where nothing is staged.

    In the link, because that is the one place Grafana's webhook names the rule
    that fired - its payload has no field of its own for it.
    """
    response = httpx2.get(
        f"{TARGET_SERVICE_BASE_URL}/scenario/status", timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    rule_uid = response.json()["rule_uid"]

    if rule_uid is None:
        return payload

    return {
        **payload,
        "alerts": [
            {**alert, "generatorURL": f"http://grafana.local/alerting/grafana/{rule_uid}/view"}
            for alert in payload["alerts"]
        ]
    }


def the_shop_raises_its_own_alert() -> Callable[[], httpx2.Response]:
    """Asks the shop's monitoring to page Argus, instead of posting a payload.

    The one case where the alert cannot be built here. Every other alert in
    this directory is a rule firing on a series, and its payload carries
    nothing the test does not already know - so assembling it locally is
    honest. This one's carries a finding: how many stored totals disagree with
    the purchases behind them, by how much, and when the oldest of them was
    written. Only the shop's own check can produce that, and a payload written
    here would be the test telling Argus what the check found.

    Waits on the walk for the reason the webhook call does, and by the same
    route: the shop holds this request open until Argus's webhook answers, so
    the whole incident runs inside it.
    """
    def step() -> httpx2.Response:
        return httpx2.post(
            f"{TARGET_SERVICE_BASE_URL}/monitoring/alert",
            timeout=WALK_TIMEOUT_SECONDS,
        )

    return step


def incident_id_from(response: httpx2.Response) -> str:
    incident_id = response.json().get("incident_id")

    if not incident_id:
        raise AssertionError(f"No incident_id in response: [{response.text}].")

    return str(incident_id)


def argus_returns_status(expected_status: int | HttpStatus) -> Assertion[httpx2.Response]:
    def assertion(response: httpx2.Response) -> bool:
        if response.status_code != expected_status:
            raise AssertionError(
                f"Expected status [{expected_status}], but got [{response.status_code}]."
            )

        return True

    return assertion


def cause_identified_as(expected: FailureMode) -> Assertion[httpx2.Response]:
    """The cause Argus settled on, and that it said how sure it was.

    One assertion for what a case asks of the hypothesis. A confidence is how the
    domain says a cause was determined at all - `no_cause_was_determined` holds the
    two absent together - so it is asserted with the mode rather than beside it.
    Both halves are the domain assertions in `tests/framework`, applied to the
    incident's hypothesis, so they stay shared with the eval and integration tiers
    rather than being restated against a database row here.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            hypothesis = hypotheses.get_latest_by_incident(conn, incident_id)

        if hypothesis is None:
            raise AssertionError(f"No hypothesis found for incident [{incident_id}].")

        return all_of(
            the_cause_was_identified_as(expected),
            some_confidence_was_given()
        )(hypothesis)

    return assertion


def argus_ended_with_status(expected_status: IncidentStatus) -> Assertion[httpx2.Response]:
    def assertion(response: httpx2.Response) -> bool:
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


def argus_went_through_statuses(*expected: IncidentStatus) -> Assertion[httpx2.Response]:
    """Every status the incident entered, in order, as it published them.

    Read from the account rather than from a table of transitions: the move and
    the sentence about it are one write now, and the acknowledgement is not
    among them - Argus having the alert adds nowhere for the incident to go, so
    it is published as the alert arriving and the first transition is a worker
    picking it up.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            recorded = events.get_by_incident(conn, incident_id)

        actual = [event.to_status for event in recorded
                  if isinstance(event, StatusChanged)]

        if actual != list(expected):
            raise AssertionError(
                f"Expected status transitions {[str(status) for status in expected]}, "
                f"got {actual}."
            )

        return True

    return assertion


def investigation_finds_a_deployment_change() -> Assertion[httpx2.Response]:
    """That the change channel answered, and answered with something.

    The one assertion that makes the Argo CD path load-bearing, since a cause
    can be named right without it. A `ChangesRetrieved` carrying an empty list is
    a channel that was asked and found nothing, which is a different fact
    about the world and cannot stand in for the deploy being visible - so what
    is checked is that at least one change reached the incident, never how
    many or which.

    Read from the incident's own events rather than from the hypothesis,
    because a model can name a deploy it inferred from prose. This is the
    record of the adapter having actually fetched one.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            recorded = events.get_by_incident(conn, incident_id)

        retrieved = [event for event in recorded if isinstance(event, ChangesRetrieved)]
        if not any(event.changes for event in retrieved):
            raise AssertionError(
                f"Expected the change channel to have answered with at least one "
                f"change, and it published {len(retrieved)} retrieval(s) carrying "
                f"{[len(event.changes) for event in retrieved]}."
            )

        return True

    return assertion


def argus_took_a_rollback_of(application: str) -> Assertion[httpx2.Response]:
    """Read from the incident's own account rather than from the platform.

    What the platform was asked is a fact about the fixture; what Argus decided
    to do is the thing under test. A rollback has no direction - there is no
    switch to have been thrown, and where it went is "the revision before" by
    construction - so the event says so by leaving it absent, and one claiming a
    direction would describe a different action from the one taken.

    Shared by the two cases that end this way, which is the point of it being
    one assertion. A value deployed into a broken state and a revision that made
    every page slower are told apart by the evidence and by the fix left
    afterwards, never by what is done about them now - so a copy per case would
    be two spellings of a single claim.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        taken = [
            event for event in _the_incidents_events(incident_id)
            if isinstance(event, ActionTaken)
        ]

        if not taken:
            raise AssertionError(
                f"Incident [{incident_id}] took no action at all, so nothing "
                f"was ever put to the question."
            )

        rollbacks = [
            event for event in taken
            if event.action_type == ROLL_BACK_DEPLOYMENT
            and event.subject == application
        ]

        if not rollbacks:
            raise AssertionError(
                f"Expected a rollback of [{application}], and what was taken "
                f"was {[(event.action_type, event.subject) for event in taken]}."
            )

        if rollbacks[-1].enabled is not None:
            raise AssertionError(
                f"Expected a rollback to carry no direction, and it reported "
                f"[{rollbacks[-1].enabled}] - which tells a later round a "
                f"switch was thrown."
            )

        return True

    return assertion


def argus_proposed_a_fix() -> Assertion[httpx2.Response]:
    """Code-Fix opened something, on any attempt rather than the last.

    For the cases a mitigation ends without resolving: the action bought the
    service back and the cause is still in the code, so the walk carries on to
    Code-Fix. Any attempt rather than the last, since a later round may ask again.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        attempts = [
            event for event in _the_incidents_events(incident_id)
            if isinstance(event, FixAttempted)
        ]

        if not any(attempt.outcome is FixOutcome.PROPOSED for attempt in attempts):
            raise AssertionError(
                f"Expected Code-Fix to have proposed a fix for incident "
                f"[{incident_id}], since the cause is still in the code. It "
                f"reported {[(attempt.outcome, attempt.detail) for attempt in attempts]}."
            )

        return True

    return assertion


def _the_incidents_events(incident_id: str) -> list[Any]:
    """Everything the walk published for one incident, in the order it happened.

    A local reading rather than `world.the_incidents_events`, which is the same
    query: that module imports this one, so calling it from here would close the
    cycle.
    """
    with psycopg.connect(DATABASE_URL) as conn:
        return events.get_by_incident(conn, incident_id)


def argus_registered_an_incident_for_the_alert(
    alert_payload: dict[str, Any]
) -> Assertion[httpx2.Response]:
    """The alert reached the database in Argus's own shape.

    The absent `labels` key is the point: a vendor's nesting must not survive
    past the webhook adapter (spec §7.9, §25).
    """
    def assertion(response: httpx2.Response) -> bool:
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


def argus_created_a_postmortem_for_the_incident() -> Assertion[httpx2.Response]:
    def assertion(response: httpx2.Response) -> bool:
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


def argus_wrote_a_postmortem() -> Assertion[httpx2.Response]:
    """The row exists, and nothing about what it says.

    The one thing about a postmortem worth waiting for. It is written in a
    single insert and never updated, so every figure on it is settled the
    instant it appears - polling one that is already there for another ten
    minutes asks a question whose answer cannot change, and turns a case that
    failed in seconds into a shard that takes half an hour.

    So a suite waits on this and asserts the contents once, rather than
    retrying the contents until a deadline that only the absent row deserved.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            postmortem = postmortems.get_by_incident(conn, incident_id)

        if postmortem is None:
            raise AssertionError(f"No postmortem exists for incident [{incident_id}].")

        return True

    return assertion


def the_model_answers_from(recording: str, *, less_code_fix: bool = False) -> Callable[[], bool]:
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

    `less_code_fix` leaves Code-Fix's answers out, for a walk that never reaches
    Code-Fix because a person resolved the incident first. The double serves in
    order and never looks at the request, so those answers left in would be
    handed to the postmortem.
    """
    def step() -> bool:
        stored = stored_as(recording)
        shift = _how_far_the_world_has_moved_since(stored)

        with httpx2.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
            control.post("/double-control/reset").raise_for_status()

            answers = _the_answers_recorded_for(stored, control)

            for answered_once in _less_code_fix(answers) if less_code_fix else answers:
                control.post(
                    "/double-control/seed",
                    json={"recording": answered_once, "repeat": 1}
                    if shift is None
                    else {"body": _rebased(load(answered_once), shift), "repeat": 1}
                ).raise_for_status()

        return True

    return step


def the_anchor_file_for(recording: str) -> Path:
    """Where a recorded set keeps the instant the world was seeded at when it
    was captured.

    A sidecar beside the recordings rather than a key inside one, because a
    recording is the raw body the API returned and a field this repo added to
    it would be the one thing in there Anthropic never said. The suffix is not
    `.json`, so the double's own listing of what it holds does not grow a
    recording nobody can replay.
    """
    return RECORDINGS_DIR / f"{recording}{ANCHOR_SUFFIX}"


def _how_far_the_world_has_moved_since(recording: str) -> timedelta | None:
    """The gap between the world a set was captured in and the world it is
    about to answer about - or `None` where there is no telling.

    A recorded answer can name the window it asked about, and those bounds are
    absolute instants frozen at capture. The scenario they were captured
    against is not frozen: the Target Service hangs its minutes and its deploy
    history off the instant it was seeded, so a set replayed an hour later asks
    about an hour that no longer holds the incident. The channel then answers
    correctly with nothing, and a case asserting on the evidence fails for a
    property of the recording rather than of Argus.

    One delta for the whole set, taken between the two seedings, because that
    is the instant both worlds are built from. Every relative distance inside
    the walk survives a single constant shift: a change fifteen minutes before
    the recorded onset lands fifteen minutes before this one.

    `None` wherever either anchor is missing - a set captured before anchors
    were written, or a case that seeds no scenario at all. Nothing is shifted
    then, which is exactly today's behaviour, rather than a guess at an anchor
    nobody recorded.
    """
    anchor = the_anchor_file_for(recording)

    if not anchor.exists():
        return None

    seeded_now = _the_instant_this_run_was_seeded()

    if seeded_now is None:
        return None

    return seeded_now - parse_iso(anchor.read_text(encoding="utf-8").strip())


def _the_instant_this_run_was_seeded() -> datetime | None:
    """When the Target Service was put into the state this case is about.

    Asked of the service rather than taken as the moment the seeding call
    returned: the service decides what instant its window hangs off, and a
    reading taken here would be a second opinion about it that drifts by
    however long the call took.
    """
    response = httpx2.get(
        f"{TARGET_SERVICE_BASE_URL}/scenario/status",
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    seeded_at = response.json().get("seeded_at")

    return parse_iso(seeded_at) if seeded_at else None


def _rebased(answer: dict[str, Any], shift: timedelta) -> dict[str, Any]:
    """One recorded answer with its retrieval windows moved into this run's world.

    The two window arguments and nothing else, which is a limit rather than a
    first pass. What the model *said* - the summaries, the evidence it quotes,
    the postmortem - names instants too, and rewriting those would make the
    stored answer something Anthropic never returned. So the replayed prose
    goes on naming the hour it was captured in, no case asserts on it, and the
    paid run is where those times are real.
    """
    content = []

    for block in answer.get("content", []):
        arguments = block.get("input") if block.get("type") == TOOL_USE_TYPE else None

        if not arguments:
            content.append(block)
            continue

        moved = {
            name: to_iso(parse_iso(bound) + shift)
            for name, bound in arguments.items()
            if name in (WINDOW_START_ARG, WINDOW_END_ARG) and isinstance(bound, str)
        }
        content.append({**block, "input": {**arguments, **moved}} if moved else block)

    return {**answer, "content": content}


def _the_answers_recorded_for(recording: str, control: httpx2.Client) -> list[str]:
    """Every stored answer belonging to one incident, in the order it was given.

    Asked of the double rather than the filesystem: the recordings belong to it,
    and a test reaching into another package's directory to list them would be
    a second opinion about what is available.

    A name with no numbered siblings answers as itself, which is every case that
    resolves on its first verdict - so this changes nothing for them.

    A name with no answers at all is refused here, before the alert is sent. The
    double takes a seed by name without looking for it and fails only when the
    model is first called, which ends the walk in a second - and the case then
    polls an incident that has already ended until its walk timeout, eighteen
    minutes spent reporting a recording nobody made.
    """
    state = control.get("/double-control/state")
    state.raise_for_status()

    belonging = [
        name
        for name in state.json().get("available_recordings", [])
        if name == recording or _is_a_later_answer_of(name, recording)
    ]

    if not belonging:
        raise AssertionError(
            f"No recording named [{recording}] for the double to answer from - "
            f"record it before replaying this case."
        )

    return sorted(belonging, key=_the_order_it_was_answered_in)


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


def _less_code_fix(answers: list[str]) -> list[str]:
    """A walk's answers without the ones Code-Fix gave.

    Told apart by what each answer did rather than by position, because where
    Code-Fix starts differs between recordings and between modes: the
    investigation ends on its last final answer, and the write-up is the answer
    that submits the postmortem. Everything between is Code-Fix's.
    """
    tools = [_the_tools_called_in(load(name)) for name in answers]
    the_investigations_end = max(position for position, called in enumerate(tools)
                                 if ANSWER_TOOL in called)
    the_write_up = next(position for position, called in enumerate(tools)
                        if SUBMIT_TOOL_NAME in called)

    return answers[:the_investigations_end + 1] + answers[the_write_up:]


def _the_tools_called_in(answer: dict[str, Any]) -> list[str]:
    return [block["name"] for block in answer.get("content", [])
            if block.get("type") == TOOL_USE_TYPE]


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
