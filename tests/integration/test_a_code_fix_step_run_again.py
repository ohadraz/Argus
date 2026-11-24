"""A Code-Fix step run again writes the fix its first attempt claimed.

A step interrupted after it wrote its branch runs again from its checkpoint.
Asked again, the model may write another patch, and the branch the first
attempt wrote refuses it - so the first attempt's fix is claimed before any of
it is written, and the step run again writes the claim instead of asking.

Every part of that is pinned somewhere smaller: the claim against a real row in
`fix_claims`' suite, its read and its order in `test_proposing`, the tree a
second asking finds in `test_branching`. What only this case can say is that
they are wired together: a claim read back from postgres, written twice through
the real write tier, reaches a host that compares trees and finds its own
branch and pull request. The host is `github_double`, whose objects are
content-addressed as GitHub's are.

Not staged here: the base branch moving between the two attempts, which the
double has no seam to do. That the second writing is on the claimed commit
rather than the head is `test_branching`'s case.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

import httpx2
import pytest
from argus_testkit import Assertion, Scenario, all_of, calling
from codefix_agent import FixSettings, propose_fix
from core import Fence, Holding, WriteMcpEndpoint, get_settings, utc_now
from core.llm import conversations_through
from core.models import (
    Alert,
    CodeOutsideThePatch,
    FailureMode,
    Hypothesis,
    ProposedFix,
    ToolDefinition,
)
from incident_record.publishing import events_into_connection
from incident_record.repository import incidents, runs
from llm_anthropic import AnthropicSettings
from orchestrator.records import Records
from postgres import connect_from_env
from write_mcp_client import WriteTier, write_mcp

from tests.framework.code_host import the_head_of
from tests.framework.models import the_configured_models
from tests.framework.recordings import the_model_answers

# The model's two answers to the first attempt: a submission, and a "no" to the
# question every submission is asked. The second attempt is answered nothing -
# none is queued for it - so a second attempt that asked would fail.
RECORDED_FIX: Final = "codefix-large-fix"
RECORDED_ANSWER_NO: Final = "codefix-answer-no"

# Outlasts the test, so the run is still the claim's when the fix is written.
A_GENEROUS_LEASE: Final = timedelta(minutes=5)

# What the double's control seam lists proposals and branches under.
PULLS_FIELD: Final = "pulls"
BRANCHES_FIELD: Final = "branches"


@pytest.mark.integration
def test_a_code_fix_step_run_again_proposes_the_fix_its_first_attempt_claimed(
    anthropic_double: httpx2.Client, github_double: httpx2.Client
) -> None:
    settings = get_settings()
    holding = Holding()
    records = Records(connect_from_env, publisher_for=events_into_connection)
    # Walked by a worker holding its run, as every fix is proposed: the write
    # tier makes a change only for the claim that holds the run it is for.
    the_run = _a_claimed_run()
    first: list[ProposedFix] = []

    with (
        write_mcp(WriteMcpEndpoint.of(settings), holding=holding) as write,
        holding.of(Fence(run_id=the_run.id, epoch=the_run.epoch))
    ):
        def an_attempt() -> ProposedFix:
            return _code_fix_for(the_run.incident_id, records, write)

        Scenario() \
            .given(
                calling(lambda: the_model_answers(anthropic_double,
                                                   RECORDED_FIX, RECORDED_ANSWER_NO)),
                calling(lambda: first.append(an_attempt()))
            ) \
            .when(
                an_attempt
            ) \
            .then(
                all_of(
                    _it_proposed_what_the_first_attempt_did(first),
                    _one_pull_request_was_opened(github_double),
                    _one_branch_was_written_for_it(github_double, first)
                )
            )


def _code_fix_for(incident_id: str, records: Records, write: WriteTier) -> ProposedFix:
    """Code-Fix for the incident, its claim the record's and its writes the
    write tier's - each attempt as the walk would bind it."""
    settings = get_settings()

    return propose_fix(
        _a_hypothesis_about(incident_id),
        incident_id,
        settings=FixSettings.of(settings, AnthropicSettings()),
        read_tier_tools=_nothing_served,
        search=_nothing_found,
        search_by_meaning=_nothing_found,
        index_notice=_nothing_to_say,
        list_files=_no_files,
        contains=_contained,
        read_file=_an_empty_file,
        code_outside=_nothing_outside,
        branch_head=the_head_of,
        write_branch=write.commit_to_new_branch,
        open_pull_request=write.open_pull_request,
        conversations=conversations_through(the_configured_models()),
        claimed=lambda: records.claimed_fix(incident_id),
        claim=lambda fix: records.claim_fix(incident_id, fix, at=utc_now())
    )


