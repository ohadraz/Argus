"""What was done to end it: a person's resolution where there is one, every
action taken, and the fix proposed beside them.

The fix sits with the actions because the mitigation ended the symptom and the
fix is what ends the cause: a resolution without it reads as finished while the
one thing still owed sits in a list further down.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import on_the_clock
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.resolution import ReportedResolution

_HEADINGS: Final = ("Time (UTC)", "Action", "By", "Kind", "Outcome")

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
    outcome it would be said wherever the action is cited."""

    model_config = ConfigDict(frozen=True)

    label: str | None
    at: str
    action: Line
    by: str
    kind: str
    outcome: str
    sync_left_off: bool = False

    @property
    def outcome_in_the_table(self) -> str:
        """The outcome as the table's row says it."""
        return f"{self.outcome}{_SYNC_LEFT_OFF if self.sync_left_off else ''}"


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
                      resolution: ReportedResolution | None) -> ActionsTakenSection:
    """The section, with a person's resolution read off the record when the
    document is shown - it can arrive after the document was written."""
    steps = tuple(StepRow(label=step.label,
                          at=on_the_clock(step.at),
                          action=Line(runs=(Run(text=step.action),)),
                          by=step.by,
                          kind="reversible" if step.reversible else "irreversible",
                          outcome=step.outcome,
                          sync_left_off=step.sync_left_off)
                  for step in postmortem.resolution)

    fix = None
    if postmortem.pull_request is not None:
        proposed = next((entry.at for entry in postmortem.timeline if entry.who == _THE_FIXER),
                        None)
        fix = StepRow(label=None,
                      at=on_the_clock(proposed) if proposed else "-",
                      action=Line(runs=(Run(text="proposed a fix: "),
                                        Run(text=f"PR #{postmortem.pull_request.number}",
                                            role=Role.LINK,
                                            address=postmortem.pull_request.url))),
                      by=_THE_FIXER,
                      kind="needs a person to merge",
                      outcome="draft - not merged")

    return ActionsTakenSection(
        person=the_person_who_resolved(resolution) if resolution else None,
        resolved_by=resolution.by if resolution else None,
        headings=_HEADINGS,
        steps=steps,
        fix=fix,
        absent=None if steps or fix or resolution else "Nothing was done to end it.")


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
