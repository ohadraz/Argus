"""A fix that is a whole large file - the shape nothing else in this suite drives.

`test_proposing_a_code_fix.py` proves the path: Code-Fix reads the service's
source, writes a branch, and opens a draft pull request for a person. It proves
it against the smallest module the shop has - a fault in seven hundred tokens of
source, answered in seven hundred tokens of fix - and for a long time that was
the only code-fix scenario there was.

Which left the whole output side of Code-Fix unexercised. `ProposedFile.content`
is a file's whole new text, so what the model has to emit is the size of the file
it is fixing, and this shop has modules of twenty-odd thousand tokens. Against
the adapter's old non-streaming default those were not tight, they were
impossible - the answer could not be carried at all, and no retry could help,
because the same request overflows the same ceiling every time. Nothing here
could have noticed, because the one file the corpus ever asked about was under
five percent of that ceiling.

So this case stages the same incident as its sibling - the same flag, the same
canary, the same shoppers failing for the same reason, the same error rate - with
the fault moved into the largest module the shop has. Everything a reader of the
telemetry can see is identical. What differs is the size of the answer, and the
size of the answer is the only thing asserted below.

Which file the model chose, and what it changed in it, are deliberately not
asserted - for the reason the sibling gives at length: that is judgement, and
judgement is measured by `nox -s eval` over fifty samples, never by one recorded
answer. What is asserted is that an answer of this size survived the round trip:
streamed out of the SDK, reassembled, parsed against the tool schema, and written
to a branch somebody can open.

This case is collected in two places and left out of two others, and both
exclusions are decisions rather than gaps.

`nox -s e2e` leaves it out by default: against the real API it bills several
times any other case's output to re-establish what the free replay already
established. Name it to run it there -
`nox -s e2e -- tests/e2e/test_proposing_a_large_code_fix.py`.

`e2e_replay` collects it under `both` alone. The claim above - that an answer
this size survives the round trip - does not vary by which tool the model found
the file with, and the per-mode walks are covered by its sibling. Recording it
under `grep` and `meaning` too would buy three recordings of one assertion, at
a real investigation each.
"""

from __future__ import annotations

import base64
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
    RECORDED_LARGE_CODE_FIX,
    REQUEST_TIMEOUT_SECONDS,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import a_scenario_was_seeded

# The scenario staging this incident. The same string as the recording's name,
# and that is not a coincidence worth hiding: one scenario, one recording, and
# a walk replayed in a world unlike the one it was captured in runs longer than
# the queue of answers it was given.
THE_LARGE_FILE_SCENARIO = RECORDED_LARGE_CODE_FIX

# What separates this case from its sibling, measured in bytes of written file.
#
# The shop's Python runs at roughly three bytes to the token, so forty thousand
# bytes is somewhere near fourteen thousand tokens of answer. Every other
# code-fix answer in this suite rewrites a 752-token module - about two thousand
# bytes - so nothing else here comes within an order of magnitude of this floor,
# and a fix that clears it carried a whole large file rather than a fragment of
# one.
#
# Deliberately below the size of the module being fixed rather than level with
# it. What is being asserted is that an answer of this size made it through;
# pinning the figure at the module's own length would additionally assert that
# the model reproduced every line of it, which is judgement and is measured
# elsewhere.
A_WHOLE_LARGE_FILE_IN_BYTES = 40_000


@pytest.mark.e2e
def test_a_fix_that_rewrites_a_large_file_reaches_the_repository() -> None:
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded(THE_LARGE_FILE_SCENARIO)),
            calling(the_model_answers_from(RECORDED_LARGE_CODE_FIX))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    _the_proposal_rewrote_a_whole_large_file()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_proposal_rewrote_a_whole_large_file() -> Assertion[httpx.Response]:
    """The branch carries a file far larger than any fix here has ever written.

    Read from the repository rather than from anything Argus said about itself,
    and by comparing the branch against the deployed one rather than by listing
    what is on it. A branch holds the whole repository, so its largest file is
    the shop's largest file whether or not the fix touched it - an assertion
    reading that would pass against a branch nothing was written to, which is
    precisely the failure this case exists to catch.

    The failure message names every file the fix wrote and how large each came
    out, because the two ways this goes wrong look nothing alike: a fix that
    wrote a small file chose a different file, and a fix that wrote a truncated
    one is the defect this case was built for.
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
                f"request, so there is no branch to read a fix from."
            )

        branch = attempted.pull_request.branch
        written = {
            path: len(_the_text_of(path, branch))
            for path in _what_changed_on(branch)
        }

        if not written:
            raise AssertionError(
                f"Branch [{branch}] changed no file at all, so the proposal is "
                f"a pull request against the deployed branch's own content."
            )

        if max(written.values()) < A_WHOLE_LARGE_FILE_IN_BYTES:
            raise AssertionError(
                f"Expected a fix rewriting at least "
                f"{A_WHOLE_LARGE_FILE_IN_BYTES} bytes of one file, and branch "
                f"[{branch}] carries {written} - which is a fix of the size "
                f"every other case here already covers."
            )

        return True

    return assertion


def _the_fix_attempted_on(incident_id: str) -> FixAttempted:
    """What Code-Fix published about this incident, or the absence of it.

    The last one if a walk somehow published two: what the incident ended up
    reporting is what a reader is shown.
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


def _what_changed_on(branch: str) -> list[str]:
    """Every path this branch changed against the branch that is deployed."""
    settings = get_settings()
    response = httpx.get(
        f"{GITHUB_DOUBLE_BASE_URL}/repos/{settings.github_repository}/compare/"
        f"{settings.github_base_branch}...{branch}",
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    compared: dict[str, Any] = response.json()

    return [changed["filename"] for changed in compared["files"]]


def _the_text_of(path: str, branch: str) -> str:
    """One file as the branch holds it, decoded the way the API sends it."""
    settings = get_settings()
    response = httpx.get(
        f"{GITHUB_DOUBLE_BASE_URL}/repos/{settings.github_repository}/contents/{path}",
        params={"ref": branch},
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    held: dict[str, Any] = response.json()

    return base64.b64decode(held["content"]).decode()
