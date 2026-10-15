"""Where to read more: every address Argus keeps for the incident, written in
full, how much evidence was read, the changes and log messages the prose cites,
and what was assumed.

Each case is one postmortem and what the section says.
"""

from __future__ import annotations

from operator import attrgetter

import pytest
from argus_core.models import CitedEvidence, OpenedPullRequest
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.supporting import EvidenceRow, the_supporting_information

from postmortem_rendering_test.framework.builders import a_postmortem

SOME_INCIDENT_ADDRESS = "http://argus.example/incidents/0b1c"


@pytest.mark.unit
def test_the_walk_the_fix_and_the_evidence_are_listed_with_every_address_in_full() -> None:
    # Read away from the screen it came from, an address relative to nothing
    # leads nowhere.
    some_fix = OpenedPullRequest(number=7, url="https://github.com/acme/shop/pull/7",
                                 branch="dont care")

    Scenario() \
        .given(
            some_postmortem := a_postmortem(pull_request=some_fix, evidence_read=14)
        ) \
        .when(
            lambda: the_supporting_information(some_postmortem, SOME_INCIDENT_ADDRESS).links
        ) \
        .then(
            the_answer_was((
                Line(runs=(Run(text="The incident's walk: "),
                           Run.an_address(SOME_INCIDENT_ADDRESS))),
                Line(runs=(Run(text="The fix it proposed: "),
                           Run(text=f"#7 {some_fix.url}", role=Role.LINK, address=some_fix.url),
                           Run(text=" "),
                           Run(text="draft - nobody has merged it", role=Role.STATUS))),
                Line(runs=(Run(text="Evidence read: 14"),)))))


@pytest.mark.unit
def test_an_incident_with_no_fix_and_uncounted_evidence_lists_the_walk_and_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(pull_request=None, evidence_read=None)
        ) \
        .when(
            lambda: tuple(line.said for line in the_supporting_information(
                some_postmortem, SOME_INCIDENT_ADDRESS).links)
        ) \
        .then(
            the_answer_was((f"The incident's walk: {SOME_INCIDENT_ADDRESS}",
                            "Evidence read: not counted")))


@pytest.mark.unit
def test_each_change_read_is_a_row_under_the_label_the_prose_cites_it_by() -> None:
    # The prose says "the deploy P2"; this is the row that says what P2 was.
    some_change = CitedEvidence(label="P2",
                                text="2026-09-02T11:59:00Z deploy rev-2 by someone: "
                                     "switched the model")

    Scenario() \
        .given(
            some_postmortem := a_postmortem(changes_read=[some_change])
        ) \
        .when(
            lambda: the_supporting_information(some_postmortem, SOME_INCIDENT_ADDRESS).changes
        ) \
        .then(
            the_answer_was((EvidenceRow(label="P2",
                                        said=Line(runs=(Run(text=some_change.text),))),)))


@pytest.mark.unit
def test_each_log_message_read_is_a_row_under_the_label_the_prose_cites_it_by() -> None:
    some_message = CitedEvidence(label="G3fa2",
                                 text="ZeroDivisionError in monthly_average - 5 occurrences")

    Scenario() \
        .given(
            some_postmortem := a_postmortem(log_messages_read=[some_message])
        ) \
        .when(
            lambda: the_supporting_information(
                some_postmortem, SOME_INCIDENT_ADDRESS).log_messages
        ) \
        .then(
            the_answer_was((EvidenceRow(label="G3fa2",
                                        said=Line(runs=(Run(text=some_message.text),))),)))


@pytest.mark.unit
def test_the_changes_and_log_messages_are_headed_with_the_zone_their_times_are_in() -> None:
    # Their rows say a time as the model was shown it, so the zone is said
    # once, over them - as the timeline's is.
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: attrgetter("changes_heading", "log_messages_heading")(
                the_supporting_information(dont_care_postmortem, SOME_INCIDENT_ADDRESS))
        ) \
        .then(
            the_answer_was(("Changes to production read (UTC)", "Log messages read (UTC)")))


@pytest.mark.unit
def test_none_read_of_either_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(changes_read=[], log_messages_read=[])
        ) \
        .when(
            lambda: attrgetter("changes_absent", "log_messages_absent")(
                the_supporting_information(some_postmortem, SOME_INCIDENT_ADDRESS))
        ) \
        .then(
            the_answer_was(("None read.", "None read.")))


@pytest.mark.unit
def test_some_read_of_both_says_nothing_in_their_place() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                changes_read=[CitedEvidence(label="P1", text="dont care")],
                log_messages_read=[CitedEvidence(label="G3fa2", text="dont care")])
        ) \
        .when(
            lambda: attrgetter("changes_absent", "log_messages_absent")(
                the_supporting_information(some_postmortem, SOME_INCIDENT_ADDRESS))
        ) \
        .then(
            the_answer_was((None, None)))


@pytest.mark.unit
def test_each_assumption_is_a_line_of_prose() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(assumptions=["revenue per minute from the last week"])
        ) \
        .when(
            lambda: the_supporting_information(some_postmortem, SOME_INCIDENT_ADDRESS).assumptions
        ) \
        .then(
            the_answer_was((Line(runs=(Run(text="revenue per minute from the last week",
                                           role=Role.PROSE),)),)))


@pytest.mark.unit
def test_the_assumptions_are_headed() -> None:
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: the_supporting_information(
                dont_care_postmortem, SOME_INCIDENT_ADDRESS).assumptions_heading
        ) \
        .then(
            the_answer_was("Assumptions"))


@pytest.mark.unit
def test_no_assumptions_says_none() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(assumptions=[])
        ) \
        .when(
            lambda: the_supporting_information(
                some_postmortem, SOME_INCIDENT_ADDRESS).assumptions_absent
        ) \
        .then(
            the_answer_was("None."))
