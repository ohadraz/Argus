"""Grafana's webhook payload, read as the one alert Argus works from.

The outermost edge of the system: a vendor's shape arrives here and nothing
downstream is allowed to know it. So both questions are about the boundary
rather than about the parsing - that the fields Argus needs were found where
Grafana puts them, and that Grafana's own nesting stopped here.

The second is the one with teeth. An `Alert` that carried `labels` through
would let every later reader reach for `alert.labels["service"]` instead of
`alert.service`, and the vendor's shape would be load-bearing everywhere by
the time anybody noticed.
"""

from __future__ import annotations

import pytest
from argus_core import to_iso
from argus_core.models import AlarmClaim, Alert
from argus_testkit import Assertion, Scenario
from argus_web.grafana import parse_grafana_alert, reports_only_resolutions

from argus_web_test.framework.builders import a_grafana_payload

SOME_RULE = "some-rule"


@pytest.mark.unit
def test_parse_grafana_alert_maps_labels_to_alert_fields() -> None:
    some_service = "checkout"
    some_alert_name = "HighErrorRate"

    Scenario() \
        .given(
            payload := a_grafana_payload(service=some_service, alert_name=some_alert_name)
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_read(
                service=some_service, alert_name=some_alert_name, severity="critical"
            )
        )


@pytest.mark.unit
def test_parse_grafana_alert_does_not_leak_grafana_labels_nesting() -> None:
    Scenario() \
        .given(
            payload := a_grafana_payload()
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _nothing_of_grafanas_came_through("labels")
        )


@pytest.mark.unit
def test_parse_grafana_alert_reads_an_onset_the_alert_states() -> None:
    # Almost no alert states one, and this is why the field exists at all: a
    # rule that fires on a series reports a minute Argus measures for itself,
    # where a check reporting what it found says when the writing went wrong
    # and fired a week later. `startsAt` is the second of those and cannot be
    # the first, so the onset travels beside it rather than in it.
    stated_onset = "2026-09-22T14:10:00Z"

    Scenario() \
        .given(
            payload := a_grafana_payload(onset=stated_onset)
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_read_an_onset_of(stated_onset)
        )


@pytest.mark.unit
def test_parse_grafana_alert_leaves_the_onset_unset_when_none_is_stated() -> None:
    # The ordinary alert, and the branch every existing incident takes. An
    # onset invented here would be a measured minute's rival with none of its
    # evidence - and worse, it would be `startsAt`, which is when somebody
    # noticed rather than when it began.
    Scenario() \
        .given(
            payload := a_grafana_payload()
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_read_an_onset_of(None)
        )


@pytest.mark.unit
def test_parse_grafana_alert_reads_the_stale_cache_keys_an_alert_names() -> None:
    # One annotation holding a comma-separated list, which is what a check
    # templating its finding into an alert actually produces. The keys are
    # addresses rather than descriptions: the format belongs to whoever wrote the
    # cache, so the parser lifts them and composes none.
    #
    # The count travels beside them and is not redundant. Split this list on the
    # wrong character and it comes out longer than the count; truncate it and it
    # comes out shorter. Either way the alert refuses itself, which is the only
    # place either mistake is visible.
    the_keys = ("io:summary:s-0007", "io:summary:s-0002")

    Scenario() \
        .given(
            payload := a_grafana_payload(stale_entry_keys=the_keys)
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_read_the_stale_keys(the_keys)
        )


@pytest.mark.unit
def test_parse_grafana_alert_leaves_the_stale_keys_unset_when_none_are_named() -> None:
    # Every alert that is not this one mode's. Unset rather than empty, as the
    # onset is: an empty tuple would say a check compared a cache against its
    # records and found everything in order, which no ordinary alert claims.
    Scenario() \
        .given(
            payload := a_grafana_payload()
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_read_the_stale_keys(None)
        )


@pytest.mark.unit
def test_parse_grafana_alert_reads_the_kind_of_claim_a_rule_makes() -> None:
    # What a rule looked at is the one thing about an alert that decides whether
    # a window holding no departure contradicts it. A check comparing stored
    # totals against the records behind them is not contradicted by any series,
    # because no series was ever its subject - and only the rule knows that, so
    # only the rule can say it.
    Scenario() \
        .given(
            payload := a_grafana_payload(claim=AlarmClaim.ITS_OWN_FINDING)
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_read_a_claim_of(AlarmClaim.ITS_OWN_FINDING)
        )


@pytest.mark.unit
def test_parse_grafana_alert_takes_an_unspoken_claim_for_a_series_condition() -> None:
    # Every alert that exists today, and the reason the default is this way
    # round. Read as a finding instead, a well service would be unfalsifiable:
    # nothing Argus retrieves could ever contradict an alarm about something no
    # series carries, so every spurious page would survive its own refutation.
    Scenario() \
        .given(
            payload := a_grafana_payload()
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_read_a_claim_of(AlarmClaim.A_SERIES_CONDITION)
        )


