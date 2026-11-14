"""The postmortem as plain text: every section under its heading, in the order
a reader reads them, each line's words with nothing wrapped round them.

For a reader with no page - the grounding judge, reading an overview against
the document it was written from. Its words are the page's, worked out once
(`render`); only the markup is left out. Every label a row goes by is said
beside the row, since a reader cites a row by it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Final

from postmortem_rendering.lines import Line
from postmortem_rendering.rendering import RenderedPostmortem
from postmortem_rendering.synopsis_text import card_said

# Between the cells of a table's row.
_CELLS: Final = " | "


def as_text(rendered: RenderedPostmortem) -> str:
    """The whole document: its title, the rows above the first section, then
    each section's heading on a line of its own and what it says under it."""
    head = rendered.head
    rows = (head.incident, head.date, head.status, head.written_by,
            *((head.first_told,) if head.first_told is not None else ()), head.ended_by)

    return "\n".join([
        rendered.title.said,
        *(f"{label}: {row.said}" for label, row in zip(head.labels, rows, strict=True)),
        *(said for key, heading in rendered.headings.items()
          for said in ("", _headed(key, heading, rendered), *_SECTIONS[key](rendered)))
    ])


def _headed(key: str, heading: str, rendered: RenderedPostmortem) -> str:
    """A section's heading - the timeline's with the zone its rows' times are
    in, as the page says it once there rather than on every row."""
    return f"{heading} {rendered.timeline.zone}" if key == "timeline" else heading


def _the_summary(rendered: RenderedPostmortem) -> Iterator[str]:
    if rendered.summary is not None:
        yield rendered.summary.said
    elif rendered.summary_absent:
        yield rendered.summary_absent


def _the_impact(rendered: RenderedPostmortem) -> Iterator[str]:
    impact = rendered.impact
    yield from (card_said(card) for card in impact.cards)
    if impact.finding:
        # What the alert said is said here alone, so it is said with its label.
        yield (f"{impact.finding_label}: {impact.finding}" if impact.finding_label
               else impact.finding)
    if impact.metrics_missing:
        yield impact.metrics_missing
    if impact.logs_in_the_gap is not None:
        yield impact.logs_in_the_gap.said


def _the_cause(rendered: RenderedPostmortem) -> Iterator[str]:
    cause = rendered.cause
    if cause.root_cause is not None:
        yield cause.root_cause.said

    yield cause.chain_heading
    if cause.chain_absent:
        yield cause.chain_absent
    for link in cause.chain:
        yield f"{link.place} {link.claim.said}"
        yield from _listed(cause.evidence_label, link.evidence)
        if link.ruled_out:
            yield f"  {cause.ruled_out_label}"
            for ruled in link.ruled_out:
                yield f"    {ruled.claim.said}"
                yield from (f"      {cited.said}" for cited in ruled.evidence)

    yield cause.factors_heading
    if cause.factors_absent:
        yield cause.factors_absent
    for factor in cause.factors:
        addressed = f" {factor.addressed_by.said}" if factor.addressed_by is not None else ""
        yield f"- {factor.text.said}{addressed}"


def _listed(label: str, lines: Sequence[Line]) -> Iterator[str]:
    if lines:
        yield f"  {label}"
        yield from (f"    {line.said}" for line in lines)


def _the_hypotheses(rendered: RenderedPostmortem) -> Iterator[str]:
    hypotheses = rendered.hypotheses
    if hypotheses.absent:
        yield hypotheses.absent
        return

    yield _CELLS.join(hypotheses.headings)
    for row in hypotheses.rows:
        yield _CELLS.join((", ".join(row.labels), row.summary.said, row.confidence,
                           row.result.said))


def _the_trigger(rendered: RenderedPostmortem) -> Iterator[str]:
    trigger = rendered.trigger
    if trigger.line is not None:
        yield trigger.line.said
    elif trigger.unestablished is not None:
        yield trigger.unestablished.said
    elif trigger.absent:
        yield trigger.absent


