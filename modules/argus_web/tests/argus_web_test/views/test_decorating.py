from __future__ import annotations

import pytest
from argus_core.events import ActionTaken, OnsetDetected, StatusChanged, VerdictReached
from argus_core.ids import new_id
from argus_core.models.action import Verdict
from argus_core.models.incident_status import IncidentStatus
from argus_narration import NarrationLine, a_narration_line
from argus_testkit import Assertion, Scenario, all_of
from argus_web.views.decorating import DecoratedLine, decorated

"""How the page dresses a line it was given, and what it points that line at.

The account is the same wherever it is read; only the page has a stylesheet and
anchors. So the narration says what happened and which minute a line is about,
and the two things that exist because this is a web page - the class on the
marked word and the link beside it - are worked out here, from the line.

Derived rather than carried, which is what keeps the renderer shared: a Slack
message wants neither of these, and a renderer that produced them anyway would
be making every destination pay for the page's furniture.
"""

SOME_MINUTE = "2026-08-30T10:03:00Z"
SOME_FLAG = "monthly-spend-feature"


@pytest.mark.unit
def test_a_status_line_wears_the_badge_the_header_wears() -> None:
    # The same green for `resolved` in both places. The class comes off the
    # status the line already marks, so the two cannot drift apart.
    Scenario() \
        .given(
            the_incident_resolving := a_narration_line(
                StatusChanged(incident_id=new_id(), to_status=IncidentStatus.RESOLVED)
            )
        ) \
        .when(lambda: decorated(the_incident_resolving)) \
        .then(_it_is_dressed_as(f"moved-to {IncidentStatus.RESOLVED}"))


@pytest.mark.unit
def test_a_verdict_line_is_dressed_as_the_verdict_it_reached() -> None:
    # Red or green, and the page's own business: what the verdict was is the
    # account's, how it is coloured is not.
    some_verdict = Verdict.CONFIRMED

    Scenario() \
        .given(
            the_verdict := a_narration_line(
                VerdictReached(incident_id=new_id(), hypothesis_id=None, outcome=some_verdict)
            )
        ) \
        .when(lambda: decorated(the_verdict)) \
        .then(_it_is_dressed_as(f"verdict {some_verdict}"))


@pytest.mark.unit
def test_a_line_with_nothing_marked_is_dressed_as_nothing() -> None:
    # Most lines. A class on a line with no marked word would be a span around
    # the whole sentence, which is a paragraph wearing a badge.
    Scenario() \
        .given(
            a_plain_line := a_narration_line(
                OnsetDetected(incident_id=new_id(), onset=SOME_MINUTE)
            )
        ) \
        .when(lambda: decorated(a_plain_line)) \
        .then(_it_is_dressed_as(""))


@pytest.mark.unit
def test_the_onset_line_points_at_the_minute_it_named() -> None:
    # It names one minute out of ninety, and finding that minute by hand is the
    # work the link saves.
    Scenario() \
        .given(
            the_onset := a_narration_line(
                OnsetDetected(incident_id=new_id(), onset=SOME_MINUTE)
            )
        ) \
        .when(lambda: decorated(the_onset)) \
        .then(_it_points_at(f"#minute-{SOME_MINUTE}", "show the minute"))


@pytest.mark.unit
def test_an_action_line_points_at_the_change_it_reverted() -> None:
    # The action names one flag, so it can point at that flag's own row.
    Scenario() \
        .given(
            the_action := a_narration_line(
                ActionTaken(
                    incident_id=new_id(),
                    hypothesis_id=new_id(),
                    action_type="revert-feature-flag",
                    subject=SOME_FLAG,
                    enabled=False
                )
            )
        ) \
        .when(lambda: decorated(the_action)) \
        .then(_it_points_at(f"#flag-{SOME_FLAG}", "the change it reverted"))


@pytest.mark.unit
def test_a_line_that_read_a_channel_points_at_nothing() -> None:
    # "Show the metrics" beside a line that just said it read the metrics takes
    # a reader to a table they were going to scroll to anyway. It looks like
    # help and is furniture, so there is none.
    Scenario() \
        .given(
            the_verdict := a_narration_line(
                VerdictReached(incident_id=new_id(), hypothesis_id=None, outcome=Verdict.CONFIRMED)
            )
        ) \
        .when(lambda: decorated(the_verdict)) \
        .then(_it_points_at("", ""))


@pytest.mark.unit
def test_everything_the_line_already_said_is_still_said() -> None:
    # Dressing a line adds to it and changes nothing: the page shows the same
    # sentence, split the same way, as every other destination.
    Scenario() \
        .given(
            the_action := a_narration_line(
                ActionTaken(
                    incident_id=new_id(),
                    hypothesis_id=new_id(),
                    action_type="revert-feature-flag",
                    subject=SOME_FLAG,
                    enabled=False
                )
            )
        ) \
        .when(lambda: decorated(the_action)) \
        .then(all_of(_it_still_reads_as(the_action), _it_still_marks(the_action)))


def _it_is_dressed_as(expected: str) -> Assertion[DecoratedLine]:
    def assertion(line: DecoratedLine) -> bool:
        if line.emphasis_class != expected:
            raise AssertionError(
                f"expected it dressed as [{expected}], got [{line.emphasis_class}]"
            )

        return True

    return assertion


def _it_points_at(target: str, label: str) -> Assertion[DecoratedLine]:
    def assertion(line: DecoratedLine) -> bool:
        if (line.link_target, line.link_label) != (target, label):
            raise AssertionError(
                f"expected a link to [{target}] reading [{label}], got "
                f"[{line.link_target}] reading [{line.link_label}]"
            )

        return True

    return assertion


def _it_still_reads_as(undressed: NarrationLine) -> Assertion[DecoratedLine]:
    def assertion(line: DecoratedLine) -> bool:
        if (line.who, line.text, line.kind) != (undressed.who, undressed.text, undressed.kind):
            raise AssertionError(
                f"expected [{undressed.who}: {undressed.text}], "
                f"got [{line.who}: {line.text}]"
            )

        return True

    return assertion


def _it_still_marks(undressed: NarrationLine) -> Assertion[DecoratedLine]:
    def assertion(line: DecoratedLine) -> bool:
        split = (line.before_emphasis, line.emphasis, line.after_emphasis)
        was = (undressed.before_emphasis, undressed.emphasis, undressed.after_emphasis)

        if split != was:
            raise AssertionError(f"expected the split {was}, got {split}")

        return True

    return assertion
