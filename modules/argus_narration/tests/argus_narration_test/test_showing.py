"""A line of the account as it is shown: the square brackets Argus and its
model quote a name in, left off, and a revision the incident read said short
and leading to its commit.

The brackets are how a name is marked off in what a model reads - "[io-shop]",
"[7c3ca00]" - and a reader of the page or the channel reads them as clutter
around a word. A revision is said whole in the record, and forty characters in
a sentence read as noise. So both are re-said where a line is shown, and only
there: the record, and what a model is told of it, keep them as written. A
revision said short is a name a reader cannot look up by hand, so where it is
shown it opens where it was committed.

Only the brackets that quote a name. An index in code keeps its brackets, as a
phrase with spaces in it and a link do, and a line a person wrote is shown as
they wrote it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
from argus_core import new_id
from argus_core.events import ChangesRetrieved
from argus_core.models import ChangeEvent, ChangeKind, RevisionSource
from argus_narration import NarrationLine
from argus_narration.showing import ShownRevision, as_shown, shown, the_revisions
from argus_testkit import Scenario, the_answer_was

DONT_CARE_MOMENT = datetime(2026, 10, 11, 12, 18, tzinfo=UTC)

# A line shown with no revision the incident read to say short.
NO_REVISIONS: Mapping[str, ShownRevision] = {}

SOME_REVISION = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"
# One sharing the first's seven characters and parting from it at the eighth.
SOME_RIVAL = "26f1d7e90000000000000000000000000000000a"


@pytest.mark.unit
def test_a_quoted_name_is_shown_without_its_brackets() -> None:
    Scenario() \
        .when(
            lambda: as_shown("Rolled [io-shop] back to [7c3ca00], which was [3] replicas")
        ) \
        .then(
            the_answer_was("Rolled io-shop back to 7c3ca00, which was 3 replicas"))


@pytest.mark.unit
@pytest.mark.parametrize("said", [
    "the list read prices[index] and names[0]",
    "it said [a phrase with spaces in it]",
    "see [the runbook](https://runbooks.example/io-shop)",
    "see [docs](https://runbooks.example/io-shop)",
    "a nested [[name]] stays as it was"
], ids=["an-index", "a-phrase", "a-link", "a-one-word-link", "nested"])
def test_brackets_that_quote_no_name_are_shown_as_written(said: str) -> None:
    # An index belongs to the code it is in, a phrase was bracketed by whoever
    # wrote it for a reason of their own, and a link's text is what it opens.
    Scenario() \
        .when(
            lambda: as_shown(said)
        ) \
        .then(
            the_answer_was(said))


@pytest.mark.unit
def test_a_line_of_the_walk_is_shown_without_brackets_in_any_part_of_it() -> None:
    # The marked word and the words either side of it are the same sentence
    # split for a destination that sets the word apart, and are shown alike.
    some_line = NarrationLine(at=DONT_CARE_MOMENT, kind="action-taken", who="Mitigation",
                              text="Rolled [io-shop] back to [7c3ca00]",
                              before_emphasis="Rolled ", emphasis="[io-shop]",
                              after_emphasis=" back to [7c3ca00]")

    Scenario() \
        .given(
            some_line
        ) \
        .when(
            lambda: shown(some_line, NO_REVISIONS)
        ) \
        .then(
            the_answer_was(some_line.model_copy(update={
                "text": "Rolled io-shop back to 7c3ca00",
                "emphasis": "io-shop",
                "after_emphasis": " back to 7c3ca00"})))


@pytest.mark.unit
def test_a_revision_the_incident_read_is_shown_short_in_every_part_of_a_line() -> None:
    some_line = NarrationLine(at=DONT_CARE_MOMENT, kind="action-taken", who="Mitigation",
                              text=f"Rolled [io-shop] back off revision [{SOME_REVISION}]",
                              before_emphasis="Rolled ", emphasis="[io-shop]",
                              after_emphasis=f" back off revision [{SOME_REVISION}]")

    Scenario() \
        .given(
            some_line
        ) \
        .when(
            lambda: shown(some_line, {SOME_REVISION: _shown_by(SOME_REVISION[:7])})
        ) \
        .then(
            the_answer_was(some_line.model_copy(update={
                "text": f"Rolled io-shop back off revision {SOME_REVISION[:7]}",
                "emphasis": "io-shop",
                "after_emphasis": f" back off revision {SOME_REVISION[:7]}",
                "links": {SOME_REVISION[:7]: _the_commit_of(SOME_REVISION)}})))


@pytest.mark.unit
def test_a_revision_shown_short_leads_to_its_commit() -> None:
    # Short, it is a name a reader cannot look up by hand.
    some_line = NarrationLine(at=DONT_CARE_MOMENT, kind="action-taken", who="Mitigation",
                              text=f"Rolled [io-shop] back off revision [{SOME_REVISION}]")

    Scenario() \
        .given(
            some_line
        ) \
        .when(
            lambda: shown(some_line, {SOME_REVISION: _shown_by(SOME_REVISION[:7])}).links
        ) \
        .then(
            the_answer_was({SOME_REVISION[:7]: _the_commit_of(SOME_REVISION)}))


@pytest.mark.unit
def test_a_revision_a_line_does_not_name_gives_it_no_link() -> None:
    # Every revision the incident read is handed to every line; a line leads
    # only where it names.
    some_line = NarrationLine(at=DONT_CARE_MOMENT, kind="action-taken", who="Mitigation",
                              text="Restarted [io-shop]")

    Scenario() \
        .given(
            some_line
        ) \
        .when(
            lambda: shown(some_line, {SOME_REVISION: _shown_by(SOME_REVISION[:7])}).links
        ) \
        .then(
            the_answer_was({}))


@pytest.mark.unit
def test_a_revision_named_by_a_start_of_it_is_shown_short_and_leads_to_its_commit() -> None:
    # The model names a revision by as much of it as it likes - eight
    # characters, often. Shown as it wrote it, one page names one revision two
    # ways, and only one of them opens.
    some_line = NarrationLine(at=DONT_CARE_MOMENT, kind="candidate-selected",
                              who="Investigator",
                              text=f"[{SOME_REVISION[:8]}] made every page slow")

    Scenario() \
        .given(
            some_line
        ) \
        .when(
            lambda: shown(some_line, {SOME_REVISION: _shown_by(SOME_REVISION[:7])})
        ) \
        .then(
            the_answer_was(some_line.model_copy(update={
                "text": f"{SOME_REVISION[:7]} made every page slow",
                "links": {SOME_REVISION[:7]: _the_commit_of(SOME_REVISION)}})))


@pytest.mark.unit
def test_a_start_two_revisions_share_is_shown_as_written() -> None:
    # It names neither, so nothing here can say which.
    some_line = NarrationLine(at=DONT_CARE_MOMENT, kind="candidate-selected",
                              who="Investigator",
                              text=f"[{SOME_REVISION[:7]}] made every page slow")

    Scenario() \
        .given(
            some_line
        ) \
        .when(
            lambda: shown(some_line, {
                SOME_REVISION: _shown_by(SOME_REVISION[:8]),
                SOME_RIVAL: ShownRevision(short=SOME_RIVAL[:8],
                                          address=_the_commit_of(SOME_RIVAL))})
        ) \
        .then(
            the_answer_was(some_line.model_copy(update={
                "text": f"{SOME_REVISION[:7]} made every page slow"})))


@pytest.mark.unit
def test_a_line_shown_twice_reads_as_it_did_shown_once() -> None:
    # Its links are read off what it names, so showing it again keeps them.
    some_line = NarrationLine(at=DONT_CARE_MOMENT, kind="action-taken", who="Mitigation",
                              text=f"Rolled [io-shop] back off revision [{SOME_REVISION}]")
    some_revisions = {SOME_REVISION: _shown_by(SOME_REVISION[:7])}

    Scenario() \
        .given(
            once := shown(some_line, some_revisions)
        ) \
        .when(
            lambda: shown(once, some_revisions)
        ) \
        .then(
            the_answer_was(once))


@pytest.mark.unit
def test_a_revision_whose_short_form_is_all_digits_still_leads_to_its_commit() -> None:
    # Seven hex characters are all digits for about one revision in
    # twenty-seven, and a short form like that reads as a number to anything
    # looking for revisions it does not know. This one it knows.
    some_digits_first = "3398001abab0000000000000000000000000000c"
    some_line = NarrationLine(at=DONT_CARE_MOMENT, kind="action-taken", who="Mitigation",
                              text=f"Rolled [io-shop] back off revision [{some_digits_first}]")

    Scenario() \
        .given(
            some_line
        ) \
        .when(
            lambda: shown(some_line, {some_digits_first: ShownRevision(
                short=some_digits_first[:7], address=_the_commit_of(some_digits_first))}).links
        ) \
        .then(
            the_answer_was({some_digits_first[:7]: _the_commit_of(some_digits_first)}))


@pytest.mark.unit
def test_a_line_a_person_wrote_is_shown_as_they_wrote_it() -> None:
    # Their brackets are theirs, and not Argus's way of quoting a name - and
    # so is a revision they wrote whole.
    some_line = NarrationLine(at=DONT_CARE_MOMENT, kind="person-wrote", who="kuki",
                              text=f"the [checkout] flag again, or {SOME_REVISION}?",
                              outside_the_walk=True)

    Scenario() \
        .given(
            some_line
        ) \
        .when(
            lambda: shown(some_line, {SOME_REVISION: _shown_by(SOME_REVISION[:7])})
        ) \
        .then(
            the_answer_was(some_line))


@pytest.mark.unit
def test_each_revision_the_incident_read_is_said_as_short_as_names_it_alone() -> None:
    # A deploy's revision, and a rival's that starts alike for seven characters
    # and so takes eight - each opening where it was committed. A flag's name is
    # no revision, and is neither shortened nor linked.
    Scenario() \
        .given(
            some_events := [_changes_read(_a_deploy(SOME_REVISION), _a_deploy(SOME_RIVAL),
                                          _a_flag_toggle("monthly-spend-feature"))]
        ) \
        .when(
            lambda: the_revisions(some_events)
        ) \
        .then(
            the_answer_was({
                SOME_REVISION: ShownRevision(short=SOME_REVISION[:8],
                                             address=_the_commit_of(SOME_REVISION)),
                SOME_RIVAL: ShownRevision(short=SOME_RIVAL[:8],
                                          address=_the_commit_of(SOME_RIVAL))}))


def _shown_by(short: str) -> ShownRevision:
    """SOME_REVISION as a line shows it: by `short`, opening at its commit."""
    return ShownRevision(short=short, address=_the_commit_of(SOME_REVISION))


def _the_commit_of(revision: str) -> str:
    return f"https://github.invalid/acme/shop/commit/{revision}"


def _changes_read(*changes: ChangeEvent) -> ChangesRetrieved:
    return ChangesRetrieved(incident_id=new_id(), window_start="dont care",
                            window_end="dont care", changes=list(changes))


def _a_deploy(revision: str) -> ChangeEvent:
    """A deploy of `revision`, which can be opened where its repository is."""
    return ChangeEvent(kind=ChangeKind.DEPLOY, occurred_at="2026-10-11T12:00:00Z",
                       reference=revision, summary="dont care",
                       revision_source=RevisionSource(
                           repository="acme/shop",
                           repository_address="https://github.invalid/acme/shop",
                           revision_address=_the_commit_of(revision)))


def _a_flag_toggle(flag: str) -> ChangeEvent:
    return ChangeEvent(kind=ChangeKind.FLAG_TOGGLE, occurred_at="2026-10-11T12:00:00Z",
                       reference=flag, summary="dont care")
