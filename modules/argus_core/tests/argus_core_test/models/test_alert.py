"""What an alert has to carry, and what it is allowed to leave out.

The first thing Argus is ever told about an incident, and the only one it does
not produce itself: a monitoring system sends it. So the two questions worth
asking of the model are the two a sender can get wrong - what may be omitted,
and what may not.
"""
from __future__ import annotations

import pytest
from argus_core.models.alert import AlarmClaim, Alert
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from pydantic import ValidationError


@pytest.mark.unit
def test_an_alert_that_said_no_more_than_it_had_to_assumes_nothing() -> None:
    # `severity` and `summary` are the sender's to add, and most senders do not.
    # Defaulted to anything else, a walk would report a severity nobody stated.
    Scenario() \
        .given(
            some_service := "checkout",
            some_alert_name := "HighErrorRate"
        ) \
        .when(
            lambda: Alert(service=some_service, alert_name=some_alert_name)
        ) \
        .then(
            _nothing_was_assumed_about(
                "severity", "summary", "stale_entry_keys", "stale_entries_found", "rule"
            )
        )


@pytest.mark.unit
def test_an_alert_saying_nothing_about_its_rule_is_taken_to_watch_a_series() -> None:
    # The one field here whose omission means something rather than nothing, and
    # it has to: what a rule looked at decides whether a window with no departure
    # in it is evidence against that rule or no evidence at all. A sender that
    # says nothing is a threshold rule, because that is what almost every rule in
    # any monitoring stack is - and taking silence for a finding instead would
    # make a well service unfalsifiable.
    #
    # Asserted as the series reading rather than as "not None", which is the
    # posture every other optional field is tested for above. A default of `None`
    # here would push the decision onto each consumer, and two consumers reading
    # one silence differently is the failure this field exists to prevent.
    Scenario() \
        .given(
            some_service := "checkout",
            some_alert_name := "HighErrorRate"
        ) \
        .when(
            lambda: Alert(service=some_service, alert_name=some_alert_name)
        ) \
        .then(
            _the_claim_was(AlarmClaim.A_SERIES_CONDITION)
        )


@pytest.mark.unit
def test_an_alert_naming_no_service_is_refused() -> None:
    # The service is what every retrieval is about. An alert without one would
    # be an incident nothing could be read for.
    Scenario() \
        .given(
            some_alert_name := "HighErrorRate"
        ) \
        .when(
            attempting(
                lambda: Alert.model_validate({"alert_name": some_alert_name})
            )
        ) \
        .then(
            an_error_was_raised(ValidationError)
        )


@pytest.mark.unit
def test_an_alert_whose_key_list_is_shorter_than_its_own_count_is_refused() -> None:
    # The one failure a payload of exact strings actually has. A list of
    # addresses can be truncated by anything between the check and here - a
    # serialiser's limit, a log line's width, a field somebody capped - and the
    # result is not malformed. It is a shorter list of real keys, which reads as
    # a smaller incident and is acted on as one, leaving entries nobody will look
    # at again until the next scheduled check.
    #
    # Nothing downstream can catch it, which is why the count is carried beside
    # the keys at all: the two fields say the same thing twice so that they can
    # be made to disagree.
    Scenario() \
        .given(
            some_service := "checkout",
            some_alert_name := "CachedFiguresAreStale",
            two_keys := ("io:summary:s-0001", "io:summary:s-0002")
        ) \
        .when(
            attempting(
                lambda: Alert(
                    service=some_service,
                    alert_name=some_alert_name,
                    stale_entry_keys=two_keys,
                    stale_entries_found=len(two_keys) + 1
                )
            )
        ) \
        .then(
            an_error_was_raised(ValidationError)
        )


@pytest.mark.unit
def test_an_alert_carrying_stale_keys_keeps_every_one_of_them_in_order() -> None:
    # The keys are the only thing in an alert that is an address rather than a
    # description, and Argus must compose none of them: the format belongs to
    # whoever wrote the cache, and a consumer that derived a key would be a
    # consumer holding another service's internals. So they are carried
    # verbatim, and this is the only place that can say they were.
    #
    # Deliberately not a set. Two keys arriving in the order the check found them
    # is what lets an action be sent one call for all of them, and a collection
    # that reordered or collapsed them would be a different set of entries
    # wearing the same count.
    Scenario() \
        .given(
            some_service := "checkout",
            some_alert_name := "CachedFiguresAreStale",
            the_keys := (
                "io:summary:s-0007", "io:summary:s-0002", "io:summary:s-0007"
            )
        ) \
        .when(
            lambda: Alert(
                service=some_service,
                alert_name=some_alert_name,
                stale_entry_keys=the_keys,
                stated_onset=None,
                stale_entries_found=len(the_keys)
            )
        ) \
        .then(
            _the_keys_came_back(the_keys)
        )


def _the_claim_was(expected: AlarmClaim) -> Assertion[Alert]:
    """That the alert reports the kind of claim its rule made.

    Identity against the member rather than against its wire spelling: what a
    consumer branches on is the member, and a test matching the string would go
    on passing if the two ever came apart.
    """
    def assertion(alert: Alert) -> bool:
        if alert.claim is not expected:
            raise AssertionError(
                f"Expected an alert that said nothing about its rule to claim "
                f"{expected}, got {alert.claim} - what a rule looked at decides "
                f"whether a window with no departure refutes it, so a silence "
                f"read the other way makes a well service unfalsifiable."
            )

        return True

    return assertion


def _nothing_was_assumed_about(*fields: str) -> Assertion[Alert]:
    """That each named field came back `None` rather than filled in.

    Named together rather than checked one at a time, because the claim is
    about the model's posture towards what it was not told - and a field that
    quietly grew a default would pass a test written about its neighbour.
    """
    def assertion(alert: Alert) -> bool:
        assumed = {field: getattr(alert, field) for field in fields}
        filled = {field: value for field, value in assumed.items() if value is not None}

        if filled:
            raise AssertionError(f"Expected nothing assumed, got {filled}.")

        return True

    return assertion


def _the_keys_came_back(expected: tuple[str, ...]) -> Assertion[Alert]:
    """That the keys arrived exactly as sent - same keys, same order, all of them.

    Identity rather than membership, and it is the point of the field. These are
    addresses an action will be sent to and nothing downstream can check one: a
    list that arrived sorted, de-duplicated or shortened is still a list of
    plausible keys, and the only place the mistake is visible is here.
    """
    def assertion(alert: Alert) -> bool:
        if alert.stale_entry_keys != expected:
            raise AssertionError(
                f"Expected the keys {expected} exactly, got "
                f"{alert.stale_entry_keys} - these are addresses to be acted on, "
                f"so a list that came back reordered or short is a different set "
                f"of entries from the one the check found."
            )

        return True

    return assertion
