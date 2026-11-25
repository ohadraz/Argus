"""`argus-write-mcp` - the tools that change state (spec §12.1, §13).

A separate process from `argus-read-mcp`, not a separate module inside it. The
split is what makes "read-only" a property of a running process: the read server
holds no credential that could authorize a change, so a compromised or confused
caller cannot mutate anything through it, whatever tools it believes it has.

Every tool here that touches the running service performs a **generic
mitigation** (§13) - one of the closed, pre-authorised set Argus may take
unasked. The rest write to a branch nothing is running, which is how a proposed
fix reaches a human without reaching production. What has no function on this
server at all is anything that would deploy: merging a pull request, applying
infrastructure. That is tier enforcement by absence rather than by a check some
future caller could skip.

Built rather than declared, for the reason the read server is: the process that
reads configuration is the process that starts, and a server assembled at import
would have bound its credentials before anything could say which deployment it
was in. The process that serves it - its telemetry, its holds, its adapters - is
`apps.write_mcp`.
"""

from __future__ import annotations

from typing import Any

from cache_store import CacheStore
from code_host import CodeHostWrites
from core import WriteMcpEndpoint, parse_iso
from core.models import (
    AcceleratorPinRestored,
    AcceleratorPinUndo,
    AutoscalerUndo,
    AutoscalingRestored,
    CacheEntriesDiscarded,
    CapacityRestored,
    ChangeFound,
    DeploymentRestored,
    DeploymentRollbackUndo,
    FlagChange,
    FlagUndo,
    Made,
    NotMade,
    OpenedPullRequest,
    Planned,
    ReplicaUndo,
    RestartedService,
)
from deployment_platform import DeploymentPlatformWrites, Mark
from flag_provider import FlagProviderWrites
from mcp.server.mcpserver import Context

from write_mcp_server import (
    accelerators,
    discarding,
    flag_state,
    marking,
    pinning,
    restarting,
    rolling_back,
    scaling,
)
from write_mcp_server.fencing import FencedMCPServer, HoldForAChange


