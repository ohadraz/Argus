"""What a deployment supplies a walk with, and when it is allowed to reach out.

`against` is the only thing in the worker that knows a database can be
had, so it is the only place a graph could quietly acquire one. Two properties
of it keep the walk testable without infrastructure, and neither is visible from
inside a node: assembling touches nothing, and every collaborator bound here is
bound *whole*. That nothing on the record has a default a forgetful test could
fall through to is the record's own, and is held where it is declared
(`test_collaborators`).

The second is the one no type checker does for us. A collaborator is bound with
`functools.partial`, and a partial that leaves a required keyword unsupplied is
a perfectly well-typed object that raises `TypeError` the first time a node
calls it - which is in the middle of an incident, after the model has been paid
for. So what is asserted below is not that the field is present but that what is
in it can be called with what its caller actually passes.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from typing import Any
from unittest.mock import create_autospec

import psycopg
import pytest
from apps.worker.assembling import (
    IncidentMemorySettings,
    against,
    the_models_at,
    the_store_for,
)
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
    the_answer_was,
)
from core import Connections, Holding, LLMSettings, Settings, get_settings
from core.models import ModelPolicy
from incident_memory.records import RememberedIncident
from orchestrator.walk.collaborators import Collaborators
from postmortem_writing import judge_policy, postmortem_policy
from read_mcp_client import ReadTier
from write_mcp_client import WriteTier

# What the mitigation node passes when it performs an action: the policy's
# admission of it, the plan its claim carries, and three arguments that carry
# their own defaults. Everything else `take_action` declares has to have been
# bound at assembly, so anything still required beyond this is a collaborator the
# walk was never given.
WHAT_THE_MITIGATION_NODE_SUPPLIES = frozenset({"admitted", "plan"})

# What puts one change back: the descriptor recording it, and nothing else. Which
# changes to undo and in what order belong to whoever holds the records.
WHAT_AN_UNDO_IS_GIVEN = frozenset({"undo_descriptor"})

# What reads where the rule that paged stands: the rule, and nothing else. The
# read tier it is asked of is the binding's.
WHAT_A_RULE_READ_IS_GIVEN = frozenset({"rule"})

# What the investigation node asks the deploy history: which service, and where
# the window ends. The settings and the read tier are the binding's.
WHAT_THE_INVESTIGATION_NODE_ASKS = frozenset({"service", "onset"})

# One window of one service, which nothing here reads.
SOME_SERVICE = "io-shop"
SOME_WINDOW_START = "2026-08-29T20:00:00Z"
SOME_WINDOW_END = "2026-08-29T22:15:00Z"

# What the investigation node hands the Investigator positionally: the alert and
# the incident. Every channel it reads is the binding's.
WHAT_AN_INVESTIGATION_IS_GIVEN = frozenset({"alert", "incident_id"})

# Where the agents' model is reached, and where the judge's is - two addresses,
# so that a binding handing one the other's provider cannot pass as the right
# one. With both left empty the judge's settings equal the agents'.
WHERE_THE_AGENTS_ARE_ANSWERED = "http://agents.invalid"
WHERE_THE_JUDGE_IS_ANSWERED = "http://judge.invalid"


@pytest.mark.unit
def test_assembling_the_collaborators_opens_no_connection() -> None:
    # Everything derived from the connections is a closure over them rather than
    # an open connection - a walk is what opens one, when a node actually runs.
    # A source that refuses to open is both the fixture and the assertion here.
    # No vector store, for the same reason: what a process opened is handed in,
    # so assembling with none is assembling with nothing to reach.
    Scenario() \
        .given(no_connections := _connections_that_must_not_be_opened()) \
        .when(lambda: against(no_connections,
                              _a_read_tier_that_must_not_be_reached(),
                              _a_write_tier_that_must_not_be_reached(),
                              None,
                              Holding(),
                              settings=get_settings())) \
        .then(_every_collaborator_was_supplied())


@pytest.mark.unit
def test_taking_an_action_is_bound_with_every_tool_it_needs() -> None:
    # The failure this exists for is quiet in every way that matters. A new kind
    # of action arrives, the agent grows a keyword-only collaborator for it, the
    # tier and the client and the agent all get their tests - and nobody adds it
    # here. Every gate stays green, because a `functools.partial` missing a
    # required keyword is well-typed until it is called; the walk then dies at
    # the mitigation node, mid-incident.
    Scenario() \
        .given(no_connections := _connections_that_must_not_be_opened()) \
        .when(lambda: against(no_connections,
                              _a_read_tier_that_must_not_be_reached(),
                              _a_write_tier_that_must_not_be_reached(),
                              None,
                              Holding(),
                              settings=get_settings())) \
        .then(all_of(
            _taking_an_action_needs_only(WHAT_THE_MITIGATION_NODE_SUPPLIES),
            _putting_a_change_back_needs_only(WHAT_AN_UNDO_IS_GIVEN),
            _reading_the_rule_needs_only(WHAT_A_RULE_READ_IS_GIVEN)
        ))


@pytest.mark.unit
def test_the_deploy_history_is_bound_with_everything_but_the_question() -> None:
    # Bound whole for the reason taking an action is. The investigation node asks
    # it about a service and an onset and nothing else, and a partial short of
    # anything more is well-typed until the first round reads it - which is in
    # the middle of an incident, after the model has been paid for.
    Scenario() \
        .given(no_connections := _connections_that_must_not_be_opened()) \
        .when(lambda: against(no_connections,
                              _a_read_tier_that_must_not_be_reached(),
                              _a_write_tier_that_must_not_be_reached(),
                              None,
                              Holding(),
                              settings=get_settings())) \
        .then(
            _reading_the_deploy_history_needs_only(WHAT_THE_INVESTIGATION_NODE_ASKS)
        )


@pytest.mark.unit
def test_the_investigation_is_bound_with_every_channel_it_reads() -> None:
    # Bound whole for the reason taking an action is. A channel the Investigator
    # gains and nobody binds here leaves a partial one argument short, well-typed
    # until the first round calls it - after the alert has paged and before
    # anything at all was read.
    Scenario() \
        .given(no_connections := _connections_that_must_not_be_opened()) \
        .when(lambda: against(no_connections,
                              _a_read_tier_that_must_not_be_reached(),
                              _a_write_tier_that_must_not_be_reached(),
                              None,
                              Holding(),
                              settings=get_settings())) \
        .then(
            _investigating_needs_only(WHAT_AN_INVESTIGATION_IS_GIVEN)
        )


@pytest.mark.unit
def test_the_investigators_change_channel_asks_each_tier_for_the_history_it_keeps() -> None:
    # The read tier's deploy history alone has the change channel's shape, so a
    # binding that handed it over by itself would type-check - and the model
    # would never be shown a flag flip, which reads exactly like an incident in
    # which no flag moved. The flags are the write tier's: the provider serves
    # its audit log to admin credentials alone.
    Scenario() \
        .given(
            read := _a_read_tier_answering_nothing_changed(),
            write := _a_write_tier_answering_nothing_changed()
        ) \
        .when(
            lambda: _the_changes_read_through(
                against(_connections_that_must_not_be_opened(), read, write,
                        None, Holding(), settings=get_settings())
            )
        ) \
        .then(all_of(
            _the_tier_was_asked_only(read, "get_change_events"),
            _the_tier_was_asked_only(write, "get_recent_flag_changes")
        ))


@pytest.mark.unit
def test_the_postmortem_is_written_by_a_model_given_its_brief() -> None:
    # The brief rides in the policy the postmortem's client is built with, and
    # nowhere else - so a binding that built the client from a policy of its own
    # would write every postmortem from the incident alone. The write-up would
    # still arrive in the right shape and read well, which is why nothing
    # downstream of here would notice.
    settings = get_settings()

    Scenario() \
        .given(no_connections := _connections_that_must_not_be_opened()) \
        .when(lambda: against(no_connections,
                              _a_read_tier_that_must_not_be_reached(),
                              _a_write_tier_that_must_not_be_reached(),
                              None,
                              Holding(),
                              settings=get_settings())) \
        .then(
            _the_postmortem_is_asked_under(
                postmortem_policy(settings.postmortem_model, settings.postmortem_effort))
        )


@pytest.mark.unit
@pytest.mark.parametrize("writer", ["write_postmortem", "write_synopsis"])
def test_both_writers_are_read_by_the_judge_at_its_own_model_and_address(writer: str) -> None:
    # Its own address, settled where the process starts, so a replay serves
    # the judge from a stand-in of its own; its own model and effort, since a
    # reading against a record is not the writing it judges.
    settings = _settings_reaching_two_addresses()

    Scenario() \
        .given(no_connections := _connections_that_must_not_be_opened()) \
        .when(lambda: against(no_connections,
                              _a_read_tier_that_must_not_be_reached(),
                              _a_write_tier_that_must_not_be_reached(),
                              None,
                              Holding(),
                              settings=settings)) \
        .then(
            _judged_under(writer,
                          judge_policy(settings.judge_model, settings.judge_effort),
                          LLMSettings.for_the_judge(settings))
        )


@pytest.mark.unit
@pytest.mark.parametrize("agent", ["investigate", "propose_fix", "write_postmortem",
                                   "write_synopsis"])
def test_every_agent_is_answered_by_the_provider_the_process_chose(agent: str) -> None:
    # Which provider answers is chosen once, here, and no agent has a default
    # of its own to fall back on - so an agent bound without it would not
    # start, and one bound with another would be answered from an address
    # nobody configured for it.
    settings = _settings_reaching_two_addresses()

    Scenario() \
        .given(no_connections := _connections_that_must_not_be_opened()) \
        .when(lambda: against(no_connections,
                              _a_read_tier_that_must_not_be_reached(),
                              _a_write_tier_that_must_not_be_reached(),
                              None,
                              Holding(),
                              settings=settings)) \
        .then(
            _answered_by(agent, the_models_at(LLMSettings.of(settings)))
        )


@pytest.mark.unit
def test_a_process_that_searches_no_memory_still_files_what_was_tried() -> None:
    # Memory switched off stops the store, never the filing: every walk files
    # its record, so a deployment that switches memory on later has every
    # incident it walked in the meantime. With no store at all, filing still
    # reaches for the database - and a filing that went nowhere would lose
    # exactly the incidents that make switching on worth it.
    Scenario() \
        .given(
            collaborators := against(_connections_that_refuse_with(_TheDatabaseWasReached()),
                                     _a_read_tier_that_must_not_be_reached(),
                                     _a_write_tier_that_must_not_be_reached(),
                                     None,
                                     Holding(),
                                     settings=get_settings())
        ) \
        .when(attempting(lambda: collaborators.remember_incident(_a_record()))) \
        .then(an_error_was_raised(_TheDatabaseWasReached))


@pytest.mark.unit
def test_the_action_a_walk_acts_for_is_held_by_the_process_holding_its_run() -> None:
    # Where the write client reads it as each call is made. Acting for an
    # action anywhere else would mark nothing the walk wrote.
    holding = Holding()
    some_action_id = "6f1c1d2e-0000-4000-8000-0000000000a1"

    Scenario() \
        .given(
            collaborators := against(_connections_that_must_not_be_opened(),
                                     _a_read_tier_that_must_not_be_reached(),
                                     _a_write_tier_that_must_not_be_reached(),
                                     None,
                                     holding,
                                     settings=get_settings())
        ) \
        .when(lambda: _the_action_held_while(collaborators, some_action_id, holding)) \
        .then(the_answer_was(some_action_id))


@pytest.mark.unit
def test_a_process_that_keeps_no_memory_says_so_when_it_starts(
    caplog: pytest.LogCaptureFixture
) -> None:
    # A real configuration rather than a failure, and the one setting that makes
    # two otherwise identical runs walk differently - so the log of a run says
    # which of the two it was.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            settings_keeping_no_memory := IncidentMemorySettings.of(
                get_settings().model_copy(update={"incident_memory_enabled": False})
            )
        ) \
        .when(lambda: _what_is_held_inside(the_store_for(settings_keeping_no_memory))) \
        .then(
            one_record_was_logged(caplog, "apps.worker.assembling", logging.INFO,
                                  "incident memory disabled")
        )


def _settings_reaching_two_addresses() -> Settings:
    """The process's settings, with the agents' model and the judge's at two
    different addresses."""
    return get_settings().model_copy(update={
        "anthropic_base_url": WHERE_THE_AGENTS_ARE_ANSWERED,
        "judge_anthropic_base_url": WHERE_THE_JUDGE_IS_ANSWERED
    })


def _the_action_held_while(collaborators: Collaborators,
                           action_id: str,
                           holding: Holding) -> str | None:
    """Which action the process holds while the walk acts for `action_id`."""
    with collaborators.acting_for(action_id):
        return holding.current_action()


def _what_is_held_inside(held: AbstractContextManager[Any]) -> Any:
    with held as inside:
        return inside


def _a_read_tier_that_must_not_be_reached() -> ReadTier:
    """The read tier, every question to which fails.

    The parallel of the connections above, and it holds for the same reason:
    assembling binds the tier's reads and asks none of them, so anything that
    asked one would fail here rather than quietly be answered.
    """
    tier: ReadTier = _a_tier_refusing_every_question(ReadTier)

    return tier


def _a_write_tier_that_must_not_be_reached() -> WriteTier:
    """The write tier, every question to which fails, for the read tier's
    reason."""
    tier: WriteTier = _a_tier_refusing_every_question(WriteTier)

    return tier


def _a_tier_refusing_every_question(tier: type[object]) -> Any:
    stood_in = create_autospec(tier, instance=True)

    for name in dir(tier):
        if not name.startswith("_") and callable(getattr(tier, name)):
            getattr(stood_in, name).side_effect = AssertionError(
                f"Assembling must not ask the tier [{name}].")

    return stood_in


def _a_read_tier_answering_nothing_changed() -> Any:
    """The read tier, whose deploy history is empty, recording what it is asked."""
    read = create_autospec(ReadTier, instance=True)
    read.get_change_events.return_value = []

    return read


def _a_write_tier_answering_nothing_changed() -> Any:
    """The write tier, whose flag history is empty, recording what it is asked."""
    write = create_autospec(WriteTier, instance=True)
    write.get_recent_flag_changes.return_value = []

    return write


def _the_changes_read_through(collaborators: Collaborators) -> None:
    """The Investigator's change channel, as assembled, asked about one window."""
    fetch_change_events = getattr(collaborators.investigate, "keywords", {})["fetch_change_events"]
    fetch_change_events(SOME_SERVICE, SOME_WINDOW_START, SOME_WINDOW_END)