def _the_resolution(rendered: RenderedPostmortem) -> Iterator[str]:
    taken = rendered.actions_taken
    if taken.person is not None:
        yield taken.person.said

    steps = [*taken.steps, *([taken.fix] if taken.fix else [])]
    if not steps:
        if taken.absent:
            yield taken.absent
        return

    yield _CELLS.join(taken.headings)
    for step in steps:
        yield _CELLS.join((step.label or "", step.at, step.action.said, step.by, step.kind,
                           step.outcome_in_the_table))


def _the_detection(rendered: RenderedPostmortem) -> Iterator[str]:
    detection = rendered.detection
    if detection.line is not None:
        yield detection.line.said
    elif detection.absent:
        yield detection.absent

    if detection.said is not None:
        yield detection.said_heading
        yield _CELLS.join((detection.said.label, detection.said.said.said))


def _the_action_items(rendered: RenderedPostmortem) -> Iterator[str]:
    items = rendered.action_items
    if items.absent:
        yield items.absent
    else:
        yield _CELLS.join(items.headings)
        for row in items.rows:
            yield _CELLS.join((row.number, row.text.said, row.type, row.owner,
                               row.tracking.said, row.status))

    if items.recommended is not None:
        yield items.recommended.said


def _the_lessons(rendered: RenderedPostmortem) -> Iterator[str]:
    for lessons in rendered.lessons:
        yield lessons.heading
        if lessons.absent:
            yield lessons.absent
        yield from (f"- {lesson.said}" for lesson in lessons.items)


def _the_timeline(rendered: RenderedPostmortem) -> Iterator[str]:
    timeline = rendered.timeline
    if timeline.absent:
        yield timeline.absent
        return

    for row in timeline.rows:
        who = f"{row.who} " if row.who else ""
        yield _CELLS.join((row.label or "", row.at, row.marker or "",
                           f"{who}{row.text.said}"))


def _the_leads(rendered: RenderedPostmortem) -> Iterator[str]:
    for lead in rendered.leads:
        yield f"{lead.label}: {lead.said.said}"
        yield f"  {lead.weighing.said}"
        if lead.effect is not None:
            yield f"  {lead.effect.said}"


def _the_response_effort(rendered: RenderedPostmortem) -> Iterator[str]:
    yield from (card_said(card) for card in rendered.cost)


def _the_supporting_information(rendered: RenderedPostmortem) -> Iterator[str]:
    supporting = rendered.supporting
    yield from (line.said for line in supporting.links)

    for heading, rows, absent in (
        (supporting.changes_heading, supporting.changes, supporting.changes_absent),
        (supporting.log_messages_heading, supporting.log_messages, supporting.log_messages_absent),
        (supporting.deployment_changes_heading, supporting.deployment_changes, None),
        (supporting.code_read_heading, supporting.code_read, None),
        (supporting.as_it_ran_heading, supporting.as_it_ran, None),
        (supporting.uses_outside_heading, supporting.uses_outside, None),
        (supporting.cause_measured_heading, supporting.cause_measured, None)
    ):
        if not rows and absent is None:
            continue
        yield heading
        yield from (_CELLS.join((row.label, row.said.said)) for row in rows)
        if absent:
            yield absent

    yield supporting.assumptions_heading
    if supporting.assumptions_absent:
        yield supporting.assumptions_absent
    yield from (f"- {assumption.said}" for assumption in supporting.assumptions)


def _the_review(rendered: RenderedPostmortem) -> Iterator[str]:
    review = rendered.review
    if review.absent:
        yield review.absent
    for row in review.rows:
        yield f"{row.mark} {row.criterion} ({row.meaning})"
        if row.because is not None:
            yield f"  {row.because.said}"


# How each section is said, by the key `render` names it by.
_SECTIONS: Final[dict[str, Callable[[RenderedPostmortem], Iterator[str]]]] = {
    "summary": _the_summary,
    "impact": _the_impact,
    "cause": _the_cause,
    "hypotheses": _the_hypotheses,
    "trigger": _the_trigger,
    "resolution": _the_resolution,
    "detection": _the_detection,
    "action-items": _the_action_items,
    "lessons": _the_lessons,
    "timeline": _the_timeline,
    "leads": _the_leads,
    "response-effort": _the_response_effort,
    "supporting": _the_supporting_information,
    "review": _the_review
}
