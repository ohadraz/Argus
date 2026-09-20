"""What Argus knows how to do about one kind of cause (spec §7.3, §13).

Proposing is policy, and policy has no lifetime: which action answers which
cause is a fact about Argus, not about the process it is running in. So a
strategy is built here, at import, and carries nothing that has to be reached
over a network. Performing an action is the other half and is not here - that
is I/O, it already has its seam in `ActionTaker` and in the Orchestrator's
`Collaborators`, and a registry built to dispatch between one member would be
the second action type's machinery bought before the second action type.

One question is asked of a strategy: `propose_action` holds a cause and asks
what to do about it. Whether Argus may then take that action unasked is a
different question with a different answer, and it lives in `admitting` - a
strategy says what would help, and has no business also saying what is
permitted.

A second question is asked of the registry rather than of any strategy, and
`a_mitigation_answers` is it: whether this kind of failure has an answer here
at all. The gate needs it to tell two silences apart - a mitigation that could
not identify what to act on, and a mode nothing in the set addresses - and
asking it here is what keeps the gate from holding its own copy of what Argus
can do.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from argus_core.models import (
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_CONFIGURATION,
    Action,
    ActionType,
    FailureMode,
    FlagChange,
    FlagUndo,
    Hypothesis,
    RestartService,
    RevertFeatureFlag,
    RollBackConfiguration,
)

__all__ = [
    "DEFAULT_STRATEGIES",
    "MitigationStrategy",
    "RestartServiceStrategy",
    "RollBackConfigurationStrategy",
    "RevertFeatureFlagStrategy",
    "Strategies",
    "a_mitigation_answers"
]


class MitigationStrategy(Protocol):
    """One generic mitigation, and the cause it answers.

    `action_type` is on the strategy rather than only on what it proposes, so
    that a strategy cannot be registered without saying which actions it
    answers for - and so that the kind a cause maps to can be read without
    building the action first.
    """

    action_type: ActionType

    def propose(self,
                hypothesis: Hypothesis,
                flag_changes: Sequence[FlagChange],
                service: str) -> Action | None: ...


class RevertFeatureFlagStrategy:
    """Answering a flag that was toggled by putting it back.

    Which flag comes from the hypothesis, confirmed against what the provider
    recorded as changing - never from Argus's configuration and never from
    which flags are currently on. A configured flag name would hardcode the
    demo's answer into the agent, and current state cannot see half the
    problem: a flag switched off into an incident is off now, exactly like
    every flag that has been off for a year.
    """

    action_type: ActionType = REVERT_FEATURE_FLAG

    def propose(self,
                hypothesis: Hypothesis,
                flag_changes: Sequence[FlagChange],
                service: str) -> Action | None:
        """The flag change to reverse, or `None` where the evidence names none.

        Reading the Investigator's conclusion is not a second investigation.
        This stays a pure function of the hypothesis and the changes handed to
        it: no retrieval, no model, and no judgement of its own about what
        caused the incident. Which way the flag moved still comes from the
        record, never from the hypothesis, so prose that described the toggle
        backwards cannot turn a flag the wrong way.

        The service is not read. A flag is named by the provider's own record
        and is the same flag whichever service was alerting on it. The
        parameter is still spelled as the protocol spells it, for the reason
        the unread `flag_changes` is spelled that way in the strategy below.
        """
        change = _the_change_to_undo(hypothesis.subject, flag_changes)

        if change is None:
            return None

        return RevertFeatureFlag(
            flag=change.flag,
            enabled=not change.enabled,
            undo_descriptor=FlagUndo(
                flag=change.flag,
                was_enabled=change.enabled
            )
        )


class RestartServiceStrategy:
    """Answering a leak by restarting the thing that is leaking.

    The textbook generic mitigation: it reclaims what accumulated without
    knowing what accumulated it, which is exactly why it can be applied before
    the cause is understood - and exactly why it mitigates rather than
    resolves. The fault is still in the code when the new process comes up, and
    the climb starts again.

    The service comes from the alert and from nowhere else. Not from Argus's
    configuration, which would hardcode one deployment's answer into the agent
    - and not from the hypothesis, whose subject is the model's description of
    what is accumulating rather than the name of anything that can be
    addressed. Those descriptions are prose: "kuki heap (memory_used_bytes /
    heap of 2048MiB limit)" is one a model actually wrote, and a restart sent
    to it asks a platform about a resource nobody has. The alert, by contrast,
    names a service because that is what an alert is about.
    """

    action_type: ActionType = RESTART_SERVICE

    def propose(self,
                hypothesis: Hypothesis,
                flag_changes: Sequence[FlagChange],
                service: str) -> Action | None:
        """The service to restart - the one the incident is about.

        Neither the hypothesis nor the recorded flag changes are read. A leak
        is not something a flag did - no toggle causes a heap to grow, and a
        flag that happened to move during the climb is a coincidence this must
        not act on - and what the candidate calls the leak is a description,
        not an address. Both parameters are still spelled as the protocol
        spells them: a strategy that renamed what it does not use would be one
        nobody could call by keyword.

        Always an action, where the older shape could answer `None`. A leak
        the model found no words for is still a leak in a service the alert
        names, and there is nothing left for this to fail to identify.
        """
        return RestartService(service=service)


class RollBackConfigurationStrategy:
    """Answering a configuration that was changed into a broken state by
    putting the previous configuration back.

    The third generic mitigation, and the one that is neither a value nor a
    process. What it restores was already deployed and already reviewed, which
    is what admits it unasked - Argus replays somebody's change rather than
    authoring one, and writing to the configuration repository would be the
    other thing entirely.

    Like a restart and unlike a flag revert, the subject comes from the alert
    and from nowhere else. Not from Argus's configuration, which would
    hardcode one deployment's answer into the agent - and not from the
    hypothesis, whose subject is the model's description of what went wrong
    rather than the name of anything that can be addressed.

    Which revision to return to is named nowhere here, because nothing at this
    layer could name it honestly: a deployment history lives with the platform,
    behind the write tier, and a strategy inventing an entry would be
    inventing a state to ship.
    """

    action_type: ActionType = ROLL_BACK_CONFIGURATION

    def propose(self,
                hypothesis: Hypothesis,
                flag_changes: Sequence[FlagChange],
                service: str) -> Action | None:
        """The deployment to roll back - the one the incident is about.

        Neither the hypothesis nor the recorded flag changes are read. A
        configuration change is not something a flag did, and a flag that
        happened to move while the wrong configuration was deployed is a
        coincidence this must not act on. Both parameters are still spelled as
        the protocol spells them, for the reason the restart strategy's unread
        ones are.

        Always an action. A configuration fault the model found no words for
        is still a fault in a deployment the alert names, and there is nothing
        left for this to fail to identify.
        """
        return RollBackConfiguration(application=service)


Strategies = Mapping[FailureMode, MitigationStrategy]

# Which mitigation answers which cause. A mode absent from this is one Argus
# has nothing to offer for, and `UPSTREAM_DEPENDENCY_FAILURE` is absent
# deliberately rather than pending: every mitigation here acts on Argus's own
# deployment, and another company's outage is reachable by none of them. The
# day something is registered for it, that will be a claim that Argus can shed
# load or fail over - which is a mitigation somebody has to build and defend,
# not a gap to be filled in.
DEFAULT_STRATEGIES: Strategies = {
    FailureMode.FEATURE_FLAG_TOGGLE: RevertFeatureFlagStrategy(),
    FailureMode.RESOURCE_LEAK: RestartServiceStrategy(),
    FailureMode.CONFIG_INDUCED_FAILURE: RollBackConfigurationStrategy()
}


def a_mitigation_answers(failure_mode: FailureMode | None,
                         strategies: Strategies = DEFAULT_STRATEGIES) -> bool:
    """Whether anything Argus knows how to do answers this kind of failure.

    Asked by the gate, which has to tell two silences apart: an incident that
    reached it with no action because nothing answers the mode at all, and one
    that reached it with no action because the mitigation that does answer the
    mode could not identify what to act on. Both end the same way and mean
    different things to whoever picks the incident up.

    Answered here rather than by the gate reading this mapping itself, for the
    reason the mapping is here at all: which cause has an answer is policy, and
    policy kept in two places is policy that comes to differ.

    A candidate that determined no mode is not answered either. There is
    nothing to look up, which is a gap in the investigation rather than a
    statement about what can be done - and the refusal that follows says so.
    """
    return failure_mode is not None and failure_mode in strategies


def _the_change_to_undo(subject: str | None,
                        flag_changes: Sequence[FlagChange]) -> FlagChange | None:
    """The recorded change an action should reverse, or `None` where the
    evidence does not identify one.

    A flag toggled more than once counts once, and it is its *latest* change
    that is undone: the incident is happening now, so the state to put back is
    the one the service is in now, not whatever it was at the far edge of the
    window. `flag_changes` arrives oldest first, so the last mention of a flag
    is the current one.

    A hypothesis that named a flag selects it from among these; a hypothesis
    that named none falls back to the window being unambiguous by itself.
    """
    latest_per_flag: dict[str, FlagChange] = {
        change.flag: change for change in flag_changes
    }

    if subject is not None:
        return latest_per_flag.get(subject)

    if len(latest_per_flag) != 1:
        return None

    return next(iter(latest_per_flag.values()))
