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
import shutil
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from io import TextIOWrapper
from pathlib import Path
from typing import Any, Final, NamedTuple

import httpx2
import psycopg
from agent_investigator.tools.answer import ANSWER_TOOL
from agent_postmortem.prompting import SUBMIT_TOOL_NAME
from anthropic_double.recordings import RECORDINGS_DIR, load
from argus_core import get_settings, to_iso
from argus_core.events import (
    ActionRecommended,
    ActionRefused,
    ActionTaken,
    FixAttempted,
    HypothesisFormed,
    LeadWeighed,
    PlatformUnavailable,
    SimilarIncidentsRecalled,
    VerdictReached,
)
from argus_core.models import ROLL_BACK_DEPLOYMENT, FixOutcome, IncidentStatus, Verdict
from argus_incidents.repository import runs
from argus_incidents.repository.runs import RunState
from pydantic import BaseModel
from qdrant_client import QdrantClient

from scripts.hold_the_stack import wait_until_told_to_stop
from tests.e2e.framework.argus import (
    MITIGATION_TIMEOUT_SECONDS,
    RECORDED_ABSENCE_OF_EVIDENCE,
    RECORDED_ACCELERATOR_HETEROGENEITY,
    RECORDED_ALARM_DISPROVEN,
    RECORDED_AUTOSCALER_FLAPPING,
    RECORDED_BAD_DEPLOYMENT,
    RECORDED_CACHE_MISCONFIGURED,
    RECORDED_CONTROL_PLANE_UNREACHABLE,
    RECORDED_CPU_SATURATION,
    RECORDED_DEPLOY_CAUSED_CORRUPTION,
    RECORDED_FALLBACK_DISABLED,
    RECORDED_FLAG_REVERT_LEAVES_A_FLAP,
    RECORDED_FLAG_TOGGLE,
    RECORDED_FLAG_TOGGLE_RED_HERRING,
    RECORDED_FLAG_TOGGLE_UNCORROBORATED,
    RECORDED_HALF_FINISHED_ROLLOUT,
    RECORDED_LEAD_BEFORE_THE_WALK,
    RECORDED_LEAD_MID_INVESTIGATION,
    RECORDED_MONITORING_BLIND_SPOT,
    RECORDED_MONITORING_CONFIGURATION_DRIFT,
    RECORDED_OUTPUT_QUALITY_DEGRADATION,
    RECORDED_PRICING_SERVICE_DEGRADED,
    RECORDED_RESOLVED_FROM_SLACK,
    RECORDED_RESOLVED_FROM_THE_PAGE,
    RECORDED_RESOLVED_IN_PAGERDUTY,
    RECORDED_RESOURCE_LEAK,
    RECORDED_SILENT_DATA_CORRUPTION,
    RECORDED_SLOW_CANARY_ROLLOUT,
    RECORDED_STATE_DIVERGENCE,
    RECORDED_UNDATED_STATE_DIVERGENCE,
    RECORDED_UPSTREAM_DEPENDENCY_FAILURE,
    THE_RECORDINGS_THAT_MUST_CARRY_A_FIX,
    THE_SERVICE_NAME,
    TOOL_USE_TYPE,
    stored_as,
    the_anchor_file_for,
    the_held_call_arrived,
    the_model_answers_from,
)
from tests.e2e.framework.builders import THE_ERROR_RATE_RULES_WORDS
from tests.e2e.framework.chat import (
    RECORDED_INTENT_INFORMATION,
    RECORDED_INTENT_RESOLVE,
    THE_WORDS_CLASSIFIED_AS_INFORMATION,
    THE_WORDS_CLASSIFIED_AS_RESOLVED,
    a_person_writes,
    the_chat_platform_knows,
    the_intent_agent_answers_from,
    the_message_became_a_lead,
    the_offer_made_in,
    the_person_presses,
    the_thread_of,
)
from tests.e2e.framework.flags import (
    THE_DEMO_FLAG,
    flags_evaluating_true,
    only_the_boot_flags_were_left_in_the_provider,
    the_boot_flags_were_put_back,
    the_flag_provider_forgot_every_change,
)
from tests.e2e.framework.memory import that_flag_was_tried_before_and_did_not_help
from tests.e2e.framework.oncall import (
    a_resolution_by,
    the_on_call_platform_delivers,
    the_on_call_platform_holds,
)
from tests.e2e.framework.worker import the_worker_is_paused, the_worker_resumes
from tests.e2e.framework.world import (
    A_SEED_SECONDS,
    the_incidents_events,
    the_recorded_anchor_was_staged,
    the_shops_stand_in_was_put_back,
    the_shops_window,
)

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
# The action Argus worked out and declined to take. Beside the refusal rather
# than folded into it, because a walk can refuse and have nothing to hand on:
# five of the six refusals reject the action itself, and only this one leaves
# somebody something to do. A recording held to the refusal alone would accept a
# walk that stopped for one of the other five.
_AN_ACTION_WAS_RECOMMENDED: Final = _Published(ActionRecommended)
# The recommendation, held to its kind. Silent corruption's action follows the
# change recorded at the onset, so a walk that recommended putting a flag back
# recommended an answer to a different incident - one this scenario never staged.
_A_ROLLBACK_WAS_RECOMMENDED: Final = _Published(
    ActionRecommended, {"action_type": ROLL_BACK_DEPLOYMENT}
)
_A_VERDICT_WAS_REACHED: Final = _Published(VerdictReached)
# The verdict, held to its outcome. A revert the rule never agreed with is the
# whole of the flap's recording, and a walk confirmed on it is the defect this
# recording exists to show closed - a recording of that is a recording of the bug.
_A_VERDICT_REFUTED_AN_ACTION: Final = _Published(
    VerdictReached, {"outcome": Verdict.REFUTED}
)
# The walk found out, mid-incident, that a platform it acts through is not
# answering. Held to for the one recording captured against a refusing platform,
# because every other expectation that recording could be held to is satisfied by
# a walk that never touched the platform at all: it would take an action, reach a
# verdict, end mitigated and write a postmortem, having simply reverted the flag
# first. That is a recording of the ordinary flag incident, stored under this
# name, and the case replaying it would fail on the one assertion the corpus was
# bought for.
_A_PLATFORM_WENT_AWAY: Final = _Published(PlatformUnavailable)
# Memory was searched during the walk and came back with something. Which record
# it came back with is not checked here - the event carries a list, and this asks
# only that the list exists, which is all a corpus can promise. The case that
# replays this one names the record it staged.
#
# The search rather than the demotion it may lead to: whether anything moves needs
# a round that offered a candidate to move the flag behind, and how many
# candidates a round offers is the model's to decide - so a recording held to the
# demotion is a recording refused for the model having been concise.
_MEMORY_WAS_READ: Final = _Published(SimilarIncidentsRecalled)
# A lead from the thread, weighed. Any standing: which one the model gives it is
# the model's judgement, and a recording is held to the pipeline having carried
# the lead to a weighing - whether a lead moves the model is the eval's question.
_A_LEAD_WAS_WEIGHED: Final = _Published(LeadWeighed)
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

    `once_opened` is whatever the replaying case does once the incident exists
    and before the walk is let go - a person writing in its thread, with the
    walk held back until what they wrote is understood. Handed the incident's
    id, because the thread is the incident's.

    `resolved_by` is whatever ends the walk from outside it once the incident
    exists - a person reporting it over. Apart from `once_opened` because the
    write-up is the walk's very next call after it: a write-up recorded afresh
    is held before this runs, where after it the call could already have found
    the queue empty and been refused.

    `walk_from` names the recording whose walk this one's is, for an incident
    that ends early in another's walk. Its answers up to the end of the
    investigation, its write-up and its anchor are what a postmortem-only run
    starts this set from, so only the write-up is paid for - and it is written
    about this incident's own shorter record rather than the longer one's.

    `may_take_seconds` is how long the walk is waited for. One figure serves
    every walk whose waits are minutes - judged by the levels, or by a rule
    looking back a minute or two; a walk judged by a rule with a long range
    waits that range out for every candidate it tries, and is given its own.

    `alert_name` is `None` for an incident the shop pages about itself. Every
    other alert here is a rule firing on a series, and a payload assembled
    locally carries nothing the run does not already know - but an alert that
    carries a *finding* cannot be written here at all. The one that dates a
    silent corruption states its onset, and an onset is what decides whether
    anything could confirm an action taken on it; a payload built from
    `alert_name` alone states none, so the walk would be recorded reaching a
    different ending than the case replaying it arranges.
    """
    name: str
    scenario: str | None
    alert_name: str | None
    ends_as: IncidentStatus
    must_have: tuple[_Published, ...]
    and_then: Callable[[], None] | None = None
    once_opened: Callable[[str], None] | None = None
    resolved_by: Callable[[str], None] | None = None
    walk_from: str | None = None
    may_take_seconds: float = A_WHOLE_INVESTIGATION_SECONDS


# How long one candidate is watched under the burn-rate rule the flap pages on:
# its ten-minute range, one evaluation and the source's lag, which is the
# deadline Mitigation reads off the rule itself. Spelled here because a script
# waiting for the walk has no rule in hand until the walk has read it.
_THE_SUSTAINED_RULES_WAIT_SECONDS: Final = (
    10 + 1 + get_settings().metrics_reporting_lag_minutes
) * 60
# The longest walk the settings allow under that rule: every round tries every
# candidate, each watched for that whole deadline - on the real clock, since a
# recording run has no other. Plus the ordinary figure, for everything that is
# not watching: the postmortem, and whatever else the walk is waited for. A
# bound rather than an expectation, so a walk that ends sooner is collected as
# soon as it does; what it buys is that the longer walk is not cut off halfway,
# with its answers paid for and unusable.
_A_WALK_JUDGED_BY_THE_SUSTAINED_RULE_SECONDS: Final = (
    get_settings().investigation_max_rounds
    * (
        get_settings().investigation_max_seconds
        + get_settings().investigation_max_candidates * _THE_SUSTAINED_RULES_WAIT_SECONDS
    )
    + A_WHOLE_INVESTIGATION_SECONDS
)

# Who writes the lead in the two recordings that have one. Nobody the replaying
# cases name: the double serves whatever name it was staged with.
_A_PERSON_ID: Final = "U0SOMEONE"
_A_PERSON: Final = "Some Person"


def _somebody_will_write_before_the_walk() -> None:
    """Readies the thread's side of the conversation, and pauses the worker so
    nothing walks the incident until the lead is understood."""
    the_intent_agent_answers_from(RECORDED_INTENT_INFORMATION)()
    the_chat_platform_knows(_A_PERSON_ID, _A_PERSON)()
    the_worker_is_paused()()


def _the_lead_is_written_before_the_walk(incident_id: str) -> None:
    """Writes the lead, waits for it to be understood, and lets the worker go.

    Resumed whatever happens on the way, because a worker left suspended walks
    no incident after this one either.
    """
    try:
        a_person_writes(_A_PERSON_ID, THE_WORDS_CLASSIFIED_AS_INFORMATION,
                        in_thread=the_thread_of(incident_id))
        the_message_became_a_lead(incident_id)
    finally:
        the_worker_resumes()


def _somebody_will_write_while_the_first_turn_is_held() -> None:
    """Readies the thread's side of the conversation, and has the walk's model
    hold its first call.

    Held here rather than through the e2e framework's `the_model_is_held`,
    which resets the double first: by now it is armed to record, and a reset
    would take that back.
    """
    the_intent_agent_answers_from(RECORDED_INTENT_INFORMATION)()
    the_chat_platform_knows(_A_PERSON_ID, _A_PERSON)()
    httpx2.post(f"{ANTHROPIC_DOUBLE_BASE_URL}/double-control/hold",
                timeout=REQUEST_TIMEOUT_SECONDS).raise_for_status()


def _the_lead_is_written_while_the_first_turn_is_held(incident_id: str) -> None:
    """Waits for the walk's first call to be held, writes the lead, waits for it
    to be understood, and lets the call go upstream.

    Released whatever happens on the way, because a held call is a walk that
    never ends.
    """
    thread = the_thread_of(incident_id)

    try:
        the_held_call_arrived()
        a_person_writes(_A_PERSON_ID, THE_WORDS_CLASSIFIED_AS_INFORMATION, in_thread=thread)
        the_message_became_a_lead(incident_id)
    finally:
        httpx2.post(f"{ANTHROPIC_DOUBLE_BASE_URL}/double-control/release",
                    timeout=REQUEST_TIMEOUT_SECONDS).raise_for_status()


# What the cases resolving an incident say, said here as they say it. The
# write-up quotes who reported the incident over and what they wrote, so a
# recording captured with other words would replay naming somebody nobody in
# the case is.
_THE_NOTE_ON_THE_PAGE: Final = "kept the flag off and told the checkout team"
_THE_ON_CALL_INCIDENT: Final = "PSOMEINCIDENT"
_THE_ON_CALL_PERSON: Final = "Some Person"
_THE_ON_CALL_PERSON_ID: Final = "PSOMEONE"
_THE_ON_CALL_NOTE: Final = "kept the flag off and paged the checkout team"
_THE_ON_CALL_INCIDENT_RESOLVED_AFTER: Final = timedelta(minutes=10)
_THE_ON_CALL_INCIDENT_ACKNOWLEDGED_AFTER: Final = timedelta(minutes=1)


def _argus_has_turned_the_flag_off() -> None:
    """Waits until Mitigation has acted, the moment those cases resolve at."""
    deadline = time.monotonic() + MITIGATION_TIMEOUT_SECONDS

    while THE_DEMO_FLAG in flags_evaluating_true():
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Argus never turned [{THE_DEMO_FLAG}] off within "
                               f"[{MITIGATION_TIMEOUT_SECONDS}s]")

        time.sleep(A_POLL_SECONDS)


def _it_was_reported_over(answered: httpx2.Response, where: str) -> None:
    if answered.status_code not in (HTTPStatus.OK, HTTPStatus.ACCEPTED):
        raise RuntimeError(f"resolving from {where} answered [{answered.status_code}]: "
                           f"{answered.text}")


def _resolved_on_the_incident_page(incident_id: str) -> None:
    """Resolves the incident from its page, with the case's note, once the flag
    is off."""
    _argus_has_turned_the_flag_off()
    _it_was_reported_over(
        httpx2.post(f"{ARGUS_WEB_BASE_URL}/incidents/{incident_id}/resolve",
                    data={"note": _THE_NOTE_ON_THE_PAGE},
                    timeout=REQUEST_TIMEOUT_SECONDS),
        "the incident page"
    )


def _the_on_call_platform_paged_somebody() -> None:
    """Stages the PagerDuty incident the case stages, for the alert this script
    sends - the key PagerDuty stamps is read off the alert group, which is the
    alert's name alone."""
    the_on_call_platform_holds(
        _THE_ON_CALL_INCIDENT,
        paged_for=_an_alert_for(THE_SERVICE_NAME, "HighErrorRate", None),
        paged_at=datetime.now(UTC),
        resolved_after=_THE_ON_CALL_INCIDENT_RESOLVED_AFTER,
        acknowledged_after={_THE_ON_CALL_PERSON_ID: _THE_ON_CALL_INCIDENT_ACKNOWLEDGED_AFTER},
        resolution_note=_THE_ON_CALL_NOTE
    )()