def _the_tier_was_asked_only(tier: Any, history: str) -> Assertion[None]:
    """That `history` was the one question the tier was asked, and asked once."""
    def assertion(dont_care_read: None) -> bool:
        asked = [name for name, dont_care_args, dont_care_keywords in tier.method_calls]

        if asked != [history]:
            raise AssertionError(
                f"Expected the tier to be asked for [{history}] alone, got {asked}.")

        return True

    return assertion


def _connections_that_must_not_be_opened() -> Connections:
    @contextmanager
    def no_connections() -> Generator[psycopg.Connection]:
        raise AssertionError("Assembling must not open a connection.")
        yield  # unreachable, and what makes this a generator

    return no_connections


class _TheDatabaseWasReached(Exception):
    """Raised by a source of connections the moment one is asked for - so a
    collaborator that reached the database says so, and one that did nothing
    says nothing."""


def _connections_that_refuse_with(refusal: Exception) -> Connections:
    @contextmanager
    def refusing() -> Generator[psycopg.Connection]:
        raise refusal
        yield  # unreachable, and what makes this a generator

    return refusing


def _a_record() -> RememberedIncident:
    """What one incident tried, as a finished walk composes it."""
    dont_care_incident = "0f5c4d6e-3a1b-4c2d-8e9f-1a2b3c4d5e6f"
    dont_care_description = "checkout began failing after a flag was switched on"

    return RememberedIncident(
        incident_id=dont_care_incident,
        described_as=dont_care_description,
        service="io-shop",
        alert_name="HighErrorRate",
        tried=[]
    )


