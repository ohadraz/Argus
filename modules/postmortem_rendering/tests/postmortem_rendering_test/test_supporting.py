"""Where to read more: every address Argus keeps for the incident, written in
full, how much evidence was read, and what was assumed.

Each case is one postmortem and what the section says.
"""

from __future__ import annotations

import pytest
from argus_core.models import OpenedPullRequest
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.supporting import the_supporting_information

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