def _resolved_in_the_on_call_platform(dont_care_incident_id: str) -> None:
    """Resolves the platform's incident once the flag is off, delivered as
    PagerDuty would deliver it."""
    _argus_has_turned_the_flag_off()
    _it_was_reported_over(
        the_on_call_platform_delivers(
            a_resolution_by(_THE_ON_CALL_PERSON, _THE_ON_CALL_PERSON_ID, _THE_ON_CALL_INCIDENT)),
        "the on-call platform"
    )


def _somebody_will_resolve_it_in_the_thread() -> None:
    """Readies the thread's side of a resolution, and has the walk's model hold
    its first call - for `_somebody_will_write_while_the_first_turn_is_held`'s
    reason, without the e2e framework's reset."""
    the_intent_agent_answers_from(RECORDED_INTENT_RESOLVE)()
    the_chat_platform_knows(_A_PERSON_ID, _A_PERSON)()
    httpx2.post(f"{ANTHROPIC_DOUBLE_BASE_URL}/double-control/hold",
                timeout=REQUEST_TIMEOUT_SECONDS).raise_for_status()


def _a_resolution_in_the_thread() -> tuple[Callable[[str], None], Callable[[str], None]]:
    """The words written while the first turn is held, and the press on what
    Argus offers back - two hooks, since the write-up comes straight after the
    press and has to be held before it, where the release before it lets every
    hold go.

    One pair sharing what was written, because the press names the message it
    answers.
    """
    written: list[str] = []

    def while_the_first_turn_is_held(incident_id: str) -> None:
        try:
            the_held_call_arrived()
            written.append(a_person_writes(_A_PERSON_ID, THE_WORDS_CLASSIFIED_AS_RESOLVED,
                                           in_thread=the_thread_of(incident_id)))
        finally:
            httpx2.post(f"{ANTHROPIC_DOUBLE_BASE_URL}/double-control/release",
                        timeout=REQUEST_TIMEOUT_SECONDS).raise_for_status()

    def pressed(incident_id: str) -> None:
        offer = the_offer_made_in(the_thread_of(incident_id))
        _it_was_reported_over(the_person_presses(_A_PERSON_ID, offer, about=written[-1]),
                              "the thread")

    return while_the_first_turn_is_held, pressed


