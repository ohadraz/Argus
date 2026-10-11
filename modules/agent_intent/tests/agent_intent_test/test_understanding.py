"""What the intent agent does with one thing a person wrote.

It keeps what the message was classified as, whatever that was, on the
incident's record - and says so, so the timeline says Argus understood it,
including that it found nothing to act on. And where the person asked for an
ending - the incident is over, or Argus is to stand down - and the incident can
still end that way, it offers that person the chance to confirm: named, so the
offer says who it is to, and carrying their own words, which become the
ending's note. A lead's writer is named too, because the postmortem owes them
the line it reports their lead in.

The record is the work and the event the account of it, so the record is
written first: what decides on a message reads the record, and an account that
went missing costs the timeline a line and nothing more.

It never ends anything. The offer is the whole of what a classification can
do, because a model's classification of a sentence is not a person's decision -
the press that answers the offer is.

The model, the incident's status, the chat platform and the record are each
stood in for: the model's classification is `classifying`'s suite, and the rest
are somebody else's.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from agent_intent.understanding import understand
from argus_core import new_id
from argus_core.events import (
    MessageUnderstood,
    Offered,
    ResolutionOffered,
    WithdrawalOffered,
)
from argus_core.models import (
    IncidentStatus,
    Meaning,
    Reference,
    ReportChannel,
    ThreadMessage,
    a_chat_message,
)
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    a_factory_that_must_not_be_called,
    all_of,
    nothing_was_collected,
    one_record_was_logged,
)

SOME_INCIDENT = new_id()
SOME_MESSAGE = a_chat_message(ReportChannel.SLACK, "C-some-channel", "1760000100.000200")
SOME_PERSON = "U-some-person"
SOME_WORDS = "rolled the flag back by hand, we're fine"
SOME_NAME = "Some Person"
SOME_TIME = datetime(2026, 10, 11, 1, 0, tzinfo=UTC)

# A status from which the incident can still end either way a person asks.
STILL_WORKED_ON = IncidentStatus.INVESTIGATING


@pytest.mark.unit
@pytest.mark.parametrize("meaning", list(Meaning))
def test_every_message_is_kept_and_told_with_what_it_was_classified_as(
        meaning: Meaning) -> None:
    happened: list[object] = []

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: meaning,
                                 status_of=lambda _: STILL_WORKED_ON,
                                 person_named=lambda _: SOME_NAME,
                                 record=_TheRecord(happened),
                                 publisher=happened.append)) \
        .then(_it_was_classified_as(happened, meaning))


@pytest.mark.unit
def test_what_a_message_meant_is_kept_before_it_is_told() -> None:
    # What decides on a message reads the record. Told first, a reader of the
    # timeline could see a message understood that the wait still holds a walk
    # for - and a failed write after it would leave the two disagreeing for good.
    happened: list[object] = []

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: Meaning.INFORMATION,
                                 status_of=lambda _: STILL_WORKED_ON,
                                 person_named=lambda _: SOME_NAME,
                                 record=_TheRecord(happened),
                                 publisher=happened.append)) \
        .then(_it_was_kept_before_it_was_told(happened))


@pytest.mark.unit
def test_a_message_the_model_could_not_classify_is_nothing_to_act_on_and_is_said(
        caplog: pytest.LogCaptureFixture) -> None:
    # Nothing to act on is the one meaning that does nothing, so the message
    # costs the person an offer and nothing else - which they can still make
    # for themselves, from the page. The warning is how anybody learns which
    # message on which incident it cost them.
    happened: list[object] = []

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: None,
                                 status_of=lambda _: STILL_WORKED_ON,
                                 person_named=lambda _: SOME_NAME,
                                 record=_TheRecord(happened),
                                 publisher=happened.append)) \
        .then(all_of(
            _it_was_classified_as(happened, Meaning.OTHER),
            _no_offer_was_made(happened),
            one_record_was_logged(caplog, "agent_intent.understanding", logging.WARNING,
                                  "message not classified",
                                  values={"incident_id": SOME_INCIDENT,
                                          "chat_message": SOME_MESSAGE.value})
        ))


@pytest.mark.unit
@pytest.mark.parametrize("named", [SOME_NAME, None], ids=["named", "unnamed"])
def test_a_person_saying_it_is_over_is_offered_the_chance_to_confirm(named: str | None) -> None:
    # They said it; the offer is theirs whatever the platform calls them.
    happened: list[object] = []

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: Meaning.RESOLVE,
                                 status_of=lambda _: STILL_WORKED_ON,
                                 person_named=lambda _: named,
                                 record=_TheRecord(happened),
                                 publisher=happened.append)) \
        .then(_the_offer_made_was(happened, IncidentStatus.RESOLVED, ResolutionOffered(
            incident_id=SOME_INCIDENT, message=SOME_MESSAGE, person_id=SOME_PERSON,
            person_name=named, said=SOME_WORDS
        )))


@pytest.mark.unit
@pytest.mark.parametrize("named", [SOME_NAME, None], ids=["named", "unnamed"])
def test_a_person_telling_argus_to_stand_down_is_offered_the_chance_to_confirm(
        named: str | None) -> None:
    # The same offer, ending the other way: a withdrawal puts back what Argus
    # changed, which is as much a person's decision as saying it is over.
    happened: list[object] = []

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: Meaning.WITHDRAW,
                                 status_of=lambda _: STILL_WORKED_ON,
                                 person_named=lambda _: named,
                                 record=_TheRecord(happened),
                                 publisher=happened.append)) \
        .then(_the_offer_made_was(happened, IncidentStatus.WITHDRAWN, WithdrawalOffered(
            incident_id=SOME_INCIDENT, message=SOME_MESSAGE, person_id=SOME_PERSON,
            person_name=named, said=SOME_WORDS
        )))


@pytest.mark.unit
@pytest.mark.parametrize(("meaning", "status"), [
    (Meaning.RESOLVE, IncidentStatus.RESOLVED),
    (Meaning.RESOLVE, IncidentStatus.WITHDRAWN),
    (Meaning.RESOLVE, IncidentStatus.DISPROVEN),
    (Meaning.WITHDRAW, IncidentStatus.MITIGATED),
    (Meaning.WITHDRAW, IncidentStatus.ESCALATED),
    (Meaning.WITHDRAW, IncidentStatus.WITHDRAWN),
    (Meaning.RESOLVE, None),
    (Meaning.WITHDRAW, None)
])
def test_no_offer_is_made_for_an_ending_the_incident_no_longer_accepts(
        meaning: Meaning, status: IncidentStatus | None) -> None:
    # A button that could only ever do nothing would be Argus asking a question
    # it had already answered - and nobody is looked up for one. An incident
    # Argus cannot find accepts nothing.
    happened: list[object] = []
    a_name_was_asked_for: Kept[bool] = Kept()

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: meaning,
                                 status_of=lambda _: status,
                                 person_named=a_factory_that_must_not_be_called(
                                     a_name_was_asked_for),
                                 record=_TheRecord(happened),
                                 publisher=happened.append)) \
        .then(all_of(_it_was_classified_as(happened, meaning),
                     _no_offer_was_made(happened),
                     nothing_was_collected(a_name_was_asked_for)))


@pytest.mark.unit
def test_a_mitigated_incident_is_still_offered_a_resolution() -> None:
    # Mitigated still owes something, and a person who finished the job is
    # reporting exactly that - where a withdrawal from it is refused.
    happened: list[object] = []

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: Meaning.RESOLVE,
                                 status_of=lambda _: IncidentStatus.MITIGATED,
                                 person_named=lambda _: SOME_NAME,
                                 record=_TheRecord(happened),
                                 publisher=happened.append)) \
        .then(_the_offer_made_was(happened, IncidentStatus.RESOLVED, ResolutionOffered(
            incident_id=SOME_INCIDENT, message=SOME_MESSAGE, person_id=SOME_PERSON,
            person_name=SOME_NAME, said=SOME_WORDS
        )))


@pytest.mark.unit
@pytest.mark.parametrize("named", [SOME_NAME, None], ids=["named", "unnamed"])
def test_a_lead_is_kept_with_the_name_of_whoever_wrote_it(named: str | None) -> None:
    # The postmortem reports each lead and owes its writer the line, and a
    # platform id is not a name a reader of the document knows. Kept as the
    # platform gave it, or as nothing where it could not say.
    happened: list[object] = []

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: Meaning.INFORMATION,
                                 status_of=lambda _: STILL_WORKED_ON,
                                 person_named=lambda _: named,
                                 record=_TheRecord(happened),
                                 publisher=happened.append)) \
        .then(all_of(_the_writer_was_named(happened, named),
                     _no_offer_was_made(happened)))


@pytest.mark.unit
@pytest.mark.parametrize("meaning", [Meaning.QUESTION, Meaning.OTHER])
def test_anything_else_is_offered_nothing_and_nobody_is_looked_up(meaning: Meaning) -> None:
    # The name is looked up only for an offer or a lead, so a thread full of
    # chatter costs the chat platform nothing.
    happened: list[object] = []
    a_name_was_asked_for: Kept[bool] = Kept()

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: meaning,
                                 status_of=lambda _: STILL_WORKED_ON,
                                 person_named=a_factory_that_must_not_be_called(
                                     a_name_was_asked_for),
                                 record=_TheRecord(happened),
                                 publisher=happened.append)) \
        .then(all_of(_no_offer_was_made(happened),
                     nothing_was_collected(a_name_was_asked_for)))


class _TheRecord:
    """Stands in for the incident's record of its conversation, keeping what
    it was told in the one list the events are published to, so the order of
    the two can be read."""

    def __init__(self, happened: list[object]) -> None:
        self._happened = happened

    def understood(self, message: Reference, meaning: Meaning) -> None:
        self._happened.append(_Understood(message, meaning))

    def named(self, message: Reference, person_name: str | None) -> None:
        self._happened.append(_NameKept(message, person_name))

    def offered(self, message: Reference, ending: IncidentStatus) -> None:
        self._happened.append(_OfferKept(message, ending))


@dataclass(frozen=True)
class _Understood:
    """The record told what a message meant."""

    message: Reference
    meaning: Meaning


@dataclass(frozen=True)
class _NameKept:
    """The record told what the message's writer is called."""

    message: Reference
    person_name: str | None


