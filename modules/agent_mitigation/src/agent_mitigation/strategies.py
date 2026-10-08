"""What Argus knows how to do about one kind of cause (spec §7.3, §13).

Proposing is policy, and policy has no lifetime: which action answers which
cause is a fact about Argus, not about the process it is running in. So a
strategy is built here, at import, and carries nothing that has to be reached
over a network. Performing an action is the other half and is not here - that
is I/O, it already has its seam in the Orchestrator's `Collaborators`, and a
registry built to dispatch between one member would be the second action type's
machinery bought before the second action type.

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
    DISCARD_CACHE_ENTRIES,
    PIN_AUTOSCALER,
    PIN_TO_ACCELERATOR,
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    SCALE_OUT,
    Action,
    ActionType,
    Circumstances,
    DiscardCacheEntries,
    FailureMode,
    FlagChange,
    FlagUndo,
    Hypothesis,
    PinAutoscaler,
    PinToAccelerator,
    RestartService,
    RevertFeatureFlag,
    RollBackDeployment,
    ScaleOut,
)

from agent_mitigation.accelerators import the_accelerator_to_pin_to

__all__ = [
    "DEFAULT_STRATEGIES",
    "DiscardCacheEntriesStrategy",
    "MitigationStrategy",
    "PinAutoscalerStrategy",
    "PinToAcceleratorStrategy",
    "RestartDependencyStrategy",
    "RestartServiceStrategy",
    "RollBackDeploymentStrategy",
    "RevertFeatureFlagStrategy",
    "ScaleOutStrategy",
    "Strategies",
    "UndoTheRecordedChangeStrategy",
    "a_mitigation_answers"
]


class MitigationStrategy(Protocol):
    """One generic mitigation, and the cause it answers.

    `action_types` is on the strategy rather than only on what it proposes, so
    that a strategy cannot be registered without saying which actions it
    answers for - and so that the kinds a cause maps to can be read without
    building the action first. A set rather than one kind, because one mode
    names the damage rather than the change, and its strategy answers with
    whichever undo the record calls for.
    """

    action_types: frozenset[ActionType]

    # Both positional. A protocol that fixes a parameter's *name* obliges every
    # implementation to repeat it, which is a real constraint on a stand-in whose
    # whole point is that it ignores what it is handed - `dont_care_hypothesis`
    # is the right name there and an error against a protocol spelling it
    # `hypothesis`.
    #
    # Everything but the candidate arrives as one value. Most strategies read
    # one or two parts of it, and a new kind of evidence is a field there rather
    # than a parameter every strategy has to spell whether or not it reads it.
    def propose(self,
                hypothesis: Hypothesis,
                circumstances: Circumstances,
                /) -> Action | None: ...


class RevertFeatureFlagStrategy:
    """Answering a flag that was toggled by putting it back.

    Which flag comes from the hypothesis, confirmed against what the provider
    recorded as changing - never from Argus's configuration and never from
    which flags are currently on. A configured flag name would hardcode the
    demo's answer into the agent, and current state cannot see half the
    problem: a flag switched off into an incident is off now, exactly like
    every flag that has been off for a year.
    """

    action_types: frozenset[ActionType] = frozenset({REVERT_FEATURE_FLAG})

    def propose(self,
                hypothesis: Hypothesis,
                circumstances: Circumstances) -> Action | None:
        """The flag change to reverse, or `None` where the evidence names none.

        Reading the Investigator's conclusion is not a second investigation.
        This stays a pure function of the hypothesis and the changes handed to
        it: no retrieval, no model, and no judgement of its own about what
        caused the incident. Which way the flag moved still comes from the
        record, never from the hypothesis, so prose that described the toggle
        backwards cannot turn a flag the wrong way.

        The service is not read. A flag is named by the provider's own record
        and is the same flag whichever service was alerting on it.
        """
        change = _the_change_to_undo(hypothesis.subject, circumstances.flag_changes)

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

    action_types: frozenset[ActionType] = frozenset({RESTART_SERVICE})

    def propose(self,
                hypothesis: Hypothesis,
                circumstances: Circumstances) -> Action | None:
        """The service to restart - the one the incident is about.

        Neither the hypothesis nor the recorded flag changes are read. A leak
        is not something a flag did - no toggle causes a heap to grow, and a
        flag that happened to move during the climb is a coincidence this must
        not act on - and what the candidate calls the leak is a description,
        not an address.

        Always an action, where the older shape could answer `None`. A leak
        the model found no words for is still a leak in a service the alert
        names, and there is nothing left for this to fail to identify.
        """
        return RestartService(service=circumstances.service)


class RollBackDeploymentStrategy:
    """Answering a change that was deployed into a broken state by putting the
    deployment back on the revision before it.

    The third generic mitigation, and the one that is neither a value nor a
    process. What it restores was already deployed and already reviewed, which
    is what admits it unasked - Argus replays somebody's change rather than
    authoring one, and writing to the repository would be the other thing
    entirely.

    Two modes are answered here, and that is not a compromise: a revision
    carries the code and the configuration it shipped with, so the platform's
    rollback is one operation over both. A configuration changed into a broken
    state and new code that broke it are different accounts of an incident and
    different fixes afterwards - a values file, or the service's source - and
    the same thing to do about it now.

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

    action_types: frozenset[ActionType] = frozenset({ROLL_BACK_DEPLOYMENT})

    def propose(self,
                hypothesis: Hypothesis,
                circumstances: Circumstances) -> Action | None:
        """The deployment to roll back - the one the incident is about.

        Neither the hypothesis nor the recorded flag changes are read. What was
        deployed is not something a flag did, and a flag that happened to move
        while the broken revision was running is a coincidence this must not
        act on.

        Always an action. A fault in what was deployed that the model found no
        words for is still a fault in a deployment the alert names, and there is
        nothing left for this to fail to identify.
        """
        return RollBackDeployment(application=circumstances.service)