_WRITTEN_IN_THE_THREAD, _PRESSED_IN_THE_THREAD = _a_resolution_in_the_thread()


def _the_shop_is_reporting() -> None:
    """Refuses to fire the alert until the shop serves a window at all.

    A disproof is of a window that was read and found flat; over an empty one
    the walk escalates instead, and the recording would be of the other ending.
    """
    the_shops_window()


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
    # The same incident, reported over by a person part of the way through it:
    # from its page and from the on-call platform once the flag is off, and
    # from its thread before anything was investigated. Each walk is the flag
    # toggle's up to where the person stops it, so only the write-up differs -
    # and it differs, because each is about a shorter record than the flag
    # toggle's and names who ended it.
    _Recording(
        RECORDED_RESOLVED_FROM_THE_PAGE,
        "feature-flag-toggle",
        "HighErrorRate",
        IncidentStatus.RESOLVED,
        (_AN_ACTION_WAS_TAKEN,),
        resolved_by=_resolved_on_the_incident_page,
        walk_from=RECORDED_FLAG_TOGGLE
    ),
    # Captured on a stack of its own, never after another incident of this
    # alert: the platform's resolution finds its incident by the alert group's
    # key, and on a shared stack an earlier incident already holds that key.
    _Recording(
        RECORDED_RESOLVED_IN_PAGERDUTY,
        "feature-flag-toggle",
        "HighErrorRate",
        IncidentStatus.RESOLVED,
        (_AN_ACTION_WAS_TAKEN,),
        and_then=_the_on_call_platform_paged_somebody,
        resolved_by=_resolved_in_the_on_call_platform,
        walk_from=RECORDED_FLAG_TOGGLE
    ),
    # Nothing beyond the ending: the person's press arrives while the walk
    # waits after its first step, before anything was acted on.
    _Recording(
        RECORDED_RESOLVED_FROM_SLACK,
        "feature-flag-toggle",
        "HighErrorRate",
        IncidentStatus.RESOLVED,
        (),
        and_then=_somebody_will_resolve_it_in_the_thread,
        once_opened=_WRITTEN_IN_THE_THREAD,
        resolved_by=_PRESSED_IN_THE_THREAD,
        walk_from=RECORDED_FLAG_TOGGLE
    ),
    # The incident whose only evidence is the deploy history. Its alert is
    # latency because nothing here fails - the revision that went out is slower
    # and still correct - and the walk now goes the whole way: the mode is
    # answered by returning the deployment, so what has to be on the record is
    # the action rather than the judgement that stopped short of one.
    _Recording(
        RECORDED_BAD_DEPLOYMENT,
        "bad-deployment",
        "HighLatency",
        IncidentStatus.MITIGATED,
        (_AN_ACTION_WAS_TAKEN,)
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
        #
        # And the memory read, because the case replaying this one stages a record
        # and asserts the walk found it. Held here so that a capture in which the
        # search found nothing is refused at record time rather than replayed for
        # weeks as a walk that never reached memory.
        (_AN_ACTION_WAS_TAKEN, _A_VERDICT_WAS_REACHED, _MEMORY_WAS_READ),
        that_flag_was_tried_before_and_did_not_help
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
    # The leak's pair, and the only walk whose mitigation adds something rather
    # than putting something back. Its alert is latency: nothing fails here and
    # the heap never stirs, so an error-rate or a memory alert would be answering
    # a question this scenario never asks - and what separates it from the leak
    # is that the consumption moved with the traffic.
    _Recording(
        RECORDED_CPU_SATURATION,
        "cpu-saturation",
        "HighLatency",
        IncidentStatus.MITIGATED,
        # The action and the verdict it earned. The action because the claim is
        # that capacity was added rather than a process restarted, and the verdict
        # because a scale-out the shop never answered for would be a recording of
        # a walk that stopped before finding out whether capacity was the answer.
        # No fix: the shop's source is correct, and a `must_have` demanding one
        # would refuse the walk this recording is of.
        (_AN_ACTION_WAS_TAKEN, _A_VERDICT_WAS_REACHED)
    ),
    # The saturation pair's near neighbour, and the longest walk in this list.
    # Its alert is latency for the reason the surge's is - nothing fails and the
    # heap never stirs - and what separates the two is that the capacity itself
    # keeps moving.
    _Recording(
        RECORDED_AUTOSCALER_FLAPPING,
        "autoscaler-flapping",
        "HighLatency",
        IncidentStatus.MITIGATED,
        # The action and the verdict it earned, exactly as the surge's are, and
        # no more than that. A walk here may reach for capacity first and be
        # refuted by the controller before it pins - that is the near-miss this
        # scenario was built to demonstrate - so a `must_have` naming the pin
        # specifically would refuse a recording of the very behaviour worth
        # capturing, and one demanding a refutation would refuse a walk that read
        # the capacity series correctly first time. What the corpus holds is what
        # happened.
        (_AN_ACTION_WAS_TAKEN, _A_VERDICT_WAS_REACHED)
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
    # The third latency incident, and the one whose answer is not the service
    # that was paged. Its alert is latency for the same reason as the two above
    # - nothing fails, the dependency answers every call slowly - and what
    # separates it from them is that the deploy history is empty, so the
    # release its shape suggests is refuted by the one channel that could
    # confirm it.
    _Recording(
        RECORDED_PRICING_SERVICE_DEGRADED,
        "pricing-service-degraded",
        "HighLatency",
        IncidentStatus.MITIGATED,
        # An action, because a recording of this walk that escalated would be a
        # recording of the model declining to name a service it was not paged
        # about - which is the failure this scenario exists to catch, not the
        # answer it exists to store.
        (_AN_ACTION_WAS_TAKEN,)
    ),
    # The one incident where no revision is at fault: a rolling update paused
    # half-way, with two correct revisions serving at once. Its alert is the error
    # rate, because a replica that cannot read an entry a newer one wrote fails the
    # page outright rather than waiting - which is the flag scenarios' page with an
    # empty flag history and a deploy at the onset, and the collision this
    # recording exists to capture the model's answer to.
    _Recording(
        RECORDED_HALF_FINISHED_ROLLOUT,
        "half-finished-rollout",
        "HighErrorRate",
        IncidentStatus.MITIGATED,
        # The action and the verdict it earned, as the capacity walks have them:
        # the action because the claim is that the deployment was returned, and the
        # verdict because a rollback the shop never answered for would be a
        # recording of a walk that stopped before finding out whether converging
        # the fleet was the answer. No fix demanded - both revisions pass the
        # shop's own tests, so what was skipped is a migration step rather than
        # anything a patch could repair, and a `must_have` naming one would refuse
        # the walk this recording is of.
        (_AN_ACTION_WAS_TAKEN, _A_VERDICT_WAS_REACHED)
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
    ),
    # The same alert over a shop that is reporting and flat. A window read and
    # holding no departure is evidence against the alarm, so the walk closes it
    # without a cause or an action - and makes no model call before the
    # write-up, which is the whole of what this recording holds. Its own rather
    # than the escalated one's: that walk names a candidate this one never
    # stores, and a write-up citing it is refused here.
    _Recording(
        RECORDED_ALARM_DISPROVEN,
        "silent-data-corruption",
        "HighErrorRate",
        IncidentStatus.DISPROVEN,
        (),
        and_then=_the_shop_is_reporting
    ),
    # The one incident whose alert is not written here. The shop's own weekly
    # check finds stored totals that stopped keeping up with the purchases
    # behind them, and pages with the count, the widest gap and the oldest
    # affected purchase - the last of which dates the fault a week back, where
    # no series marks anything at all.
    #
    # Held to the recommendation rather than to the refusal alone. A walk that
    # refused for any of the other five reasons would also publish
    # `action-refused`, and would be a recording of the wrong ending: this one
    # is of Argus naming the cause, working out the move, and declining to make
    # it because only next week's check could say whether it worked.
    _Recording(
        RECORDED_SILENT_DATA_CORRUPTION,
        "silent-data-corruption",
        None,
        IncidentStatus.RECOMMENDED,
        (_A_HYPOTHESIS_WAS_FORMED,
         _AN_ACTION_WAS_REFUSED,
         _AN_ACTION_WAS_RECOMMENDED)
    ),
    # The same damage by the other change. No flag moved; a revision went out at
    # the instant the oldest short total was written, and the deploy history is
    # the only place that says so. Held to the rollback rather than to any
    # recommendation, because the kind is the whole of what separates this walk
    # from the flag one above it.
    _Recording(
        RECORDED_DEPLOY_CAUSED_CORRUPTION,
        "monthly-totals-falling-behind",
        None,
        IncidentStatus.RECOMMENDED,
        (_A_HYPOTHESIS_WAS_FORMED,
         _AN_ACTION_WAS_REFUSED,
         _A_ROLLBACK_WAS_RECOMMENDED)
    ),
    # The one incident staged against a platform that will not act. Two changes
    # moved in the window and the closer of them is the deployment, so the walk
    # is meant to reach for the rollback, be told the platform is unavailable,
    # pass over the three other actions that go through it, and end on the flag
    # revert - the only mitigation left to it.
    #
    # Captured under `both` alone, like the case that replays it: nothing in this
    # claim varies by which tool found a file. The two attempts cost what one
    # does - a platform that refuses an action ends that attempt without the model
    # being asked anything - so what this bills for is the investigation and the
    # fix, like the cheapest walk here.
    _Recording(
        RECORDED_CONTROL_PLANE_UNREACHABLE,
        "control-plane-unreachable",
        "HighErrorRate",
        IncidentStatus.MITIGATED,
        (_A_PLATFORM_WENT_AWAY, _AN_ACTION_WAS_TAKEN, _A_VERDICT_WAS_REACHED)
    ),
    # The other incident the shop pages about itself, and the only one whose
    # evidence is an absence. A revision renames the port the shop's metrics are
    # served on, so `/metrics` carries no row from that minute on and no rule
    # watching a series fires at all - what pages is the rule that notices a
    # series which was reporting has stopped. The alert cannot be written here
    # for the reason the corruption's cannot: it states the last sample as its
    # onset, and that minute is the whole of what dates the incident.
    #
    # Held to the action and the verdict rather than the ending alone. The
    # cause here lies *after* the onset - the change is what ended the
    # readings - so a walk that reached the right hypothesis and still found
    # no change to reverse would escalate, which is the ending this scenario
    # had before the change window learned to reach past a stated onset. A
    # terminal status would not tell those two apart.
    _Recording(
        RECORDED_MONITORING_BLIND_SPOT,
        "monitoring-blind-spot",
        None,
        IncidentStatus.MITIGATED,
        (_A_HYPOTHESIS_WAS_FORMED, _AN_ACTION_WAS_TAKEN, _A_VERDICT_WAS_REACHED)
    ),
    # The blind spot's sibling: the same silence, from a rename that was meant.
    # Held to a refusal and a proposal rather than to an action, because the
    # whole claim is that the walk declines the rollback it could take - a walk
    # that reached `escalated` having rolled back first would carry a different
    # account, and the terminal status alone could not tell the two apart.
    _Recording(
        RECORDED_MONITORING_CONFIGURATION_DRIFT,
        "monitoring-configuration-drift",
        None,
        IncidentStatus.ESCALATED,
        (_A_HYPOTHESIS_WAS_FORMED, _AN_ACTION_WAS_REFUSED, _A_FIX_WAS_PROPOSED)
    ),
    # The third incident the shop pages about itself, and the only one whose
    # alert carries addresses. Replication to the summary cache's standby broke
    # three hours before the primary died; the standby was promoted and has been
    # serving whatever it last managed to copy. The alert cannot be written here
    # for the reason the other two cannot - it states the promotion as the onset,
    # and that minute is the whole of what dates the incident - and it carries one
    # key per stale entry, which only the shop's own check can produce.
    #
    # Held to the action and the verdict rather than the ending alone, as the
    # blind spot is, and here the verdict is the point. No series ever departed,
    # so nothing could come back down: what confirms this attempt is the store's
    # own count of what it removed. A walk that reached `MITIGATED` without one
    # would have closed the incident on a window that was never evidence of
    # anything, which is the hole this mode exists to close.
    _Recording(
        RECORDED_STATE_DIVERGENCE,
        "cache-failed-over",
        None,
        IncidentStatus.MITIGATED,
        (_A_HYPOTHESIS_WAS_FORMED, _AN_ACTION_WAS_TAKEN, _A_VERDICT_WAS_REACHED)
    ),
    # The same failover with nobody recording when it happened, so the shop's
    # alert carries its finding and no onset. Held to the same three as the dated
    # walk: what differs is what the investigation is anchored on, not what it
    # has to reach.
    _Recording(
        RECORDED_UNDATED_STATE_DIVERGENCE,
        "cache-failed-over-undated",
        None,
        IncidentStatus.MITIGATED,
        (_A_HYPOTHESIS_WAS_FORMED, _AN_ACTION_WAS_TAKEN, _A_VERDICT_WAS_REACHED)
    ),
    # The flag incident again, with a revert that does not hold: one clean minute,
    # then single failing minutes at gaps that never repeat. The rule that paged
    # is the burn-rate one, which goes on firing while any minute in ten fails, so
    # it is what judges the revert - and the payload names it, as the case's does.
    #
    # Held to the revert's refutation, which is the whole claim. `ESCALATED` is a
    # guess at the ending rather than the case's demand: what the walk does once
    # the revert is refuted is the model's to choose, and the case asserts only
    # that it did not end mitigated. A capture ending some other way short of
    # that is still kept on disk, as every refused capture is, and replays.
    _Recording(
        RECORDED_FLAG_REVERT_LEAVES_A_FLAP,
        "flag-revert-leaves-a-flap",
        "ErrorRateSustained",
        IncidentStatus.ESCALATED,
        (_AN_ACTION_WAS_TAKEN, _A_VERDICT_REFUTED_AN_ACTION),
        may_take_seconds=_A_WALK_JUDGED_BY_THE_SUSTAINED_RULE_SECONDS
    ),
    # A categoriser upgrade that files purchases worse, and nothing else moves:
    # the one series that departs is the share the shop's rule watches, so the
    # onset, the verdict and the recovery are all read off it. Captured under
    # `both` alone, like the case that replays it.
    #
    # Held to the verdict as well as the action, because the rollback is judged
    # by that rule and nothing else could confirm it - and to the fix, because
    # the upgrade is still on the branch once the earlier model is back.
    _Recording(
        RECORDED_OUTPUT_QUALITY_DEGRADATION,
        "categoriser-model-upgraded",
        "CategorisationConfidenceLow",
        IncidentStatus.MITIGATED,
        (_AN_ACTION_WAS_TAKEN, _A_VERDICT_WAS_REACHED, _A_FIX_WAS_PROPOSED)
    ),
    # A replica rescheduled onto a card that rounds, and nothing deployed: the
    # categoriser's shape with the cause moved off the change channel and into
    # the placement. Captured under `both` alone, like the case that replays it.
    #
    # Held to the verdict and the fix for the categoriser's reasons: the pin is
    # judged by the rule that paged, and the scorer still allows TF32 wherever
    # it runs once every replica is back on V100.
    _Recording(
        RECORDED_ACCELERATOR_HETEROGENEITY,
        "scorer-replica-rescheduled",
        "FraudHoldsHigh",
        IncidentStatus.MITIGATED,
        (_AN_ACTION_WAS_TAKEN, _A_VERDICT_WAS_REACHED, _A_FIX_WAS_PROPOSED)
    ),
    # Two flags changed in one minute, and somebody in the thread saying which
    # is the cause - before the walk has started, so the lead is in the
    # Investigator's opening. Held to the lead being weighed, and not to how:
    # the first capture refuted it twice over on the shop's evidence, which is
    # a judgement, and a recording refused for a judgement is a run paid for and
    # thrown away.
    _Recording(
        RECORDED_LEAD_BEFORE_THE_WALK,
        "competing-flag-changes",
        "HighErrorRate",
        IncidentStatus.MITIGATED,
        (_A_LEAD_WAS_WEIGHED, _AN_ACTION_WAS_TAKEN),
        and_then=_somebody_will_write_before_the_walk,
        once_opened=_the_lead_is_written_before_the_walk
    ),
    # The same, with the lead written while the Investigator's first call is
    # held: after the opening has gone out, so it arrives with the first turn's
    # results rather than in the opening.
    _Recording(
        RECORDED_LEAD_MID_INVESTIGATION,
        "competing-flag-changes",
        "HighErrorRate",
        IncidentStatus.MITIGATED,
        (_A_LEAD_WAS_WEIGHED, _AN_ACTION_WAS_TAKEN),
        and_then=_somebody_will_write_while_the_first_turn_is_held,
        once_opened=_the_lead_is_written_while_the_first_turn_is_held
    )
)

EVERY_RECORDING_KEYWORD = "all"


# The words each scenario's rule pages with, where that rule is not the shop's
# error-rate rule: the shop's own `_WHAT_FIRED` (`monitoring.py` in the demo
# app), word for word, as the e2e case replaying each recording sends them.
# Three latency rules share one alert name, so the words are the only thing in
# the page that says which percentile moved - and Argus names the paging rule's
# series by them.
_WHAT_EACH_SCENARIO_PAGES_WITH: Final[dict[str, str]] = {
    "bad-deployment": "p95 latency above threshold for 5m",
    "cache-misconfigured": "p50 latency above threshold for 5m",
    "slow-canary-rollout": "p99 latency above threshold for 5m",
    "resource-leak": "Memory usage climbing against the container limit for 15m",
    "pricing-service-degraded": "p95 latency above threshold for 5m",
    "cpu-saturation": "p95 latency above threshold for 5m",
    "autoscaler-flapping": "p95 latency above threshold for 5m",
    "flag-revert-leaves-a-flap": "Error rate above 2.5% averaged over 10m",
    "categoriser-model-upgraded": "Share of purchases categorised confidently below 80% for 5m",
    "scorer-replica-rescheduled": "Share of purchases held for review above 10% for 5m"
}


def _an_alert_for(service: str,
                  alert_name: str,
                  rule_uid: str | None,
                  scenario: str | None = None) -> dict[str, Any]:
    """A Grafana webhook payload, as Grafana would send it.

    `startsAt` is now, and that matters: retrieval is anchored on the alert
    time and the Target Service stages a scenario relative to the moment it was
    staged, so a fixed timestamp would point the window at minutes the fixture
    never wrote.

    `summary` is the words the staged scenario's rule pages with. Argus reads
    them as the sender's own account and names the paging rule's series by
    them, so a recording captured under other words is a model answering an
    alert no replay of it sends.

    `generatorURL` links to the rule the staged scenario trips, which is the
    one place Grafana's webhook names the rule that fired, and the e2e suite's
    alerts link to it the same way. It is what decides how a mitigation is
    judged - by the rule where one is named, by the levels where none is - so a
    payload without it records a walk judged one way and replays it judged the
    other. Where nothing is staged the link is the one the suite's builder
    sends.
    """
    summary = _WHAT_EACH_SCENARIO_PAGES_WITH.get(scenario or "", THE_ERROR_RATE_RULES_WORDS)
    linked = service if rule_uid is None else rule_uid

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
                "generatorURL": f"http://grafana.local/alerting/grafana/{linked}/view",
                "fingerprint": "abc123def456"
            }
        ],
        "groupLabels": {"alertname": alert_name},
        "commonLabels": {"alertname": alert_name, "service": service},
        "commonAnnotations": {"summary": summary},
        "externalURL": "http://grafana.local",
        "version": "1",
        "groupKey": f'{{}}/{{alertname="{alert_name}"}}',
    }


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
    with httpx2.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
        control.post("/double-control/reset").raise_for_status()
        control.post("/double-control/record", json={"name": name}).raise_for_status()


