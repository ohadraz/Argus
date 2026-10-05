"""The incident answered by throwing something away, end to end.

Every other mitigation here restores, adds or stops something. This one removes:
a cache in front of the shop's monthly totals is serving figures the ledger has
moved past, and the answer is to discard them so the next read works them out
again from records that never moved.

Replication to the summary cache's standby broke three hours before anybody
noticed. The primary died, the standby was promoted, and the shop has been
serving whatever the standby last managed to copy. Nothing fails and nothing
slows, so no rule fires - and no judged series says so, because the shop
publishes no telemetry window for this scenario at all. What pages Argus is the
shop's own data check, comparing what the cache holds against the purchases
behind it.

Flat and absent are one state to everything this case exercises: no level
departed, so none can come back, and the action's own receipt is the only
confirmation available either way. The stronger world is the intended one - the
scenario is meant to serve series that are present and flat - and
`generated_window()` in the shop has no branch for `cache-failed-over`, so it
falls through to the flag timeline and answers nothing. That is a fixture debt
rather than a gap in what is asserted below: every assertion here raises on an
absence instead of passing through one.

Four things this case pins that no other one can.

**A mitigation that removes.** The criterion that admits an action unasked is
membership of the declared set (spec §13) and nothing about the kind of change it
makes - which has now had to hold against a restore, an addition, a stop and a
removal. A discard records no way back, and that is a statement rather than a
gap: the figures were a copy, and writing the old ones in again would recreate
the incident.

**The write tier reaching a datastore rather than a control plane.** No platform
offers this write. A deployment platform's built-in actions reach a workload's
lifecycle and its size, and none of them reaches what a cache holds, so the
discard goes over Redis's own protocol to a third platform of its own.

**Confirmation from the action's own receipt.** The window never departed, so
there is no level to come back down and nothing a recovery rule could read -
every minute of such a window counts as recovered, which is how a walk reading
this as something else closes the incident with every page still wrong. What
settles it is the store saying how many entries it removed, which is the whole of
what was wrong.

**The onset is the promotion, not the oldest missing purchase.** The alert carries
two dates hours apart. The older one is when replication broke; a reader taking
it for the onset dates the incident from before anybody could have seen it.

What is asserted is Argus throughout, and never a figure the fixture chose. The
count discarded is compared against the count the evidence named - two things
Argus holds - plus the claim that it acted at all, because a bare relation is
satisfied by zero equals zero.
"""

from __future__ import annotations

import re
from typing import Any, Final

import httpx2
import pytest
from argus_core import parse_iso
from argus_core.events import (
    ActionTaken,
    AlertAcknowledged,
    OnsetDetected,
    StatusChanged,
)
from argus_core.models import DISCARD_CACHE_ENTRIES, FailureMode, IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_STATE_DIVERGENCE,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_wrote_a_postmortem,
    cause_identified_as,
    incident_id_from,
    the_model_answers_from,
    the_shop_raises_its_own_alert,
)
from tests.e2e.framework.world import a_scenario_was_seeded, the_incidents_events

# How many figures the store said it removed, read out of the sentence the
# attempt was recorded as.
#
# The count reaches no event as a number. `ActionTaken` carries the kind, the
# subject and the direction an action moved its subject in, and what an action
# reported *changing* lives in the detail - which is where the record of an
# attempt was deliberately put, because that sentence is where every reader of
# the incident meets it.
#
# Anchored on the verb rather than on the first bracket in the line. The sentence
# names the service in brackets too, and a pattern matching any bracket would
# read a figure out of whichever one came first.
_WHAT_THE_STORE_REMOVED: Final = re.compile(r"discarded \[(\d+)\]")


