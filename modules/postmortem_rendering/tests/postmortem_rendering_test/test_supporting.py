"""Where to read more: every address Argus keeps for the incident, written in
full, how much evidence was read, the changes and log messages the prose cites,
and what was assumed.

Each case is one postmortem and what the section says.
"""

from __future__ import annotations

from datetime import UTC, datetime
from operator import attrgetter

import pytest
from argus_core.models import CitedEvidence, OpenedPullRequest
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.supporting import EvidenceRow, the_supporting_information

from postmortem_rendering_test.framework.builders import (
    SOME_DEPLOYED_REVISION,
    SOME_REPOSITORY_ADDRESS,
    a_change_read,
    a_deploy_read,
    a_postmortem,
)

SOME_INCIDENT_ADDRESS = "http://argus.example/incidents/0b1c"

# When the builders' changes were made.
THE_CHANGES_MOMENT = datetime(2026, 10, 11, 14, 0, tzinfo=UTC)


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
def test_a_deploy_read_is_a_row_naming_its_revision_short_then_whole_each_a_link_to_it() -> None:
    # The prose says "the deploy P2"; this is the row that says what P2 was.
    # Its revision short first, as the prose writes it, then whole in what the
    # deploy shipped - and the revision, the repository and the directory each
    # lead to where a reader opens them.
    commit = f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"
    directory = f"{SOME_REPOSITORY_ADDRESS}/tree/{SOME_DEPLOYED_REVISION}/deploy"

    Scenario() \
        .given(
            some_postmortem := a_postmortem(changes_read=[a_deploy_read("P2")])
        ) \
        .when(
            lambda: the_supporting_information(some_postmortem, SOME_INCIDENT_ADDRESS).changes
        ) \
        .then(
            the_answer_was((EvidenceRow(label="P2", said=Line(runs=(
                Run.a_moment(THE_CHANGES_MOMENT),
                Run(text=" deploy "),
                Run(text=SOME_DEPLOYED_REVISION[:7], role=Role.LINK, address=commit),
                Run(text=" by kuki: "),
                Run(text="deployed revision "),
                Run(text=SOME_DEPLOYED_REVISION, role=Role.LINK, address=commit),
                Run(text=" from the "),
                Run(text="acme/shop", role=Role.LINK, address=SOME_REPOSITORY_ADDRESS),
                Run(text=" repository's "),
                Run(text="deploy", role=Role.LINK, address=directory),
                Run(text="/ directory")))),)))


@pytest.mark.unit
def test_each_revision_a_change_read_names_leads_where_it_opens_short_and_whole() -> None:
    # The prose names a deploy by its revision - short, as it is told to write
    # one, or whole - and a reader follows either to the commit. A flag toggle
    # has nowhere to open, so nothing it names leads anywhere.
    commit = f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"

    Scenario() \
        .given(
            some_postmortem := a_postmortem(changes_read=[a_deploy_read("P2"),
                                                          a_change_read("P1")])
        ) \
        .when(
            lambda: the_supporting_information(
                some_postmortem, SOME_INCIDENT_ADDRESS).revision_addresses
        ) \
        .then(
            the_answer_was({SOME_DEPLOYED_REVISION[:7]: commit, SOME_DEPLOYED_REVISION: commit}))


@pytest.mark.unit
def test_a_change_with_nowhere_to_open_names_what_it_changed_in_code_and_who_nobody_named() -> None:
    # A flag toggle, or a deploy from a host whose pages are not known: its
    # reference is a name, said as one, and a change no one is named for is
    # said to be, rather than shown with a blank where the name goes.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(changes_read=[a_change_read("P1",
                                                                        summary="switched on")])
        ) \
        .when(
            lambda: the_supporting_information(some_postmortem, SOME_INCIDENT_ADDRESS).changes
        ) \
        .then(
            the_answer_was((EvidenceRow(label="P1", said=Line(runs=(
                Run.a_moment(THE_CHANGES_MOMENT),
                Run(text=" flag toggle "),
                Run(text="dont-care", role=Role.CODE),
                Run(text=" by someone unnamed: "),
                Run(text="switched on")))),)))


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
def test_the_log_messages_are_headed_with_the_zone_their_times_are_in_and_the_changes_not() -> None:
    # A log message says a time as the model was shown it, so the zone is said
    # once, over them - as the timeline's is. A change's row says its moment
    # with its zone already.
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: attrgetter("changes_heading", "log_messages_heading")(
                the_supporting_information(dont_care_postmortem, SOME_INCIDENT_ADDRESS))
        ) \
        .then(
            the_answer_was(("Changes to production read", "Log messages read (UTC)")))


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
                changes_read=[a_change_read("P1")],
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