class _AWalkIsStillLive(Exception):
    """A walk that would not stop, which ends the run rather than the case:
    every capture after it would be recorded into a world nobody controls."""


def _no_walk_is_live() -> None:
    """Ends whatever walk is still live, and waits until none is.

    A precondition of every case rather than cleanup after a failed one,
    because a walk outlives its case whatever ended the case - a failure, an
    interrupt, an earlier invocation - and a live one acts on the world the next
    case stages: it answers its calls from that case's queue, has its write-up
    caught by that case's hold, and between calls still reverts the flags that
    case has just set. That is how a flap walk once came to be recorded as the
    categoriser's write-up.

    The worker is resumed so a paused one lets its run go; the double is reset
    so the walk's next call finds nothing queued and fails. Then the wait, bounded
    by the longest walk there is, since a walk watching a verification asks
    nothing until the watch ends.
    """
    the_worker_resumes()
    with httpx2.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
        control.post("/double-control/reset").raise_for_status()

    deadline = time.monotonic() + _A_WALK_JUDGED_BY_THE_SUSTAINED_RULE_SECONDS

    while True:
        with psycopg.connect(DATABASE_URL) as connection:
            live = runs.get_unsettled_runs(connection)

        if not live:
            return

        if time.monotonic() >= deadline:
            raise _AWalkIsStillLive(
                f"incidents {[run.incident_id for run in live]} were still being walked "
                f"after [{_A_WALK_JUDGED_BY_THE_SUSTAINED_RULE_SECONDS:.0f}s]"
            )

        time.sleep(A_POLL_SECONDS)