class RestartDependencyStrategy:
    """Answering a neighbour's fault by restarting the neighbour.

    The same call the leak is answered with, addressed somewhere else - and that
    is the whole of what is new here. `RestartService` already carries the
    service it acts on; what changes is where that name comes from.

    It comes from the hypothesis, and this is the one strategy where that is
    right. The three above refuse to read the hypothesis for a subject, and the
    refusal is sound: what a model writes in `subject` is its description of what
    went wrong, and a platform call sent to "kuki heap (memory_used_bytes / heap
    of 2048MiB limit)" asks about a resource nobody has. `faulting_service` is a
    different field for exactly that reason - an address rather than a
    description, written from the service register, which is the only place the
    name a platform knows a service by can be copied from.

    Not from the alert, which is the point of the whole mode: the alerting
    service is well. A strategy that fell back to it when the hypothesis named
    nothing would restart the one process the incident has established is
    healthy, and would then read that service's unchanged telemetry as evidence
    that restarting does not help - a wrong action and a wrong conclusion drawn
    from it.

    Whether Argus may then touch the service named is a different question with a
    different answer, and it is not asked here: a strategy says what would help,
    and `admitting` says what is permitted. That separation is why this one can
    propose a restart of anything the investigation blamed without also being the
    thing that decides how far Argus's authority reaches.
    """

    action_types: frozenset[ActionType] = frozenset({RESTART_SERVICE})

    def propose(self,
                hypothesis: Hypothesis,
                circumstances: Circumstances) -> Action | None:
        """The dependency to restart, or `None` where the evidence names none.

        `None` rather than a restart of the alerting service, for the reason
        above. It reaches the same place a flag revert's `None` reaches - a
        refusal saying no mitigation could be identified for this cause - which
        is the honest account: the mode has an answer in general and this
        particular diagnosis did not say what to apply it to.

        Nothing in the circumstances is read. The alerting service is the one
        thing this must never fall back to, and a neighbour being slow is not
        something a flag did: one that happened to move meanwhile is a
        coincidence this must not act on.
        """
        if hypothesis.faulting_service is None:
            return None

        return RestartService(service=hypothesis.faulting_service)


class ScaleOutStrategy:
    """Answering load that outgrew its capacity by adding capacity.

    The fourth generic mitigation, and the only one that adds something rather
    than restoring something. That is not a weaker kind of answer: Google SRE's
    own list of generic mitigations names adding capacity beside draining,
    rolling back and restarting, and what admits any of them unasked is
    membership of the declared set rather than what they leave behind.

    It answers the other half of resource exhaustion. A leak is answered by
    reclaiming what accumulated, which a restart does without knowing what
    accumulated it; a deployment meeting load it was never sized for has nothing
    to reclaim, and a restart of it buys a moment before the traffic returns it
    to where it was. Two modes, because what dispatches on a mode is the choice
    of mitigation.

    Like a restart and a rollback, the deployment comes from the alert and from
    nowhere else. Not from Argus's configuration, which would hardcode one
    estate's answer into the agent - and not from the hypothesis, whose subject
    is the model's description of what ran out of room rather than the name of
    anything a platform can be asked about.

    How many replicas to ask for is named nowhere here, for a stronger version
    of the reason a rollback names no revision. A target count is meaningless
    without the count it replaces, that count is live state only the write tier
    can read, and a strategy asserting "six" would be asserting the deployment
    is running three - a fact no evidence in front of it carries, and one that
    stops being true the moment anybody has scaled anything.
    """

    action_types: frozenset[ActionType] = frozenset({SCALE_OUT})

    def propose(self,
                hypothesis: Hypothesis,
                circumstances: Circumstances) -> Action | None:
        """The deployment to make larger - the one the incident is about.

        Neither the hypothesis nor the recorded flag changes are read. Traffic
        arriving is not something a toggle did, and a flag that happened to move
        while the load climbed is a coincidence this must not act on.

        Always an action. A shortfall the model found no words for is still a
        shortfall in a deployment the alert names, and there is nothing left for
        this to fail to identify.
        """
        return ScaleOut(application=circumstances.service)


