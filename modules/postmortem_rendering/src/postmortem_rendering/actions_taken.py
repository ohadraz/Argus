"""What was done to end it: a person's resolution where there is one, every
action taken, and the fix proposed beside them.

The fix sits with the actions because the mitigation ended the symptom and the
fix is what ends the cause: a resolution without it reads as finished while the
one thing still owed sits in a list further down.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Final

from argus_core import said_as_a_time
from argus_core.models import (
    PostmortemDocument,
    ResolutionStep,
    for_the_candidate,
    whether_it_can_be_put_back,
)
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import on_the_clock_of
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.resolution import ReportedResolution
from postmortem_rendering.supporting import OPENED_AS_A_DRAFT

# The first column is the label a citation of a step names, headed by nothing,
# as the hypotheses' is.
_HEADINGS: Final = ("", "Time (UTC)", "Action", "By", "Kind", "Outcome")

# Who the narration says proposed a fix, which dates the fix's row.
_THE_FIXER: Final = "Code-Fix Agent"

# Said after an action's outcome in its row, where it left automatic sync off.
_SYNC_LEFT_OFF: Final = " - automatic sync left off"


class StepRow(BaseModel):
    """One row: when, what, by whom, whether it undoes, and what it came to.
    `label` is the row's name for a citation, `None` on the fix's row.

    `outcome` is what the action came to, as a citation of it shows it;
    `sync_left_off` whether it left the platform's automatic sync off, which
    the table says beside the outcome and nothing else does - the one row is
    where whether the action still stands is explained, and said in the
    outcome it would be said wherever the action is cited. `came_to` and
    `standing` are the outcome's two halves, where the step carries them.
    """

    model_config = ConfigDict(frozen=True)

    label: str | None
    at: str
    action: Line
    by: str
    kind: str
    outcome: str
    sync_left_off: bool = False
    came_to: str | None = None
    standing: str | None = None

    @property
    def outcome_in_the_table(self) -> str:
        """The outcome as the table's row says it: whether the action still
        stands left out where the Kind beside it says it already - "nothing
        to put back" in both cells said it twice."""
        said = (self.came_to if self.came_to is not None
                and self.standing in (None, self.kind) else self.outcome)

        return f"{said}{_SYNC_LEFT_OFF if self.sync_left_off else ''}"


class ActionsTakenSection(BaseModel):
    """A person's resolution, the table, the fix's row, and the sentence said
    in place of all three where there is none - each `None` where it does not
    apply. `resolved_by` names the person on their own, for a destination that
    marks the line with them."""

    model_config = ConfigDict(frozen=True)

    person: Line | None
    resolved_by: str | None
    headings: tuple[str, ...]
    steps: tuple[StepRow, ...]
    fix: StepRow | None
    absent: str | None


def the_actions_taken(postmortem: PostmortemDocument,
                      resolution: ReportedResolution | None,
                      day: date | None) -> ActionsTakenSection:
    """The section, with a person's resolution read off the record when the
    document is shown - it can arrive after the document was written.

    Each time is said against `day`, the day the head names: alone on it, and
    with its own day on any other, since the response often runs on a later
    day than the incident began. `None` where the document names no day, and
    every time is said alone."""
    def said(at: datetime) -> str:
        return on_the_clock_of(at, day) if day is not None else said_as_a_time(at)

    steps = tuple(StepRow(label=step.label,
                          at=said(step.at),
                          action=_the_action_of(step),
                          by=step.by,
                          kind=whether_it_can_be_put_back(step.has_a_way_back,
                                                          step.left_behind_known),
                          outcome=step.outcome,
                          sync_left_off=step.sync_left_off,
                          came_to=step.came_to,
                          standing=step.standing)
                  for step in postmortem.resolution)

    fix = None
    if postmortem.pull_request is not None:
        proposed = next((entry.at for entry in postmortem.timeline if entry.who == _THE_FIXER),
                        None)
        fix = StepRow(label=None,
                      at=said(proposed) if proposed else "-",
                      action=Line(runs=(Run(text="Proposed a fix: "),
                                        Run.a_pull_request(postmortem.pull_request)
                                        .linked_to(postmortem.pull_request.url))),
                      by=_THE_FIXER,
                      # A draft changes nothing running, so - like a restart -
                      # there is nothing of it to put back: the column says of
                      # the fix what it says of every action.
                      kind=whether_it_can_be_put_back(False, left_behind_known=True),
                      outcome=OPENED_AS_A_DRAFT)

    return ActionsTakenSection(
        person=the_person_who_resolved(resolution) if resolution else None,
        resolved_by=resolution.by if resolution else None,
        headings=_HEADINGS,
        steps=steps,
        fix=fix,
        absent=None if steps or fix or resolution else _why_nothing_was_done(postmortem))


def _why_nothing_was_done(postmortem: PostmortemDocument) -> str:
    """Said in place of the section where nothing was done: of a disproven
    alarm, that nothing needed doing - "nothing was done to end it" reads as an
    incident left running."""
    if postmortem.disproven_at is not None:
        return "Nothing needed doing: the alarm was disproven."

    return "Nothing was done to end it."


def _the_action_of(step: ResolutionStep) -> Line:
    """What a step did, and the candidate it was for, citing that candidate's
    row - where the step names one. A refusal's words name it already, as its
    line does, so there it is cited where it stands rather than said twice."""
    if step.candidate is None:
        return Line(runs=(Run(text=step.action),))

    said = Run(text=step.action if step.refused is not None
               else f"{step.action} {for_the_candidate(step.candidate)}")

    return Line(runs=said.with_citations({step.candidate}))


def the_person_who_resolved(resolution: ReportedResolution) -> Line:
    """Who ended the incident, from where, when, and in what words.

    Public because an incident a person resolved before any document was
    written is shown with this line and nothing else, and it says it in the
    words the document would.
    """
    runs = [Run(text="Resolved by "),
            Run(text=resolution.by, role=Role.STRONG),
            Run(text=f" from {resolution.channel}, "),
            Run.a_moment(resolution.at)]
    if resolution.note:
        runs += [Run(text=" - "), Run(text=resolution.note, role=Role.QUOTE)]

    return Line(runs=tuple(runs))