def _a_world_this_recording_can_be_captured_in() -> None:
    """Puts the Target Environment back before each incident is driven.

    The e2e suite's own teardown, step for step and in its order: the worker
    resumed, in case the last recording paused it and failed before letting
    it go, the service's scenario reset, the shop's stand-in made to forget any
    anchor staged and never seeded from, both boot flags put back where the
    stack starts them, every
    flag the environment did not boot with deleted, the provider's record of
    what changed erased, and what Argus remembers of earlier incidents dropped.
    Reused rather than restated, because a recording captured in a world the
    replaying case never arranges is a recording of a different incident.

    This is what one shared stack costs. Running the session per recording got
    a virgin world from `compose down -v`; here the previous recording's
    mitigations are still on the flags, and its toggles are still in the
    history the next investigation reads as evidence.

    Memory is the step that outlives Postgres, and leaving it out cost a
    recording. Every walk files what it tried, and a later walk demotes any
    candidate whose action a similar incident already refuted - so the red
    herring's refuted flag revert, eleven walks earlier in the same run,
    demoted the *correct* leading candidate of a flag incident recorded after
    it. That walk then acted on a runner-up naming a deployment, asked the
    platform to roll back a scenario that stages no deploy, and escalated. The
    model had ranked it right; what changed the answer was a store neither
    recording mentions.
    """
    the_worker_resumes()
    httpx2.post(f"{TARGET_SERVICE_BASE_URL}/scenario/reset", timeout=30.0)
    the_shops_stand_in_was_put_back()
    the_boot_flags_were_put_back()
    only_the_boot_flags_were_left_in_the_provider()
    the_flag_provider_forgot_every_change()
    _long_term_memory_was_forgotten()