class PinAutoscalerStrategy:
    """Answering a controller that will not settle by taking away its room to shrink.

    The fifth generic mitigation, and the first that stops something rather than
    adding or restoring something. The set's criterion is unchanged by that, as it
    was unchanged by the one that adds: what admits an action unasked is membership
    of the declared set, never what kind of change it makes.

    It answers the other half of capacity, and the half is not a smaller version of
    the first. A deployment that outgrew its size has too little capacity and is
    answered by more of it; this one has enough capacity twice in every three
    minutes and cannot keep it, so more would be taken away as fast as it arrived.
    The scale-out is not merely insufficient here - it is the action the incident
    is made of, performed by Argus instead of by the controller.

    Which is why this cannot be the scale-out with a different target. The replica
    count belongs to the autoscaler, so the only write that holds it is one aimed
    at what the autoscaler is allowed to do, and an action that raised a floor
    while calling itself a scale-out would leave a reader of the record unable to
    say which of the two owns the number.

    Like a restart, a rollback and a scale-out, the deployment comes from the alert
    and from nowhere else. Not from Argus's configuration, which would hardcode one
    estate's answer into the agent - and not from the hypothesis, whose subject is
    the model's description of what would not settle rather than the name of
    anything a platform can be asked about.

    How high to raise the floor is named nowhere here, for the scale-out's reason
    and one more. A floor is meaningless without the ceiling it is raised to meet,
    that ceiling is live state only the write tier can read - and it is a bound
    somebody declared for this deployment, so it is not Argus's to choose even in
    principle.
    """

    action_types: frozenset[ActionType] = frozenset({PIN_AUTOSCALER})

    def propose(self,
                hypothesis: Hypothesis,
                circumstances: Circumstances) -> Action | None:
        """The deployment whose autoscaler to hold - the one the incident is about.

        Neither the hypothesis nor the recorded flag changes are read. A controller
        oscillating is not something a toggle did, and a flag that happened to move
        while the count went up and down is a coincidence this must not act on.

        Always an action. A control loop the model found no words for is still a
        control loop on a deployment the alert names, and there is nothing left for
        this to fail to identify.
        """
        return PinAutoscaler(application=circumstances.service)


class DiscardCacheEntriesStrategy:
    """Answering copies that stopped agreeing with their records by throwing them away.

    The sixth generic mitigation, and the first that removes something rather than
    restoring, adding or stopping something. The set's criterion is unchanged by
    that, as it was unchanged by the one that adds and the one that stops: what
    admits an action unasked is membership of the declared set, never the kind of
    change it makes. This is the member most likely to be read as a weakening,
    because removing data sounds heavier than putting a value back - and it is
    not, because what it removes was derived from records it never touches.

    It is also the one strategy whose action is addressed by something the
    evidence had to name. The other six are addressed to a flag the provider
    recorded or to a service the alert named - the pin to a card holding that
    service to a card the recorded placement names; an entry in a store is
    addressed by
    a key, a key's format belongs to whoever wrote the store, and so there is no
    honest way for Argus to work one out. The check that found the divergence
    built those keys in order to compare the copies, which is why it can hand them
    over and this cannot derive them.

    So this is the one strategy that reads `stale_entry_keys`, and the only one
    that can answer `None` for a reason the flag revert's does not share: the mode
    is right and the evidence did not say what to act on. A discard of nothing
    would reach the store, be refused by it, and be reported as a store that could
    not be reached - which would narrow the walk away from every action on a store
    that is perfectly well.
    """

    action_types: frozenset[ActionType] = frozenset({DISCARD_CACHE_ENTRIES})

    def propose(self,
                hypothesis: Hypothesis,
                circumstances: Circumstances) -> Action | None:
        """The entries to discard, or `None` where the evidence named none.

        The keys are passed through exactly as they arrived - same keys, same
        order, duplicates included. A `set` here would answer with a collection of
        the same size for a different set of entries, and that is the one
        corruption the receipt cannot expose: the store would report a count,
        the count would look right, and entries the check found would still be
        wrong with nobody left looking at them.

        Neither the hypothesis nor the recorded flag changes are read. A copy that
        fell behind is not something a toggle did, and a flag that moved while it
        drifted is a coincidence this must not act on. The service comes from the
        alert, as a restart's does, because the store holds that service's copies
        and the model's `subject` is a description rather than an address.
        """
        if not circumstances.stale_entry_keys:
            return None

        return DiscardCacheEntries(
            service=circumstances.service, keys=tuple(circumstances.stale_entry_keys)
        )


