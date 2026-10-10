"""What the intent agent does with one thing a person wrote.

It records what the message was classified as, whatever that was - so the
timeline says Argus understood it, including that it found nothing to act on.
And where the person asked for an ending - the incident is over, or Argus is to
stand down - and the incident can still end that way, it offers that person the
chance to confirm: named, so the offer says who it is to, and carrying their
own words, which become the ending's note.

It never ends anything. The offer is the whole of what a classification can
do, because a model's classification of a sentence is not a person's decision -
the press that answers the offer is.

The model, the incident's status and the chat platform are each stood in for:
the model's classification is `classifying`'s suite, and the other two are
somebody else's.
"""

from __future__ import annotations

import logging

import pytest
from agent_intent.understanding import understand
from argus_core import new_id
from argus_core.events import (
    IncidentEvent,
    MessageUnderstood,
    Offered,
    PersonWrote,
    ResolutionOffered,
    WithdrawalOffered,
)
from argus_core.models import IncidentStatus, Meaning, ReportChannel, a_chat_message
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

# A status from which the incident can still end either way a person asks.
STILL_WORKED_ON = IncidentStatus.INVESTIGATING


@pytest.mark.unit
@pytest.mark.parametrize("meaning", list(Meaning))
def test_every_message_is_recorded_with_what_it_was_classified_as(meaning: Meaning) -> None:
    published: list[IncidentEvent] = []

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: meaning,
                                 status_of=lambda _: STILL_WORKED_ON,
                                 person_named=lambda _: SOME_NAME,
                                 publisher=published.append)) \
        .then(_it_was_classified_as(published, meaning))


@pytest.mark.unit
def test_a_message_the_model_could_not_classify_is_nothing_to_act_on_and_is_said(
        caplog: pytest.LogCaptureFixture) -> None:
    # Nothing to act on is the one meaning that does nothing, so the message
    # costs the person an offer and nothing else - which they can still make
    # for themselves, from the page. The warning is how anybody learns which
    # message on which incident it cost them.
    published: list[IncidentEvent] = []

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: None,
                                 status_of=lambda _: STILL_WORKED_ON,
                                 person_named=lambda _: SOME_NAME,
                                 publisher=published.append)) \
        .then(all_of(
            _it_was_classified_as(published, Meaning.OTHER),
            _no_offer_was_made(published),
            one_record_was_logged(caplog, "agent_intent.understanding", logging.WARNING,
                                  "message not classified",
                                  values={"incident_id": SOME_INCIDENT,
                                          "chat_message": SOME_MESSAGE.value})
        ))


@pytest.mark.unit
@pytest.mark.parametrize("named", [SOME_NAME, None], ids=["named", "unnamed"])
def test_a_person_saying_it_is_over_is_offered_the_chance_to_confirm(named: str | None) -> None:
    # They said it; the offer is theirs whatever the platform calls them.
    published: list[IncidentEvent] = []

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: Meaning.RESOLVE,
                                 status_of=lambda _: STILL_WORKED_ON,
                                 person_named=lambda _: named,
                                 publisher=published.append)) \
        .then(_the_offer_made_was(published, ResolutionOffered(
            incident_id=SOME_INCIDENT, message=SOME_MESSAGE, person_id=SOME_PERSON,
            person_name=named, said=SOME_WORDS
        )))


@pytest.mark.unit
@pytest.mark.parametrize("named", [SOME_NAME, None], ids=["named", "unnamed"])
def test_a_person_telling_argus_to_stand_down_is_offered_the_chance_to_confirm(
        named: str | None) -> None:
    # The same offer, ending the other way: a withdrawal puts back what Argus
    # changed, which is as much a person's decision as saying it is over.
    published: list[IncidentEvent] = []

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: Meaning.WITHDRAW,
                                 status_of=lambda _: STILL_WORKED_ON,
                                 person_named=lambda _: named,
                                 publisher=published.append)) \
        .then(_the_offer_made_was(published, WithdrawalOffered(
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
    published: list[IncidentEvent] = []
    a_name_was_asked_for: Kept[bool] = Kept()

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: meaning,
                                 status_of=lambda _: status,
                                 person_named=a_factory_that_must_not_be_called(
                                     a_name_was_asked_for),
                                 publisher=published.append)) \
        .then(all_of(_it_was_classified_as(published, meaning),
                     _no_offer_was_made(published),
                     nothing_was_collected(a_name_was_asked_for)))


@pytest.mark.unit
def test_a_mitigated_incident_is_still_offered_a_resolution() -> None:
    # Mitigated still owes something, and a person who finished the job is
    # reporting exactly that - where a withdrawal from it is refused.
    published: list[IncidentEvent] = []

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: Meaning.RESOLVE,
                                 status_of=lambda _: IncidentStatus.MITIGATED,
                                 person_named=lambda _: SOME_NAME,
                                 publisher=published.append)) \
        .then(_the_offer_made_was(published, ResolutionOffered(
            incident_id=SOME_INCIDENT, message=SOME_MESSAGE, person_id=SOME_PERSON,
            person_name=SOME_NAME, said=SOME_WORDS
        )))


@pytest.mark.unit
@pytest.mark.parametrize("meaning", [Meaning.QUESTION, Meaning.INFORMATION, Meaning.OTHER])
def test_anything_else_is_offered_nothing_and_nobody_is_looked_up(meaning: Meaning) -> None:
    # The name is looked up only for an offer, so a thread full of chatter
    # costs the chat platform nothing.
    published: list[IncidentEvent] = []
    a_name_was_asked_for: Kept[bool] = Kept()

    Scenario() \
        .when(lambda: understand(_a_person_writing(), meaning_of=lambda _: meaning,
                                 status_of=lambda _: STILL_WORKED_ON,
                                 person_named=a_factory_that_must_not_be_called(
                                     a_name_was_asked_for),
                                 publisher=published.append)) \
        .then(all_of(_no_offer_was_made(published),
                     nothing_was_collected(a_name_was_asked_for)))


def _a_person_writing() -> PersonWrote:
    return PersonWrote(incident_id=SOME_INCIDENT, message=SOME_MESSAGE,
                       person_id=SOME_PERSON, text=SOME_WORDS)


def _it_was_classified_as(published: list[IncidentEvent],
                          meaning: Meaning) -> Assertion[object]:
    def assertion(_: object) -> bool:
        understood = [(event.incident_id, event.message, event.meaning) for event in published
                      if isinstance(event, MessageUnderstood)]

        if understood != [(SOME_INCIDENT, SOME_MESSAGE, meaning)]:
            raise AssertionError(
                f"Expected the message recorded once as classified as [{meaning}], got "
                f"{understood}."
            )

        return True

    return assertion


def _the_offer_made_was(published: list[IncidentEvent],
                        expected: Offered) -> Assertion[object]:
    """Exactly one offer, and it is this one - its kind included, which is
    what says which ending the press will confirm."""
    def assertion(_: object) -> bool:
        offers = [event.model_dump(exclude={"id", "at"}) for event in published
                  if isinstance(event, ResolutionOffered | WithdrawalOffered)]
        wanted = expected.model_dump(exclude={"id", "at"})

        if offers != [wanted]:
            raise AssertionError(f"Expected one offer, {wanted}, got {offers}.")

        return True

    return assertion


def _no_offer_was_made(published: list[IncidentEvent]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        offers = [event for event in published
                  if isinstance(event, ResolutionOffered | WithdrawalOffered)]

        if offers:
            raise AssertionError(f"Expected no offer, got {offers}.")

        return True

    return assertion
