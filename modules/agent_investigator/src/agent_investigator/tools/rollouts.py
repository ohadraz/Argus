"""The rollout channel: whether the deployment has finished arriving.

The sixth, and the third that is not a window over time. Whether a rollout
converged is a fact about the deployment running now, so there is nothing to
date, nothing to widen and no reading to record - and, like the register, nothing
for a model to name: the service is the incident's.

The one channel whose ordinary answer is itself a finding. Every scenario the
fixture stages but one answers that the deployment converged, and that is not a
blank - it rules out two revisions serving at once and leaves the revision itself
as the subject of whatever a reader concludes next. Said as "all but one" rather
than as a count, because a count here is a number nothing checks and the fixture
gains scenarios.

Which is exactly why an empty answer is said in words rather than passed through.
Everywhere else in the tier, nothing coming back is a gap; here the reading a
model most expects is "it converged", so emptiness left to speak for itself is
not a missing finding but the wrong one - and the wrong one sends a walk to blame
a revision that is not at fault.

Its silence is not evidence, so it reports rather than raises, as the register
does. A rollout nobody could read supports no conclusion either way, and the
model can still answer - at a lower confidence, or by naming the distinction it
could not draw.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import ToolCall, ToolDefinition

from agent_investigator.retrieval import RolloutFetcher
from agent_investigator.tools.results import Served, answered, could_not_be_read

ROLLOUT_TOOL: Final = "get_rollout_state"

_NOTHING_CAME_BACK = (
    "The read tier answered about this deployment's rollout with nothing at all, "
    "which is not an answer it gives - treat the rollout as unread rather than "
    "as finished. Nothing here says how many replicas are on which revision."
)


def rollout_tool() -> ToolDefinition:
    """The offer: find out whether the deployment that landed actually arrived."""
    return ToolDefinition(
        name=ROLLOUT_TOOL,
        description=(
            "Whether the deployment this service is running has finished "
            "arriving: how many replicas are on the revision being rolled out, "
            "how many are still on the one before it, and whether the rolling "
            "update is paused. Read this before saying a deployment at the onset "
            "is the fault - a revision that is wrong and a revision that reached "
            "only half the fleet arrive identically in the change channel, and "
            "the second fails only the requests that cross between the two "
            "versions now serving. Nothing else you can retrieve says: a deploy "
            "history records syncs that finished, and a rollout that has not "
            "finished is not in it. A deployment that has converged is an answer "
            "worth having too - it rules the split out. Takes no arguments; it "
            "answers about the service this incident is about."
        ),
        properties={},
        required=[]
    )


def read_the_rollout(call: ToolCall,
                     service: str,
                     fetch_rollout: RolloutFetcher) -> Served:
    """How far the deployment got, or why that could not be read.

    No narrator event and no reading, for the reason the register channel records
    neither: a reading is what tells a later round which minutes are already in
    front of the model, and there are no minutes here.

    Anything at all going wrong is reported as the same fact, which is why this
    catches broadly. Across the tier boundary the platform's own failure has
    already become a transport error, so there is no useful class left to
    distinguish - and every one of them means one thing to a model: it does not
    get to find out whether the deployment converged.
    """
    try:
        said = fetch_rollout(service)
    except Exception as error:
        return could_not_be_read(
            call,
            (f"the rollout of [{service}] could not be read, so nothing here says "
             f"whether the deployment that landed reached every replica: {error}"),
            what_was_asked="how far the deployment had rolled out",
            because=str(error)
        )

    if not said:
        return answered(call, _NOTHING_CAME_BACK)

    return answered(call, "\n".join(said))
