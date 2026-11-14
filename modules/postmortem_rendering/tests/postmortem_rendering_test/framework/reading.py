"""What a rendered postmortem holds, read off it in the order a reader reads
it - for a case asserting that a destination says all of it, in order,
rather than a list of words copied from the builder that wrote it."""

from __future__ import annotations

from postmortem_rendering.lines import Line
from postmortem_rendering.rendering import RenderedPostmortem


def everything_held(rendered: RenderedPostmortem) -> list[str]:
    """Every value the rendered document holds, in the order a reader reads
    it - each row's cells in the order the page sets them."""
    head = rendered.head
    cause = rendered.cause
    taken = rendered.actions_taken
    items = rendered.action_items
    supporting = rendered.supporting
    said = [rendered.title.said,
            *(line.said for line in (head.incident, head.date, head.status, head.written_by,
                                     head.first_told, head.ended_by) if line is not None),
            *said_of(rendered.summary),
            *(part for card in rendered.impact.cards
              for part in (card.value, card.label, *held(card.note))),
            *held(rendered.impact.metrics_missing),
            *said_of(rendered.impact.logs_in_the_gap),
            *said_of(cause.root_cause)]
    for link in cause.chain:
        said += [link.place, link.claim.said,
                 *([cause.evidence_label] if link.evidence else []),
                 *(line.said for line in link.evidence),
                 *([cause.ruled_out_label] if link.ruled_out else [])]
        for ruled in link.ruled_out:
            said += [ruled.claim.said, *(line.said for line in ruled.evidence)]
    for factor in cause.factors:
        said += [factor.text.said, *said_of(factor.addressed_by)]
    for row in rendered.hypotheses.rows:
        said += [*row.labels, row.summary.said, row.confidence, row.result.said]
    said += [*said_of(rendered.trigger.line), *said_of(taken.person)]
    for step in [*taken.steps, *([taken.fix] if taken.fix else [])]:
        said += [*held(step.label), step.at, step.action.said, step.by, step.kind,
                 step.outcome_in_the_table]
    said += said_of(rendered.detection.line)
    if rendered.detection.said is not None:
        said += [rendered.detection.said.label, rendered.detection.said.said.said]
    for item in items.rows:
        said += [item.number, item.text.said, item.type, item.owner, item.tracking.said,
                 item.status]
    said += said_of(items.recommended)
    for lessons in rendered.lessons:
        said += [lessons.heading, *(lesson.said for lesson in lessons.items)]
    for line in rendered.timeline.rows:
        said += [*held(line.label), line.at, *held(line.marker), *held(line.who),
                 line.text.said]
    for lead in rendered.leads:
        said += [lead.label, lead.said.said, lead.weighing.said, *said_of(lead.effect)]
    said += [part for card in rendered.cost
             for part in (card.value, card.label, *held(card.note))]
    said += [line.said for line in supporting.links]
    for heading, rows in ((supporting.changes_heading, supporting.changes),
                          (supporting.log_messages_heading, supporting.log_messages),
                          (supporting.deployment_changes_heading, supporting.deployment_changes),
                          (supporting.code_read_heading, supporting.code_read),
                          (supporting.as_it_ran_heading, supporting.as_it_ran),
                          (supporting.uses_outside_heading, supporting.uses_outside),
                          (supporting.cause_measured_heading, supporting.cause_measured)):
        said += [heading, *(part for row in rows for part in (row.label, row.said.said))]
    said += [supporting.assumptions_heading,
             *(assumption.said for assumption in supporting.assumptions)]
    for check in rendered.review.rows:
        said += [check.mark, check.criterion, check.meaning, *said_of(check.because)]

    return said


def every_labelled_row(rendered: RenderedPostmortem) -> list[tuple[str, str]]:
    """Every row a label names, as that label and the row's own words."""
    supporting = rendered.supporting
    return [*((row.label, row.summary.said) for row in rendered.hypotheses.rows),
            *((step.label, step.action.said) for step in rendered.actions_taken.steps
              if step.label),
            *((item.number, item.text.said) for item in rendered.action_items.rows),
            *((line.label, line.text.said) for line in rendered.timeline.rows if line.label),
            *((lead.label, lead.said.said) for lead in rendered.leads),
            *(((rendered.detection.said.label, rendered.detection.said.said.said),)
              if rendered.detection.said else ()),
            *((row.label, row.said.said)
              for rows in (supporting.changes, supporting.log_messages,
                           supporting.deployment_changes, supporting.code_read,
                           supporting.as_it_ran, supporting.uses_outside,
                           supporting.cause_measured)
              for row in rows)]


def said_of(line: Line | None) -> list[str]:
    """A line's words, or nothing where there is no line."""
    return [line.said] if line is not None else []


def held(value: str | None) -> list[str]:
    """A value, or nothing where there is none."""
    return [value] if value else []
