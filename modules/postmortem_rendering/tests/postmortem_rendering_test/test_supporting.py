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
def test_the_walk_and_the_fix_are_listed_with_every_address_in_full() -> None:
    # Read away from the screen it came from, an address relative to nothing
    # leads nowhere. The fix is named as everywhere else in the document, and
    # this is the one place its address is written out - the address the link,
    # and the name its caption.
    some_fix = OpenedPullRequest(number=7, url="https://github.com/acme/shop/pull/7",
                                 branch="dont care")

    Scenario() \
        .given(
            some_postmortem := a_postmortem(pull_request=some_fix)
        ) \
        .when(
            lambda: the_supporting_information(some_postmortem, SOME_INCIDENT_ADDRESS).links
        ) \
        .then(
            the_answer_was((
                Line(runs=(Run(text="The incident's walk: "),
                           Run.an_address(SOME_INCIDENT_ADDRESS))),
                Line(runs=(Run(text="The fix it proposed: "),
                           Run(text="PR #7"),
                           Run(text=" ("),
                           Run.an_address(some_fix.url),
                           Run(text=") "),
                           Run(text="draft - nobody has merged it", role=Role.STATUS))))))


@pytest.mark.unit
def test_an_incident_with_no_fix_lists_the_walk_alone() -> None:
    # No count of the evidence the writer was shown: it is a number of labels
    # in a prompt, and tells a reader nothing they can act on.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(pull_request=None)
        ) \
        .when(
            lambda: tuple(line.said for line in the_supporting_information(
                some_postmortem, SOME_INCIDENT_ADDRESS).links)
        ) \
        .then(
            the_answer_was((f"The incident's walk: {SOME_INCIDENT_ADDRESS}",)))


@pytest.mark.unit
def test_a_deploy_read_is_a_row_naming_its_revision_short_each_time_a_link_to_it() -> None:
    # The prose says "the deploy P2"; this is the row that says what P2 was.
    # Its revision named once, short, as the prose writes it - the read tier's
    # words name it again, and one revision said twice in a row reads as two -
    # and the revision, the repository and the directory each lead to where a
    # reader opens them.
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
                Run(text="from the "),
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
def test_what_each_deployment_changed_is_a_row_of_its_lines_its_revisions_leading_to_them() -> None:
    # The prose says "as D1 shows"; this is the row that shows it - every line
    # as the model read it, and each revision a change read names said short,
    # as the change's own row says it, and leading to its commit.
    commit = f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"
    some_diff = CitedEvidence(
        label="D1",
        text=(f"Deployment of revision some-revision to io-shop, compared against "
              f"{SOME_DEPLOYED_REVISION} - the revision deployed before it.\n"
              f"modified deploy/values-production.yaml\n"
              f"  -  model: v1\n"
              f"  +  model: v2"))

    Scenario() \
        .given(
            some_postmortem := a_postmortem(changes_read=[a_deploy_read("P1")],
                                            deployment_changes_read=[some_diff])
        ) \
        .when(
            lambda: the_supporting_information(
                some_postmortem, SOME_INCIDENT_ADDRESS).deployment_changes
        ) \
        .then(
            the_answer_was((EvidenceRow(label="D1", said=Line(runs=(
                Run(text="Deployment of revision some-revision to io-shop, compared against "),
                Run(text=SOME_DEPLOYED_REVISION[:7], role=Role.LINK, address=commit),
                Run(text=" - the revision deployed before it.\n"
                         "modified deploy/values-production.yaml\n"
                         "  -  model: v1\n"
                         "  +  model: v2")))),)))


