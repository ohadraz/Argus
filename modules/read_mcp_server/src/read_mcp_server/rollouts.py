"""Whether a deployment converged, read as evidence (spec §16).

The sixth retrieval channel, and the only one that reads a deployment as a
stretch rather than as an instant. Every channel before it describes something
that happened at a moment: the metrics say when the service departed, the logs
say what it said about it, the flag provider and the deploy history say what
changed, and the diff says what a change carried. The history in particular
records that a revision was deployed and is silent on whether it finished
arriving - so a rollout that stopped part way is invisible to all five, and that
is precisely what separates a revision that is wrong from two revisions serving
at once.

Two reads meet here and neither leaves the tier. The live Deployment says how
many replicas have reached the new revision and whether the rolling update is
paused; the application's history names the revision being converged on and the
one the replicas that have not updated are still running.

The live resource rather than the history, and the distinction is the module's
reason to exist. The history is what the platform reports about syncs that
*completed*; whether the pods have turned over is on the Deployment itself, and
a convergence derived from the history would answer about a past event while
appearing to answer about the present one.

Nothing here judges. A deployment part way through a rollout is the ordinary
condition of every deployment for a minute or two, and a channel that called one
stuck would be deciding, on a timing it cannot know, a question that belongs to
whoever weighs causes - who holds the onset this channel has never seen. It says
what the platform reports and when the state began, and leaves the reading.

When rather than how long, and that is a limit rather than an omission. This
tier has no clock, a duration computed from one would differ between two reads
of the same state, and a reader holding an onset can do the arithmetic against
the moment the deployment landed.
"""

from __future__ import annotations

from argus_core.models import ChangeEvent, RolloutProgress
from deployment_platform import DeploymentPlatformError, DeploymentPlatformReads

from read_mcp_server.deploy_history import the_revisions_deployed


class RolloutUnreadable(Exception):
    """The platform would not say what the deployment is running.

    Raised rather than answered emptily, and this is the one failure in the tier
    where that matters most. "It converged" is an answer a reader acts on - it
    rules the mode out and sends them back to the revision - so an outage
    reported as convergence would send a walk to blame a revision that is not at
    fault.
    """


def how_the_rollout_is_going(service: str,
                             *,
                             platform: DeploymentPlatformReads) -> list[str]:
    """Whether the deployment of `service` finished arriving, as lines a model
    reads.

    The service is the only subject. Which revisions are involved is found here,
    in the deployment history, rather than asked of the caller: a caller naming
    the revision it believes is going out would be naming the thing this channel
    exists to check.
    """
    progress = _the_rollout_of(service, platform)
    deployed = the_revisions_deployed(service, platform=platform)

    if progress.replicas_updated >= progress.replicas_serving:
        return _converged(service, progress.replicas_serving, deployed)

    return _still_converging(service, progress, deployed)


def how_far_the_rollout_has_got(service: str,
                                *,
                                platform: DeploymentPlatformReads
                                ) -> RolloutProgress:
    """How many of `service`'s replicas have reached the revision being rolled
    out, as a value a caller can act on.

    The same read as the lines above, answered for a different reader. Those
    exist for a model - the Investigator hands them to one, and this channel
    describes rather than judges - and they must keep existing. A caller wanting
    the count would have to search that prose for a number, which is the mistake
    this repo refuses at every other wire: a vendor's phrasing becoming a
    dependency one layer in.

    Why a caller wants it. Until every replica is on the revision a rollback
    returned to, a minute of metrics is a minute the old code was still serving,
    so a recovery measured across those minutes is a recovery measured of the
    wrong deployment. This is what says when the measuring may begin, which is
    the only thing Mitigation needs and strictly less than the lines say.

    No history is read, where `how_the_rollout_is_going` reads two things. Which
    revisions are involved is what a *reader* wants named; whether the change has
    arrived is answered by the counts alone, so asking the application would buy
    a second read and nothing with it.

    It still refuses rather than guesses, and here that matters more than it does
    above. A caller told the rollout converged starts judging immediately, so a
    platform that could not be reached must not come back as arrival - it would
    have Mitigation measure the minutes before its own change landed and reach a
    verdict on them.

    Whether the rolling update is paused, and whether the platform says it cannot
    finish, travel with the counts: they are what give a caller's wait an end. A
    rollout stopped part way satisfies neither count and never will, and the
    controller goes on scaling a paused Deployment, so only a failure ends a
    scale-out's wait. Both are the platform's own report - not a judgement made
    here.
    """
    return _the_rollout_of(service, platform)


def _the_rollout_of(service: str,
                    platform: DeploymentPlatformReads) -> RolloutProgress:
    """The platform's account of the running Deployment, or a refusal.

    Refused whichever way the platform failed. A Deployment this could not read
    is one whose rollout is unknown, and the one answer that must never be
    reached by guesswork is that it converged.
    """
    try:
        return platform.rollout_of(service)
    except DeploymentPlatformError as error:
        raise RolloutUnreadable(
            f"could not read what [{service}] is running: {error}"
        ) from error


def _converged(service: str,
               serving: int,
               deployed: list[ChangeEvent]) -> list[str]:
    """A deployment that finished arriving, said plainly.

    Said at all, rather than answered with silence, because this is evidence: a
    reader weighing a deploy at the onset has been told it is not half-applied,
    which rules one mode out and leaves the revision itself as the subject.
    """
    if not deployed:
        return [
            f"Deployment of {service} has converged: all {serving} replicas are "
            f"running the same revision. The deployment history holds no "
            f"deployment at all, so nothing here names which."
        ]

    latest = deployed[-1]

    return [
        f"Deployment of {service} has converged: all {serving} replicas are "
        f"running revision [{latest.reference}], deployed at "
        f"{latest.occurred_at}."
    ]


def _still_converging(service: str,
                      progress: RolloutProgress,
                      deployed: list[ChangeEvent]) -> list[str]:
    """A deployment part way through, and the two revisions that are serving.

    Both named, because a count with one subject is a count a reader cannot use:
    what is being asked is whether two versions are running at once, and one
    revision and a number does not say what the other version is.
    """
    serving = progress.replicas_serving
    updated = progress.replicas_updated
    said = [
        f"Deployment of {service} has not converged: {updated} of {serving} "
        f"replicas are running {_the_revision_going_out(deployed)}, and "
        f"{serving - updated} are still running "
        f"{_the_revision_before_it(deployed)}."
    ]

    if progress.is_paused:
        said.append(
            "Its rolling update is paused, so the platform is not converging it "
            "on its own."
        )

    if deployed:
        said.append(
            f"The revision it is converging on was deployed at "
            f"{deployed[-1].occurred_at}, which is when the replicas first "
            f"differed."
        )

    return said


def _the_revision_going_out(deployed: list[ChangeEvent]) -> str:
    if not deployed:
        return "a revision the deployment history does not hold"

    return f"revision [{deployed[-1].reference}]"


def _the_revision_before_it(deployed: list[ChangeEvent]) -> str:
    """What the replicas that have not updated are running.

    Said as unknown rather than left out where the history has nothing earlier. A
    reader told only about the new revision reads the split as a count with one
    subject, which is the reading this channel exists to prevent.
    """
    if len(deployed) < 2:
        return (
            "whatever preceded it - there is no earlier deployment in the "
            "history to name it by"
        )

    return f"revision [{deployed[-2].reference}]"