def _a_claimed_run() -> runs.Run:
    """An incident whose run a worker has claimed, as the claim it holds."""
    with connect_from_env() as conn:
        incident_id = incidents.create(
            conn, Alert(service="io-shop", alert_name="HighErrorRate"), at=utc_now()
        )
        runs.enqueue(conn, incident_id)
        the_run = runs.claim(conn, "dont-care-worker", A_GENEROUS_LEASE)
        assert the_run is not None

    return the_run


def _a_hypothesis_about(incident_id: str) -> Hypothesis:
    # What the model is shown, which the double never reads: it answers from
    # what was queued, whatever it was asked.
    return Hypothesis(
        incident_id=incident_id,
        summary="dont care what the investigation concluded",
        failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
        confidence=0.9,
        supporting_evidence=[]
    )


# The read side, which nothing in this case reaches but the head: the model's
# first answer is the submission. Empty rather than raising, because a read
# that raised would be answered to the model as a failed tool call.
def _nothing_served() -> list[ToolDefinition]:
    return []


def _nothing_found(_asked: str, _ref: str, /) -> list[str]:
    return []


def _nothing_to_say(_ref: str, /) -> str:
    return ""


def _no_files(_ref: str, /) -> list[str]:
    return []


def _contained(_branch: str, _revision: str, /) -> bool:
    return True


def _an_empty_file(_path: str, _ref: str, /) -> str:
    return ""


def _nothing_outside(_files: dict[str, str], _ref: str, /) -> CodeOutsideThePatch:
    return CodeOutsideThePatch(uses=[], defined={})


def _it_proposed_what_the_first_attempt_did(attempts: list[ProposedFix]
                                            ) -> Assertion[ProposedFix]:
    """The same pull request, on the same branch, with the same reading - what
    the first attempt claimed, answered again."""
    def assertion(again: ProposedFix) -> bool:
        first = attempts[0]

        if first.pull_request is None:
            raise AssertionError(
                f"Expected the first attempt to propose a fix, it proposed none: "
                f"{first.explanation}"
            )

        if again != first:
            raise AssertionError(
                f"Expected the step run again to answer what the first attempt did, "
                f"[{first!r}], and it answered [{again!r}]."
            )

        return True

    return assertion


def _one_pull_request_was_opened(github_double: httpx2.Client) -> Assertion[ProposedFix]:
    """One proposal on the host, however many times the fix was written - read
    off the host rather than off what Argus said of itself."""
    def assertion(dont_care_again: ProposedFix) -> bool:
        response = github_double.get("/double-control/pulls")
        response.raise_for_status()
        proposed: list[dict[str, Any]] = response.json()[PULLS_FIELD]

        if len(proposed) != 1:
            raise AssertionError(
                f"Expected one pull request opened over both attempts, got {proposed}."
            )

        return True

    return assertion


def _one_branch_was_written_for_it(github_double: httpx2.Client,
                                   attempts: list[ProposedFix]) -> Assertion[ProposedFix]:
    """One branch beside the base, the one the pull request is on - read off
    the host. A second write refused would leave this as well; what it adds to
    the pull request's half is that no second branch was written for the fix."""
    def assertion(dont_care_again: ProposedFix) -> bool:
        proposed = attempts[0].pull_request
        response = github_double.get("/double-control/branches")
        response.raise_for_status()
        written = set(response.json()[BRANCHES_FIELD]) - {_the_base_branch()}

        if proposed is None or written != {proposed.branch}:
            raise AssertionError(
                f"Expected one branch written, the proposal's, got {sorted(written)} "
                f"for the proposal {proposed!r}."
            )

        return True

    return assertion


def _the_base_branch() -> str:
    """The branch the fix is cut from, as this deployment names it."""
    return FixSettings.of(get_settings(), AnthropicSettings()).deployed_branch