@pytest.mark.unit
def test_the_revision_a_deploy_was_compared_against_is_said_short_and_leads_to_its_commit() -> None:
    # No change read is the deploy before, so no row gives its forms - but it
    # is a commit of the deploy's own repository, which opens it where it opens
    # the deploy's, but for the revision.
    some_earlier_revision = "f061a97b221b57258899d4b3d82998815008d7bf"
    some_diff = CitedEvidence(
        label="D1",
        text=(f"Deployment of revision {SOME_DEPLOYED_REVISION} to io-shop, compared against "
              f"{some_earlier_revision} - the revision deployed before it.\n"
              f"modified deploy/values-production.yaml"))

    Scenario() \
        .given(
            some_postmortem := a_postmortem(changes_read=[a_deploy_read("P1")],
                                            deployment_changes_read=[some_diff])
        ) \
        .when(
            lambda: the_supporting_information(
                some_postmortem, SOME_INCIDENT_ADDRESS).deployment_changes[0].said
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text="Deployment of revision "),
                Run(text=SOME_DEPLOYED_REVISION[:7], role=Role.LINK,
                    address=f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"),
                Run(text=" to io-shop, compared against "),
                Run(text=some_earlier_revision[:7], role=Role.LINK,
                    address=f"{SOME_REPOSITORY_ADDRESS}/commit/{some_earlier_revision}"),
                Run(text=" - the revision deployed before it.\n"
                         "modified deploy/values-production.yaml")))))


@pytest.mark.unit
def test_a_compared_against_revision_whose_address_cannot_be_told_stays_whole() -> None:
    # Where the deploy's own address does not hold its revision, there is no
    # address to put the other in - and a link to the deploy's commit under
    # the other's name would lead somewhere else without saying so.
    some_earlier_revision = "f061a97b221b57258899d4b3d82998815008d7bf"
    some_deploy = a_deploy_read("P1")
    assert some_deploy.change.revision_source is not None
    some_deploy_opened_by_number = some_deploy.model_copy(update={
        "change": some_deploy.change.model_copy(update={
            "revision_source": some_deploy.change.revision_source.model_copy(update={
                "revision_address": "https://git.example/changes/42"})})})
    some_diff = CitedEvidence(label="D1",
                              text=f"Deployment of revision {SOME_DEPLOYED_REVISION}, "
                                   f"compared against {some_earlier_revision}.")

    Scenario() \
        .given(
            some_postmortem := a_postmortem(changes_read=[some_deploy_opened_by_number],
                                            deployment_changes_read=[some_diff])
        ) \
        .when(
            lambda: the_supporting_information(
                some_postmortem, SOME_INCIDENT_ADDRESS).deployment_changes[0].said
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text="Deployment of revision "),
                Run(text=SOME_DEPLOYED_REVISION[:7], role=Role.LINK,
                    address="https://git.example/changes/42"),
                Run(text=f", compared against {some_earlier_revision}."),))))


@pytest.mark.unit
def test_a_revision_a_diff_line_quotes_is_kept_as_the_file_says_it() -> None:
    # A patch line is the file's own content - an image tag pinned to the
    # commit is common - and said short it would misquote the file. Only
    # Argus's own lines say a revision short; both still lead to the commit.
    commit = f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"
    some_diff = CitedEvidence(
        label="D1",
        text=(f"Deployment of revision {SOME_DEPLOYED_REVISION} to io-shop.\n"
              f"  +  tag: {SOME_DEPLOYED_REVISION}"))

    Scenario() \
        .given(
            some_postmortem := a_postmortem(changes_read=[a_deploy_read("P1")],
                                            deployment_changes_read=[some_diff])
        ) \
        .when(
            lambda: the_supporting_information(
                some_postmortem, SOME_INCIDENT_ADDRESS).deployment_changes
        ) \
        .then(
            the_answer_was((EvidenceRow(label="D1", said=Line(runs=(
                Run(text="Deployment of revision "),
                Run(text=SOME_DEPLOYED_REVISION[:7], role=Role.LINK, address=commit),
                Run(text=" to io-shop.\n  +  tag: "),
                Run(text=SOME_DEPLOYED_REVISION, role=Role.LINK, address=commit)))),)))