class UndoTheRecordedChangeStrategy:
    """Answering damage a change left behind by undoing whichever change the
    record holds.

    Every other strategy here answers a mode that is itself a statement about
    what kind of thing went wrong - a flag, a revision, a heap, a controller. A
    mode that names the damage instead says nothing of the sort: wrong data can
    be written by a flag somebody turned on, by a revision somebody deployed, by
    a migration or by a person at a console. So the mode chooses the family of
    answers - undo the change - and the record chooses which member.

    The flag revert is asked first, because it is the narrower claim. It answers
    only where a recorded change matches the flag the candidate named, or - where
    the candidate named none - is the only flag that moved; an estate deploys far
    more often than it toggles, so a deployment in the window says less. The
    rollback follows where the platform recorded one, and is addressed to the
    alerting service as every rollback is.

    Neither is a default. Where the record holds no change, nothing is proposed:
    a rollback recommended with no deployment behind it sends a person to undo
    somebody else's work for a fault it did not cause.
    """

    action_types: frozenset[ActionType] = frozenset(
        {REVERT_FEATURE_FLAG, ROLL_BACK_DEPLOYMENT}
    )

    def propose(self,
                hypothesis: Hypothesis,
                circumstances: Circumstances) -> Action | None:
        """The flag revert where the flag history names the change, else the
        rollback where the platform recorded a deployment, else `None`."""
        flag_revert = RevertFeatureFlagStrategy().propose(hypothesis, circumstances)

        if flag_revert is not None:
            return flag_revert

        if circumstances.deployments:
            return RollBackDeploymentStrategy().propose(hypothesis, circumstances)

        return None


class PinToAcceleratorStrategy:
    """Answering a replica moved onto another card by holding the deployment to
    the card the fleet ran on.

    The seventh generic mitigation, and a drain: pods move off a class of hardware
    and nothing deployed changes. Admitted on the ground every member is -
    somebody declared it - and named beside rolling back, restarting and adding
    capacity on Google SRE's own list.

    The deployment comes from the alert, as every action addressed to a service's
    platform does. The card comes from the placement the round recorded against
    its onset and from nowhere else: not the hypothesis, whose subject is prose,
    and not a read made now, after the walk may already have moved the pods.

    Which card is decided by `the_accelerator_to_pin_to`, and where it names none
    this proposes nothing. That reaches the gate as no mitigation proposed, the
    walk moves on, and an ambiguous placement ends with a person - which is how
    "the evidence does not say which card" is escalated without a route of its own.
    """

    action_types: frozenset[ActionType] = frozenset({PIN_TO_ACCELERATOR})

    def propose(self,
                hypothesis: Hypothesis,
                circumstances: Circumstances) -> Action | None:
        """The deployment to hold and the card to hold it to, or `None` where
        the placement does not name one card unambiguously.

        Neither the hypothesis nor the recorded histories are read. A replica the
        platform moved is not something a flag or a deployment did, and one that
        happened to move meanwhile is a coincidence this must not act on.
        """
        card = the_accelerator_to_pin_to(circumstances.placement)

        if card is None:
            return None

        return PinToAccelerator(application=circumstances.service, accelerator=card)


Strategies = Mapping[FailureMode, MitigationStrategy]

