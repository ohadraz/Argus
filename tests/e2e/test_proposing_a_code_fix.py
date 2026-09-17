"""What Argus leaves on the repository once it has done what it can itself.

Code-Fix is the last step of the walk and the only one that ends with somebody
else's turn (spec §7.4): it reads the service's own source, and where it finds
the fault it opens a **draft** pull request for a person to review. Merging one
is outside Argus's autonomy entirely (§13), so what is asserted here is the
proposal and its draftness - read from the repository the write tier actually
called, never from what Argus wrote about itself.

Run the two ways every case here is, and they prove different things - see
`test_scenario_investigation.py` for the full statement of it. Under
`nox -s e2e_replay` the answers are replayed, so a green run proves the path
exists: the index, the read tier serving the source, the write tier writing a
branch, the proposal itself, and the account the incident keeps of where it
went. Under `nox -s e2e` a real model reads the real source and decides for
itself whether there is anything to change.

Which is why nothing below names a file, a line or a word of the fix. Whether
the model changed the right code is judgement, and judgement is measured by
`nox -s eval` over fifty samples a case - here it would be an assertion on one
recorded answer.

The repository is the GitHub double either way, which is what makes this case
free to run on every push: a pull request number, once spent on the real API,
is spent for good.

The case runs once per way of finding code, because the session is parametrized
by `CODE_SEARCH` (`nox -s "e2e_replay(mode='meaning')"`) and each mode is a
stack with a tool list of its own. Under `meaning` the model is offered no grep
at all, so a proposal opened there was localized by the index and could not have
come from anywhere else - the same argument the bad-deployment case makes about
the change channel.
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx
import psycopg
import pytest
from argus_core import get_settings
from argus_core.events import FixAttempted
from argus_core.models import FixOutcome, IncidentStatus
from argus_incidents.repository import events
from argus_testkit import Assertion, Scenario, all_of, calling, eventually
from github_double.server import DEFAULT_BASE_URL as GITHUB_DOUBLE_BASE_URL

from tests.e2e.framework.argus import (
    DATABASE_URL,
    RECORDED_FLAG_TOGGLE,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with


@pytest.mark.e2e
def test_a_mitigated_incident_leaves_a_draft_pull_request_for_a_person() -> None:
    # The flag scenario, because a reverted flag is where a code fix starts:
    # the toggle is what stopped the bleeding, and the fault it exposed is
    # still in the source afterwards. An incident Argus can mitigate is
    # therefore the one case where both halves of §7.4 run - the reversible
    # action, and then the permanent fix somebody else has to approve.
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(_a_feature_flag_was_toggled_on()),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    _a_fix_was_proposed(),
                    _the_repository_holds_the_proposal_the_incident_names(),
                    _it_is_a_draft_onto_the_deployed_branch()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _a_fix_was_proposed() -> Assertion[httpx.Response]:
    """The incident's own account says Code-Fix opened something.

    Read from the events rather than from the status, because the status cannot
    carry it: a mitigated incident is mitigated whether a fix was proposed, was
    not warranted, or could not be proposed at all (§10). The outcome is what
    separates those, and the failure message quotes the agent's own detail -
    "the repository refused" and "there was nothing to change" are different
    mornings for whoever reads a red run.
    """
    def assertion(response: httpx.Response) -> bool:
        attempted = _the_fix_attempted_on(incident_id_from(response))

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

        return True

    return assertion


def _the_repository_holds_the_proposal_the_incident_names() -> Assertion[httpx.Response]:
    """What Argus said it did, and what the repository was actually asked for.

    Both halves, because either alone passes for the wrong reason: an event
    written by a step that never called anything, or a pull request opened by
    some other case in the run. They are tied together by the number and the
    branch, and the branch has to exist - a proposal is a promise about one, and
    a pull request pointing at nothing is a review nobody can do.
    """
    def assertion(response: httpx.Response) -> bool:
        proposal = _the_fix_attempted_on(incident_id_from(response)).pull_request

        if proposal is None:
            raise AssertionError("Code-Fix named no pull request to look for.")

        held = _the_proposal_numbered(proposal.number)

        if held is None:
            raise AssertionError(
                f"The incident names pull request [{proposal.number}], and the "
                f"repository holds {[each['number'] for each in _what_was_proposed()]}."
            )

        if held["head"] != proposal.branch:
            raise AssertionError(
                f"The incident names branch [{proposal.branch}] and pull request "
                f"[{proposal.number}] proposes [{held['head']}]."
            )

        if proposal.branch not in _the_branches_written():
            raise AssertionError(
                f"Pull request [{proposal.number}] proposes branch "
                f"[{proposal.branch}], which the repository does not have."
            )

        return True

    return assertion


def _it_is_a_draft_onto_the_deployed_branch() -> Assertion[httpx.Response]:
    """Proposed to a human, onto what is running, and never merged (§13).

    The one assertion here that is about autonomy rather than about the walk
    working. Argus writes a branch and asks; a pull request that arrived
    ready to merge, or aimed somewhere other than the deployed branch, is the
    write tier having quietly widened what Argus may do to a repository.
    """
    def assertion(response: httpx.Response) -> bool:
        proposal = _the_fix_attempted_on(incident_id_from(response)).pull_request

        if proposal is None:
            raise AssertionError("Code-Fix named no pull request to look for.")

        held = _the_proposal_numbered(proposal.number) or {}
        deployed = get_settings().github_base_branch

        if not held.get("draft"):
            raise AssertionError(
                f"Pull request [{proposal.number}] was not opened as a draft, so "
                f"Argus proposed a change that is ready to merge."
            )

        if held.get("base") != deployed:
            raise AssertionError(
                f"Pull request [{proposal.number}] proposes onto "
                f"[{held.get('base')!r}] rather than the deployed branch "
                f"[{deployed!r}]."
            )

        return True

    return assertion


def _the_fix_attempted_on(incident_id: str) -> FixAttempted:
    """What Code-Fix published about this incident, or the absence of it.

    One event, and the last one if a walk somehow published two: what the
    incident ended up reporting is what a reader is shown.
    """
    with psycopg.connect(DATABASE_URL) as conn:
        published = events.get_by_incident(conn, incident_id)

    attempts = [event for event in published if isinstance(event, FixAttempted)]

    if not attempts:
        raise AssertionError(
            f"Incident [{incident_id}] has no account of Code-Fix at all, so the "
            f"walk ended without ever asking about a permanent fix."
        )

    return attempts[-1]


def _the_proposal_numbered(number: int) -> dict[str, Any] | None:
    """One proposal as the repository recorded it being opened, or nothing.

    By number rather than by position, because every case in a run proposes
    into the same repository: the double is reset when the stack starts and not
    between cases, and "the last pull request" is whichever case finished last.
    """
    for proposal in _what_was_proposed():
        if proposal["number"] == number:
            return proposal

    return None


def _what_was_proposed() -> list[dict[str, Any]]:
    response = httpx.get(
        f"{GITHUB_DOUBLE_BASE_URL}/double-control/pulls",
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    proposals: list[dict[str, Any]] = response.json()["pulls"]

    return proposals


def _the_branches_written() -> list[str]:
    response = httpx.get(
        f"{GITHUB_DOUBLE_BASE_URL}/double-control/branches",
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    written: dict[str, Any] = response.json()["branches"]

    return list(written)


def _a_feature_flag_was_toggled_on() -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "feature-flag-toggle"},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
