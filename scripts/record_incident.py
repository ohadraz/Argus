"""Captures real model answers as replayable recordings.

Recording is a proxy inside the Anthropic double rather than a script that
builds its own request: the double is told to record, then the stack drives one
real incident through it, so the request that gets stored is by construction the
request the adapter sends - prompt, schema transform and all.

This script is the part around that: arm the double, stage the Target Service,
fire the alert, and say what was written. It exists so a recording is one
command rather than four hand-typed curls whose order matters - seeds take
precedence over record mode, so a double that was seeded by a previous run
records nothing and the mistake looks like a working run.

It takes recording *names* and nothing else. What each one stages, and which
alert it fires, is the mapping below rather than something typed at the command
line: a recording is replayed for one specific e2e case, so the world it was
captured in is a property of the recording, not a choice. Getting that wrong is
not a failure - it is a plausible-looking recording of the wrong incident, paid
for and committed.

What it does *not* take is the mode. `CODE_SEARCH` is a property of the stack
around this script - which tools the read tier registers, and so which tools the
walk is offered - so the session that brought that stack up is what decides it,
and every name captured in a run is stored under that mode's prefix.

Several names in one run share one stack, and `all` is every name. The stack is
the slow part - a build, a compose up, four local services - and it is brought
up once by the nox session around this script whether it captures one recording
or five. What is *not* shared is the world: each recording is captured in the
same reset environment the e2e suite arranges for the case that replays it.

Costs one real investigation per name, which is why it is a session nobody runs
by accident and never part of a suite.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from io import TextIOWrapper
from pathlib import Path
from typing import Any, Final, NamedTuple

import httpx
import psycopg
from anthropic_double.recordings import RECORDINGS_DIR
from argus_core import get_settings, to_iso
from argus_core.events import (
    ActionRefused,
    ActionTaken,
    FixAttempted,
    HypothesisFormed,
    VerdictReached,
)
from argus_core.models import FixOutcome, IncidentStatus
from pydantic import BaseModel

from tests.e2e.framework.argus import (
    RECORDED_ABSENCE_OF_EVIDENCE,
    RECORDED_BAD_DEPLOYMENT,
    RECORDED_CACHE_MISCONFIGURED,
    RECORDED_FALLBACK_DISABLED,
    RECORDED_FLAG_TOGGLE,
    RECORDED_FLAG_TOGGLE_RED_HERRING,
    RECORDED_FLAG_TOGGLE_UNCORROBORATED,
    RECORDED_LARGE_CODE_FIX,
    RECORDED_RESOURCE_LEAK,
    RECORDED_SLOW_CANARY_ROLLOUT,
    RECORDED_UPSTREAM_DEPENDENCY_FAILURE,
    THE_RECORDINGS_THAT_MUST_CARRY_A_FIX,
    THE_SERVICE_NAME,
    stored_as,
)
from tests.e2e.framework.flags import (
    only_the_boot_flags_were_left_in_the_provider,
    the_boot_flags_were_put_back,
    the_flag_provider_forgot_every_change,
)
from tests.e2e.framework.world import the_incidents_events

ARGUS_WEB_BASE_URL = "http://localhost:8000"
TARGET_SERVICE_BASE_URL = "http://localhost:8080"
ANTHROPIC_DOUBLE_BASE_URL = "http://localhost:8091"
DATABASE_URL = get_settings().database_url

# How long one recording's walk may take before this gives up on it.
#
# A floor rather than a measurement, and knowingly so. At 900 it cut three
# walks of eleven off mid-read - `cache-misconfigured` at 21 answers,
# `slow-canary-rollout` at 25, `monthly-statement-panel` at 21 - each of them
# mitigated, none of them written up, all three still calling
# `read_repository_file` when the clock ran out. What they would have taken is
# exactly what a bound that binds cannot tell you, so this is doubled rather
# than fitted, and the figure worth writing here is the longest walk a run
# under it actually reports.
A_WHOLE_INVESTIGATION_SECONDS = 1800.0
# The webhook only writes the incident down, so this bounds a write rather than
# a walk - the walk is waited out by polling below.
REQUEST_TIMEOUT_SECONDS = 30.0
A_POLL_SECONDS = 5.0


class _Published(NamedTuple):
    """One thing a walk has to have put on the record, and what it has to say.

    `saying` exists because the event alone is not always the claim. Code-Fix
    publishes `fix-attempted` whether it opened a pull request, found nothing
    worth changing, or ran out of turns halfway through reading - five
    outcomes, one event. A check that asked only whether the event was there
    would accept a walk that searched the repository twenty-three times,
    proposed nothing, and stopped; which is not a recording of this incident,
    it is a recording of a budget running out.
    """
    event: type[BaseModel]
    saying: dict[str, object] | None = None

    @property
    def kind(self) -> str:
        """The wire name this event publishes itself under.

        Asked of the type rather than spelled here. These strings are this
        repo's own vocabulary and they are already written down once, on the
        event that carries them - a second copy in this file would be a check
        that passes because both halves were renamed and a check that fails
        because only one half was, and neither is worth the characters saved.
        """
        return str(self.event.model_fields["kind"].default)

    def was_in(self, published: list[Any]) -> bool:
        """Whether the walk published this, saying what it had to say."""
        return any(
            event.kind == self.kind
            and all(getattr(event, field, None) == said
                    for field, said in (self.saying or {}).items())
            for event in published
        )

    def __str__(self) -> str:
        said = ", ".join(f"{field}={said}" for field, said in (self.saying or {}).items())

        return f"{self.kind} ({said})" if said else self.kind


# The stages a walk can be held to having reached. Named for the event rather
# than for what any one scenario uses it to mean: `action-taken` is a flag put
# back in one recording and a service restarted in another, and a constant
# called after either would read as a lie in the other.
_A_HYPOTHESIS_WAS_FORMED: Final = _Published(HypothesisFormed)
_AN_ACTION_WAS_TAKEN: Final = _Published(ActionTaken)
_AN_ACTION_WAS_REFUSED: Final = _Published(ActionRefused)
_A_VERDICT_WAS_REACHED: Final = _Published(VerdictReached)
# The proposal, not the attempt. See `_Published.saying`.
_A_FIX_WAS_PROPOSED: Final = _Published(
    FixAttempted, {"outcome": FixOutcome.PROPOSED}
)

# What no recording may contain, whichever incident it is of. `not-answered` is
# Code-Fix stopping mid-read with its turns spent - a statement about the bound
# rather than about the code - and the answers it leaves behind are a queue that
# ends in the middle of reading a repository. Replayed, that walk spends the
# whole corpus searching and reaches the postmortem with nothing left, which is
# how two of these came to be committed. Refused for every scenario rather than
# listed per recording: no case asserts a walk that ran out, and the two whose
# cases happened not to check are exactly the two it was found in.
_THE_FIX_RAN_OUT_OF_TURNS: Final = _Published(
    FixAttempted, {"outcome": FixOutcome.NOT_ANSWERED}
)


class _Recording(NamedTuple):
    """One recording, and the incident that has to happen for it to exist.

    `scenario` is `None` for the one recording captured against a shop with
    nothing wrong in its logs - absence of evidence is itself the case under
    test, and it is staged by staging nothing.

    `ends_as` and `must_have` are what the walk has to have *done* for this
    recording to be worth keeping, taken from the case that replays it rather
    than invented here. They exist because a walk can stop cleanly having
    skipped a whole stage: a terminal status and a written postmortem are
    satisfied by an investigation that reached no fix at all, and a corpus
    captured from one looks complete, replays for a while and fails somewhere
    nobody was thinking about. Positive expectations only - "it never took an
    action" reads well and would refuse a real recording of a walk that tried
    something and put it back.

    `and_then` is whatever the replaying case arranges *after* seeding the
    scenario and before the alert. A recording is a queue of answers served in
    order, not a model that reasons afresh, so a walk replayed in a world
    unlike the one it was captured in runs longer than the queue and the double
    runs dry mid-incident. Anything a case stages, this stages too.
    """
    name: str
    scenario: str | None
    alert_name: str
    ends_as: IncidentStatus
    must_have: tuple[_Published, ...]
    and_then: Callable[[], None] | None = None


# Every recording the offline suites rest on, in the order a full run captures
# them. The names are imported from the e2e framework rather than spelled here:
# a recording this script stores under a name nothing replays is a recording
# that cost money and answers no question.
EVERY_RECORDING: tuple[_Recording, ...] = (
    _Recording(
        RECORDED_FLAG_TOGGLE,
        "feature-flag-toggle",
        "HighErrorRate",
        IncidentStatus.MITIGATED,
        (_AN_ACTION_WAS_TAKEN, _A_FIX_WAS_PROPOSED)
    ),
    _Recording(
        RECORDED_BAD_DEPLOYMENT,
        "bad-deployment",
        "HighLatency",
        IncidentStatus.ESCALATED,
        (_A_HYPOTHESIS_WAS_FORMED,)
    ),
    _Recording(
        RECORDED_FALLBACK_DISABLED,
        "fallback-disabled",
        "HighErrorRate",
        IncidentStatus.MITIGATED,
        (_AN_ACTION_WAS_TAKEN,)
    ),
    _Recording(
        RECORDED_FLAG_TOGGLE_RED_HERRING,
        "flag-toggle-red-herring",
        "HighErrorRate",
        IncidentStatus.ESCALATED,
        # Both halves, because this recording is of the pair: the action is
        # what makes it a red herring, and the verdict against it is what makes
        # it correct. The verdict rather than a `ChangeUndone` - the flag does
        # go back, but a refuted action is put back inside the mitigation loop
        # and recorded as the measurement that refuted it. `ChangeUndone` is
        # what a *withdrawal* publishes, which is a different case entirely.
        (_AN_ACTION_WAS_TAKEN, _A_VERDICT_WAS_REACHED)
    ),
    # The same scenario as the first, in a world where the provider has no
    # record of the flag having changed - so Mitigation refuses to write to a
    # flag only the model names, and the walk goes back to investigate. That
    # walk is longer than the corroborated one, which is why it cannot share
    # its recording.
    _Recording(
        RECORDED_FLAG_TOGGLE_UNCORROBORATED,
        "feature-flag-toggle",
        "HighErrorRate",
        IncidentStatus.ESCALATED,
        # The refusal is the whole recording. A walk that escalated without one
        # reached the same status by a different road - out of evidence rather
        # than out of authority - and replaying it would prove nothing about
        # the thing this case exists to hold.
        (_AN_ACTION_WAS_REFUSED,),
        the_flag_provider_forgot_every_change
    ),
    # The one incident a mitigation relieves without ending. Its alert is
    # memory rather than errors, because memory is the signal that moves first
    # on a leak - and a walk recorded against an error-rate alert would be
    # answering a question this scenario never asks.
    _Recording(
        RECORDED_RESOURCE_LEAK,
        "resource-leak",
        "HighMemoryUsage",
        IncidentStatus.MITIGATED,
        # A restart and a fix, because relieving a leak is not ending one - the
        # case that replays this asserts both, and a corpus carrying only the
        # restart is a recording of an incident left to climb again.
        (_AN_ACTION_WAS_TAKEN, _A_FIX_WAS_PROPOSED)
    ),
    # The one incident nothing Argus may do can touch. Its alert is the error
    # rate, because that is what a dependency's outage does to the shop that
    # depends on it - every account page waits on the provider and then fails.
    _Recording(
        RECORDED_UPSTREAM_DEPENDENCY_FAILURE,
        "upstream-dependency-failure",
        "HighErrorRate",
        IncidentStatus.ESCALATED,
        # A named cause and nothing done about it. Escalating here is the
        # answer rather than the leftover, so what has to be on the record is
        # that the walk got as far as saying what was wrong.
        (_A_HYPOTHESIS_WAS_FORMED,)
    ),
    # The one incident a monitor watching the tail never sees. Its alert is
    # latency, as a bad deployment's is: nothing here fails, so an error-rate
    # alert would be answering a question this scenario never asks, and what the
    # two latency cases are told apart by is the evidence rather than the page.
    _Recording(
        RECORDED_CACHE_MISCONFIGURED,
        "cache-misconfigured",
        "HighLatency",
        IncidentStatus.MITIGATED,
        (_AN_ACTION_WAS_TAKEN,)
    ),
    # The mirror of the one above: that incident hides in the tail, this one
    # behind it. Its alert is latency too, and for the same reason - nothing
    # fails here either - but the summary names the percentile, because a rule
    # written against p95 would never fire on this at all.
    _Recording(
        RECORDED_SLOW_CANARY_ROLLOUT,
        "slow-canary-rollout",
        "HighLatency",
        IncidentStatus.MITIGATED,
        (_AN_ACTION_WAS_TAKEN,)
    ),
    # The flag scenario again, with the fault moved into the largest module the
    # shop has. Everything a reader of the telemetry sees is the first
    # recording's incident - same flag, same cohort, same error rate - and the
    # answers are not the first recording's, because the file Code-Fix is sent
    # to is twenty-odd thousand tokens rather than seven hundred. A whole-file
    # answer of that size is what it is captured for.
    #
    # Worth capturing under `both` alone. The case that replays it is collected
    # in that mode only - see `noxfile._the_cases_for`, which argues it - so a
    # `grep` or `meaning` run of this name costs a real investigation and
    # stores it where nothing looks.
    _Recording(
        RECORDED_LARGE_CODE_FIX,
        "monthly-statement-panel",
        "HighErrorRate",
        IncidentStatus.MITIGATED,
        # The fix alone, though this walk mitigates too. What the case replaying
        # it asserts is the size of the written file, and that claim rests on
        # Code-Fix having answered at all.
        (_A_FIX_WAS_PROPOSED,)
    ),
    # Nothing beyond the ending. The shop's logs say nothing is wrong, so there
    # is no cause to name and nothing to act on - escalation and a postmortem
    # are the entire claim, and a `must_have` invented to fill the column would
    # refuse the one walk this recording is of.
    _Recording(
        RECORDED_ABSENCE_OF_EVIDENCE,
        None,
        "HighErrorRate",
        IncidentStatus.ESCALATED,
        ()
    )
)

EVERY_RECORDING_KEYWORD = "all"


def _an_alert_for(service: str, alert_name: str) -> dict[str, Any]:
    """A Grafana webhook payload, as Grafana would send it.

    `startsAt` is now, and that matters: retrieval is anchored on the alert
    time and the Target Service stages a scenario relative to the moment it was
    staged, so a fixed timestamp would point the window at minutes the fixture
    never wrote.
    """
    summary = f"Error rate above threshold on {service}"

    return {
        "receiver": "argus-webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": alert_name,
                    "service": service,
                    "severity": "critical",
                },
                "annotations": {"summary": summary},
                "startsAt": to_iso(datetime.now(UTC)),
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": f"http://grafana.local/alerting/grafana/{service}/view",
                "fingerprint": "abc123def456",
            }
        ],
        "groupLabels": {"alertname": alert_name},
        "commonLabels": {"alertname": alert_name, "service": service},
        "commonAnnotations": {"summary": summary},
        "externalURL": "http://grafana.local",
        "version": "1",
        "groupKey": f'{{}}/{{alertname="{alert_name}"}}',
    }


def _replay_from(name: str) -> None:
    """Serves a stored recording for every call instead of forwarding upstream.

    The same drive, for free. What it is for is the question a recording cannot
    answer on its own - what the *graph* did with that answer - and being able
    to ask it repeatedly, without paying for a fresh verdict each time, is the
    difference between reading a timeline and guessing at one.

    Every answer is seeded, once each and in the order they were given, exactly
    as the e2e suite seeds one. A recording is a walk rather than a reply: the
    single-seed spelling this used to have - one name, repeating forever - kept
    handing the walk its opening move whatever it had just asked, and the
    investigation spent its whole tool budget re-reading the same two channels
    before escalating for want of evidence. That reads as a walk that went
    wrong, which is precisely the thing this is used to rule out.
    """
    with httpx.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
        control.post("/double-control/reset").raise_for_status()
        for answered_once in _the_set_named(name):
            control.post(
                "/double-control/seed",
                json={"recording": answered_once.stem, "repeat": 1}
            ).raise_for_status()


def _the_timeline_of(published: list[Any]) -> list[str]:
    """What the incident recorded about itself, in order.

    Read while the stack is still up rather than left for someone to query
    afterwards, because it comes down the moment this script returns - and the
    account is the only record of which branch the walk actually took.
    """
    return [
        f"  {event.kind:<22} {_what_it_said(event.model_dump())}"
        for event in published
    ]


def _what_it_said(payload: dict[str, object]) -> str:
    """The part of an event worth reading in a one-line summary.

    Whichever of these the event happens to carry, because the fields that say
    what an event was about differ by kind and a recording is read by a person
    scanning it rather than by anything that parses it.
    """
    said = [f"{field}={payload[field]}"
            for field in ("to_status", "refusal", "outcome", "summary", "flag",
                          "agent", "channel", "minute", "recovered", "detail")
            if payload.get(field) is not None]

    return " ".join(said) or "-"


def _arm_the_double(name: str) -> None:
    """Clears anything a previous run left queued, then enters record mode.

    The reset is not optional: a seeded answer is served ahead of record mode,
    so a double still holding a seed would replay it and store nothing.
    """
    with httpx.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
        control.post("/double-control/reset").raise_for_status()
        control.post("/double-control/record", json={"name": name}).raise_for_status()


def _a_world_this_recording_can_be_captured_in() -> None:
    """Puts the Target Environment back before each incident is driven.

    The e2e suite's own teardown, step for step and in its order: the service's
    scenario reset, both boot flags put back where the stack starts them, every
    flag the environment did not boot with deleted, the provider's record of
    what changed erased. Reused rather than restated, because a recording
    captured in a world the replaying case never arranges is a recording of a
    different incident.

    This is what one shared stack costs. Running the session per recording got
    a virgin world from `compose down -v`; here the previous recording's
    mitigations are still on the flags, and its toggles are still in the
    history the next investigation reads as evidence.
    """
    httpx.post(f"{TARGET_SERVICE_BASE_URL}/scenario/reset", timeout=30.0)
    the_boot_flags_were_put_back()
    only_the_boot_flags_were_left_in_the_provider()
    the_flag_provider_forgot_every_change()


def _stage(scenario_id: str) -> None:
    httpx.post(
        f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
        json={"scenario_id": scenario_id},
        timeout=30.0,
    ).raise_for_status()


def _an_incident_was_opened_by(service: str, alert_name: str) -> str:
    """Fires the alert and returns the incident the webhook wrote down.

    Separate from waiting for the walk, because they are two things: the
    webhook writes the incident down and answers at once, and a worker walks it
    afterwards. Waiting on the webhook alone returns two seconds later with an
    incident nobody has investigated yet - and this script would then store the
    answers of a walk that had not happened, which is to say none, and discard
    the answers of the one that had.

    Split from the wait so the caller holds the id *before* the walk can fail.
    A walk that does not finish is the one whose account is worth reading, and
    a wait that owned the id took it down with it.
    """
    response = httpx.post(
        f"{ARGUS_WEB_BASE_URL}/webhooks/alerts",
        json=_an_alert_for(service, alert_name),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return str(response.json().get("incident_id", "unknown"))


def _the_walk_came_to_a_stop(incident_id: str) -> None:
    """Waits until the incident has stopped moving *and* been written up.

    Both, because a terminal status is not the last model call: the postmortem
    is written after the incident ends, so a wait that stopped at `resolved`
    would store every answer but the last one - and a recording one answer
    short replays as a walk that runs out of answers mid-write, which is how
    this was found.

    Loudly when neither arrives, because the alternative is worse than a slow
    run: a partial answer set replays as a walk stopping halfway, and nothing
    downstream reads that as a recording problem.
    """
    deadline = time.monotonic() + A_WHOLE_INVESTIGATION_SECONDS

    while True:
        status = _the_status_of(incident_id)

        if status is not None and status.is_terminal() and _was_written_up(incident_id):
            return

        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"incident [{incident_id}] was [{status}] with "
                f"[{'a' if _was_written_up(incident_id) else 'no'}] postmortem after "
                f"[{A_WHOLE_INVESTIGATION_SECONDS:.0f}s] - nothing was recorded from it"
            )

        time.sleep(A_POLL_SECONDS)


def _the_walk_did_what_this_recording_is_of(
    recording: _Recording, incident_id: str, published: list[Any]
) -> None:
    """Refuses a walk that stopped cleanly without doing what it was driven for.

    The gap this closes is the one that cost two paid runs: a walk can reach a
    terminal status and write its postmortem having skipped a whole stage, and
    the corpus it leaves behind is a plausible file set, a green run and a
    suite that fails weeks later on an agent nobody had touched. A status says
    the walk stopped; only the events say what it did on the way.

    Raised rather than returned, so one bad recording lands in the run's own
    `failed` list beside a scenario that threw - it is the same news, and a
    reader scanning for what to re-run should not have to find it twice.

    Nothing is deleted. A recording that failed this is still the only copy of
    answers that cost real money, and the walk it describes is worth reading
    before anybody decides it was worthless.
    """
    ended_as = _the_status_of(incident_id)
    missing = [
        str(expected) for expected in recording.must_have
        if not expected.was_in(published)
    ]

    if ended_as is not recording.ends_as:
        raise AssertionError(
            f"[{recording.name}] ended as [{ended_as}], and the case that "
            f"replays it expects [{recording.ends_as}] - so this is a "
            f"recording of a different walk"
        )

    if missing:
        raise AssertionError(
            f"[{recording.name}] never published [{', '.join(missing)}], which "
            f"the case that replays it asserts - so a stage did not finish and "
            f"the corpus is short of it"
        )

    if _THE_FIX_RAN_OUT_OF_TURNS.was_in(published):
        raise AssertionError(
            f"[{recording.name}] stopped with [{_THE_FIX_RAN_OUT_OF_TURNS}] - "
            f"Code-Fix spent its turns reading and never answered, so these "
            f"answers end mid-read and replay as a walk that runs dry"
        )


def _was_written_up(incident_id: str) -> bool:
    """Whether the postmortem exists - the last thing an incident produces."""
    with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM postmortem WHERE incident_id = %s LIMIT 1", (incident_id,)
        )

        return cursor.fetchone() is not None


def _the_status_of(incident_id: str) -> IncidentStatus | None:
    """Where the incident is now, asked of the record rather than of the walk.

    `None` where no row answers, which is a run whose incident never reached
    the database - reported by the wait above rather than read as an ending.
    """
    with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT status FROM incident WHERE id = %s", (incident_id,))
        found = cursor.fetchone()

        return IncidentStatus(found[0]) if found else None


def _the_set_named(name: str) -> list[Path]:
    """Every file one recording's answers are stored across, in answer order.

    A recording is not one file: a walk takes as many turns as it takes, and
    each answer is stored beside the last under a numbered name. The digits
    are checked rather than just the prefix, because two recordings can share
    one - `feature-flag-toggle-red-herring` is not the fourth answer of
    `feature-flag-toggle`.
    """
    belonging = [
        path
        for path in RECORDINGS_DIR.glob(f"{name}*.json")
        if path.stem == name or path.stem[len(name) + 1:].isdigit()
    ]

    # By the number rather than by the name: the first answer carries no digits
    # at all, and sorting the rest as text would put a tenth answer second.
    return sorted(belonging, key=lambda path: int(path.stem[len(name) + 1:] or 1))


def _discard_what_was_not_answered_again(name: str, started_at: float) -> list[Path]:
    """Deletes the answers of the previous recording this run did not replace.

    Not housekeeping - correctness. `save` overwrites one file at a time, so a
    walk that ends in two turns leaves the third through eighth answers of the
    walk before it exactly where they were, and the double serves them: the
    replayed investigation reads six answers to questions this recording never
    asked, and escalates on evidence from another incident. The failure is
    silent both ways round, because a longer new recording overwrites the lot
    and looks fine.

    Done after the run rather than before it, and by what the run actually
    wrote. Clearing up front is the same mistake in the other direction: an
    incident that never reaches the model - one escalated on retrieval alone,
    which is a real path and a tested one - records nothing, and a store
    emptied in advance of it loses a recording that no rerun can put back.

    Returns what it deleted, so a run can say so rather than leaving the
    difference between "this walk was shorter" and "your store just lost six
    files" to be noticed later.
    """
    stale = [
        path
        for path in _the_set_named(name)
        if path.stat().st_mtime < started_at
    ]
    for path in stale:
        path.unlink()

    return stale


def _capture(recording: _Recording, service: str, replaying: bool) -> None:
    """Drives the one incident this recording is of, and says what came of it.

    The name asked for on the command line is the *case*; the name on disk is
    that case as this run's `CODE_SEARCH` stores it. Converted here rather than
    in the mapping above, because a run records the world it is in - and the
    same case captured under two modes is two recordings of two different walks.
    """
    stored = stored_as(recording.name)
    print(f"=== {stored} ===")

    if replaying:
        _replay_from(stored)
    else:
        _arm_the_double(stored)

    # Read before anything is written, and from the clock the files are stamped
    # by: what makes an answer stale is that this run did not write it, and
    # every comparison after this point is against this moment.
    started_at = time.time()

    _a_world_this_recording_can_be_captured_in()

    if recording.scenario:
        _stage(recording.scenario)

    if recording.and_then:
        recording.and_then()

    incident_id = _an_incident_was_opened_by(service, recording.alert_name)

    print(f"incident [{incident_id}] drove scenario [{recording.scenario or 'none'}]")

    # The account is printed whatever happened to the walk. A walk that never
    # finished is the one whose timeline is worth reading - it is the only
    # record of how far it got and what it was doing when it stopped - and
    # printing it only on the way out meant the one failure nobody could
    # diagnose was the only one anybody needed to.
    try:
        _the_walk_came_to_a_stop(incident_id)
    finally:
        if not replaying:
            discarded = _discard_what_was_not_answered_again(stored, started_at)
            written = [path.stem for path in _the_set_named(stored)]
            print(f"recorded: {', '.join(written) or 'nothing'}")
            if discarded:
                print(
                    f"discarded: {', '.join(path.stem for path in discarded)} "
                    f"- answers of a longer walk this run did not need"
                )

        print("timeline:")
        for entry in _the_timeline_of(the_incidents_events(incident_id)):
            print(entry)

    # Judged only once the walk has actually stopped, and after the timeline is
    # out - so a refusal is read beside the account of what earned it.
    _the_walk_did_what_this_recording_is_of(
        recording, incident_id, the_incidents_events(incident_id)
    )


def _what_was_asked_for(names: list[str]) -> list[_Recording]:
    """The recordings named, or every one of them.

    An unknown name is refused rather than recorded under: the mapping is the
    whole point of taking names alone, and a typo would otherwise cost a real
    investigation and store its answer where nothing reads it.
    """
    known = {recording.name: recording for recording in EVERY_RECORDING}

    if names == [EVERY_RECORDING_KEYWORD]:
        return list(EVERY_RECORDING)

    unknown = [name for name in names if name not in known]
    if unknown:
        raise SystemExit(
            f"unknown recording(s): {', '.join(unknown)} - "
            f"known: {', '.join(known)}, or '{EVERY_RECORDING_KEYWORD}'"
        )

    return [known[name] for name in names]


def _the_two_declarations_of_a_fix_agree() -> None:
    """Refuses to start if the recorder and the grader disagree about fixes.

    Which walks have to come back with a patch is said twice, and has to be: the
    table below carries more than that - actions taken, hypotheses formed - while
    the grader wants only the names. So they are not merged; they are checked
    against each other, here, before a single token is spent.

    Drifting apart is not a loud failure otherwise. A scenario added to one and
    not the other leaves either a paid recording nobody refuses when the fix
    stops arriving, or a grader reporting a case as silent that was never
    supposed to speak.
    """
    recorder_says = {
        recording.name for recording in EVERY_RECORDING
        if _A_FIX_WAS_PROPOSED in recording.must_have
    }

    if recorder_says != set(THE_RECORDINGS_THAT_MUST_CARRY_A_FIX):
        raise SystemExit(
            f"the two declarations of which walks must carry a fix disagree: this "
            f"script expects {sorted(recorder_says)}, and "
            f"THE_RECORDINGS_THAT_MUST_CARRY_A_FIX says "
            f"{sorted(THE_RECORDINGS_THAT_MUST_CARRY_A_FIX)}. Put them back in "
            f"step before recording anything"
        )


def main() -> int:
    # The timeline printed at the end quotes the model, and the model writes
    # arrows and dashes this console cannot encode - a Windows terminal defaults
    # to a legacy codepage, and printing one character outside it raises. That
    # ended a *paid* run in a traceback after the recordings were safely on
    # disk, which reads as a failed recording and invites running it again.
    #
    # Asked whether it is a real stream rather than cast to one. `sys.stdout`
    # is only a `TextIOWrapper` when it is attached to a console or a file -
    # something that captures it hands over an object with no encoding to set,
    # and a cast would turn a check mypy can do into an `AttributeError` at the
    # top of a run that has already been paid for.
    # `line_buffering` for a second reason, and it is the one that shows. A run
    # this long is always started in the background with its output redirected,
    # and Python block-buffers a redirected stream - so the file stays empty of
    # everything this script says while the httpx logs, which go through
    # `logging`, fill it. Every line of progress then arrives at once, at the
    # end, which is exactly when nobody needs it: the question a person asks of
    # a run like this is how far it has got, and the answer was in the buffer.
    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(
            encoding="utf-8", errors="replace", line_buffering=True
        )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "names",
        nargs="+",
        help=f"the recordings to capture, or '{EVERY_RECORDING_KEYWORD}' for all of "
             f"them; each stages the scenario and fires the alert it belongs to",
    )
    parser.add_argument("--service", default=THE_SERVICE_NAME)
    parser.add_argument(
        "--replay",
        action="store_true",
        help="serve the stored recordings instead of calling the real API",
    )
    arguments = parser.parse_args()

    _the_two_declarations_of_a_fix_agree()

    asked_for = _what_was_asked_for(arguments.names)
    failed: list[str] = []

    # One failure does not end the run. The stack is up and paid for by the
    # time anything is captured, and a scenario that fails to record is a
    # reason to look at that scenario - not a reason to throw away the four
    # recordings that would have worked.
    for recording in asked_for:
        try:
            _capture(recording, arguments.service, arguments.replay)
        except Exception as error:
            print(f"FAILED {recording.name}: {error!r}")
            failed.append(recording.name)

    print(f"captured {len(asked_for) - len(failed)} of {len(asked_for)}")
    if failed:
        print(f"failed: {', '.join(failed)}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
