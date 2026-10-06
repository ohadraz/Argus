"""The blind spot whose answer is not a rollback, end to end.

The same silence as `test_a_monitoring_blind_spot_is_ended.py`, from a change
that was meant. A revision names every port in Io's deployment for the protocol
it carries - the platform's convention, applied across the estate - and the
scrape configuration in the repository still selects the metrics port by its
old name. The shop goes on trading exactly as it was, and from the minute the
revision landed `/metrics` carries no row at all.

Everything a responder can see is the blind spot's: the absence alert, the rows
stopping at the onset, the logs answering across the missing minutes, one
revision at that minute. Only the diff differs - a rule applied rather than one
value changed - and so does what is owed. Rolling the revision back would bring
the rows back by undoing somebody's work, and a rollback is right there to take:
the deployment history names the revision before, and the platform would accept
it.

So what this case pins is a walk that declines a move it could make.

**That the cause is the watching, not the revision.** Named as
`monitoring-configuration-drift`, which no mitigation answers.

**That nothing is taken.** Not the rollback, and not anything a lower-ranked
explanation would have reached for: a mode nothing answers ends the mitigation
phase rather than passing to the next candidate.

**That the scrape configuration is proposed forward.** A draft pull request
writing `deploy/scrape.yaml` - the change nobody here may make, handed to
somebody who may.

**That the sight is still lost when it ends.** The hole in the window is open at
the close, which is the honest outcome: a proposal is not merged, so nothing has
brought the collecting back, and the incident escalates holding that proposal.

Run the two ways every case here is. Under `nox -s e2e_replay` a green run proves
the path exists. Under `nox -s e2e` a real model reads a convention diff and
decides for itself whether the change it is looking at was a mistake.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx2
import psycopg
import pytest
from argus_core import utc_now
from argus_core.events import ActionTaken, FixAttempted
from argus_core.models import FailureMode, FixOutcome, IncidentStatus
from argus_incidents.repository import events
from argus_testkit import Assertion, Scenario, all_of, calling, eventually
from github_double.server import DEFAULT_BASE_URL as GITHUB_DOUBLE_BASE_URL

from tests.e2e.framework.argus import (
    DATABASE_URL,
    RECORDED_MONITORING_CONFIGURATION_DRIFT,
    REQUEST_TIMEOUT_SECONDS,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_wrote_a_postmortem,
    cause_identified_as,
    incident_id_from,
    the_model_answers_from,
    the_shop_raises_its_own_alert,
)
from tests.e2e.framework.world import a_scenario_was_seeded, the_shops_window

# The scenario, named as the Target Service registers it.
A_SHOP_RENAMED_TO_THE_CONVENTION = "monitoring-configuration-drift"

# How long the window has to have been silent at the close for the hole to still
# be open. The blind-spot case asks the same of the stretch it saw close; here it
# is asked of the stretch that never did.
A_HOLE_WORTH_PAGING_FOR = timedelta(minutes=3)

# The two commits this scenario's deployment history names, and the one path
# between them. Written here because this is the case that chose them: the shop
# stages the same pair under its own names, and these are the only other place
# they appear.
BEFORE_THE_CONVENTION = "f061a97b221b57258899d4b3d82998815008d7bf"
THE_CONVENTION = "53f02e9f6cb774f7f5869637bcc879941dcbc82d"

# The diff is the whole of what separates this case from the blind spot: every
# port renamed to one rule, with the rule stated, rather than one name changed.
THE_MANIFEST = "deploy/values-production.yaml"
THE_PORTS_BEFORE = (
    "ports:\n"
    "  web:\n    port: 8000\n    portName: web\n"
    "  admin:\n    port: 8081\n    portName: admin\n"
    "  metrics:\n    port: 9090\n    portName: metrics\n"
)
THE_PORTS_AFTER = (
    "# Every port is named for the protocol it carries, then what it is for:\n"
    "# `<protocol>[-<purpose>]`. The platform's convention, applied estate-wide.\n"
    "ports:\n"
    "  web:\n    port: 8000\n    portName: http\n"
    "  admin:\n    port: 8081\n    portName: http-admin\n"
    "  metrics:\n    port: 9090\n    portName: http-metrics\n"
)

# The file a roll-forward has to write: the monitoring's own configuration.
THE_SCRAPE_CONFIGURATION = "deploy/scrape.yaml"


@pytest.mark.e2e
def test_a_rename_the_monitoring_did_not_follow_is_fixed_forward_not_rolled_back() -> None:
    # The alert is raised by the shop rather than built here, for the reason the
    # blind-spot case gives: the rows stop, so nothing measures an onset, and the
    # minute the alert states is the only thing dating the incident.
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(A_SHOP_RENAMED_TO_THE_CONVENTION)),
            calling(the_model_answers_from(RECORDED_MONITORING_CONFIGURATION_DRIFT)),
            calling(_the_deployment_history_was_staged())
        ) \
        .when(
            the_shop_raises_its_own_alert()
        ) \
        .then(
            eventually(
                all_of(
                    cause_identified_as(FailureMode.MONITORING_CONFIGURATION_DRIFT),
                    argus_ended_with_status(IncidentStatus.ESCALATED),
                    _argus_took_no_action(),
                    _argus_proposed_a_fix_to(THE_SCRAPE_CONFIGURATION),
                    # The scrape still asks for the old port name, and the fix is
                    # only proposed - nothing merged it.
                    _metrics_still_not_collected(),
                    argus_wrote_a_postmortem()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_deployment_history_was_staged() -> Callable[[], bool]:
    """Puts this scenario's two commits into the repository double.

    Staged by the case rather than held by the double, for the reason the
    blind-spot case gives: they are this scenario's facts and nothing else's.
    """
    def stage_them() -> bool:
        return all(
            httpx2.post(
                f"{GITHUB_DOUBLE_BASE_URL}/double-control/stage-commit",
                json={"sha": sha, "files": {THE_MANIFEST: manifest}},
                timeout=REQUEST_TIMEOUT_SECONDS
            ).status_code == HttpStatus.OK
            for sha, manifest in (
                (BEFORE_THE_CONVENTION, THE_PORTS_BEFORE),
                (THE_CONVENTION, THE_PORTS_AFTER)
            )
        )

    return stage_them


def _argus_took_no_action() -> Assertion[httpx2.Response]:
    """No action of any kind, read from the incident's own account.

    Any action rather than a rollback in particular. The rollback is the one the
    walk would reach for, but a walk that declined it and restarted the shop
    instead would have acted on an explanation the diagnosis ranked lower - which
    is the failure this case exists to catch, in a different spelling.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        taken = [
            event for event in _the_events_of(incident_id)
            if isinstance(event, ActionTaken)
        ]

        if taken:
            raise AssertionError(
                f"Expected incident [{incident_id}] to take nothing, and it took "
                f"{[(event.action_type, event.subject) for event in taken]}."
            )

        return True

    return assertion