def _long_term_memory_was_forgotten() -> None:
    """Drops the collection this stack remembers incidents in.

    Dropped rather than emptied, as the suite that replays these does it: an
    absent collection reads as an empty corpus everywhere above the store, and
    the first write makes it again.
    """
    store = QdrantClient(url=get_settings().qdrant_url)

    try:
        store.delete_collection(get_settings().incident_memory_collection)
    finally:
        store.close()


class _Staged(NamedTuple):
    """What the shop said when a scenario was staged: when, and which rule it trips.

    Both are the shop's to say. The instant is the one its window hangs off, and
    the rule is the series rule a page about the scenario names - the shop's
    default error-rate rule for a scenario whose own page is a finding.
    """
    seeded_at: str | None
    rule_uid: str | None


def _stage(scenario_id: str) -> _Staged:
    """Puts the shop into the state this recording is of, and says when and
    which rule it trips.

    The instant comes back from the service rather than being read off a clock
    here: the shop decides what its window hangs off, and a moment taken on
    this side would differ from it by however long the call took.
    """
    staged = httpx2.post(
        f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
        json={"scenario_id": scenario_id},
        timeout=A_SEED_SECONDS,
    )
    staged.raise_for_status()
    said = staged.json()

    return _Staged(seeded_at=said.get("seeded_at"), rule_uid=said.get("rule_uid"))


def _write_the_anchor(stored: str, seeded_at: str | None) -> None:
    """Records the instant the world these answers were given about was seeded.

    Without it a replay has no left-hand side. A recorded answer can name the
    window it asked about, and those bounds are absolute instants frozen here;
    the scenario they were captured against is not frozen, so a set replayed an
    hour later asks about an hour that no longer holds the incident. Whoever
    seeds the double lines the two up by the gap between the two seedings, and
    this is the half only a recording run can know.

    Beside the answers and not inside one: a recording is the raw body the API
    returned, and a field this repo added to it would be the one thing in there
    Anthropic never said.

    A recording of no scenario at all writes nothing, and the absence is the
    honest answer - there was no seeding for anything to be dated against, so
    there is nothing for a later run to line up with.
    """
    anchor = the_anchor_file_for(stored)

    if seeded_at is None:
        anchor.unlink(missing_ok=True)
        return

    anchor.write_text(f"{seeded_at}\n", encoding="utf-8", newline="\n")