def _every_collaborator_was_supplied() -> Assertion[Collaborators]:
    """That the record came back whole.

    A frozen dataclass with no defaults cannot be built short, so this is really
    an assertion that `against` returned at all - which, given the source it was
    handed, is the assertion that it reached for nothing.
    """
    def assertion(collaborators: Collaborators) -> bool:
        missing = [field.name for field in dataclasses.fields(collaborators)
                   if getattr(collaborators, field.name) is None]

        if missing:
            raise AssertionError(f"Assembled without {sorted(missing)}")

        return True

    return assertion


def _taking_an_action_needs_only(supplied: frozenset[str]) -> Assertion[Collaborators]:
    def assertion(collaborators: Collaborators) -> bool:
        _nothing_beyond(supplied, _still_required_of(collaborators.take), "take an action")

        return True

    return assertion


def _putting_a_change_back_needs_only(supplied: frozenset[str]) -> Assertion[Collaborators]:
    """The undo bound *inside* the action, which the check above cannot see.

    Supplying `undo` satisfies `take_action`'s own signature however short the
    undo itself was bound, so the two are separate questions - and the undo's is
    asked on the path a refuted mitigation takes, which is the path nobody
    watches.
    """
    def assertion(collaborators: Collaborators) -> bool:
        undo = getattr(collaborators.take, "keywords", {}).get("undo")

        if undo is None:
            raise AssertionError(
                "Taking an action was bound without an undo, so a refuted "
                "mitigation has nothing to put itself back with."
            )

        _nothing_beyond(supplied, _still_required_of(undo), "put a change back")

        return True

    return assertion


