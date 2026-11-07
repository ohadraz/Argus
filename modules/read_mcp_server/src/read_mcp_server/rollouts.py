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

Answered as a value, never in sentences. Two readers say it - an
Investigator's model, and the account of the incident - and each in its own
words; sentences written here would leave the second searching the first's for
a revision and a moment.
"""

from __future__ import annotations

from argus_core.models import RolloutAccount, RolloutProgress
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
                             platform: DeploymentPlatformReads) -> RolloutAccount:
    """Whether the deployment of `service` finished arriving, and the revisions
    it is between - as a value, for each reader to say in its own words.

    The service is the only subject. Which revisions are involved is found here,
    in the deployment history, rather than asked of the caller: a caller naming
    the revision it believes is going out would be naming the thing this channel
    exists to check.
    """
    progress = _the_rollout_of(service, platform)
    deployed = the_revisions_deployed(service, platform=platform)

    return RolloutAccount(progress=progress,
                          going_out=deployed[-1] if deployed else None,
                          before_it=deployed[-2] if len(deployed) >= 2 else None)


def how_far_the_rollout_has_got(service: str,
                                *,
                                platform: DeploymentPlatformReads
                                ) -> RolloutProgress:
    """How many of `service`'s replicas have reached the revision being rolled
    out, as a value a caller can act on.

    The counts of the account above, without the revisions. A caller waiting on
    a change it made needs to know the change has arrived, and nothing about
    which revisions a reader would name.

    Why a caller wants it. Until every replica is on the revision a rollback
    returned to, a minute of metrics is a minute the old code was still serving,
    so a recovery measured across those minutes is a recovery measured of the
    wrong deployment. This is what says when the measuring may begin, which is
    the only thing Mitigation needs and strictly less than the account says.

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

