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
reason to exist. Argo CD's history is what it reports about syncs that
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

import json
from collections.abc import Callable
from typing import Any, Final, Protocol

import httpx2
from argus_core import SettingsSlice
from argus_core.models import ChangeEvent, RolloutProgress

from read_mcp_server.argocd import FetchApplication, the_revisions_deployed

# Kubernetes' own wire vocabulary for the parts of a Deployment this reads.
# Named once rather than spelled at each lookup: they are another project's
# field names, and a typo in one is a silent `None` rather than an error - which
# here would be a split fleet reported as a converged one.
SPEC: Final = "spec"
STATUS: Final = "status"
REPLICAS: Final = "replicas"
UPDATED_REPLICAS: Final = "updatedReplicas"
PAUSED: Final = "paused"

# Argo CD's own wrapper for a managed resource: the manifest arrives as *text*
# and the caller parses it, which is the vendor's shape for this response.
MANIFEST: Final = "manifest"

REQUEST_TIMEOUT_SECONDS: Final = 10.0


class RolloutReadSettings(SettingsSlice):
    """Where the live Deployment is read from, and under what credential.

    Its own slice and its own path rather than the write tier's, because the two
    tiers configure their own routes and neither reads the other's - that
    separation is what the tier split is. The path is a template for the reason
    every Argo CD path here is one: the demo's stand-in and a real server are one
    setting with two values.

    No namespace. Argo CD's managed-resource route accepts selectors and this
    asks for none, exactly as the write tier's own read of the same endpoint asks
    for none: there is one deployment behind this address, and a selector
    configured in a second place is a second place to correct when it moves.
    """

    argocd_base_url: str
    argocd_resource_path: str
    argocd_auth_token: str


HttpGet = Callable[..., httpx2.Response]


class RolloutUnreadable(Exception):
    """The platform would not say what the deployment is running.

    Raised rather than answered emptily, and this is the one failure in the tier
    where that matters most. "It converged" is an answer a reader acts on - it
    rules the mode out and sends them back to the revision - so an outage
    reported as convergence would send a walk to blame a revision that is not at
    fault.
    """


class FetchLiveDeployment(Protocol):
    """How this module asks the platform what an application is running.

    A `Protocol` rather than a `Callable` alias for the reason `FetchApplication`
    is one: a test stands it in with `create_autospec`, which needs something
    introspectable. Naming an application is all this asks - where that server is
    and under what credential was decided where the process started.
    """

    def __call__(self, application: str, /) -> dict[str, Any]: ...


def fetch_live_deployment(application: str,
                          settings: RolloutReadSettings,
                          get: HttpGet = httpx2.get) -> dict[str, Any]:
    """Asks the platform for one application's running Deployment.

    Any failure to get an answer - unreachable host, error status, unreadable
    body - becomes `RolloutUnreadable`. None of them may become "it converged".
    """
    url = (
        f"{settings.argocd_base_url}"
        f"{settings.argocd_resource_path.format(application=application)}"
    )

    try:
        response = get(
            url,
            headers=_headers_for(settings.argocd_auth_token),
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
    except Exception as error:
        raise RolloutUnreadable(
            f"could not read what [{application}] is running, from [{url}]: "
            f"{error}"
        ) from error

    return body


def how_the_rollout_is_going(service: str,
                             *,
                             fetch_deployment: FetchLiveDeployment,
                             fetch: FetchApplication) -> list[str]:
    """Whether the deployment of `service` finished arriving, as lines a model
    reads.

    The service is the only subject. Which revisions are involved is found here,
    in the deployment history, rather than asked of the caller: a caller naming
    the revision it believes is going out would be naming the thing this channel
    exists to check.
    """
    manifest = _the_manifest_of(service, fetch_deployment)
    _wanted, serving, updated = _how_many_replicas(service, manifest)
    deployed = the_revisions_deployed(service, fetch=fetch)

    if updated >= serving:
        return _converged(service, serving, deployed)

    return _still_converging(service, serving, updated, manifest, deployed)


def how_far_the_rollout_has_got(service: str,
                                *,
                                fetch_deployment: FetchLiveDeployment
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
    verdict on them. `_the_manifest_of` raises, and that is left to propagate.

    Whether the rolling update is paused travels with the counts, and it is what
    gives a caller's wait an end. A rollout stopped part way satisfies neither
    count and never will, so a caller holding only those would poll until its
    lease expired. Reported and not judged, as everything here is: this says the
    platform has stopped, and how long a rollout that is merely slow may take is
    still nobody's business on this side of §16.
    """
    manifest = _the_manifest_of(service, fetch_deployment)
    wanted, serving, updated = _how_many_replicas(service, manifest)

    return RolloutProgress(
        replicas_wanted=wanted,
        replicas_serving=serving,
        replicas_updated=updated,
        is_paused=bool(manifest.get(SPEC, {}).get(PAUSED))
    )


def _the_manifest_of(service: str,
                     fetch_deployment: FetchLiveDeployment) -> dict[str, Any]:
    """The running Deployment, parsed out of the platform's wrapper.

    Refused rather than assumed where the body is not what it should be. A
    manifest this could not read is a deployment whose rollout is unknown, and
    the one answer that must never be reached by guesswork is that it converged.
    """
    resource = fetch_deployment(service)

    try:
        manifest: dict[str, Any] = json.loads(resource[MANIFEST])
    except Exception as error:
        raise RolloutUnreadable(
            f"[{service}]'s running Deployment could not be read from what the "
            f"platform answered: {error}"
        ) from error

    return manifest


def _how_many_replicas(service: str,
                       manifest: dict[str, Any]) -> tuple[int, int, int]:
    """How many replicas were asked for, how many are serving, and how many
    are on the newest revision.

    The count asked for is `spec.replicas`, and it is returned rather than
    only compared against because a scale-out is the action that writes it: a
    caller waiting for capacity to arrive needs the target as well as the
    arrivals, and reading the manifest a second time for it would be a second
    chance to disagree about what this one said.

    A manifest carrying no rollout status at all reads as converged, and that is
    a decision rather than a fallback. Nothing in it says any replica is lagging,
    so nothing is - and the alternative answers would each be worse: refusing
    would leave every deployment that is simply running with an unhelpful line,
    and assuming a split would invent an incident out of a field the platform did
    not fill in.
    """
    try:
        wanted = int(manifest[SPEC][REPLICAS])
    except Exception as error:
        raise RolloutUnreadable(
            f"[{service}]'s manifest does not say how many replicas it was told "
            f"to run: {error}"
        ) from error

    status = manifest.get(STATUS, {})

    return (
        wanted,
        int(status.get(REPLICAS, wanted)),
        int(status.get(UPDATED_REPLICAS, wanted))
    )


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
                      serving: int,
                      updated: int,
                      manifest: dict[str, Any],
                      deployed: list[ChangeEvent]) -> list[str]:
    """A deployment part way through, and the two revisions that are serving.

    Both named, because a count with one subject is a count a reader cannot use:
    what is being asked is whether two versions are running at once, and one
    revision and a number does not say what the other version is.
    """
    lagging = serving - updated
    said = [
        f"Deployment of {service} has not converged: {updated} of {serving} "
        f"replicas are running {_the_revision_going_out(deployed)}, and "
        f"{lagging} are still running {_the_revision_before_it(deployed)}."
    ]

    if manifest.get(SPEC, {}).get(PAUSED):
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


def _headers_for(auth_token: str) -> dict[str, str]:
    """No token means no header at all, as every Argo CD adapter here does."""
    return {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