def _reading_the_rule_needs_only(supplied: frozenset[str]) -> Assertion[Collaborators]:
    """The rule reader, which `take_action` defaults to none.

    So the check on the action cannot see it missing: the action is callable
    without it, and an incident paged by a series alert is then judged by the
    levels rather than by the rule that paged - a wrong verdict, not a
    `TypeError`, and so the quieter of the two.
    """
    def assertion(collaborators: Collaborators) -> bool:
        read_rule = getattr(collaborators.take, "keywords", {}).get("read_rule")

        if read_rule is None:
            raise AssertionError(
                "Taking an action was bound without a way to read the alert "
                "rule, so a mitigation on a series alert is judged by the "
                "levels rather than by the rule that paged."
            )

        _nothing_beyond(supplied, _still_required_of(read_rule), "read the rule that paged")

        return True

    return assertion


def _reading_the_deploy_history_needs_only(
    supplied: frozenset[str]
) -> Assertion[Collaborators]:
    def assertion(collaborators: Collaborators) -> bool:
        _nothing_beyond(
            supplied,
            _still_required_of(collaborators.fetch_deployments),
            "read what was deployed"
        )

        return True

    return assertion


def _investigating_needs_only(supplied: frozenset[str]) -> Assertion[Collaborators]:
    def assertion(collaborators: Collaborators) -> bool:
        _nothing_beyond(
            supplied,
            _still_required_of(collaborators.investigate),
            "investigate"
        )

        return True

    return assertion