@pytest.mark.unit
def test_what_each_deployment_changed_is_headed_as_what_was_looked_into() -> None:
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: the_supporting_information(
                dont_care_postmortem, SOME_INCIDENT_ADDRESS).deployment_changes_heading
        ) \
        .then(
            the_answer_was("What each deployment looked into changed"))


@pytest.mark.unit
def test_an_incident_that_looked_into_no_deployment_has_no_row_for_one() -> None:
    # Nothing in its place either: most incidents look into no deployment, and
    # "none read" under a heading for them would say a read was missed.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(deployment_changes_read=[])
        ) \
        .when(
            lambda: the_supporting_information(
                some_postmortem, SOME_INCIDENT_ADDRESS).deployment_changes
        ) \
        .then(
            the_answer_was(()))


@pytest.mark.unit
def test_what_code_fix_read_in_the_source_is_a_row_under_its_label() -> None:
    some_reading = CitedEvidence(label="F1", text="the categoriser does not lowercase")

    Scenario() \
        .given(
            some_postmortem := a_postmortem(code_read=[some_reading])
        ) \
        .when(
            lambda: the_supporting_information(some_postmortem, SOME_INCIDENT_ADDRESS).code_read
        ) \
        .then(
            the_answer_was((EvidenceRow(label="F1",
                                        said=Line(runs=(Run(text=some_reading.text),))),)))


@pytest.mark.unit
def test_what_code_fix_read_sets_the_code_it_quotes_apart_without_its_backticks() -> None:
    # Code-Fix writes Markdown, and a backtick printed is a mark nobody reading
    # the page or the paper was meant to see.
    some_reading = CitedEvidence(label="F1",
                                 text="v2 sets `lowercases_its_input=False`, so `categorise` "
                                      "misses")

    Scenario() \
        .given(
            some_postmortem := a_postmortem(code_read=[some_reading])
        ) \
        .when(
            lambda: the_supporting_information(some_postmortem,
                                               SOME_INCIDENT_ADDRESS).code_read[0].said
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="v2 sets "),
                                      Run(text="lowercases_its_input=False", role=Role.CODE),
                                      Run(text=", so "),
                                      Run(text="categorise", role=Role.CODE),
                                      Run(text=" misses")))))


@pytest.mark.unit
@pytest.mark.parametrize("named", [SOME_DEPLOYED_REVISION, SOME_DEPLOYED_REVISION[:7]],
                         ids=["whole", "short"])
def test_a_revision_what_code_fix_read_names_is_said_short_and_leads_where_it_opens(
        named: str) -> None:
    # Everywhere else the document says a revision short and opens its
    # commit, and one left plain here reads as another revision.
    some_reading = CitedEvidence(label="F1", text=f"deploy {named} switched the model")

    Scenario() \
        .given(
            some_postmortem := a_postmortem(changes_read=[a_deploy_read("P2")],
                                            code_read=[some_reading])
        ) \
        .when(
            lambda: the_supporting_information(some_postmortem,
                                               SOME_INCIDENT_ADDRESS).code_read[0].said
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text="deploy "),
                Run(text=SOME_DEPLOYED_REVISION[:7], role=Role.LINK,
                    address=f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"),
                Run(text=" switched the model")))))


@pytest.mark.unit
def test_what_code_fix_read_is_headed_as_a_reading_nothing_ran() -> None:
    # The mechanism as it was read off the source: a reader weighs a cause
    # resting on it by knowing that nothing ran it.
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: the_supporting_information(
                dont_care_postmortem, SOME_INCIDENT_ADDRESS).code_read_heading
        ) \
        .then(
            the_answer_was("What Code-Fix read in the source - a static reading, nothing ran it"))


@pytest.mark.unit
def test_an_incident_code_fix_said_nothing_of_has_no_row_for_it() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(code_read=[])
        ) \
        .when(
            lambda: the_supporting_information(some_postmortem, SOME_INCIDENT_ADDRESS).code_read
        ) \
        .then(
            the_answer_was(()))


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
