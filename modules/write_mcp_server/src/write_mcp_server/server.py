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
was in.
"""

from __future__ import annotations

from typing import Any, Final

from core import DatabaseSettings, TelemetrySettings, WriteMcpEndpoint, get_settings, parse_iso
from core.models import (
    AcceleratorPinRestored,
    AcceleratorPinUndo,
    AutoscalerUndo,
    AutoscalingRestored,
    CacheEntriesDiscarded,
    CapacityRestored,
    DeploymentRestored,
    DeploymentRollbackUndo,
    FlagChange,
    FlagUndo,
    OpenedPullRequest,
    Planned,
    ReplicaUndo,
    RestartedService,
)
from deployment_platform import DeploymentPlatformWrites, Mark
from deployment_platform.argocd import ArgoCd, ArgoCdSettings
from flag_provider import FlagProviderWrites
from flag_provider.unleash import Unleash, UnleashSettings
from mcp.server.fastmcp import Context
from telemetry import start_telemetry

from write_mcp_server import (
    accelerators,
    branching,
    discarding,
    flag_state,
    marking,
    pinning,
    pull_requests,
    restarting,
    rolling_back,
    scaling,
)
from write_mcp_server.discarding import DiscardSettings
from write_mcp_server.fencing import (
    FencedFastMCP,
    HoldForAChange,
    OpensHolds,
    holds_in_the_database,
)
from write_mcp_server.pull_requests import RepositoryWriteSettings

# What this process is called in its telemetry, and the directory its runs are
# written under.
_SERVICE: Final = "argus-write-mcp"


def build_server(endpoint: WriteMcpEndpoint,
                 flags: FlagProviderWrites,
                 repository_settings: RepositoryWriteSettings,
                 platform: DeploymentPlatformWrites,
                 discard_settings: DiscardSettings,
                 hold_for_a_change: HoldForAChange,
                 argus_account: str) -> FencedFastMCP:
    """Registers the write tools against one deployment's configuration.

    Two slices and two ports. The code tool speaks to the repository, and the
    discard speaks to the store a service keeps its derived copies in. The flag
    tools speak to the flag provider, and the restart, the rollback, the
    scale-out, the autoscaler pin and the pin to a card all speak to the
    deployment platform - and both are handed their port rather than a slice:
    where each is, under what credential and by which routes is its adapter's,
    built once in `main`. Every credential named belongs to this tier, and none
    of them belongs in another's calls. What keeps the *tiers* apart is what each
    server is handed - the read server gets each reads port, and no slice with a
    field any of these could arrive in - not a check made here.

    The tool bodies stay registration only; the behaviour, and the seams a
    decorated function cannot carry, live in a module per route beside this one.

    Every tool that changes something is registered as a change, and made only
    for the claim that holds the run it is for - asked of `hold_for_a_change`
    (`fencing`). The reads are not: a stale walk reading the provider's
    history, asking whose a change in it was, or planning a change, gets
    nothing wrong.

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
    (`marking`). Read off the call's `Context`, which FastMCP hands the tool and
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
    mcp = FencedFastMCP(
        "argus-write-mcp",
        hold_for_a_change=hold_for_a_change,
        host=endpoint.write_mcp_host,
        port=endpoint.write_mcp_port,
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

        Answered as made, writing nothing, where Argus's own change since the
        plan already landed; refused as changed since where somebody else's
        did. Returns only once the change is visible to evaluation, and raises
        rather than reporting an unchanged flag as changed: a caller about to
        judge whether the service recovered has to know the service was
        actually changed. The behavior lives in `flag_state.set_flag`; this is
        registration only."""
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
                             ctx: Context[Any, Any, Any]) -> DeploymentRollbackUndo:
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
        ctx: Context[Any, Any, Any]
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
    def scale_out(planned: Planned[ReplicaUndo], ctx: Context[Any, Any, Any]) -> ReplicaUndo:
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
                              ctx: Context[Any, Any, Any]) -> CapacityRestored:
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
                       ctx: Context[Any, Any, Any]) -> AutoscalerUndo:
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
        return discarding.discard_cache_entries(keys, discard_settings)

    @mcp.change(marked=True)
    def restore_autoscaler_floor(
        descriptor: AutoscalerUndo,
        ctx: Context[Any, Any, Any]
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
                           ctx: Context[Any, Any, Any]) -> AcceleratorPinUndo:
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
        ctx: Context[Any, Any, Any]
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
    def was_flag_changed_by_argus_since(flag: str, since: str) -> bool | None:
        """Answers whether Argus's own change to `flag` was recorded at or after
        `since`, or nothing where nobody can say.

        The question a walk asks when it is resumed after its worker died with
        an action claimed: only the provider's history knows whether the change
        it was making landed, and the history is served to this tier's
        credential alone.

        No answer is an answer of its own, and never "no": the history could not
        be read, or the provider cannot tell Argus's changes from anybody's. The
        behavior lives behind the flag provider's port; this is registration
        only."""
        return flags.argus_changed_since(flag, parse_iso(since))

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
                             base_branch: str,
                             files: dict[str, str],
                             message: str) -> str:
        """Puts a proposed fix on a branch of its own, cut from the branch it
        fixes, and returns the branch it wrote.

        `files` maps a repository path to that file's whole new content. A
        branch is the only thing this writes to - never the base - so a wrong
        patch ends up somewhere nobody is running rather than in production.

        Every file the patch names is written, tests included - a fix that
        brings the test exposing the bug is the one a person can trust. The
        behavior lives in `branching.commit_to_new_branch`; this is
        registration only."""
        return branching.commit_to_new_branch(
            branch=branch,
            base_branch=base_branch,
            files=files,
            message=message,
            settings=repository_settings
        )

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
        at. The behavior lives in `pull_requests.open_pull_request`; this is
        registration only."""
        return pull_requests.open_pull_request(
            head_branch=head_branch,
            base_branch=base_branch,
            title=title,
            body=body,
            settings=repository_settings
        )

    return mcp


def _the_mark_of(ctx: Context[Any, Any, Any]) -> Mark:
    """The mark the call asking for a tool names, as `marking` reads it off the
    call's `_meta`."""
    meta = ctx.request_context.meta

    return marking.the_mark_in(meta.model_dump() if meta is not None else None)


def main(holds: OpensHolds = holds_in_the_database) -> None:
    """The process: one read of the environment, then serve until killed.

    The only place in this server that calls `get_settings`, and the one that
    starts its telemetry - closed on the way out, so what it collected last is
    on disk. So are the holds a change is made under, which are the database's
    own runs: `holds` defaults to them, and a suite that serves the real tools
    over a run it stands in for hands its own.
    """
    settings = get_settings()

    with (
        start_telemetry(TelemetrySettings.of(settings), _SERVICE),
        holds(DatabaseSettings.of(settings)) as hold_for_a_change
    ):
        build_server(
            WriteMcpEndpoint.of(settings),
            # The flag provider's adapter, built here and nowhere else in this
            # tier and handed on as the writes port, for the platform's reason.
            Unleash(UnleashSettings()),
            RepositoryWriteSettings.of(settings),
            # The adapter is built here and nowhere else in this tier, and handed
            # on as the writes port: no action below names a route.
            ArgoCd(ArgoCdSettings.of(settings)),
            DiscardSettings.of(settings),
            hold_for_a_change,
            settings.argocd_actor
        ).serve()


if __name__ == "__main__":
    main()
