"""A model upgrade that files purchases worse, end to end.

Io upgraded the categoriser that files every purchase into an aisle. The new model
was trained on titles tokenised one way and is served them another, so most of
what it is handed matches nothing it knows: it files the purchase under "General"
and says it was not sure. Nothing fails and nothing slows - filing a purchase costs
the same whichever model does it - so the error rate, every latency quantile,
memory and CPU are where they always were. The one series that moves is the
categoriser's own share of confident answers, and the shop's rule watches it.

Three things this case pins that no other one can.

**An onset dated on the rule's series alone.** Every other series alarm here has a
fixed signal that departs. This one's departure is in the series the rule that
paged evaluates and nowhere else, so an onset exists only because the walk read
that series - and it has to fall where the series fell.

**A cause told apart by which signal moved.** A revision that went out just before
the onset is what a bad deployment looks like too. What separates the two is that
requests are not failing or slowing, and the cause asserted is the one that says
so.

**Mitigated by a rollback the rule agreed with.** The rollback puts the earlier
model back and the share recovers, so the incident ends `mitigated` - judged by
the rule that paged, since no other series ever moved to recover. The upgrade is
still on the branch, which is why a fix is proposed afterwards.

Run under `both` only, like the undated finding: one recording rather than three
of one assertion that does not vary by which tool found the file.
"""

from __future__ import annotations

import httpx2
import pytest
from argus_core.events import FixAttempted, OnsetDetected
from argus_core.models import FailureMode, FixOutcome, IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_OUTPUT_QUALITY_DEGRADATION,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_took_a_rollback_of,
    argus_wrote_a_postmortem,
    cause_identified_as,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import (
    a_scenario_was_seeded,
    the_incidents_events,
    the_shops_window,
)

# What the shop's own monitoring pages on here: its rule on the share of purchases
# filed with confidence, which no other scenario trips.
A_CONFIDENCE_ALERT = "CategorisationConfidenceLow"

# The shop's name for the series its rule watches, as its own metrics report it.
# Read straight from the shop rather than through Argus, for the reason every
# reading in `world` is.
THE_RULES_SERIES = "categoriser_confident_ratio"

# How far from the minute the filing fell the onset may be dated. The minute the
# upgrade lands in is filed partly by each model and reads between the two, so it
# can sit on either side of halfway - and the detector can date that minute or the
# one after it. One minute either way is that ramp and nothing more.
THE_ONSET_MAY_BE_MINUTES_AWAY = 1


@pytest.mark.e2e
def test_a_categoriser_upgrade_that_files_purchases_worse_is_rolled_back() -> None:
    some_severity = "warning"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=A_CONFIDENCE_ALERT,
                                            severity=some_severity)

    # The scenario's id is also the recording's name, so one constant serves both.
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(RECORDED_OUTPUT_QUALITY_DEGRADATION)),
            calling(the_model_answers_from(RECORDED_OUTPUT_QUALITY_DEGRADATION))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    cause_identified_as(FailureMode.OUTPUT_QUALITY_DEGRADATION),
                    _the_onset_is_where_the_filing_fell(),
                    argus_took_a_rollback_of(THE_SERVICE_NAME),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    _a_fix_was_proposed(),
                    argus_wrote_a_postmortem()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_onset_is_where_the_filing_fell() -> Assertion[httpx2.Response]:
    """The incident is dated where the rule's series fell, read off the shop.

    "Fell" is split at halfway between the window's highest and lowest share
    rather than at a threshold copied out of the shop's rule, so what is asserted
    is a relation between the onset and the series: the walk dated the minute
    the series moved, not the minute the alert fired and not the window's edge.

    The first onset the walk published, because that is the one the
    investigation measured and every window after it is anchored on.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        onsets = [
            event.onset for event in the_incidents_events(incident_id)
            if isinstance(event, OnsetDetected)
        ]

        if not onsets:
            raise AssertionError(
                f"Incident [{incident_id}] never dated an onset, so the rule's "
                f"series either was not read or was read and not judged."
            )

        minutes = _the_minutes_the_series_reports()
        shares = [share for _, share in minutes]
        halfway = (max(shares) + min(shares)) / 2
        fell_at = next(
            (index for index, (_, share) in enumerate(minutes) if share < halfway), None
        )

        if fell_at is None:
            raise AssertionError(
                f"Expected the share filed confidently to fall past halfway between "
                f"its highest and lowest, and it never did. The shop's minutes were "
                f"{minutes}."
            )

        near_it = [
            bucket_id for bucket_id, _ in minutes[
                max(0, fell_at - THE_ONSET_MAY_BE_MINUTES_AWAY):
                fell_at + THE_ONSET_MAY_BE_MINUTES_AWAY + 1
            ]
        ]

        if onsets[0] not in near_it:
            raise AssertionError(
                f"Expected the onset within a minute of [{minutes[fell_at][0]}], "
                f"where the share filed confidently fell past halfway, and it was "
                f"dated [{onsets[0]}]. The shop's minutes were {minutes}."
            )

        return True

    return assertion


def _a_fix_was_proposed() -> Assertion[httpx2.Response]:
    """The rollback put the earlier model back; the upgrade is still on the branch.

    So the walk carries on to Code-Fix, and Code-Fix opens something. Any attempt
    proposed rather than the last, since a later round may ask again.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        attempts = [
            event for event in the_incidents_events(incident_id)
            if isinstance(event, FixAttempted)
        ]

        if not any(attempt.outcome is FixOutcome.PROPOSED for attempt in attempts):
            raise AssertionError(
                f"Expected Code-Fix to have proposed a fix for incident "
                f"[{incident_id}], since the upgrade is still on the branch. It "
                f"reported {[(attempt.outcome, attempt.detail) for attempt in attempts]}."
            )

        return True

    return assertion


def _the_minutes_the_series_reports() -> list[tuple[str, float]]:
    """Each minute the shop filed anything in, beside the share it filed confidently.

    A minute with no purchases has no share, and is left out rather than read as
    a share of nothing.
    """
    minutes = [
        (minute["bucket_id"], minute[THE_RULES_SERIES])
        for minute in the_shops_window()
        if minute.get(THE_RULES_SERIES) is not None
    ]

    if not minutes:
        raise AssertionError(
            f"The shop reported no minute carrying [{THE_RULES_SERIES}], so there "
            f"is no series to date an onset against."
        )

    return minutes
