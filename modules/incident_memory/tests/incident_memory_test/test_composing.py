"""What a finished incident is remembered as: its subjects, and how each ended.

The record is not a summary of the incident. It is the list of things Argus
changed and what each change turned out to be worth, because that is the one
part a later incident cannot work out from its own evidence however long it
looks.

Which is why the cases below are all about what survives the composing and what
does not. A verdict nobody reached says nothing about a subject; a subject
nobody recorded cannot be matched against anything later; and an incident with
neither is an incident there is no point remembering.
"""

from __future__ import annotations

import pytest
from argus_core.models import RESTART_SERVICE, ActionIdentity, Verdict
from argus_testkit import Assertion, Scenario, all_of
from incident_memory.composing import a_memory_of
from incident_memory.records import RememberedIncident

from incident_memory_test.framework.builders import (
    DONT_CARE_DESCRIPTION,
    SOME_INCIDENT,
    an_action,
    an_action_on_nothing,
    an_alert,
)


@pytest.mark.unit
def test_an_incident_resolved_by_one_action_remembers_that_action() -> None:
    # The cheerful half of the record, and the less useful one: it says a thing
    # worked once. The ordering rule reads it to leave a subject where it is.
    the_flag_that_was_put_back = "new-checkout-flow"

    Scenario() \
        .given(an_action(the_flag_that_was_put_back, Verdict.CONFIRMED)) \
        .when(lambda: a_memory_of(
            SOME_INCIDENT,
            an_alert(),
            [an_action(the_flag_that_was_put_back, Verdict.CONFIRMED)],
            described_as=DONT_CARE_DESCRIPTION
        )) \
        .then(all_of(
            _it_remembers_trying(the_flag_that_was_put_back),
            _it_remembers_the_verdict(Verdict.CONFIRMED)
        ))


@pytest.mark.unit
def test_an_incident_escalated_after_two_refutations_remembers_both() -> None:
    # The valuable half. Two subjects were changed and the service stayed
    # broken, which is evidence no later investigation can produce for itself
    # at any budget.
    a_flag_that_did_not_help = "new-checkout-flow"
    another_flag_that_did_not_help = "payments-fallback"

    Scenario() \
        .given(an_alert()) \
        .when(lambda: a_memory_of(
            SOME_INCIDENT,
            an_alert(),
            [
                an_action(a_flag_that_did_not_help, Verdict.REFUTED),
                an_action(another_flag_that_did_not_help, Verdict.REFUTED)
            ],
            described_as=DONT_CARE_DESCRIPTION
        )) \
        .then(all_of(
            _it_remembers_trying(a_flag_that_did_not_help),
            _it_remembers_trying(another_flag_that_did_not_help),
            _it_remembers_this_many_attempts(2)
        ))


@pytest.mark.unit
def test_an_incident_where_no_attempt_reached_a_verdict_is_not_remembered() -> None:
    # Escalated before anything could be measured, or withdrawn while the
    # service was still being watched. The record's whole content is what
    # attempts reached, so there is nothing here to write down.
    dont_care_flag = "new-checkout-flow"

    Scenario() \
        .given(an_alert()) \
        .when(lambda: a_memory_of(
            SOME_INCIDENT,
            an_alert(),
            [
                an_action(dont_care_flag, Verdict.ESCALATED),
                an_action(dont_care_flag, Verdict.WITHDRAWN),
                an_action(dont_care_flag, verdict=None)
            ],
            described_as=DONT_CARE_DESCRIPTION
        )) \
        .then(_nothing_is_remembered())


@pytest.mark.unit
def test_an_attempt_with_no_verdict_is_dropped_from_a_record_that_has_others() -> None:
    # A walk that stopped between acting and saying what happened leaves a row
    # with no outcome. Remembering it as an attempt would put a subject on the
    # list with nothing said about it, which a later ordering would read as
    # evidence it has no right to.
    the_flag_that_was_judged = "new-checkout-flow"
    the_flag_that_was_not = "payments-fallback"

    Scenario() \
        .given(an_alert()) \
        .when(lambda: a_memory_of(
            SOME_INCIDENT,
            an_alert(),
            [
                an_action(the_flag_that_was_judged, Verdict.REFUTED),
                an_action(the_flag_that_was_not, verdict=None)
            ],
            described_as=DONT_CARE_DESCRIPTION
        )) \
        .then(all_of(
            _it_remembers_trying(the_flag_that_was_judged),
            _it_remembers_this_many_attempts(1)
        ))


@pytest.mark.unit
def test_an_attempt_on_no_recorded_subject_is_dropped() -> None:
    # Nothing later can match against it. A record is consulted by asking
    # whether this candidate's subject was tried before, and a remembered
    # attempt naming no subject can only ever answer no.
    the_flag_that_was_named = "new-checkout-flow"

    Scenario() \
        .given(an_alert()) \
        .when(lambda: a_memory_of(
            SOME_INCIDENT,
            an_alert(),
            [an_action(the_flag_that_was_named, Verdict.REFUTED), an_action_on_nothing()],
            described_as=DONT_CARE_DESCRIPTION
        )) \
        .then(all_of(
            _it_remembers_trying(the_flag_that_was_named),
            _it_remembers_this_many_attempts(1)
        ))


@pytest.mark.unit
def test_a_record_keeps_what_was_done_as_well_as_what_it_was_done_to() -> None:
    # Half a key is a key that is sometimes right. A later walk asks what it
    # would do about a candidate and matches the answer here, and a record
    # saying only that io-shop was tried cannot tell it whether io-shop was a
    # service somebody restarted or a flag somebody put back.
    the_service_that_was_restarted = "io-shop"

    Scenario() \
        .given(an_alert()) \
        .when(lambda: a_memory_of(
            SOME_INCIDENT,
            an_alert(),
            [an_action(the_service_that_was_restarted,
                       Verdict.REFUTED,
                       action_type=RESTART_SERVICE)],
            described_as=DONT_CARE_DESCRIPTION
        )) \
        .then(_it_remembers_doing(
            ActionIdentity(action_type=RESTART_SERVICE,
                           subject=the_service_that_was_restarted)
        ))