@dataclass(frozen=True)
class _OfferKept:
    """The record told an offer was made."""

    message: Reference
    ending: IncidentStatus


def _a_person_writing() -> ThreadMessage:
    return ThreadMessage(incident_id=SOME_INCIDENT, message=SOME_MESSAGE,
                         person_id=SOME_PERSON, text=SOME_WORDS, written_at=SOME_TIME)


def _it_was_classified_as(happened: list[object], meaning: Meaning) -> Assertion[object]:
    def assertion(_: object) -> bool:
        kept = [entry for entry in happened if isinstance(entry, _Understood)]
        told = [(event.incident_id, event.message, event.meaning) for event in happened
                if isinstance(event, MessageUnderstood)]

        if kept != [_Understood(SOME_MESSAGE, meaning)] \
                or told != [(SOME_INCIDENT, SOME_MESSAGE, meaning)]:
            raise AssertionError(
                f"Expected the message kept and told once as classified as [{meaning}], "
                f"got kept {kept} and told {told}."
            )

        return True

    return assertion


def _it_was_kept_before_it_was_told(happened: list[object]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        order = [type(entry).__name__ for entry in happened
                 if isinstance(entry, _Understood | MessageUnderstood)]

        if order != [_Understood.__name__, MessageUnderstood.__name__]:
            raise AssertionError(
                f"Expected what the message meant kept, then told, got {order}."
            )

        return True

    return assertion


def _the_writer_was_named(happened: list[object], named: str | None) -> Assertion[object]:
    """The writer's name kept once, against the message they wrote."""
    def assertion(_: object) -> bool:
        kept = [entry for entry in happened if isinstance(entry, _NameKept)]
        wanted = _NameKept(SOME_MESSAGE, named)

        if kept != [wanted]:
            raise AssertionError(f"Expected the writer kept as {wanted}, got {kept}.")

        return True

    return assertion


def _the_offer_made_was(happened: list[object],
                        ending: IncidentStatus,
                        expected: Offered) -> Assertion[object]:
    """Exactly one offer, kept and told, and it is this one - its kind
    included, which is what says which ending the press will confirm - with
    its writer's name kept against the message it answers."""
    def assertion(_: object) -> bool:
        kept = [entry for entry in happened if isinstance(entry, _OfferKept)]
        told = [event.model_dump(exclude={"id", "at"}) for event in happened
                if isinstance(event, ResolutionOffered | WithdrawalOffered)]
        wanted = expected.model_dump(exclude={"id", "at"})
        wanted_kept = _OfferKept(SOME_MESSAGE, ending)

        if kept != [wanted_kept] or told != [wanted]:
            raise AssertionError(
                f"Expected one offer, kept as {wanted_kept} and told as {wanted}, got kept "
                f"{kept} and told {told}."
            )

        return _the_writer_was_named(happened, expected.person_name)(_)

    return assertion


def _no_offer_was_made(happened: list[object]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        offers = [entry for entry in happened
                  if isinstance(entry, _OfferKept | ResolutionOffered | WithdrawalOffered)]

        if offers:
            raise AssertionError(f"Expected no offer, got {offers}.")

        return True

    return assertion
