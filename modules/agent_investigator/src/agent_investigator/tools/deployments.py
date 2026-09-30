"""The deployment channel: what one deployment changed.

The fifth, and the second that is not a window over time. What a deployment
changed is a fact about one commit, so there is nothing to date, nothing to widen
and no reading to record - but unlike the register it takes an argument, because
there is more than one deployment and which one is being asked about is the
model's to name.

The one channel that composes with another. The change channel says a deployment
happened and hands over its revision; this says what was in it. So its
description names where the revision comes from: a model that has just read the
change channel already holds everything this needs, and a model that has not
should read that first.

Its silence is not evidence, so it reports rather than raises. The change channel
raises when it cannot be read, because "nothing changed in this window" is a
conclusion something acts on and a source never read must not arrive looking like
one read and found empty. A comparison nobody could make supports no conclusion
about the deployment either way, and the model can still answer - at a lower
confidence, or by naming the distinction it could not draw. Ending the
investigation over it would throw away everything already retrieved to avoid a
gap the model is able to report.
"""

from __future__ import annotations

from typing import Any, Final

from argus_core.models import ToolCall, ToolDefinition

from agent_investigator.retrieval import DeploymentDiffFetcher
from agent_investigator.tools.results import Served, answered, could_not_be_read, could_not_serve

DEPLOYMENT_DIFF_TOOL: Final = "get_what_a_deployment_changed"

# The one argument, named once because the schema offers it and the code below
# reads it back - and those two agreeing is the whole point of offering a strict
# schema.
REVISION_ARG: Final = "revision"

_STRING_TYPE: Final = "string"

_NOTHING_CAME_BACK = (
    "The read tier answered about this deployment with nothing at all, which is "
    "not an answer it gives - treat what this deployment changed as unread rather "
    "than as empty."
)


def deployment_diff_tool() -> ToolDefinition:
    """The offer: find out whether a deployment shipped code or configuration."""
    return ToolDefinition(
        name=DEPLOYMENT_DIFF_TOOL,
        description=(
            "What one deployment changed: the files that differ from the revision "
            "deployed before it, and the change made to each. Read this before "
            "saying which of two causes a deployment was - a deployment that "
            "shipped bad code and one that shipped a broken configuration value "
            "arrive identically, move the same signals, and are put right the same "
            "way, and the only thing that separates them is what was in the "
            "commit. Nothing else you can retrieve says: the path a deployment "
            "syncs from is where its manifests live, and is the same directory "
            "whatever the commit touched. Takes the deploy's own revision, exactly "
            "as get_changes reported it."
        ),
        properties={
            REVISION_ARG: {
                "type": _STRING_TYPE,
                "description": (
                    "The deployment's revision, copied from the change this asks "
                    "about. What it is compared against is not yours to name - the "
                    "revision deployed before it is in the deployment history, "
                    "which you cannot see."
                )
            }
        },
        required=[REVISION_ARG]
    )


def read_what_a_deployment_changed(
    call: ToolCall,
    service: str,
    fetch_what_a_deployment_changed: DeploymentDiffFetcher
) -> Served:
    """What the deployment the model named changed, or why that could not be read.

    No narrator event and no reading, for the reason the register channel records
    neither: a reading is what tells a later round which minutes are already in
    front of the model, and there are no minutes here.

    Anything at all going wrong is reported as the same fact, which is why this
    catches broadly. Across the tier boundary the repository's own failure has
    already become a transport error, so there is no useful class left to
    distinguish - and every one of them means one thing to a model: it does not
    get to find out what this deployment changed.
    """
    revision = _the_revision_named_in(call)

    if not revision:
        return could_not_serve(call, (
            f"that call named no {REVISION_ARG}, so there is no deployment to read "
            f"about. Call it again with the revision of the deployment you mean, "
            f"as the change channel reported it."
        ))

    try:
        said = fetch_what_a_deployment_changed(service, revision)
    except Exception as error:
        return could_not_be_read(
            call,
            (f"what the deployment of [{revision}] changed could not be read, so "
             f"nothing here says whether it shipped source code or a configuration "
             f"value: {error}"),
            what_was_asked=f"what the deployment of [{revision}] changed",
            because=str(error)
        )

    if not said:
        return answered(call, _NOTHING_CAME_BACK)

    return answered(call, "\n".join(said))


def _the_revision_named_in(call: ToolCall) -> str:
    """The revision the model asked about, as text, or empty if it named none.

    Read defensively although the schema is strict. A blank string and a missing
    key mean the same thing here - there is no deployment to ask about - and both
    are cheaper to refuse in a sentence than to send to the read tier, which would
    spend a request to answer about nothing.
    """
    named: Any = call.arguments.get(REVISION_ARG)

    return named.strip() if isinstance(named, str) else ""