def _the_postmortem_is_asked_under(expected: ModelPolicy) -> Assertion[Collaborators]:
    """The policy the postmortem's model is built with, read off the binding.

    Off the binding because that is the only place it can be seen: the client
    is built per incident, inside the walk, and a model asked without its brief
    answers in the same shape as one asked with it.
    """
    def assertion(collaborators: Collaborators) -> bool:
        client_for = getattr(collaborators.write_postmortem, "keywords", {}).get("client_for")
        policy = getattr(client_for, "keywords", {}).get("policy")

        if policy != expected:
            raise AssertionError(
                f"Expected the postmortem to be written by a model asked under "
                f"[{expected}], got [{policy}].")

        return True

    return assertion


def _judged_under(writer: str, policy: ModelPolicy,
                  settings: LLMSettings) -> Assertion[Collaborators]:
    """The policy and the provider the judge of `writer` is built with, read
    off the binding - where alone they can be seen, as the postmortem's own
    model's are."""
    def assertion(collaborators: Collaborators) -> bool:
        judge_for = getattr(getattr(collaborators, writer), "keywords", {}).get("judge_for")
        bound = getattr(judge_for, "keywords", {})
        reached = next(iter(getattr(judge_for, "args", ())), None)

        if bound.get("policy") != policy or reached != the_models_at(settings):
            # By address alone: the settings carry the key.
            raise AssertionError(
                f"Expected [{writer}] read by a judge asked under [{policy}] at "
                f"[{settings.anthropic_base_url}], got [{bound.get('policy')}] from "
                f"[{_the_address_of(reached)}].")

        return True

    return assertion


def _answered_by(agent: str, provider: object) -> Assertion[Collaborators]:
    """The provider `agent`'s model is built over, read off the binding.

    The two agents with a loop are handed a factory of conversations, whose
    client comes from a factory bound to the provider; the two writers are
    handed the client factory itself.
    """
    def assertion(collaborators: Collaborators) -> bool:
        bound = getattr(getattr(collaborators, agent), "keywords", {})
        conversations = bound.get("conversations")
        client_for = (getattr(conversations, "keywords", {}).get("client_for")
                      if conversations is not None else bound.get("client_for"))
        reached = next(iter(getattr(client_for, "args", ())), None)

        if reached != provider:
            # By address alone: the settings carry the key.
            raise AssertionError(
                f"Expected [{agent}] answered by the provider at "
                f"[{_the_address_of(provider)}], got one at [{_the_address_of(reached)}].")

        return True

    return assertion


def _the_address_of(provider: object) -> object:
    """Where a provider reaches its model, and nothing else it was built with."""
    return getattr(getattr(provider, "settings", None), "anthropic_base_url", None)


def _still_required_of(call: Callable[..., Any]) -> set[str]:
    """Every parameter the call has left, after whatever was bound into it.

    `inspect.signature` resolves a partial's bound keywords into defaults, so
    what comes back here is exactly what a caller would still have to pass -
    which is the question being asked.
    """
    return {
        name for name, parameter in inspect.signature(call).parameters.items()
        if parameter.default is inspect.Parameter.empty
        and parameter.kind not in (
            inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD
        )
    }


def _nothing_beyond(supplied: frozenset[str], required: set[str], what: str) -> None:
    unbound = required - supplied

    if unbound:
        raise AssertionError(
            f"Assembling left {sorted(unbound)} unbound, so the walk would "
            f"raise TypeError the first time it tried to {what} - and every "
            f"gate would pass until it did."
        )