# Which mitigation answers which cause. A mode absent from this is one Argus
# has nothing to offer for, and `UPSTREAM_DEPENDENCY_FAILURE` is absent
# deliberately rather than pending: every mitigation here acts on Argus's own
# deployment, and another company's outage is reachable by none of them. The
# day something is registered for it, that will be a claim that Argus can shed
# load or fail over - which is a mitigation somebody has to build and defend,
# not a gap to be filled in.
#
# Many-to-one, and the three deployment modes are where that shows: a revision
# carries the code and the configuration it shipped with, so returning the
# deployment answers a bad deploy and a broken value alike. A mode is a
# distinction a reader of an incident makes, never one this mapping makes for
# them - what separates those two is the account the incident gives and the fix
# left afterwards, not what is done about it now.
#
# The third of them reaches this strategy for a reason the other two do not
# share, and it is worth reading before anybody concludes the mapping is merely
# loose. For a bad deploy and a broken value, returning the deployment *removes*
# the thing that was wrong. For an in-flight compatibility break nothing that was
# deployed is wrong: each revision alone would work, and what returning the
# deployment does is get every replica onto one of them. One call, two things
# achieved - and the record says which in the hypothesis rather than in the
# action, because the narration dispatches on what was done and what was done is
# identical in all three. A line that varied with the diagnosis would put a
# verdict in a sentence about a call the platform answered the same way.
#
# The two restarts are the other shape of the same thing, and they are two
# strategies rather than one because they differ in something a caller cannot
# supply: where the service comes from. A leak is in the service that alerted, so
# that strategy is handed the name; a neighbour's fault is somewhere the alert
# never mentioned, so that one reads the address the investigation wrote down.
# Both produce the same kind of action, which is why `GENERIC_MITIGATIONS` is
# unaffected by this mode arriving.
#
# The two halves of resource exhaustion are the one place the mapping's own
# distinctions are load-bearing in the other direction: a leak and a saturated
# deployment look alike on a latency graph and are answered by opposite things,
# so they map to different strategies and a reader who cannot tell them apart
# gets the wrong one. That is what the mode is for.
#
# The capacity family's third member sharpens that to a point. A flapping
# autoscaler *is* a saturated deployment at the bottom of every cycle, so the
# near-miss is not a careless reading of different evidence - it is the same
# evidence, read a minute too early. And the wrong answer is worse here than
# anywhere else in this mapping: a scale-out against a controller that owns the
# count is the incident performed by Argus rather than an action that merely fails
# to help. What separates them is one series, and it is retrievable.
DEFAULT_STRATEGIES: Strategies = {
    FailureMode.BAD_DEPLOYMENT: RollBackDeploymentStrategy(),
    FailureMode.FEATURE_FLAG_TOGGLE: RevertFeatureFlagStrategy(),
    FailureMode.RESOURCE_LEAK: RestartServiceStrategy(),
    FailureMode.CONFIG_INDUCED_FAILURE: RollBackDeploymentStrategy(),
    FailureMode.INTERNAL_DEPENDENCY_FAILURE: RestartDependencyStrategy(),
    FailureMode.DEMAND_SATURATION: ScaleOutStrategy(),
    FailureMode.AUTOSCALING_PATHOLOGY: PinAutoscalerStrategy(),
    FailureMode.IN_FLIGHT_COMPATIBILITY_BREAK: RollBackDeploymentStrategy(),
    # Whichever change the record holds at the onset, undone - and the one entry
    # here whose action the gate will decline. That refusal is the gate's
    # judgement and not this table's: a mode absent from this mapping answers
    # `None`, which is refused as nothing answering the kind of failure at all,
    # and the incident then ends saying a person is needed without saying what
    # for. Named here so there is something to recommend.
    FailureMode.SILENT_DATA_CORRUPTION: UndoTheRecordedChangeStrategy(),
    # The fourth mode returning a deployment, and the only one where what comes
    # back is the sight of the service rather than its behaviour. Nothing about
    # the service got worse; a revision changed what reaches the scrape, and
    # returning it is what puts the readings back. So what confirms this action
    # is the rows existing again rather than a level coming down, which is the
    # one place in this table where the action and what judges it come apart.
    FailureMode.MONITORING_BLIND_SPOT: RollBackDeploymentStrategy(),
    # The sixth mitigation, and the only entry here whose action is addressed by
    # something no other mode's evidence carries. Every other strategy can be
    # handed an incident and work out what to act on; this one is handed the
    # addresses or proposes nothing, because a cache key is not Argus's to
    # compose.
    FailureMode.STATE_DIVERGENCE: DiscardCacheEntriesStrategy(),
    # The fifth mode returning a deployment, and the one whose requests never
    # failed: the revision made the answers worse while every request still
    # succeeded as fast as before. Returning it puts the answers back, and what
    # confirms that is the rule that paged - whose series is the only one that
    # moved.
    FailureMode.OUTPUT_QUALITY_DEGRADATION: RollBackDeploymentStrategy(),
    # The seventh mitigation, and the near-miss of the entry above. Both are
    # answers that got worse while every request still succeeded as fast as
    # before; what separates them is whether a revision or a placement changed at
    # the onset, and the two are undone by opposite kinds of action.
    FailureMode.ACCELERATOR_HETEROGENEITY: PinToAcceleratorStrategy()
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
