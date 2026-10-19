"""What is left to do: every action item, and what Argus declined to do and
recommends a person does instead.

Argus edits no item after the document is written, so an open item has no
owner until a person takes it on somewhere else.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.lines import Line, Role, Run

_HEADINGS: Final = ("Item", "Action", "Type", "Owner", "Tracking", "Status")


class ItemRow(BaseModel):
    """One item. `unassigned` says the owner is nobody yet, for a destination
    that marks it."""

    model_config = ConfigDict(frozen=True)

    number: str
    text: Line
    type: str
    owner: str
    tracking: Line
    status: str
    unassigned: bool = False


class ActionItemsSection(BaseModel):
    """The table, the sentence said in its place where there are no items, and
    the recommendation - each `None` where it does not apply."""

    model_config = ConfigDict(frozen=True)

    headings: tuple[str, ...]
    rows: tuple[ItemRow, ...]
    absent: str | None
    recommended: Line | None


def the_action_items(postmortem: PostmortemDocument) -> ActionItemsSection:
    """Every item in its number's order, as the agent numbered them."""
    rows = tuple(ItemRow(number=item.number,
                         text=Line(runs=(Run(text=item.text, role=Role.PROSE),)),
                         type=item.type.value,
                         owner=item.owner or "unassigned",
                         tracking=Line(runs=(_where_it_is_tracked(item.tracking, postmortem),)),
                         status=item.status.value,
                         unassigned=item.owner is None)
                 for item in postmortem.action_items)

    recommended = None
    if postmortem.recommended_action:
        recommended = Line(runs=(Run(text="Argus declined to act, and recommends: "),
                                 Run(text=postmortem.recommended_action, role=Role.PROSE)))

    return ActionItemsSection(headings=_HEADINGS,
                              rows=rows,
                              absent=None if rows else "No action items.",
                              recommended=recommended)


def _where_it_is_tracked(tracking: str | None, postmortem: PostmortemDocument) -> Run:
    """The item's tracking, said as the rest of the document says it.

    Not a guess at what an address is: the item tracking the fix is given the
    fix's own address when the document is written, so an equal address is
    that pull request, and is named as the resolution and the supporting
    information name it."""
    fix = postmortem.pull_request
    if tracking is None:
        return Run(text="-")
    if fix is not None and tracking == fix.url:
        return Run.a_pull_request(fix.number).linked_to(fix.url)
    return Run.an_address(tracking)
