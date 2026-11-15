"""What the model is asked for the executive synopsis's overview, and the one
shape its answer may take.

Asked after the postmortem is finished, of the finished postmortem - its
figures as the page writes them, what a reader saw, the cause in plain words,
and what was done - so the overview says the same incident the document does,
in words for the people who lead rather than the people who responded.

Every figure goes by name, and code writes it in (`figure_rules` refuses one the
prose writes itself). Pay goes by name alone, never by amount: the request
reaches the model's provider and its recording is committed, and the model
needs only where the figure goes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Final

from argus_core.models import Ask, Effort, ModelPolicy, ToolDefinition, Transcript

OVERVIEW_TOOL_NAME: Final = "submit_executive_overview"
OVERVIEW_FIELD: Final = "overview"

# The figures an overview has to name wherever the record holds them: how long
# it lasted, what it cost the business, and what it cost the people who
# responded - in the order a reader asks.
_REQUIRED: Final = ("duration", "customer_loss", "responder_cost")

# Figures shown by name and never by amount.
_PAY: Final = frozenset({"responder_cost"})

# What each figure is, as the ask says it before the figure and its name.
_SAID_AS: Final = {
    "duration": "How long it lasted",
    "peak_error_rate": "Requests failing at the worst minute",
    # Whose estimate: "(estimated)" alone, 4 overviews in 10 said "We estimate".
    "customer_loss": "What it cost the shop in takings (estimated by Argus)",
    "responders": "People who responded",
    "engineer_minutes": "Their time, added together",
    "responder_cost": "What their time cost"
}

NO_SIZE_IN_WORDS: Final = (
    "Write no figure yourself - not in digits, not spelled out, and not as a word "
    "that sizes it (\"a brief outage\", \"a minor loss\", \"tripled\"). Where a figure "
    "goes, write its name, braces and all, and the synopsis writes the figure in."
)

NOTHING_BEYOND_THE_LIST: Final = (
    "Say nothing about how the incident was resolved beyond what the list of what "
    "was done says: a draft fix has not run, and nothing it would do has happened."
)

SPEAK_OF_ARGUS_BY_NAME: Final = (
    "Speak of Argus by name, never as \"we\", \"our\" or \"us\": Argus is the system "
    "that responded, and each line of what was done says who did it."
)

# Barred from sizing words, a model dropped "many" and said "shoppers" - every
# one of them - where the cause says which. And where the cause does not say
# which, a model left with no word for "some" said everyone who tried.
WHICH_ONES_WERE_AFFECTED: Final = (
    "Where you say who was affected, say which ones, as the cause does, or that some "
    "were, where it does not say which - never how many, and never all of them, where "
    "the cause does not say all."
)


class Paging(StrEnum):
    """Why the response has figures or has none: somebody answered a page;
    nobody was paged; a page went out and nobody acknowledged it; or nobody
    can say."""

    ANSWERED = "answered"
    NOT_PAGED = "not-paged"
    UNACKNOWLEDGED = "unacknowledged"
    NOT_KNOWN = "not-known"


# Said among the figures in place of the response's, where nobody responded:
# asked what the incident cost the people who responded, the model has nothing
# true to say it from otherwise - and a page nobody acknowledged is no page
# never sent. Nobody paged goes with the record's reason, in the postmortem
# ask's words: given none, a model beside a disproven alarm's line put it down
# to nothing having broken, and hid the gap the postmortem says went wrong.
_SAID_IN_PLACE_OF_THE_RESPONSE: Final = {
    Paging.NOT_PAGED: "- Nobody was paged: no on-call incident was linked to this one.",
    Paging.UNACKNOWLEDGED: "- Somebody was paged, and nobody acknowledged the page."
}

# Said first among the figures where the alarm was disproven: asked how long it
# lasted and handed no duration, a model said the record did not say how long
# the alarm stayed active - beside a synopsis saying when it was raised and
# when it was disproven.
NOTHING_LASTED: Final = (
    "- Nothing broke: the alarm was disproven, so there was no failure to time."
)

LIKELY_ONLY_WHERE_THE_CAUSE_SAYS: Final = (
    "Keep \"likely\" on what the cause says is likely, and only there."
)

SUBMIT_EXECUTIVE_OVERVIEW: Final = ToolDefinition(
    name=OVERVIEW_TOOL_NAME,
    description=(
        "Submit the overview of the executive synopsis: one short paragraph in plain "
        "words, naming figures rather than writing them."
    ),
    properties={OVERVIEW_FIELD: {"type": "string"}},
    required=[OVERVIEW_FIELD]
)


def synopsis_policy(model: str, effort: Effort) -> ModelPolicy:
    """The overview's model at the deployment's choice of model and effort, for
    one tool call per turn, and under no brief: everything it needs is in its
    one message, and the postmortem's brief asks for a tool it is not offered."""
    return ModelPolicy(model=model, effort=effort, one_tool_call_per_turn=True)


