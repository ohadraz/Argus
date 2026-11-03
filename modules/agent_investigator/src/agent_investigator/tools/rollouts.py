"""The rollout channel: whether the deployment has finished arriving.

The sixth, and the third that is not a window over time. Whether a rollout
converged is a fact about the deployment running now, so there is nothing to
date, nothing to widen and no reading to record - and, like the register, nothing
for a model to name: the service is the incident's.

The one channel whose ordinary answer is itself a finding. Every scenario the
fixture stages but one answers that the deployment converged, and that is not a
blank - it rules out two revisions serving at once and leaves the revision itself
as the subject of whatever a reader concludes next.

The read tier answers with a value, and the words the model reads are written
here. They describe and do not judge: every deployment is part way through for a
minute or two, so they say what the platform reports and when the state began,
and whether that is too long is the model's to weigh against an onset this
channel has never seen.

Its silence is not evidence, so it reports rather than raises, as the register
does. A rollout nobody could read supports no conclusion either way, and the
model can still answer - at a lower confidence, or by naming the distinction it
could not draw.
"""

from __future__ import annotations

from typing import Final

from argus_core.events import Narrator, RolloutRead
from argus_core.models import ChangeEvent, RolloutAccount, ToolCall

from agent_investigator.retrieval import RolloutFetcher
from agent_investigator.tools.results import Served, answered, could_not_be_read

ROLLOUT_TOOL: Final = "get_rollout_state"


def read_the_rollout(call: ToolCall,
                     service: str,
                     fetch_rollout: RolloutFetcher,
                     narrator: Narrator) -> Served:
    """How far the deployment got, or why that could not be read.

    No reading, for the reason the register channel records none: a reading is
    what tells a later round which minutes are already in front of the model,
    and there are no minutes here. What came back is narrated all the same, as
    the value it is, so the account of the incident can say it in its own words.

    Anything at all going wrong is reported as the same fact, which is why this
    catches broadly. Across the tier boundary the platform's own failure has
    already become a transport error, so there is no useful class left to
    distinguish - and every one of them means one thing to a model: it does not
    get to find out whether the deployment converged.
    """
    try:
        account = fetch_rollout(service)
    except Exception as error:
        return could_not_be_read(
            call,
            (f"the rollout of [{service}] could not be read, so nothing here says "
             f"whether the deployment that landed reached every replica: {error}"),
            what_was_asked="how far the deployment had rolled out",
            because=str(error)
        )

    narrator.say(RolloutRead, account=account)

    return answered(call, "\n".join(_as_the_model_reads_it(service, account)))


def _as_the_model_reads_it(service: str, account: RolloutAccount) -> list[str]:
    """The rollout said for a model, a line to each fact."""
    progress = account.progress

    if progress.has_converged:
        return _converged(service, progress.replicas_serving, account.going_out)

    return _still_converging(service, account)


def _converged(service: str, serving: int, going_out: ChangeEvent | None) -> list[str]:
    """A deployment that finished arriving, said plainly.

    Said at all, rather than answered with silence, because this is evidence: a
    reader weighing a deploy at the onset has been told it is not half-applied,
    which rules one mode out and leaves the revision itself as the subject.
    """
    if going_out is None:
        return [
            f"Deployment of {service} has converged: {_every_replica(serving)} "
            f"running the same revision. The deployment history holds no "
            f"deployment at all, so nothing here names which."
        ]

    return [
        f"Deployment of {service} has converged: {_every_replica(serving)} "
        f"running revision [{going_out.reference}], deployed at "
        f"{going_out.occurred_at}."
    ]


def _every_replica(serving: int) -> str:
    """Every replica serving, agreeing in number with how many there are."""
    return "its 1 replica is" if serving == 1 else f"all {serving} replicas are"


def _still_converging(service: str, account: RolloutAccount) -> list[str]:
    """A deployment part way through, and the two revisions that are serving.

    Both named, because a count with one subject is a count a reader cannot use:
    what is being asked is whether two versions are running at once, and one
    revision and a number does not say what the other version is.
    """
    progress = account.progress
    serving = progress.replicas_serving
    updated = progress.replicas_updated
    behind = serving - updated
    said = [
        f"Deployment of {service} has not converged: {updated} of {serving} "
        f"replica{'' if serving == 1 else 's'} {'is' if updated == 1 else 'are'} "
        f"running {_the_revision_going_out(account.going_out)}, and "
        f"{behind} {'is' if behind == 1 else 'are'} still running "
        f"{_the_revision_before_it(account.before_it)}."
    ]

    # A rolling update can run more replicas than the deployment is sized for
    # while it surges. The count serving alone reads as the fleet the rollout
    # finishes with, so the size is said wherever the two differ.
    wanted = progress.replicas_wanted
    if serving != wanted:
        said.append(
            f"The deployment is sized for {wanted} replica{'' if wanted == 1 else 's'}."
        )

    if progress.is_paused:
        said.append(
            "Its rolling update is paused, so the platform is not converging it "
            "on its own."
        )

    if account.going_out is not None:
        said.append(
            f"The revision it is converging on was deployed at "
            f"{account.going_out.occurred_at}, which is when the replicas first "
            f"differed."
        )

    return said


def _the_revision_going_out(going_out: ChangeEvent | None) -> str:
    if going_out is None:
        return "a revision the deployment history does not hold"

    return f"revision [{going_out.reference}]"


def _the_revision_before_it(before_it: ChangeEvent | None) -> str:
    """What the replicas that have not updated are running.

    Said as unknown rather than left out where the history has nothing earlier. A
    reader told only about the new revision reads the split as a count with one
    subject, which is the reading this channel exists to prevent.
    """
    if before_it is None:
        return (
            "whatever preceded it - there is no earlier deployment in the "
            "history to name it by"
        )

    return f"revision [{before_it.reference}]"