@pytest.mark.unit
def test_parse_grafana_alert_takes_a_claim_it_does_not_recognise_the_same_way() -> None:
    # A rule from a stack nobody here configured, which is the case the default
    # exists for rather than an error to refuse. Argus is not the only thing
    # writing rules against this estate, and an alert rejected at the boundary is
    # an incident nobody is told about.
    Scenario() \
        .given(
            payload := a_grafana_payload(claim="whatever-some-other-tool-writes")
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_read_a_claim_of(AlarmClaim.A_SERIES_CONDITION)
        )


@pytest.mark.unit
def test_parse_grafana_alert_reads_the_rule_the_alert_names() -> None:
    # Which rule fired, so that whether it has stopped firing can be asked of it.
    # Carried as a reference that names no vendor: a mitigation judged by the
    # rule reaches it through a port, and Grafana is one adapter behind it.
    Scenario() \
        .given(
            payload := a_grafana_payload(rule_uid=SOME_RULE)
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_names_the_rule(SOME_RULE)
        )


@pytest.mark.unit
def test_parse_grafana_alert_finds_the_rule_in_the_link_the_documentation_shows() -> None:
    # Grafana's webhook has no field naming the rule; the link to it does. The
    # documentation shows that link as `/alerting/<uid>/edit` where the releases
    # build `/alerting/grafana/<uid>/view`, so what follows the uid is not read.
    some_rule = "1afz29v7z"

    Scenario() \
        .given(
            payload := a_grafana_payload(
                generator_url=f"https://play.grafana.org/alerting/{some_rule}/edit"
            )
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_names_the_rule(some_rule)
        )


@pytest.mark.unit
@pytest.mark.parametrize("generator_url", [
    # Served under a path of its own, behind a proxy that hosts other things.
    f"https://ops.example/grafana/alerting/grafana/{SOME_RULE}/view",
    f"https://grafana.example/alerting/grafana/{SOME_RULE}/",
    f"https://grafana.example/alerting/grafana/{SOME_RULE}"
])
def test_parse_grafana_alert_finds_the_rule_wherever_grafana_is_served_and_however_the_link_ends(
    generator_url: str
) -> None:
    Scenario() \
        .given(
            payload := a_grafana_payload(generator_url=generator_url)
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_names_the_rule(SOME_RULE)
        )


@pytest.mark.unit
@pytest.mark.parametrize("generator_url", [
    "https://grafana.example/d/some-dashboard",
    "https://grafana.example/alerting/",
    "https://grafana.example/alerting/grafana/"
])
def test_parse_grafana_alert_names_no_rule_from_a_link_that_names_none(
    generator_url: str
) -> None:
    # A link elsewhere, or to the alerting pages with no rule in it. Read as a
    # rule regardless, whatever segment was found would be asked after as one.
    Scenario() \
        .given(
            payload := a_grafana_payload(generator_url=generator_url)
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_names_the_rule(None)
        )


@pytest.mark.unit
def test_parse_grafana_alert_reads_the_alert_that_is_firing() -> None:
    # A notification carries every alert of its group, and one that resolved can
    # come first. It never starts an incident, so the one read is the one firing.
    the_rule = "some-rule-still-firing"
    some_resolved = a_grafana_payload(rule_uid="some-rule-that-resolved", status="resolved")
    some_firing = a_grafana_payload(rule_uid=the_rule)

    Scenario() \
        .given(
            payload := {**some_firing, "alerts": [*some_resolved["alerts"], *some_firing["alerts"]]}
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_names_the_rule(the_rule)
        )


@pytest.mark.unit
def test_parse_grafana_alert_names_no_rule_when_the_alert_names_none() -> None:
    # Unset rather than guessed from the alert's name, which is a title several
    # rules can share.
    Scenario() \
        .given(
            payload := a_grafana_payload()
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_names_the_rule(None)
        )


@pytest.mark.unit
def test_a_notification_of_resolved_alerts_alone_reports_only_resolutions() -> None:
    some_resolved = a_grafana_payload(rule_uid="some-rule-that-resolved", status="resolved")
    some_other_resolved = a_grafana_payload(rule_uid="some-other-rule", status="resolved")

    Scenario() \
        .given(
            payload := {
                **some_resolved,
                "alerts": [*some_resolved["alerts"], *some_other_resolved["alerts"]]
            }
        ) \
        .when(
            lambda: reports_only_resolutions(payload)
        ) \
        .then(
            _it_reports_only_resolutions(True)
        )


@pytest.mark.unit
def test_a_notification_with_one_alert_still_firing_reports_more_than_resolutions() -> None:
    # The envelope here reads `resolved`, and is not what decides: the one
    # alert still firing is what opens an incident.
    some_resolved = a_grafana_payload(rule_uid="some-rule-that-resolved", status="resolved")
    some_firing = a_grafana_payload(rule_uid="some-rule-still-firing")

    Scenario() \
        .given(
            payload := {
                **some_resolved,
                "alerts": [*some_resolved["alerts"], *some_firing["alerts"]]
            }
        ) \
        .when(
            lambda: reports_only_resolutions(payload)
        ) \
        .then(
            _it_reports_only_resolutions(False)
        )