def paging_of(paged: bool | None, responders: int | None) -> Paging:
    """Why the response has figures or none, read off whether a page went out
    and how many answered it - the count alone is nobody both for a page
    nobody acknowledged and for no page."""
    if responders:
        return Paging.ANSWERED
    if responders == 0 and paged is False:
        return Paging.NOT_PAGED
    if responders == 0 and paged is True:
        return Paging.UNACKNOWLEDGED

    return Paging.NOT_KNOWN


def required_figures(figures: Mapping[str, str]) -> tuple[str, ...]:
    """The figures the overview has to name: each required one the record
    holds."""
    return tuple(name for name in _REQUIRED if name in figures)


def overview_ask(service: str,
                 symptom: str | None,
                 cause: str | None,
                 figures: Mapping[str, str],
                 paging: Paging,
                 disproven: bool,
                 resolution: Sequence[str]) -> Transcript:
    """The finished incident in one message, and what the overview must and
    must not say - with why nobody responded, where that is known, and why
    nothing lasted, where the alarm was disproven."""
    in_place_of_the_response = _SAID_IN_PLACE_OF_THE_RESPONSE.get(paging)
    required = required_figures(figures)

    return [Ask(text="\n".join([
        f"Write the overview of the executive synopsis for the incident on {service} "
        f"below: a short paragraph in plain words, for the people who lead the "
        f"company rather than the engineers who responded - what happened, how long "
        f"it lasted, what it cost the business and the people who responded, and "
        f"how it was resolved.",
        "",
        *([f"What a reader saw: {symptom}"] if symptom else []),
        *([f"Why, in plain words: {cause}"] if cause else []),
        "",
        "Figures:",
        *([NOTHING_LASTED] if disproven else []),
        *(_a_figure(name, written) for name, written in figures.items()),
        *([in_place_of_the_response] if in_place_of_the_response else []),
        "",
        "What was done to end it:",
        *(f"- {line}" for line in resolution),
        "",
        *([f"Name {_listed(required)} in your overview."] if required else []),
        NO_SIZE_IN_WORDS,
        NOTHING_BEYOND_THE_LIST,
        SPEAK_OF_ARGUS_BY_NAME,
        WHICH_ONES_WERE_AFFECTED,
        LIKELY_ONLY_WHERE_THE_CAUSE_SAYS,
        "",
        f"Call {OVERVIEW_TOOL_NAME} with your overview."
    ]))]


def _a_figure(name: str, written: str) -> str:
    """One figure's line: what it is, the figure and its name - or its name
    alone, for pay."""
    said = _SAID_AS.get(name, name)
    if name in _PAY:
        return f"- {said}: {{{name}}} (its amount is not shown to you; name it where it goes)"

    return f"- {said}: {written} {{{name}}}"


def _listed(names: Sequence[str]) -> str:
    """Names in braces, joined as a sentence joins them."""
    braced = [f"{{{name}}}" for name in names]

    return braced[0] if len(braced) == 1 else f"{', '.join(braced[:-1])} and {braced[-1]}"
