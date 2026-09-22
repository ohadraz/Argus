"""The postmortem row, shaped for transport.

Nothing here is derived, judged or rounded: every field is one the Postmortem
agent wrote down, carried across unchanged. Which makes the only thing that can
go wrong a hand-written mapping of fifteen fields getting two of them crossed -
so these do not check the fields one at a time, they check the mapping.

Every figure in the built row is distinct, and distinct in the way that matters:
the three responder costs are the pair most easily swapped, and three equal
Decimals would let a swap pass. The comparison is against the row itself rather
than against literals restated here, so a field added to both sides is covered
the day it is added.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from argus_core import new_id
from argus_core.models import OpenedPullRequest, Postmortem
from argus_testkit import Assertion, Scenario
from argus_web.views.postmortems import PostmortemView, build_postmortem_view


@pytest.mark.unit
def test_every_field_the_page_shows_is_the_one_that_was_written_down() -> None:
    # A postmortem read back as a different postmortem is the one failure this
    # can have, and crossing two costs is how it would happen.
    some_postmortem = _a_postmortem_with_a_distinct_value_in_every_field()

    Scenario() \
        .given(some_postmortem) \
        .when(lambda: build_postmortem_view(some_postmortem)) \
        .then(_it_carries_every_field_of(some_postmortem))


@pytest.mark.unit
def test_a_postmortem_that_costed_nothing_comes_across_costing_nothing() -> None:
    # An incident nobody could price, or one written before the sources
    # answered. Blank has to survive as blank: a zero here would be a claim the
    # incident cost nothing, which is a different statement from not knowing.
    some_postmortem_with_nothing_costed = _a_postmortem_with_nothing_filled_in()

    Scenario() \
        .given(some_postmortem_with_nothing_costed) \
        .when(lambda: build_postmortem_view(some_postmortem_with_nothing_costed)) \
        .then(_it_carries_every_field_of(some_postmortem_with_nothing_costed))


@pytest.mark.unit
def test_the_page_is_told_where_the_proposed_fix_can_be_read() -> None:
    # The one thing on this page a reader acts on. Named explicitly rather than
    # left to the field-by-field check above, which reads the view's own fields
    # and so would pass a view that had quietly dropped this one.
    some_postmortem = _a_postmortem_with_a_distinct_value_in_every_field()

    Scenario() \
        .given(some_postmortem) \
        .when(lambda: build_postmortem_view(some_postmortem)) \
        .then(_it_proposes_the_fix_at("https://github.invalid/ohadraz/io-shop/pull/7"))


@pytest.mark.unit
def test_a_postmortem_with_no_fix_proposed_offers_the_page_nowhere_to_send_anyone() -> None:
    # The ordinary ending. A link rendered from nothing would read as a
    # proposal whose address went missing.
    some_postmortem_proposing_nothing = _a_postmortem_with_nothing_filled_in()

    Scenario() \
        .given(some_postmortem_proposing_nothing) \
        .when(lambda: build_postmortem_view(some_postmortem_proposing_nothing)) \
        .then(_it_proposes_no_fix())


def _a_postmortem_with_a_distinct_value_in_every_field() -> Postmortem:
    """One postmortem whose fields cannot be confused with one another.

    Every number differs from every other, so a mapping that read the minimum
    where it meant the maximum fails rather than agreeing with itself.
    """
    return Postmortem(
        id=new_id(),
        incident_id=new_id(),
        root_cause="the checkout fallback flag was switched off",
        customer_loss_estimate=Decimal("1234.56"),
        estimate_currency="USD",
        engineer_minutes=47,
        responders=3,
        responder_titles=["SRE", "Backend Engineer", "Engineering Manager"],
        responder_cost_estimate=Decimal("311.00"),
        responder_cost_minimum=Decimal("208.00"),
        responder_cost_maximum=Decimal("492.00"),
        responder_cost_currency="EUR",
        tokens_spent=81_402,
        assumptions=["responder pay taken from the published band"],
        executive_summary="A ramp left a fallback off and checkout failed for 47 minutes.",
        pull_request=OpenedPullRequest(
            number=7,
            url="https://github.invalid/ohadraz/io-shop/pull/7",
            branch="argus/fix-abc"
        ),
        checklist_complete=True,
        created_at=datetime(2026, 8, 30, 11, 2, tzinfo=UTC)
    )


def _it_proposes_the_fix_at(expected: str) -> Assertion[PostmortemView]:
    def assertion(view: PostmortemView) -> bool:
        proposed = view.pull_request.url if view.pull_request else None

        if proposed != expected:
            raise AssertionError(
                f"Expected the fix proposed at [{expected}], got [{proposed}].")

        return True

    return assertion


def _it_proposes_no_fix() -> Assertion[PostmortemView]:
    def assertion(view: PostmortemView) -> bool:
        if view.pull_request is not None:
            raise AssertionError(
                f"Expected no fix proposed, got [{view.pull_request}].")

        return True

    return assertion


def _a_postmortem_with_nothing_filled_in() -> Postmortem:
    """One postmortem the agent could put no figure in.

    `checklist_complete` and `created_at` are not optional and so are still
    said: the row exists, which is itself the fact that the rest is missing
    rather than unasked.
    """
    return Postmortem(
        id=new_id(),
        incident_id=new_id(),
        root_cause=None,
        customer_loss_estimate=None,
        estimate_currency=None,
        engineer_minutes=None,
        responders=None,
        responder_titles=[],
        responder_cost_estimate=None,
        responder_cost_minimum=None,
        responder_cost_maximum=None,
        responder_cost_currency=None,
        tokens_spent=None,
        assumptions=[],
        executive_summary=None,
        checklist_complete=False,
        created_at=datetime(2026, 8, 30, 11, 2, tzinfo=UTC)
    )


def _it_carries_every_field_of(postmortem: Postmortem) -> Assertion[PostmortemView]:
    """Each field of the view against the field of that name on the row.

    Read off the view rather than listed here, so a field added to both sides
    is checked without this test being touched - and reported together, because
    two fields crossed is one mistake and naming only the first of them would
    send a reader looking for half of it.
    """
    def assertion(view: PostmortemView) -> bool:
        carried = view.model_dump()
        # Both sides dumped, so a field holding a model is compared as the same
        # shape on each: a row's `OpenedPullRequest` and a view's dict of it are
        # the same value, and comparing the two directly reports every nested
        # field as wrong.
        recorded = postmortem.model_dump()
        differing = {
            name: (recorded[name], value)
            for name, value in carried.items()
            if recorded[name] != value
        }

        if differing:
            raise AssertionError(
                "the page shows something other than what was written down:\n"
                + "\n".join(
                    f"  {name}: recorded [{recorded}], shown [{shown}]"
                    for name, (recorded, shown) in sorted(differing.items())
                )
            )

        return True

    return assertion