@pytest.mark.unit
@pytest.mark.parametrize("payload", [
    {**a_grafana_payload(), "alerts": []},
    {key: value for key, value in a_grafana_payload().items() if key != "alerts"}
], ids=["empty", "absent"])
def test_a_notification_of_no_alerts_reports_only_resolutions(payload: dict[str, object]) -> None:
    # Nothing in it is firing, so it opens nothing: answered as a notification
    # of resolutions is, rather than refused.
    Scenario() \
        .when(
            lambda: reports_only_resolutions(payload)
        ) \
        .then(
            _it_reports_only_resolutions(True)
        )


def _it_read(service: str, alert_name: str, severity: str) -> Assertion[Alert]:
    """The three fields lifted out of Grafana's labels, checked together.

    Together because they are read out of one nested mapping by three separate
    lookups: a parser that reached into the wrong alert of the list, or the
    wrong key, gets more than one of them wrong at once, and a run of
    assertions stopping at the first would describe a narrower fault than the
    one that happened.
    """
    def assertion(alert: Alert) -> bool:
        wanted = {"service": service, "alert_name": alert_name, "severity": severity}
        wrong = {
            field: (expected, getattr(alert, field))
            for field, expected in wanted.items()
            if getattr(alert, field) != expected
        }
        if wrong:
            raise AssertionError(
                f"Expected the alert to read {wanted}, and {wrong} differed "
                f"(expected, got)."
            )

        return True

    return assertion


def _nothing_of_grafanas_came_through(*fields: str) -> Assertion[Alert]:
    """That the vendor's own field names are absent from what Argus carries.

    Asserted by name rather than by comparing whole shapes, because what is
    being prevented is specific: a later reader finding `alert.labels` and
    using it. An `Alert` that grew other fields is not this failure.
    """
    def assertion(alert: Alert) -> bool:
        leaked = [field for field in fields if hasattr(alert, field)]

        if leaked:
            raise AssertionError(f"Expected Grafana's {leaked} not to survive parsing.")

        return True

    return assertion


def _it_read_a_claim_of(expected: AlarmClaim) -> Assertion[Alert]:
    """What the alert says its rule looked at.

    One assertion for every direction rather than a present/absent pair, for the
    reason the onset has one: the failure worth catching is a parser that answers
    the same way whatever it was handed, and a check that only asked "is it the
    default?" would pass against one that ignored the annotation entirely.
    """
    def assertion(alert: Alert) -> bool:
        if alert.claim is not expected:
            raise AssertionError(
                f"Expected the alert to claim [{expected}], got [{alert.claim}]."
            )

        return True

    return assertion


def _it_read_an_onset_of(expected: str | None) -> Assertion[Alert]:
    """What the alert says about when the incident began, or nothing.

    One assertion for both directions rather than a present/absent pair,
    because the failure worth catching is a parser that answers the same way
    whatever it was handed - and a check that only ever asked "is it set?"
    would pass against one that always set it to the time the alert fired.
    """
    def assertion(alert: Alert) -> bool:
        stated = to_iso(alert.stated_onset) if alert.stated_onset else None

        if stated != expected:
            raise AssertionError(
                f"Expected the alert to state an onset of [{expected}], got "
                f"[{stated}]."
            )

        return True

    return assertion


def _it_read_the_stale_keys(expected: tuple[str, ...] | None) -> Assertion[Alert]:
    """The keys lifted out of one annotation, exactly and in order.

    Identity rather than membership, for the reason the alert's own test gives:
    these are addresses, nothing downstream can check one, and a list that
    arrived short or reordered is still a list of plausible keys.

    `None` is asserted the same way, because the ordinary alert states none and
    an empty tuple would be the parser claiming a check ran and found nothing.
    """
    def assertion(alert: Alert) -> bool:
        if alert.stale_entry_keys != expected:
            raise AssertionError(
                f"Expected the alert to carry the stale keys [{expected}], got "
                f"[{alert.stale_entry_keys}]."
            )

        return True

    return assertion


def _it_names_the_rule(expected: str | None) -> Assertion[Alert]:
    """Which rule the alert says fired, or that it named none."""
    def assertion(alert: Alert) -> bool:
        if alert.rule != expected:
            raise AssertionError(
                f"Expected the alert to name the rule [{expected}], got [{alert.rule}]."
            )

        return True

    return assertion


def _it_reports_only_resolutions(expected: bool) -> Assertion[bool]:
    def assertion(only_resolutions: bool) -> bool:
        if only_resolutions is not expected:
            raise AssertionError(
                f"Expected the notification to report only resolutions [{expected}], "
                f"got [{only_resolutions}]."
            )

        return True

    return assertion
