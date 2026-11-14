"""The executive synopsis, written from the stored postmortem.

A step of its own after the postmortem, which it reads and never changes. What
the postmortem does not store - the minutes and the bands per title - is read
again through the postmortem's own sources and shown only where it agrees with
the postmortem's totals (`breakdown`). The overview is the model's, kept or
given up by its own conversation (`synopsis_conversation`).

The figures and the resolution arrive already worded, as the postmortem's page
words them and as prose says them: the page's words are not this agent's to
work out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from argus_core.llm import LLMClient
from argus_core.models import ExecutiveSynopsisDocument, PostmortemDocument, TitleCost

from agent_postmortem.assumptions import SHARED_PAGE_ASSUMPTION_LABEL
from agent_postmortem.breakdown import agreeing_breakdown
from agent_postmortem.cost_by_title import cost_by_title
from agent_postmortem.pull_requests import the_pull_request_named
from agent_postmortem.sources import EngagementAnswer, Sources
from agent_postmortem.synopsis_conversation import Overview, the_overview
from agent_postmortem.synopsis_prompting import Paging, paging_of


class Overviewing(Protocol):
    """The conversation that comes to the overview (`the_overview`)."""

    def __call__(self,
                 llm: LLMClient,
                 /,
                 *,
                 service: str,
                 symptom: str | None,
                 cause: str | None,
                 figures: Mapping[str, str],
                 said: Mapping[str, str],
                 paging: Paging,
                 disproven: bool,
                 resolution: Sequence[str],
                 judge: LLMClient | None,
                 document: str,
                 labels: frozenset[str],
                 incident_id: str) -> Overview:
        ...


def write_executive_synopsis(postmortem: PostmortemDocument,
                             *,
                             incident_id: str,
                             service: str,
                             figures: Mapping[str, str],
                             said: Mapping[str, str],
                             resolution: Sequence[str],
                             document: str,
                             labels: frozenset[str],
                             sources: Sources,
                             llm: LLMClient,
                             judge: LLMClient | None,
                             overview_of: Overviewing = the_overview
                             ) -> ExecutiveSynopsisDocument:
    """The synopsis of one written-up incident: its overview, or why there is
    none, and its human cost per title where that agrees with the postmortem.

    `figures` are as the tiles write them, which the model is shown; `said` the
    same, as prose says them, which the overview kept has written in. Any pull
    request the overview names is the record's, as in the postmortem's prose.

    `document` is the postmortem as its reader reads it, and `labels` every
    label its rows go by: what `judge` reads the overview against.
    """
    overview = overview_of(llm, service=service, symptom=postmortem.symptom,
                           cause=postmortem.cause_in_plain_words, figures=figures, said=said,
                           paging=paging_of(postmortem.paged, postmortem.responders),
                           disproven=postmortem.disproven_at is not None,
                           resolution=resolution, judge=judge, document=document,
                           labels=labels, incident_id=incident_id)
    breakdown = _the_breakdown(postmortem, incident_id, sources)

    return ExecutiveSynopsisDocument(
        overview=(the_pull_request_named(overview.text, postmortem.pull_request)
                  if overview.text is not None else None),
        withheld_because=overview.withheld_because,
        cost_by_title=breakdown if breakdown is not None else [],
        # Said only where there was a response to break down: nobody
        # responding - unpaged, or paged and unacknowledged - or nobody able to
        # say who did, is nothing left out.
        breakdown_unmatched=breakdown is None and bool(postmortem.responders),
        response_shared=_the_page_shared(postmortem)
    )


def _the_page_shared(postmortem: PostmortemDocument) -> str | None:
    """The postmortem's own line saying its on-call page also covered other
    incidents, or `None` where it did not - taken whole rather than said again,
    so the synopsis says it in the postmortem's words."""
    return next((assumption for assumption in postmortem.assumptions
                 if assumption.startswith(f"{SHARED_PAGE_ASSUMPTION_LABEL}:")), None)


def _the_breakdown(postmortem: PostmortemDocument,
                   incident_id: str,
                   sources: Sources) -> list[TitleCost] | None:
    """The response read again, by title, where it agrees with the postmortem's
    totals - or `None` where it could not be read again or does not agree."""
    engaged = sources.engagement(incident_id)
    bands = sources.bands()
    if not isinstance(engaged, EngagementAnswer) or bands is None:
        return None

    used = {bands[responder.job_title].currency for responder in engaged.engaged
            if responder.job_title is not None and responder.job_title in bands}
    # One currency or none: rows in two have no total, and agree with nothing.
    currency = next(iter(used)) if len(used) == 1 else None

    return agreeing_breakdown(cost_by_title(engaged.engaged, bands, sources.working_hours_a_year),
                              currency, postmortem)
