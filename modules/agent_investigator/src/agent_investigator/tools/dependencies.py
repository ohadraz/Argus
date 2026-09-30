"""The register channel: what this service calls, and whose each of those is.

The one channel here that is not a window over time. What a service calls is a
fact about how it is built, so there is nothing to date, nothing to widen and no
reading to record - which is also why it takes no arguments at all: the service
is the incident's, exactly as it is for the change channel, and there is nothing
else for a model to name.

It is the one channel whose silence supports no conclusion either. "Nothing
changed in this window" is a finding something acts on, which is why the change
channel lets an unreachable source raise; a register nobody can reach says
nothing about the estate, and the model can still answer - at a lower confidence,
or by naming the distinction it could not make. Ending the investigation over it
would throw away everything already retrieved to avoid a gap the model is able to
report.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import ServiceDependency, ToolCall, ToolDefinition

from agent_investigator.retrieval import DependencyFetcher
from agent_investigator.tools.results import Served, answered, could_not_be_read

DEPENDENCIES_TOOL: Final = "get_service_dependencies"

_NOTHING_REGISTERED = (
    "The service register holds no dependencies for this service. As far as it "
    "knows, this service calls nothing - which is a fact about the register, and "
    "registers go out of date."
)


def dependencies_tool() -> ToolDefinition:
    """The offer: find out whose the thing on the other end of a call is."""
    return ToolDefinition(
        name=DEPENDENCIES_TOOL,
        description=(
            "What this service calls, what each of those is for, and whether the "
            "organisation owns it. Worth reading whenever the time a request "
            "spends, or the failure it reports, points at something this service "
            "does not run - because the response depends entirely on whose that "
            "something is, and nothing else you can retrieve says. A host name "
            "will not tell you: an internal-looking name is internal-looking "
            "because somebody chose the spelling. Takes no arguments; it answers "
            "about the service this incident is about."
        ),
        properties={},
        required=[]
    )


def read_dependencies(call: ToolCall,
                      service: str,
                      fetch_dependencies: DependencyFetcher) -> Served:
    """What the register says about this service, or why it could not be read.

    No narrator event and no reading. A reading is what tells a later round which
    minutes are already in front of the model, and there are no minutes here -
    one recorded for this would put a windowed retrieval in the record for a
    question that has no window, and `channels_unread` would begin reporting a
    channel that cannot be unread in the sense the other three are.

    Anything at all going wrong is reported as the same fact, which is why this
    catches broadly. Across the tier boundary the register's own exception has
    already become a transport error, so there is no useful class left to
    distinguish - and every one of them means the same thing to a model: it does
    not get to find out whose the dependency is.
    """
    try:
        dependencies = fetch_dependencies(service)
    except Exception as error:
        return could_not_be_read(
            call,
            (f"the service register could not be read, so nothing here says "
             f"whether a failing dependency belongs to this organisation: {error}"),
            what_was_asked="the service register",
            because=str(error)
        )

    if not dependencies:
        return answered(call, _NOTHING_REGISTERED)

    return answered(call, "\n".join([
        f"What {service} depends on, as the organisation's service register "
        f"records it:",
        *(_one_line_about(dependency) for dependency in dependencies)
    ]))


def _one_line_about(dependency: ServiceDependency) -> str:
    """One entry, said in the order a reader needs it.

    The name first, because that is what an action would be addressed to; then
    whose it is, because that decides whether there is an action; then the host
    and what it is for, which is how a log line gets matched to an entry.

    The ownership is said as the register said it, including a word Argus does
    not recognise. Substituting one of its own would hide the only thing that
    explains, afterwards, why a service of the organisation's own was out of
    reach - so the unrecognised case says so beside the word rather than instead
    of it.
    """
    whose = (
        dependency.ownership
        if dependency.is_recognised
        else f"{dependency.ownership} (a word this system does not recognise)"
    )

    return (
        f"- {dependency.name}: {whose}, owned by {dependency.owner}, "
        f"at {dependency.host} - {dependency.purpose}"
    )