def _an_incident_was_opened_by(service: str,
                               alert_name: str | None,
                               rule_uid: str | None,
                               scenario: str | None) -> str:
    """Fires the alert and returns the incident the webhook wrote down.

    Two ways in, and which one is used is the recording's to say. A named alert
    is assembled here and posted to Argus, as Grafana would; `None` asks the
    shop's own monitoring to page instead, because that alert carries a finding
    only the shop can produce - and the finding is what the walk turns on. Both
    answer with the incident the webhook wrote down.

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
    if alert_name is None:
        # The shop holds this open until Argus's webhook answers, which it does
        # as soon as the incident is written down - so this returns with an id
        # and the walk carries on behind it, exactly as the posted payload does.
        raised = httpx2.post(
            f"{TARGET_SERVICE_BASE_URL}/monitoring/alert",
            timeout=A_WHOLE_INVESTIGATION_SECONDS,
        )
        raised.raise_for_status()

        return str(raised.json().get("incident_id") or "unknown")

    response = httpx2.post(
        f"{ARGUS_WEB_BASE_URL}/webhooks/alerts",
        json=_an_alert_for(service, alert_name, rule_uid, scenario),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return str(response.json().get("incident_id", "unknown"))


def _the_walk_came_to_a_stop(incident_id: str, may_take_seconds: float) -> None:
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
    deadline = time.monotonic() + may_take_seconds

    while True:
        status = _the_status_of(incident_id)

        if status is not None and status.is_terminal() and _was_written_up(incident_id):
            return

        # A walk that died writes no postmortem, so waiting out the deadline for
        # one only delays the same answer - by half an hour a walk, which is
        # what a replay of answers a newer check refuses costs per scenario.
        failed_because = _why_the_walk_failed(incident_id)
        if failed_because is not None:
            raise RuntimeError(
                f"incident [{incident_id}] stopped without a postmortem: the walk "
                f"failed with {failed_because} - nothing was recorded from it"
            )

        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"incident [{incident_id}] was [{status}] with "
                f"[{'a' if _was_written_up(incident_id) else 'no'}] postmortem after "
                f"[{may_take_seconds:.0f}s] - nothing was recorded from it"
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


def _why_the_walk_failed(incident_id: str) -> str | None:
    """What the worker failed the incident's run with, or `None` while it has
    not - asked of the queue, which is where the worker says so."""
    with psycopg.connect(DATABASE_URL) as connection:
        run = runs.get_run_for_incident(connection, incident_id)

    if run is None or run.state is not RunState.FAILED:
        return None

    return run.failure_reason or "no reason given"


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


# Where a postmortem-only run records the write-up before it is put in place.
# Not digits after the name, so nothing reads it as one of the set's answers.
_THE_WRITE_UP_AFRESH: Final = "-write-up-afresh"


def _calls_the_write_up(answer: Path) -> bool:
    return any(block.get("type") == TOOL_USE_TYPE and block.get("name") == SUBMIT_TOOL_NAME
               for block in load(answer.stem).get("content", []))


def _where_the_write_up_begins(stored: str) -> int:
    """The position of the set's first write-up, refusing a set that answers
    anything else after it.

    The double serves in order and never reads the request, so a postmortem
    recorded afresh is only replayable where nothing comes after it: an answer
    of the walk's own left behind the write-up would be handed to whichever
    call asked next. Checked before anything is spent.
    """
    answers = _the_set_named(stored)
    begins = next((position for position, answer in enumerate(answers)
                   if _calls_the_write_up(answer)), None)

    if begins is None:
        raise RuntimeError(f"[{stored}] holds no write-up to record afresh")

    after = [answer.stem for answer in answers[begins:] if not _calls_the_write_up(answer)
             and any(block.get("type") == TOOL_USE_TYPE
                     for block in load(answer.stem).get("content", []))]
    if after:
        raise RuntimeError(f"[{stored}] answers the walk again after its write-up: {after}")

    return begins


def _the_walk_is_taken_from(source: str, stored: str) -> None:
    """Makes `stored` the walk `source` recorded, less Code-Fix's answers, with
    `source`'s write-up and anchor beside it.

    The write-up is copied to be replaced: a postmortem-only run records one in
    place of the set's own, and refuses a set holding none. The anchor because
    a postmortem-only run writes none, and without it the replayed walk's times
    are the day `source` was captured.

    Copied afresh every time rather than once, so a set taken from a walk that
    was since re-recorded is that walk, not the one before it.
    """
    answers = _the_set_named(source)
    if not answers:
        raise RuntimeError(f"[{source}] holds no walk to take [{stored}] from")

    called = [_the_tools_called_in(answer) for answer in answers]
    the_investigations_end = max(position for position, tools in enumerate(called)
                                 if ANSWER_TOOL in tools)
    the_write_up = next(position for position, tools in enumerate(called)
                        if SUBMIT_TOOL_NAME in tools)
    taken = answers[:the_investigations_end + 1] + answers[the_write_up:]

    for old in _the_set_named(stored):
        old.unlink()

    for position, answer in enumerate(taken):
        named = stored if position == 0 else f"{stored}-{position + 1}"
        shutil.copyfile(answer, RECORDINGS_DIR / f"{named}.json")

    anchor = the_anchor_file_for(source)
    if anchor.exists():
        shutil.copyfile(anchor, the_anchor_file_for(stored))
    else:
        the_anchor_file_for(stored).unlink(missing_ok=True)

    print(f"taken from [{source}]: {', '.join(path.stem for path in _the_set_named(stored))}")


def _the_tools_called_in(answer: Path) -> list[str]:
    return [block["name"] for block in load(answer.stem).get("content", [])
            if block.get("type") == TOOL_USE_TYPE]


def _put_the_write_up_in_place(stored: str, begins: int) -> list[str]:
    """Swaps the set's old write-up for the one just recorded, and says what
    the set now holds.

    The old write-up's files go first, every one of them: a model that answers
    in one attempt where the last took two would otherwise leave the second
    behind, served to nothing until it is served to something.
    """
    afresh = _the_set_named(f"{stored}{_THE_WRITE_UP_AFRESH}")

    if not afresh:
        raise RuntimeError(f"[{stored}] recorded no write-up - the old one is left in place")

    for old in _the_set_named(stored)[begins:]:
        old.unlink()

    for offset, answer in enumerate(afresh):
        position = begins + offset
        named = stored if position == 0 else f"{stored}-{position + 1}"
        answer.rename(RECORDINGS_DIR / f"{named}.json")

    return [answer.stem for answer in _the_set_named(stored)]


def _the_write_up_was_asked_for(incident_id: str, may_take_seconds: float) -> None:
    """Waits until the walk's write-up is at the double, held.

    Bounded by the walk's own bound rather than by an investigation's: the
    write-up is the walk's last call, and a walk judged by the sustained rule
    reaches it well after an investigation's bound has passed. Sooner where the
    walk failed first, since a walk that failed asks for no write-up at all.
    """
    deadline = time.monotonic() + may_take_seconds

    with httpx2.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
        while True:
            state = control.get("/double-control/state")
            state.raise_for_status()

            if state.json()["held"]:
                return

            failed_because = _why_the_walk_failed(incident_id)
            if failed_because is not None:
                raise RuntimeError(
                    f"incident [{incident_id}] stopped before its write-up: the walk "
                    f"failed with {failed_because}"
                )

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"incident [{incident_id}] asked for no write-up within "
                    f"[{may_take_seconds:.0f}s]"
                )

            time.sleep(A_POLL_SECONDS)


def _the_held_call_is_the_write_up(incident_id: str, ends_as: IncidentStatus) -> None:
    """Refuses the held call, at no cost, unless the incident has already ended
    as the case expects.

    The hold catches whichever call first finds the queue empty, and that is
    the write-up only for a walk that went where its replayed answers lead. One
    that went further - a resolution that never took, so the walk carried on
    into Code-Fix - had Code-Fix's first call held, released and paid for as
    though it were the write-up. The write-up is asked for only once the walk
    has ended, so an incident not yet at its ending is holding some other call.
    """
    status = _the_status_of(incident_id)

    if status == ends_as:
        return

    with httpx2.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
        control.post("/double-control/reset").raise_for_status()

    raise RuntimeError(
        f"incident [{incident_id}] held a call while [{status}], not [{ends_as}] - "
        f"so not its write-up; refused before it reached the real model"
    )


def _the_write_up_is_recorded_afresh(stored: str) -> None:
    """Names where the held write-up is recorded, then lets it go to the real
    model.

    Held until now so that the name is in place before the call goes out. The
    walk it writes up was replayed into this run's world, and its times are
    this run's only where the shop hangs them off the seeding: two runs act,
    judge and recover in different minutes, as two real ones would. So no time
    the replayed findings quote is checked against this run - the write-up
    states every time by name, and code writes it in from this run's record.
    """
    with httpx2.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
        control.post(
            "/double-control/record", json={"name": f"{stored}{_THE_WRITE_UP_AFRESH}"}
        ).raise_for_status()
        control.post("/double-control/release").raise_for_status()


def _capture(recording: _Recording,
             service: str,
             replaying: bool,
             postmortem_only: bool = False) -> None:
    """Drives the one incident this recording is of, and says what came of it.

    The name asked for on the command line is the *case*; the name on disk is
    that case as this run's `CODE_SEARCH` stores it. Converted here rather than
    in the mapping above, because a run records the world it is in - and the
    same case captured under two modes is two recordings of two different walks.

    `postmortem_only` records the write-up and nothing else: the rest of the
    walk replays its stored answers, rebased as the e2e suite rebases them, and
    the one call left unanswered goes to the real model. A walk's answers are
    unchanged by a change to the postmortem alone, so paying for all of them
    again buys nothing but different answers to questions already settled.
    """
    stored = stored_as(recording.name)
    print(f"=== {stored} ===")

    # First, before the double is armed: arming resets it and enters record
    # mode, which would put a walk still live from earlier on the paid line,
    # under this case's name.
    _no_walk_is_live()

    if postmortem_only and recording.walk_from:
        _the_walk_is_taken_from(stored_as(recording.walk_from), stored)

    begins = _where_the_write_up_begins(stored) if postmortem_only else 0

    if not replaying and not postmortem_only:
        _arm_the_double(stored)

    # Read before anything is written, and from the clock the files are stamped
    # by: what makes an answer stale is that this run did not write it, and
    # every comparison after this point is against this moment.
    started_at = time.time()

    _a_world_this_recording_can_be_captured_in()

    # A walk that replays is answered about the world it was recorded in, so
    # the shop is told that world's anchor before it seeds. Not on a fresh
    # capture: its world is the one this run writes the anchor of.
    if replaying or postmortem_only:
        the_recorded_anchor_was_staged(recording.name)

    staged = (
        _stage(recording.scenario) if recording.scenario
        else _Staged(seeded_at=None, rule_uid=None)
    )

    if not replaying and not postmortem_only:
        _write_the_anchor(stored, staged.seeded_at)

    # After staging, because the rebasing reads when this world was seeded;
    # and record mode after the seeds, because a seed is served ahead of it.
    # A replay is seeded here too, and by the suite's own seeder: answers served
    # as they were stored name instants from the day they were recorded, and
    # the walk replaying them is in a world staged today.
    if replaying:
        the_model_answers_from(recording.name)()
    elif postmortem_only:
        the_model_answers_from(recording.name, less_postmortem=True)()

    # After the seeding, never before it: seeding resets the double first, and a
    # reset ends whatever hold a case had already armed - which left a walk
    # answered straight through while its case waited for a held first turn.
    if recording.and_then:
        recording.and_then()

    incident_id = _an_incident_was_opened_by(
        service, recording.alert_name, staged.rule_uid, recording.scenario
    )

    print(f"incident [{incident_id}] drove scenario [{recording.scenario or 'none'}]")

    asked_for_the_write_up = False

    # The account is printed whatever happened to the walk. A walk that never
    # finished is the one whose timeline is worth reading - it is the only
    # record of how far it got and what it was doing when it stopped - and
    # printing it only on the way out meant the one failure nobody could
    # diagnose was the only one anybody needed to.
    try:
        if recording.once_opened:
            recording.once_opened(incident_id)

        if postmortem_only:
            # Held rather than recorded straight away: the write-up is the one
            # call paid for, and where it is recorded is named before it goes
            # out. Armed only once the case is done with the walk, because a
            # release lets every hold go - and the lead written mid-investigation
            # releases the first turn, which took this hold with it and left the
            # write-up asking an empty queue. Arming it this late relies on the
            # walk still having replayed answers to spend, which it spends over
            # minutes; a walk that ran dry first had its write-up refused, failed
            # for it, and is reported as that by the wait below. A case that ends
            # the walk itself does it after this, in `resolved_by`, since the
            # write-up is then the walk's very next call.
            with httpx2.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
                control.post("/double-control/hold-when-dry").raise_for_status()

        if recording.resolved_by:
            recording.resolved_by(incident_id)

        if postmortem_only:
            _the_write_up_was_asked_for(incident_id, recording.may_take_seconds)
            _the_held_call_is_the_write_up(incident_id, recording.ends_as)
            _the_write_up_is_recorded_afresh(stored)
            asked_for_the_write_up = True

        _the_walk_came_to_a_stop(incident_id, recording.may_take_seconds)
    finally:
        if postmortem_only and asked_for_the_write_up:
            print(f"recorded: {', '.join(_put_the_write_up_in_place(stored, begins))}")
        elif postmortem_only:
            print("recorded: nothing - the write-up was never asked for, and the old "
                  "one is left in place")
        elif not replaying:
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
    # everything this script says while the httpx2 logs, which go through
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
    parser.add_argument(
        "--postmortem-only",
        action="store_true",
        help="replay each walk's stored answers and record only its write-up afresh",
    )
    parser.add_argument(
        "--hold",
        action="store_true",
        help="keep the stack up once every capture is done, until Enter - so what "
             "the walks left on the record can be read, or recorded against",
    )
    arguments = parser.parse_args()

    _the_two_declarations_of_a_fix_agree()

    asked_for = _what_was_asked_for(arguments.names)
    failed: list[str] = []
    left_quiet = True

    # One failure does not end the run. The stack is up and paid for by the
    # time anything is captured, and a scenario that fails to record is a
    # reason to look at that scenario - not a reason to throw away the four
    # recordings that would have worked. A walk that will not stop does end
    # it: nothing captured after it could be trusted.
    for position, recording in enumerate(asked_for):
        try:
            _capture(recording, arguments.service, arguments.replay,
                     postmortem_only=arguments.postmortem_only)
        except _AWalkIsStillLive as error:
            print(f"STOPPED at {recording.name}: {error}")
            failed.extend(left.name for left in asked_for[position:])
            left_quiet = False
            break
        except Exception as error:
            print(f"FAILED {recording.name}: {error!r}")
            failed.append(recording.name)

    # The stack left quiet, for a `--hold` to be read against and for nothing
    # to be mid-call when it comes down. Not asked again after a walk already
    # would not stop: that is one more whole bound spent learning the same.
    if left_quiet:
        try:
            _no_walk_is_live()
        except _AWalkIsStillLive as error:
            print(f"NOT QUIET at the end: {error}")
            left_quiet = False

    print(f"captured {len(asked_for) - len(failed)} of {len(asked_for)}")
    if failed:
        print(f"failed: {', '.join(failed)}")

    # The stack comes down the moment this returns, and every incident with it.
    if arguments.hold:
        print("holding the stack: press Enter, or interrupt, to bring it down")
        wait_until_told_to_stop()

    return 1 if failed or not left_quiet else 0


if __name__ == "__main__":
    sys.exit(main())