@pytest.mark.unit
def test_an_attempt_of_a_kind_this_version_cannot_read_is_dropped() -> None:
    # The kind is a column of text, so an incident old enough can hand back a
    # kind some version since removed. The row is history and still has to come
    # out of the table - but nothing later could match it, because matching it
    # means proposing an action of a kind this Argus no longer has.
    the_flag_that_was_named = "new-checkout-flow"
    a_kind_nobody_has_any_more = an_action("io-shop", Verdict.REFUTED) \
        .model_copy(update={"type": "adjust-the-thermostat"})

    Scenario() \
        .given(an_alert()) \
        .when(lambda: a_memory_of(
            SOME_INCIDENT,
            an_alert(),
            [an_action(the_flag_that_was_named, Verdict.REFUTED),
             a_kind_nobody_has_any_more],
            described_as=DONT_CARE_DESCRIPTION
        )) \
        .then(all_of(
            _it_remembers_trying(the_flag_that_was_named),
            _it_remembers_this_many_attempts(1)
        ))


@pytest.mark.unit
def test_the_record_carries_what_the_search_narrows_by() -> None:
    # The description is what a later incident is compared against, and the
    # service and alert name are what a search narrows to before it compares
    # anything. All three come from here or from nowhere.
    the_service_it_happened_to = "io-shop"
    the_alert_that_opened_it = "HighErrorRate"
    the_description_it_is_found_by = "checkout began failing after a flag was switched on"

    Scenario() \
        .given(an_alert(the_alert_that_opened_it, the_service_it_happened_to)) \
        .when(lambda: a_memory_of(
            SOME_INCIDENT,
            an_alert(the_alert_that_opened_it, the_service_it_happened_to),
            [an_action("new-checkout-flow", Verdict.REFUTED)],
            described_as=the_description_it_is_found_by
        )) \
        .then(all_of(
            _it_is_the_incident(SOME_INCIDENT),
            _it_is_described_as(the_description_it_is_found_by),
            _it_happened_to(the_service_it_happened_to),
            _it_was_opened_by(the_alert_that_opened_it)
        ))


def _a_record(remembered: RememberedIncident | None) -> RememberedIncident:
    if remembered is None:
        raise AssertionError("expected an incident to be remembered, got nothing")

    return remembered


def _it_remembers_doing(expected: ActionIdentity) -> Assertion[RememberedIncident | None]:
    def assertion(remembered: RememberedIncident | None) -> bool:
        done = [attempt.identity for attempt in _a_record(remembered).tried]

        if expected not in done:
            raise AssertionError(f"expected [{expected}] among {done}")

        return True

    return assertion


def _it_remembers_trying(subject: str) -> Assertion[RememberedIncident | None]:
    def assertion(remembered: RememberedIncident | None) -> bool:
        subjects = [attempt.identity.subject for attempt in _a_record(remembered).tried]

        if subject not in subjects:
            raise AssertionError(f"expected [{subject}] among {subjects}")

        return True

    return assertion


def _it_remembers_the_verdict(verdict: Verdict) -> Assertion[RememberedIncident | None]:
    def assertion(remembered: RememberedIncident | None) -> bool:
        verdicts = [attempt.verdict for attempt in _a_record(remembered).tried]

        if verdict not in verdicts:
            raise AssertionError(f"expected [{verdict}] among {verdicts}")

        return True

    return assertion


def _it_remembers_this_many_attempts(expected: int) -> Assertion[RememberedIncident | None]:
    def assertion(remembered: RememberedIncident | None) -> bool:
        tried = _a_record(remembered).tried

        if len(tried) != expected:
            raise AssertionError(f"expected [{expected}] attempts, got {tried}")

        return True

    return assertion


def _nothing_is_remembered() -> Assertion[RememberedIncident | None]:
    def assertion(remembered: RememberedIncident | None) -> bool:
        if remembered is not None:
            raise AssertionError(f"expected nothing to be remembered, got [{remembered}]")

        return True

    return assertion


def _it_is_the_incident(incident_id: str) -> Assertion[RememberedIncident | None]:
    def assertion(remembered: RememberedIncident | None) -> bool:
        recorded = _a_record(remembered).incident_id

        if recorded != incident_id:
            raise AssertionError(f"expected [{incident_id}], got [{recorded}]")

        return True

    return assertion


def _it_is_described_as(description: str) -> Assertion[RememberedIncident | None]:
    def assertion(remembered: RememberedIncident | None) -> bool:
        described_as = _a_record(remembered).described_as

        if described_as != description:
            raise AssertionError(f"expected [{description}], got [{described_as}]")

        return True

    return assertion


def _it_happened_to(service: str) -> Assertion[RememberedIncident | None]:
    def assertion(remembered: RememberedIncident | None) -> bool:
        recorded = _a_record(remembered).service

        if recorded != service:
            raise AssertionError(f"expected [{service}], got [{recorded}]")

        return True

    return assertion


def _it_was_opened_by(alert_name: str) -> Assertion[RememberedIncident | None]:
    def assertion(remembered: RememberedIncident | None) -> bool:
        recorded = _a_record(remembered).alert_name

        if recorded != alert_name:
            raise AssertionError(f"expected [{alert_name}], got [{recorded}]")

        return True

    return assertion