def _argus_proposed_a_fix_to(path: str) -> Assertion[httpx2.Response]:
    """A proposal, and one that writes the monitoring's configuration.

    Both halves. A proposal that touched only the shop's source would be a fix to
    a service that was never wrong, and a branch that holds the scrape
    configuration without a proposal is a change nobody was asked to review.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        attempts = [
            event for event in _the_events_of(incident_id)
            if isinstance(event, FixAttempted)
        ]

        if not attempts:
            raise AssertionError(
                f"Incident [{incident_id}] has no account of Code-Fix at all, so "
                f"the walk ended without asking for the change that is owed."
            )

        attempted = attempts[-1]

        if attempted.outcome is not FixOutcome.PROPOSED:
            raise AssertionError(
                f"Expected a fix to be proposed, and Code-Fix reported "
                f"[{attempted.outcome}]: {attempted.detail}"
            )

        if attempted.pull_request is None:
            raise AssertionError(
                f"Code-Fix reported [{FixOutcome.PROPOSED}] and named no pull "
                f"request, so nobody reading the incident could go and open it."
            )

        written = _the_files_on(attempted.pull_request.branch)

        if path not in written:
            raise AssertionError(
                f"Expected the proposal to write [{path}], "
                f"and branch [{attempted.pull_request.branch}] holds {written}."
            )

        return True

    return assertion


def _metrics_still_not_collected() -> Assertion[httpx2.Response]:
    """The shop's newest minute is old.

    The outcome only. That the window stops at the onset in the first place is the
    scenario's staging, and the demo app's own suite asserts it.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        published = sorted(
            datetime.fromisoformat(minute["bucket_id"].replace("Z", "+00:00"))
            for minute in the_shops_window()
        )

        if published and utc_now() - published[-1] < A_HOLE_WORTH_PAGING_FOR:
            raise AssertionError(
                f"Expected the shop to be uncollected still, and its newest "
                f"minute [{published[-1]}] is under [{A_HOLE_WORTH_PAGING_FOR}] "
                f"old - so something brought the collecting back."
            )

        return True

    return assertion


def _the_events_of(incident_id: str) -> list[Any]:
    with psycopg.connect(DATABASE_URL) as conn:
        published: list[Any] = events.get_by_incident(conn, incident_id)

    return published


def _the_files_on(branch: str) -> list[str]:
    response = httpx2.get(
        f"{GITHUB_DOUBLE_BASE_URL}/double-control/branches",
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    written: dict[str, list[str]] = response.json()["branches"]

    return written.get(branch, [])
