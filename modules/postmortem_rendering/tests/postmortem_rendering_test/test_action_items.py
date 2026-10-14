"""What is left to do: every action item, numbered by Argus and edited by
nobody after, and what Argus declined to do and recommends a person does.

Each case is one postmortem and what the section says.
"""

from __future__ import annotations

import pytest
from argus_core.models import ActionItem, ActionItemStatus, ActionItemType
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.action_items import ItemRow, the_action_items
from postmortem_rendering.lines import Line, Role, Run

from postmortem_rendering_test.framework.builders import a_postmortem


@pytest.mark.unit
def test_an_item_done_by_argus_is_a_row_with_its_owner_and_no_tracking() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(action_items=[
                ActionItem(number="AI-1", text="turn the flag off, per C1",
                           type=ActionItemType.MITIGATE, owner="Argus", tracking=None,
                           status=ActionItemStatus.DONE)])
        ) \
        .when(
            lambda: the_action_items(some_postmortem).rows
        ) \
        .then(
            the_answer_was((ItemRow(number="AI-1",
                                    text=Line(runs=(Run(text="turn the flag off, per C1",
                                                        role=Role.PROSE),)),
                                    type="mitigate", owner="Argus",
                                    tracking=Line(runs=(Run(text="-"),)),
                                    status="done"),)))


@pytest.mark.unit
def test_an_open_item_is_unassigned_and_linked_to_where_it_is_tracked() -> None:
    # Argus edits no item after the document is written, so an open item has
    # no owner until a person takes it on somewhere else.
    some_tracking = "https://github.com/acme/shop/pull/7"

    Scenario() \
        .given(
            some_postmortem := a_postmortem(action_items=[
                ActionItem(number="AI-2", text="review the fix", type=ActionItemType.PREVENT,
                           owner=None, tracking=some_tracking,
                           status=ActionItemStatus.OPEN)])
        ) \
        .when(
            lambda: the_action_items(some_postmortem).rows[0]
        ) \
        .then(
            the_answer_was(ItemRow(number="AI-2",
                                   text=Line(runs=(Run(text="review the fix", role=Role.PROSE),)),
                                   type="prevent", owner="unassigned",
                                   tracking=Line(runs=(Run.an_address(some_tracking),)),
                                   status="open", unassigned=True)))


@pytest.mark.unit
def test_the_table_names_its_columns() -> None:
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: the_action_items(dont_care_postmortem).headings
        ) \
        .then(
            the_answer_was(("Item", "Action", "Type", "Owner", "Tracking", "Status")))


@pytest.mark.unit
def test_no_items_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(action_items=[])
        ) \
        .when(
            lambda: the_action_items(some_postmortem).absent
        ) \
        .then(
            the_answer_was("No action items."))


@pytest.mark.unit
def test_what_argus_declined_to_do_is_recommended_to_a_person() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(recommended_action="roll io-shop back to 4c810f2")
        ) \
        .when(
            lambda: the_action_items(some_postmortem).recommended
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="Argus declined to act, and recommends: "),
                                      Run(text="roll io-shop back to 4c810f2",
                                          role=Role.PROSE)))))


@pytest.mark.unit
def test_an_incident_argus_acted_on_recommends_nothing() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(recommended_action=None)
        ) \
        .when(
            lambda: the_action_items(some_postmortem).recommended
        ) \
        .then(
            the_answer_was(None))
