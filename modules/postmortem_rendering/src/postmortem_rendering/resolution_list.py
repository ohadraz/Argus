"""What was done to end it, as the executive synopsis lists it.

A person's resolution where there is one, then one line per action and what it
came to, then the draft fix, then what Argus recommends and did not do - each
read off the sections the postmortem's own page shows, so the synopsis and the
page it links to cannot say one action two ways. A list rather than prose:
every line is a fact the record holds, and the claims a model has got wrong
before ("the fix corrects it") are these.

Each line opens with who acted, as the page's By column and "Ended by" line
say it: handed a list without it, a model credited the people it was told
responded with Argus's revert. And no line names a candidate by its label,
which only the postmortem defines - copied into the overview, it names a row
the synopsis does not have.
"""

from __future__ import annotations

import re
from typing import Final

from argus_core.models import NOT_JUDGED, OpenedPullRequest, PostmortemDocument, ResolutionStep

from postmortem_rendering.action_items import the_action_items
from postmortem_rendering.actions_taken import StepRow, the_actions_taken
from postmortem_rendering.resolution import ReportedResolution

# Who proposes a fix and whose verdict an action waits on, as the synopsis's
# reader knows it: Code-Fix and Mitigation are Argus's agents, and the list
# names Argus wherever Argus acted or judged.
_ARGUS: Final = "Argus"

# A refused candidate, where its label stood in the refusal's words.
_A_SUSPECTED_CAUSE: Final = "a suspected cause"


def the_resolution_list(postmortem: PostmortemDocument,
                        resolution: ReportedResolution | None) -> tuple[str, ...]:
    """The list, or the one sentence the page says in place of the actions
    where nothing was done - and where nobody resolved it and nothing was
    recommended either."""
    taken = the_actions_taken(postmortem, resolution=None, day=None)
    recommended = the_action_items(postmortem).recommended
    # The refusal that recommends what it refused, said with the recommendation:
    # as two lines, an overview said one decision as two.
    recommending = (next((step for step in reversed(postmortem.resolution)
                          if step.refused is not None), None)
                    if postmortem.recommended_action else None)

    said = (*((_the_person_s(resolution),) if resolution is not None else ()),
            *(_the_recommending_refusal(step, postmortem.recommended_action)
              if step is recommending and postmortem.recommended_action
              else _the_line_of(step, row, resolution)
              for step, row in zip(postmortem.resolution, taken.steps, strict=True)),
            *((_the_fix_s(postmortem.pull_request, taken.fix),)
              if postmortem.pull_request is not None and taken.fix is not None else ()),
            *((recommended.said,) if recommended is not None and recommending is None else ()))

    if said or taken.absent is None:
        return said

    return (taken.absent,)


def _the_person_s(resolution: ReportedResolution) -> str:
    """Who ended it, from where, and in what words."""
    said = f"{resolution.by}: resolved it from {resolution.channel}"

    return f'{said} - "{resolution.note}"' if resolution.note else said


def _the_line_of(step: ResolutionStep,
                 row: StepRow,
                 resolution: ReportedResolution | None) -> str:
    """A row as one line: who acted, what was done, and what it came to as the
    table says it - a verdict never reached said as Argus's, and why."""
    outcome = row.outcome_in_the_table
    if step.came_to == NOT_JUDGED and outcome.startswith(NOT_JUDGED):
        why = f" ({resolution.by} resolved it first)" if resolution is not None else ""
        outcome = f"{NOT_JUDGED} by {_ARGUS}{why}{outcome[len(NOT_JUDGED):]}"

    return f"{row.by}: {_lowered(_the_action_unlabelled(step))} - {outcome}"


def _the_recommending_refusal(step: ResolutionStep, recommended: str) -> str:
    """The refusal and what it recommends instead, as one line - with no
    outcome, since "refused" says it was not taken."""
    return (f"{step.by}: {_lowered(_the_action_unlabelled(step))} - recommends: "
            f"{_lowered(recommended)}")


def _the_fix_s(pull_request: OpenedPullRequest, fix: StepRow) -> str:
    """The draft fix, proposed by Argus, and what it came to."""
    return f"{_ARGUS}: proposed a fix, {pull_request.name} - {fix.outcome_in_the_table}"


def _the_action_unlabelled(step: ResolutionStep) -> str:
    """What a step did, with no candidate's label: an action's own words carry
    none, and a refusal's name the candidate where the label stands."""
    if step.candidate is None or step.refused is None:
        return step.action

    return re.sub(rf"\b{re.escape(step.candidate)}\b", _A_SUSPECTED_CAUSE, step.action)


def _lowered(said: str) -> str:
    """A sentence's opening as it reads after who did it."""
    return said[:1].lower() + said[1:]