def build_server(endpoint: WriteMcpEndpoint,
                 flags: FlagProviderWrites,
                 code: CodeHostWrites,
                 platform: DeploymentPlatformWrites,
                 store: CacheStore,
                 hold_for_a_change: HoldForAChange,
                 argus_account: str) -> FencedMCPServer:
    """Registers the write tools against one deployment's configuration.

    Four ports. The discard speaks to the store a service keeps its derived
    copies in, the code tools to the code host, the flag tools to the flag
    provider, and the restart, the rollback, the scale-out, the autoscaler pin
    and the pin to a card all to the deployment platform - and each is handed
    its port rather than a slice:
    where each is, under what credential and by which routes is its adapter's,
    built once by the process's root (`apps.write_mcp`). Every credential named
    belongs to this tier, and none of them belongs in another's calls. What
    keeps the *tiers* apart is what each server is handed - the read server gets
    each reads port, and no slice with a field any of these could arrive in -
    not a check made here.

    The tool bodies stay registration only; the behaviour, and the seams a
    decorated function cannot carry, live in a module per route beside this one.

    Every tool that changes something is registered as a change, and made only
    for the claim that holds the run it is for - asked of `hold_for_a_change`
    (`fencing`). The reads are not: a stale walk reading the provider's
    history, asking whose a change in it was, planning a change, or asking what
    became of one, gets nothing wrong.

    A walk resumed after its worker died asks two reads per kind of change
    that leaves something to put back: whether a claim's change was made -
    each kind's write rule on the claim's plan, with the write left out, so it
    refuses where the write would - and whether a performed change is still as
    Argus left it. Each takes only what the row recorded; the account goes to
    the rollback's, and the claim the call's `_meta` names to every one whose
    compare reads a claim's mark, read off `Context` as a marked change's is.

    Every change that leaves something to put back is planned first, by a read
    of its own: the plan works out the change from the estate as it stands and
    dates it by the clock of the port it was read through, and changes nothing -
    so it is asked holding no run, because the walk plans before it claims. The
    write is then handed the plan back whole and takes nothing it could work out
    again: the plan is what the claim recorded, and a write that re-derived it
    would compare the estate with something nobody wrote down. On the write tier
    rather than the read one because the plan is what the write compares
    against, read through the same port the compare reads through - and the
    flag's admin read needs the admin token only this tier holds.

    The changes that write to the deployment platform and leave something to
    put back are registered as marked too: each is made only for a call naming
    the action it is for, and every write it makes carries that action's mark
    (`marking`). Read off the call's `Context`, which the SDK hands the tool and
    leaves out of what the tool declares, so no caller is offered it as an
    argument. A restart and a discard leave nothing to put back, and the flag
    provider and the repository record whose a change was in their own way.

    `argus_account` is the account Argus signs in to the deployment platform as,
    which the platform writes on every history entry a rollback of Argus's adds.
    Handed to the rollback, which asks whether an entry made since its plan is
    Argus's own landed rollback before it answers as made, and to its restore,
    which asks whether the newest entry is still Argus's own before it puts
    anything back - and is the server's to hand both, because nothing in a call
    names it and a write told any other name would take Argus's rollback for a
    person's, or a person's for Argus's.
    """
    mcp = FencedMCPServer(
        "argus-write-mcp",
        hold_for_a_change=hold_for_a_change,
        host=endpoint.write_mcp_host,
        port=endpoint.write_mcp_port
    )

    @mcp.tool()
    def plan_flag(flag: str, enabled: bool) -> Planned[FlagUndo]:
        """Plans setting a feature flag on or off: the state the provider holds
        it in, which is what puts it back, dated by the provider's own clock.

        A read, and changes nothing. Refused as an exhausted action where the
        flag is already as asked. The behavior lives in `flag_state.plan_flag`;
        this is registration only."""
        return flag_state.plan_flag(flag, enabled, flags)

    @mcp.change()
    def set_feature_flag(planned: Planned[FlagUndo], enabled: bool) -> FlagUndo:
        """Sets the planned feature flag on or off in the configured
        environment, where nobody has changed it since the plan.

        A generic mitigation (§13): it is taken unasked because its kind is
        in the declared set, not because it can be undone. It does leave
        something behind, and the state it changed is recorded in the undo
        descriptor returned with it, so whoever holds that record can put the
        change back if the mitigation turns out to be refuted.

        Both directions, one tool. A flag causes an incident by changing, and
        the damaging direction is not always "on" - undoing a flag that was
        switched off means switching it back on, and undoing this call is a
        plan and this call with the state reversed.

        Answered as made, writing nothing, where Argus's own flip to the state
        asked for still stands; refused as changed since where somebody else
        changed it. Returns only once the change is visible to evaluation, and
        raises rather than reporting an unchanged flag as changed: a caller
        about to judge whether the service recovered has to know the service
        was actually changed. The behavior lives in `flag_state.set_flag`; this
        is registration only."""
        return flag_state.set_flag(planned, enabled, flags)

    @mcp.change()
    def restart_service(service: str) -> RestartedService:
        """Restarts a service and returns the start time of the process now
        serving it.

        A generic mitigation (§13): the industry's most common first response
        to a resource leak, taken unasked because it is in the declared set of
        routine responses - not because it can be undone, which it cannot. It
        changes no persistent state, so it returns no undo descriptor and
        there is nothing for a withdrawal to put back.

        Returns only once a new process is actually serving, and raises rather
        than reporting an unrestarted service as restarted: a caller about to
        judge whether the leak was reclaimed has to know the process it is
        judging is a new one. The behavior lives in
        `restarting.restart_service`; this is registration only."""
        return restarting.restart_service(service, platform)

    @mcp.tool()
    def plan_rollback(application: str) -> Planned[DeploymentRollbackUndo]:
        """Plans returning a deployment to the revision it ran before: the
        entry it is on, the entry it would go back to, and whether the platform
        reconciles it itself, dated by the platform's own clock.

        Which revision is worked out here and not asked for, because nothing
        above this port holds a deployment history to choose from: the last
        entry of the stretch of one revision before the one running. A read,
        and changes nothing. The behavior lives in
        `rolling_back.plan_rollback`; this is registration only."""
        return rolling_back.plan_rollback(application, platform)

    @mcp.change(marked=True)
    def roll_back_deployment(planned: Planned[DeploymentRollbackUndo],
                             ctx: Context[Any, Any]) -> DeploymentRollbackUndo:
        """Returns a deployment to the entry its plan named, and reports what
        that cost.

        A generic mitigation (§13), admissible unasked for one specific
        reason: the revision it applies was reviewed and ran before, so this
        replays somebody's change rather than authoring one. It writes nothing
        to the repository, and must not - that would be an infrastructure
        change requiring approval.

        Compared with the estate before anything is written: answered as made
        where this action's rollback already landed, by the account Argus signs
        in as; refused as changed since where anybody else moved the deployment
        or its reconciliation since the plan; written only where it is as the
        plan found it.

        Mitigates without resolving. The repository still holds the change
        that caused the incident, and the platform's own reconciliation has
        been suspended so that it is not re-applied; both are recorded in the
        descriptor returned, and both are what a withdrawal puts back. The
        behavior lives in `rolling_back.roll_back_deployment`; this is
        registration only."""
        return rolling_back.roll_back_deployment(
            planned, platform, _the_mark_of(ctx), argus_account
        )

    @mcp.change(marked=True)
    def restore_deployment(
        descriptor: DeploymentRollbackUndo,
        ctx: Context[Any, Any]
    ) -> DeploymentRestored:
        """Puts back both of the things a rollback changed, where they are
        still Argus's, and reports which of them it managed.

        The revision the deployment was running, and the reconciliation that
        had to be suspended to leave it. Both, or it is not undone: a
        deployment whose revision is back while the platform is still not
        reconciling it looks correct from every angle a reader has, and
        silently receives nothing anybody ships to it.

        Neither where somebody has changed the deployment since - a revision
        they deployed, or images they set without a deployment. That is left
        as they set it, with the reconciliation Argus suspended left
        suspended, and the answer says what was found: putting it back would
        overwrite them, and so would resuming sync.

        Answers with which halves it managed rather than raising, because a
        restore can half-succeed and the caller has to be able to say which
        half is still changed - "the revision is back and reconciliation is
        still suspended" is a sentence somebody can act on, where "it did not
        work" is not.

        The order is the platform's to dictate: automated sync refuses a
        rollback, so the revision is put back before reconciliation is
        re-enabled. The behavior lives in
        `rolling_back.restore_deployment`; this is registration only."""
        return rolling_back.restore_deployment(
            descriptor, platform, _the_mark_of(ctx), argus_account
        )

    @mcp.tool()
    def plan_scale_out(application: str) -> Planned[ReplicaUndo]:
        """Plans giving a deployment more replicas than it is running: the
        count it runs, the count it would be given, and whether the platform
        reconciles it itself, dated by the platform's own clock.

        How many is worked out here and not asked for, for the reason the
        scale-out gives. A read, and changes nothing. The behavior lives in
        `scaling.plan_scale_out`; this is registration only."""
        return scaling.plan_scale_out(application, platform)

    @mcp.change(marked=True)
    def scale_out(planned: Planned[ReplicaUndo], ctx: Context[Any, Any]) -> ReplicaUndo:
        """Gives a deployment the replicas its plan asked for, and reports what
        that cost.

        A generic mitigation (§13), and the only one that adds capacity rather
        than restoring state - which changes nothing about what admits it: an
        action is taken unasked because its kind is in the declared set, never
        because it can be put back. Google SRE's own list of generic mitigations
        names adding capacity beside draining, rolling back and restarting.

        How many is not a parameter. The plan asked the platform what the
        deployment is running and doubled that count, and the write bounds it
        again by a ceiling this tier holds - because a target is meaningless
        without the count it replaces, and nothing above this port can read that
        count. What the repository asks for is a different number as soon as
        anybody has scaled. Both figures are reported back. Compared with the
        estate before anything is written, as the rollback is.

        There is no tool for the reverse, and there should not be. Being wrong
        about adding capacity costs money; being wrong about removing it costs an
        outage.

        Mitigates without resolving. The repository still asks for the size that
        was too small, the platform's own reconciliation has been suspended so
        that nothing re-applies it, and the traffic that outgrew the deployment
        is still arriving; the first two are recorded in the descriptor returned
        and are what a withdrawal puts back. The behavior lives in
        `scaling.scale_out`; this is registration only."""
        return scaling.scale_out(planned, platform, _the_mark_of(ctx))

    @mcp.change(marked=True)
    def restore_replica_count(descriptor: ReplicaUndo,
                              ctx: Context[Any, Any]) -> CapacityRestored:
        """Puts back both of the things a scale-out changed, where they are
        still Argus's, and reports which of them it managed.

        The count the deployment was running, and the reconciliation that had to
        be suspended to leave it. Both, or it is not undone: a deployment back at
        its declared size while the platform is still not reconciling it looks
        correct from every angle a reader has, and silently receives nothing
        anybody ships to it.

        Neither where somebody has set the count since: that is left as they
        set it, with the reconciliation Argus suspended left suspended, and the
        answer says what was found. Where an autoscaler owns the count, the
        count is left to it and only the sync is put back.

        Answers with which halves it managed rather than raising, for the reason
        the rollback's restore does: a restore can half-succeed, and the caller
        has to be able to say which half is still changed.

        The count is put back before reconciliation is re-enabled. The other
        order would have the platform set the count itself, unverifiably, at a
        moment nothing here chose. The behavior lives in
        `scaling.restore_replica_count`; this is registration only."""
        return scaling.restore_replica_count(descriptor, platform, _the_mark_of(ctx))

    @mcp.tool()
    def plan_autoscaler_pin(application: str) -> Planned[AutoscalerUndo]:
        """Plans stopping a deployment's autoscaler moving the replica count
        about: the floor it has, the floor it would be raised to, and whether
        the platform reconciles it itself, dated by the platform's own clock.

        How high is worked out here and not asked for, for the reason the pin
        gives. A read, and changes nothing. The behavior lives in
        `pinning.plan_autoscaler_pin`; this is registration only."""
        return pinning.plan_autoscaler_pin(application, platform)

    @mcp.change(marked=True)
    def pin_autoscaler(planned: Planned[AutoscalerUndo],
                       ctx: Context[Any, Any]) -> AutoscalerUndo:
        """Stops a deployment's autoscaler moving the replica count about, as
        its plan said, and reports the floor it had.

        A generic mitigation (§13), and the first that stops something rather
        than adding or restoring something - which changes nothing about what
        admits it: an action is taken unasked because its kind is in the declared
        set, never because of the kind of change it makes.

        What it stops is a control loop, and it stops it by raising the floor to
        the ceiling: the controller is left running with nowhere left to scale
        down to. Nothing is removed and the ceiling is never moved, which is what
        makes this reversible - lowering a ceiling would reduce a deployment's
        capacity, and nothing here does that autonomously.

        How high is not a parameter, for a stronger version of the reason a
        scale-out takes no count. There a target is meaningless without the count
        it replaces; here the number is not Argus's to choose even in principle,
        because the ceiling is a bound a human declared.

        Mitigates without resolving. The repository still declares the floor the
        controller was thrashing between, the platform's own reconciliation has
        been suspended so that nothing re-applies it, and whatever the controller
        was reacting to is still there; the first two are recorded in the
        descriptor returned and are what a withdrawal puts back. Compared with
        the estate before anything is written, as the rollback is. The behavior
        lives in `pinning.pin_autoscaler`; this is registration only."""
        return pinning.pin_autoscaler(planned, platform, _the_mark_of(ctx))

    @mcp.change()
    def discard_cache_entries(keys: list[str]) -> CacheEntriesDiscarded:
        """Removes the named entries from the service's cache and reports how
        many of them were there.

        A generic mitigation (§13), and the only one that reaches a datastore
        rather than a control plane: no platform offers this write, because a
        platform's own actions reach a workload's lifecycle and its size and
        none of them reaches what a cache holds.

        Takes the keys and nothing that could match a key it was not given - no
        pattern, no prefix, no service. The entries to remove are the ones an
        incident's evidence named; a pattern would be a blast radius its caller
        could not state, and emptying the cache would discard entries nothing
        proved wrong.

        Returns no undo descriptor and there is nothing for a withdrawal to put
        back - not because no state changed, which is the restart's reason, but
        because what was removed was a copy of records this never touched.
        Whatever reads one of those entries next works it out again from those
        records, so putting the old values back would be recreating the
        incident.

        The count is the confirmation. It is the store saying which of the named
        keys existed and are now gone, which is the whole of what the incident
        was - so nothing is read back afterwards. Raises rather than reporting
        zero where the store could not be reached at all: a store that answered
        and held none of them is a divergence something else already cleared,
        and a store that never answered is a mitigation that did not happen.
        The behavior lives in `discarding.discard_cache_entries`; this is
        registration only."""
        return discarding.discard_cache_entries(keys, store)

    @mcp.change(marked=True)
    def restore_autoscaler_floor(
        descriptor: AutoscalerUndo,
        ctx: Context[Any, Any]
    ) -> AutoscalingRestored:
        """Puts back both of the things a pin changed, where they are still
        Argus's, and reports which of them it managed.

        The floor the autoscaler had, and the reconciliation that had to be
        suspended to leave it. Both, or it is not undone: an autoscaler back at
        its declared floor while the platform is still not reconciling it looks
        correct from every angle a reader has, and silently receives nothing
        anybody ships to it.

        Neither where somebody has set the floor since, or taken the autoscaler
        away: that is left as they set it, with the reconciliation Argus
        suspended left suspended, and the answer says what was found.

        Answers with which halves it managed rather than raising, for the reason
        the other two restores do: a restore can half-succeed, and the caller has
        to be able to say which half is still changed.

        The floor is put back before reconciliation is re-enabled. The other
        order would have the platform re-apply the manifest itself,
        unverifiably, at a moment nothing here chose. The behavior lives in
        `pinning.restore_autoscaler_floor`; this is registration only."""
        return pinning.restore_autoscaler_floor(descriptor, platform, _the_mark_of(ctx))

    @mcp.tool()
    def plan_accelerator_pin(application: str,
                             accelerator: str) -> Planned[AcceleratorPinUndo]:
        """Plans holding a deployment's pods to one accelerator card: the card
        they are held to now, the card they would be held to, and whether the
        platform reconciles the application itself, dated by the platform's own
        clock.

        Which card is a parameter because it is the one thing the action cannot
        work out for itself: it comes from where the replicas started before
        the onset, which the caller read and this tier never saw. A read, and
        changes nothing. The behavior lives in
        `accelerators.plan_accelerator_pin`; this is registration only."""
        return accelerators.plan_accelerator_pin(application, accelerator, platform)

    @mcp.change(marked=True)
    def pin_to_accelerator(planned: Planned[AcceleratorPinUndo],
                           ctx: Context[Any, Any]) -> AcceleratorPinUndo:
        """Holds a deployment's pods to the card its plan named, and reports the
        card they were held to before.

        A generic mitigation (§13): a drain, which Google SRE's list of generic
        mitigations names beside rolling back, restarting and adding capacity.
        The pods move off a class of hardware and nothing deployed changes.
        Compared with the estate before anything is written, as the rollback
        is.

        Mitigates without resolving. The repository still declares a template
        that lets the pods land on any card, the platform's own reconciliation
        has been suspended so that nothing re-applies it, and the code that
        behaves differently on the other card is still there; the first two are
        recorded in the descriptor returned and are what a withdrawal puts back.
        The behavior lives in `accelerators.pin_to_accelerator`; this is
        registration only."""
        return accelerators.pin_to_accelerator(planned, platform, _the_mark_of(ctx))

    @mcp.change(marked=True)
    def restore_accelerator_pin(
        descriptor: AcceleratorPinUndo,
        ctx: Context[Any, Any]
    ) -> AcceleratorPinRestored:
        """Puts back both of the things a pin to a card changed, where they are
        still Argus's, and reports which of them it managed.

        The card the pods were held to, or that they were held to none, and the
        reconciliation that had to be suspended to leave it. Both, or it is not
        undone - and neither where somebody has moved the pods since, which is
        left as they set it with the reconciliation Argus suspended left
        suspended. Answers with which halves it managed rather than raising, for
        the reason the other restores do.

        The pin is put back before reconciliation is re-enabled. The behavior
        lives in `accelerators.restore_accelerator_pin`; this is registration
        only."""
        return accelerators.restore_accelerator_pin(descriptor, platform, _the_mark_of(ctx))

    @mcp.tool()
    def get_recent_flag_changes(since: str) -> list[FlagChange]:
        """Returns the flag toggles the provider recorded since `since`, oldest
        first - for each, the flag, the state it was changed to, when, and who
        by.

        A read on the write server, which is where the credential to make it
        lives: the provider serves its history to admin tokens only, and an
        admin token can also change a flag. Issuing the read server one would
        defeat the tier split; reading from a process that can already write
        does not.

        It answers the question current state cannot - which flag changed, and
        in which direction - so that a flag switched *off* into an incident is
        distinguishable from one that was off all along. The behavior lives
        behind the flag provider's port; this is registration only."""
        return flags.changes_since(parse_iso(since))

    @mcp.tool()
    def whether_flag_was_made(planned: Planned[FlagUndo]) -> Made[FlagUndo] | NotMade[FlagUndo]:
        """Answers whether the flag change a claim planned was made: made, with
        when the provider recorded it; not made, leaving nothing behind, where
        nothing landed; refused as
        `set_feature_flag` refuses it where it would.

        The first question a walk resumed after its worker died asks of a
        claim. A read, asked holding no run. The behavior lives in
        `flag_state.whether_it_was_made`; this is registration only."""
        return flag_state.whether_it_was_made(planned, flags)

    @mcp.tool()
    def flag_still_argus_s(planned: Planned[FlagUndo], descriptor: FlagUndo) -> ChangeFound:
        """Answers whether a flag change Argus made is still as Argus left it,
        from the provider's history since the plan it was made from - both as
        the claim stored them.

        What a walk resumed after its worker died asks before it watches a
        change an earlier worker made. A read, asked holding no run. The
        behavior lives in `flag_state.still_argus_s`; this is registration
        only."""
        return flag_state.still_argus_s(planned, descriptor, flags)

    @mcp.tool()
    def whether_rollback_was_made(planned: Planned[DeploymentRollbackUndo],
                                  ctx: Context[Any, Any]
                                  ) -> (Made[DeploymentRollbackUndo]
                                        | NotMade[DeploymentRollbackUndo]):
        """Answers whether the rollback a claim planned was made: made, with
        when the platform says it was; not made where nothing landed, carrying
        the plan where the claim's suspension of the sync stands; refused as
        `roll_back_deployment` refuses it where it would - its compare reads
        the sync switch under the claim the call names.

        A read, asked holding no run. The behavior lives in
        `rolling_back.whether_it_was_made`; this is registration only."""
        return rolling_back.whether_it_was_made(planned, platform, _the_action_of(ctx),
                                                argus_account)

    @mcp.tool()
    def rollback_still_argus_s(descriptor: DeploymentRollbackUndo) -> ChangeFound:
        """Answers whether a rollback Argus made is still as Argus left it - the
        restore's own check, asked on its own, against the account Argus signs
        in as.

        A read, asked holding no run. The behavior lives in
        `rolling_back.still_argus_s`; this is registration only."""
        return rolling_back.still_argus_s(descriptor, platform, argus_account)

    @mcp.tool()
    def whether_scale_out_was_made(planned: Planned[ReplicaUndo],
                                   ctx: Context[Any, Any]
                                   ) -> Made[ReplicaUndo] | NotMade[ReplicaUndo]:
        """Answers whether the scale-out a claim planned was made under the
        claim the call names: made, with when its mark says; not made where
        nothing landed, carrying the plan where the claim's suspension of the
        sync stands; refused as `scale_out` refuses it where it would.

        A read, asked holding no run. The behavior lives in
        `scaling.whether_it_was_made`; this is registration only."""
        return scaling.whether_it_was_made(planned, platform, _the_action_of(ctx))

    @mcp.tool()
    def scale_out_still_argus_s(descriptor: ReplicaUndo,
                                ctx: Context[Any, Any]) -> ChangeFound:
        """Answers whether a scale-out Argus made is still as Argus left it,
        under the claim the call names.

        A read, asked holding no run. The behavior lives in
        `scaling.still_argus_s`; this is registration only."""
        return scaling.still_argus_s(descriptor, platform, _the_action_of(ctx))

    @mcp.tool()
    def whether_autoscaler_pin_was_made(planned: Planned[AutoscalerUndo],
                                        ctx: Context[Any, Any]
                                        ) -> Made[AutoscalerUndo] | NotMade[AutoscalerUndo]:
        """Answers whether the autoscaler pin a claim planned was made under the
        claim the call names: made, with when its mark says; not made where
        nothing landed, carrying the plan where the claim's suspension of the
        sync stands; refused as `pin_autoscaler` refuses it where it would.

        A read, asked holding no run. The behavior lives in
        `pinning.whether_it_was_made`; this is registration only."""
        return pinning.whether_it_was_made(planned, platform, _the_action_of(ctx))

    @mcp.tool()
    def autoscaler_pin_still_argus_s(descriptor: AutoscalerUndo,
                                     ctx: Context[Any, Any]) -> ChangeFound:
        """Answers whether an autoscaler pin Argus made is still as Argus left
        it, under the claim the call names.

        A read, asked holding no run. The behavior lives in
        `pinning.still_argus_s`; this is registration only."""
        return pinning.still_argus_s(descriptor, platform, _the_action_of(ctx))

    @mcp.tool()
    def whether_accelerator_pin_was_made(planned: Planned[AcceleratorPinUndo],
                                         ctx: Context[Any, Any]
                                         ) -> (Made[AcceleratorPinUndo]
                                               | NotMade[AcceleratorPinUndo]):
        """Answers whether the pin to a card a claim planned was made under the
        claim the call names: made, with when its mark says; not made where
        nothing landed, carrying the plan where the claim's suspension of the
        sync stands; refused as `pin_to_accelerator` refuses it where it would.

        A read, asked holding no run. The behavior lives in
        `accelerators.whether_it_was_made`; this is registration only."""
        return accelerators.whether_it_was_made(planned, platform, _the_action_of(ctx))

    @mcp.tool()
    def accelerator_pin_still_argus_s(descriptor: AcceleratorPinUndo,
                                      ctx: Context[Any, Any]) -> ChangeFound:
        """Answers whether a pin to a card Argus made is still as Argus left
        it, under the claim the call names.

        A read, asked holding no run. The behavior lives in
        `accelerators.still_argus_s`; this is registration only."""
        return accelerators.still_argus_s(descriptor, platform, _the_action_of(ctx))

    @mcp.tool()
    def was_flag_changed_by_others_since(flag: str, since: str) -> bool | None:
        """Answers whether anybody but Argus changed `flag` at or after `since`,
        or nothing where nobody can say.

        What an undo asks before it writes: a change made after Argus's own is
        somebody's deliberate decision, and putting the flag back would
        overwrite it.

        No answer is never "nobody": the two are the difference between putting
        a change back and overwriting a person. The behavior lives behind the
        flag provider's port; this is registration only."""
        return flags.others_changed_since(flag, parse_iso(since))

    @mcp.change()
    def commit_to_new_branch(branch: str,
                             base_commit: str,
                             files: dict[str, str],
                             message: str) -> str:
        """Puts a proposed fix on a branch of its own, cut from `base_commit` -
        where the branch it fixes pointed when the fix was claimed - and
        returns the branch it wrote.

        `files` maps a repository path to that file's whole new content. A
        branch is the only thing this writes to - never the base - so a wrong
        patch ends up somewhere nobody is running rather than in production.

        Every file the patch names is written, tests included - a fix that
        brings the test exposing the bug is the one a person can trust. The
        behavior lives behind the code host's writes port; this is
        registration only."""
        return code.commit_to_new_branch(branch, base_commit, files, message)

    @mcp.change()
    def open_pull_request(head_branch: str,
                          base_branch: str,
                          title: str,
                          body: str) -> OpenedPullRequest:
        """Opens a draft pull request proposing a code fix, from the branch the
        fix sits on onto the branch it fixes.

        The half of a deploy that Argus is trusted with (§13). Opening a
        proposal changes nothing about the running service; *merging* one is
        the deploy itself, and there is no tool here that does it -
        not a guarded one, not an approval-gated one, none. That absence is the
        enforcement, and it is why this returns a place to read rather than an
        outcome: what happens next is a human's to decide.

        There is no draft parameter, because it is not the caller's choice.
        Returns the pull request's number and the address a person can read it
        at. The behavior lives behind the code host's writes port; this is
        registration only."""
        return code.propose(head_branch, base_branch, title, body)

    return mcp


def _the_mark_of(ctx: Context[Any, Any]) -> Mark:
    """The mark the call asking for a tool names, as `marking` reads it off the
    call's `_meta`."""
    return marking.the_mark_in(_the_meta_of(ctx))


def _the_action_of(ctx: Context[Any, Any]) -> str | None:
    """The claim the call asking for a read names, as `marking` reads it off the
    call's `_meta` - `None` where it names none, which the read answers as a
    question nobody can answer rather than refusing to be asked."""
    return marking.the_action_in(_the_meta_of(ctx))


def _the_meta_of(ctx: Context[Any, Any]) -> dict[str, Any] | None:
    """The call's `_meta`, as a mapping, or `None` where it carried none."""
    meta = ctx.request_context.meta

    return dict(meta) if meta is not None else None