@pytest.mark.e2e
def test_a_cache_serving_figures_the_ledger_moved_past_is_discarded() -> None:
    # The alert is raised by the shop rather than built here, and that is
    # load-bearing rather than tidy. Every other case in this directory
    # assembles its own payload, because every other alert is a rule firing on a
    # series the walk measures again for itself. This one carries a finding - how
    # many entries disagree, out of how many checked, the widest gap, and the
    # minute the standby was promoted - and a payload assembled here would be the
    # test telling Argus what the check found, which is the whole of what is
    # under test.
    #
    # The scenario's id is also the recording's name, which is why one constant
    # serves both: a recording is stored under the scenario it was captured from.
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(RECORDED_STATE_DIVERGENCE)),
            calling(the_model_answers_from(RECORDED_STATE_DIVERGENCE))
        ) \
        .when(
            the_shop_raises_its_own_alert()
        ) \
        .then(
            eventually(
                all_of(
                    cause_identified_as(FailureMode.STATE_DIVERGENCE),
                    _the_onset_argus_holds_is_the_one_the_alert_stated(),
                    _the_action_that_ended_it_was_a_discard_of(THE_SERVICE_NAME),
                    _as_many_figures_went_as_the_evidence_named(),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    argus_wrote_a_postmortem()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_onset_argus_holds_is_the_one_the_alert_stated() -> Assertion[httpx2.Response]:
    """Two things Argus holds, compared against each other.

    A measured onset is preferred wherever there is one, and this window has no
    departure to measure - so the minute the alert stated is the only thing
    dating this incident, and the onset Argus published has to be it.

    The point is not that the arithmetic works. The alert carries two dates hours
    apart: the promotion, and the oldest purchase the cache never heard about.
    Only the first is the onset. An incident dated from the second is dated from
    before the standby was serving, which is before anybody could have seen
    anything - and a postmortem measuring impact from it would bill three hours
    that nobody was affected in.

    Both halves are asserted, because the comparison alone is satisfied by two
    absences: an alert that stated nothing and a walk that published nothing
    agree with each other perfectly.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        recorded = the_incidents_events(incident_id)

        stated = [
            event.alert.stated_onset for event in recorded
            if isinstance(event, AlertAcknowledged)
        ]
        published = [
            event.onset for event in recorded if isinstance(event, OnsetDetected)
        ]

        if not stated or stated[0] is None:
            raise AssertionError(
                f"The alert Argus stored for incident [{incident_id}] states no "
                f"onset, so there is nothing here the walk could have agreed "
                f"with - and the shop's check is the only thing that dates this "
                f"incident at all."
            )

        if not published:
            raise AssertionError(
                f"Incident [{incident_id}] published no onset, so the walk never "
                f"dated it. Nothing downstream can bound a window, and the "
                f"postmortem falls back to the minute somebody noticed."
            )

        if parse_iso(published[0]) != stated[0]:
            raise AssertionError(
                f"Incident [{incident_id}] is dated [{published[0]}] where its "
                f"alert stated [{stated[0]}]. Either a series departed after all "
                f"and a measured onset won, or the walk took the date "
                f"replication broke for the date the standby started serving - "
                f"which dates the incident from before anybody could have seen "
                f"it."
            )

        return True

    return assertion


def _the_action_that_ended_it_was_a_discard_of(
    service: str
) -> Assertion[httpx2.Response]:
    """The *last* action, not the only one.

    A walk that reached for something else first and was refuted is a walk that
    carried on, which is the ordinary shape of this suite. What matters is that
    the thing Argus finished on is the one that holds.

    Addressed to the service the alert named, and the gate is why that is worth
    asserting rather than assuming. Reach is asked before confirmability, so a
    discard addressed anywhere else is refused for a reason that looks nothing
    like the rule this scenario exists to exercise.

    A discard carries no direction - the entries are gone, and there is no second
    state they could have been moved to instead - so an event reporting one would
    describe a different action from the one taken.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        taken = [
            event for event in the_incidents_events(incident_id)
            if isinstance(event, ActionTaken)
        ]

        if not taken:
            raise AssertionError(
                f"Incident [{incident_id}] took no action at all, so nothing was "
                f"ever put to the question."
            )

        if (
            taken[-1].action_type != DISCARD_CACHE_ENTRIES
            or taken[-1].subject != service
        ):
            raise AssertionError(
                f"Expected the last action to be a discard addressed to "
                f"[{service}], and what was taken was "
                f"{[(event.action_type, event.subject) for event in taken]} - so "
                f"either the mode reached the wrong strategy, or the discard was "
                f"addressed somewhere the gate will not let it reach."
            )

        if taken[-1].enabled is not None:
            raise AssertionError(
                f"Expected a discard to carry no direction, and it reported "
                f"[{taken[-1].enabled}] - which tells a later round a switch was "
                f"thrown."
            )

        return True

    return assertion


def _as_many_figures_went_as_the_evidence_named() -> Assertion[httpx2.Response]:
    """The store's count against the alert's, and neither of them zero.

    Two things Argus holds, which is what lets this be asserted at all: the
    figure is the fixture's choice and no test here may name it, but the alert
    Argus stored and the receipt Argus recorded are both its own, and they have
    to agree.

    The relation alone would not do. Zero equals zero, so a discard that removed
    nothing against an alert that found nothing satisfies it perfectly while
    describing a shop still serving wrong figures - which is why the claim that
    something actually went is stated separately.

    This is the one action nothing downstream double-checks. A flag revert is
    judged by a series coming back; this is judged by its own answer, so a count
    read wrong here is a count nothing else contradicts and the incident closes
    `MITIGATED` over a shop nobody fixed.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        recorded = the_incidents_events(incident_id)

        named = [
            event.alert.stale_entries_found for event in recorded
            if isinstance(event, AlertAcknowledged)
        ]
        removed = _the_counts_the_store_reported(recorded)

        if not named or named[0] is None:
            raise AssertionError(
                f"The alert Argus stored for incident [{incident_id}] names no "
                f"count of stale entries, so there is nothing for a receipt to "
                f"be checked against."
            )

        if not removed:
            raise AssertionError(
                f"Nothing in incident [{incident_id}]'s account reports how many "
                f"figures the store removed, so the one thing that confirms this "
                f"action was never recorded."
            )

        if removed[-1] == 0:
            raise AssertionError(
                f"Incident [{incident_id}] discarded [0] figures. A zero is true "
                f"about the store and misleading about the incident: the shop is "
                f"still serving every stale figure the check found."
            )

        if removed[-1] != named[0]:
            raise AssertionError(
                f"Incident [{incident_id}] discarded [{removed[-1]}] figures "
                f"where its own evidence named [{named[0]}]. The entries the "
                f"check found stale are the entries the action was addressed to, "
                f"so a shortfall is figures left serving that Argus was told "
                f"about."
            )

        return True

    return assertion


def _the_counts_the_store_reported(recorded: list[Any]) -> list[int]:
    """Every figure a discard reported, in the order the walk recorded them.

    Read out of the sentences the transitions were narrated as, because that is
    the only place the count is. A walk refuted once and discarding again reports
    twice, so this answers a list and the caller takes the attempt the incident
    ended on.
    """
    counts: list[int] = []

    for event in recorded:
        if not isinstance(event, StatusChanged) or event.detail is None:
            continue

        found = _WHAT_THE_STORE_REMOVED.search(event.detail)

        if found is not None:
            counts.append(int(found.group(1)))

    return counts
