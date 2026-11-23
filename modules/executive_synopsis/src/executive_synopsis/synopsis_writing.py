"""The executive synopsis, written from the stored postmortem.

A step of its own after the postmortem, which it reads and never changes. The
response arrives already priced from the postmortem's minutes by title
(`synopsis_pricing`), since the figures the overview may name include its
cost. The overview is the model's, kept or given up by its own conversation
(`synopsis_conversation`).

The figures and the resolution arrive already worded, as the postmortem's page
words them and as prose says them: the page's words are not the Postmortem Writer's to
work out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from core.llm import LLMClient
from core.models import ExecutiveSynopsisDocument, PostmortemDocument, PricedResponse
from postmortem_writing import SHARED_PAGE_ASSUMPTION_LABEL, the_pull_request_named

from executive_synopsis.synopsis_conversation import Overview, the_overview
from executive_synopsis.synopsis_prompting import Paging, paging_of


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
                 incident_id: str,
                 outage_ends_it: bool = False) -> Overview:
        ...


def write_executive_synopsis(postmortem: PostmortemDocument,
                             *,
                             incident_id: str,
                             service: str,
                             cost: PricedResponse,
                             figures: Mapping[str, str],
                             said: Mapping[str, str],
                             resolution: Sequence[str],
                             document: str,
                             labels: frozenset[str],
                             llm: LLMClient,
                             judge: LLMClient | None,
                             outage_ends_it: bool = False,
                             overview_of: Overviewing = the_overview
                             ) -> ExecutiveSynopsisDocument:
    """The synopsis of one written-up incident: its overview, or why there is
    none, beside what the response cost (`cost`, `the_response_priced`).

    `figures` are as the tiles write them, which the model is shown; `said` the
    same, as prose says them, which the overview kept has written in. Any pull
    request the overview names is the record's, as in the postmortem's prose.

    `document` is the postmortem as its reader reads it, and `labels` every
    label its rows go by: what `judge` reads the overview against.
    `outage_ends_it` is whether a model that cannot be reached gives the
    overview up, as on a run's last try, rather than failing the run.
    """
    overview = overview_of(llm, service=service, symptom=postmortem.symptom,
                           cause=postmortem.cause_in_plain_words, figures=figures, said=said,
                           paging=paging_of(postmortem.paged, postmortem.responders),
                           disproven=postmortem.disproven_at is not None,
                           resolution=resolution, judge=judge, document=document,
                           labels=labels, incident_id=incident_id,
                           outage_ends_it=outage_ends_it)

    return ExecutiveSynopsisDocument(
        **cost.model_dump(),
        overview=(the_pull_request_named(overview.text, postmortem.pull_request)
                  if overview.text is not None else None),
        withheld_because=overview.withheld_because,
        response_shared=_the_page_shared(postmortem)
    )


def _the_page_shared(postmortem: PostmortemDocument) -> str | None:
    """The postmortem's own line saying its on-call page also covered other
    incidents, or `None` where it did not - taken whole rather than said again,
    so the synopsis says it in the postmortem's words."""
    return next((assumption for assumption in postmortem.assumptions
                 if assumption.startswith(f"{SHARED_PAGE_ASSUMPTION_LABEL}:")), None)
