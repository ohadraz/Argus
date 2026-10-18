"""A fix that is a whole large file, carried from the model's answer onto a branch.

Code-Fix's answer is the fix's whole text - each file it changes, in full - so
what the model emits is the size of the file it is fixing, and the Target
Service has modules of twenty-odd thousand tokens. Every other fix this
repository replays rewrites a module of seven hundred. So this case replays one
real answer that rewrote the shop's largest module, and follows it through
everything that carries it: the Anthropic adapter on its streaming path, the
tool schema it is parsed against, the question a submission is asked, the write
MCP server over its transport, and the repository the branch is written to.

What is asserted is that the branch holds what the model submitted, byte for
byte. Which file the model chose and what it changed are judgement, measured
by `nox -s eval` over many samples and never by one replayed answer. An e2e
walk asserted this once, and passed or failed by which of two good fixes the
model happened to choose - the case was about the size of an answer, and could
only be as large as the model decided it would be.

Two limits on what a pass means, said rather than implied:

- Putting a stream's events back together is the SDK's work, not Argus's. The
  double streams each field as one event where the real API sends many, and
  what this proves about Argus is that a Code-Fix call takes the streaming path
  and uses what the SDK assembled.
- The repository is `github_double`, which has no contract test against
  GitHub. That the answer reached the double is in evidence; that GitHub would
  accept a request this size is not.

The model reads nothing here - its first answer is the submission - so the read
side is stubbed rather than served: no part of the answer travels over it. The
write side is the real one, because the answer's size travels over all of it.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from functools import partial
from typing import Any, Final

import httpx2
import pytest
from agent_codefix import FixSettings, SubmittedFix, propose_fix
from anthropic_double import recordings
from anthropic_double.server import DEFAULT_BASE_URL as ANTHROPIC_DOUBLE_BASE_URL
from argus_core import WriteMcpEndpoint, get_settings
from argus_core.models import FailureMode, Hypothesis, ProposedFix
from argus_testkit import Assertion, Scenario, all_of, calling
from github_double.server import DEFAULT_BASE_URL as GITHUB_DOUBLE_BASE_URL
from write_mcp_client import commit_to_new_branch, open_pull_request, write_mcp

# The two answers the model gives, each a real one. The first is a submission
# that rewrote `monthly_statement.py` whole, recorded from a walk that chose to
# fix it there; the second is a "no" to the question every submission is asked,
# recorded from a later walk that fixed the same incident in a smaller file. The
# answer is read for its yes or no alone, so whose patch it was given about
# changes nothing that reaches the branch.
RECORDED_LARGE_FIX: Final = "codefix-large-fix"
RECORDED_ANSWER_NO: Final = "codefix-answer-no"

# Anthropic's word for a block that calls a tool, and Code-Fix's name for the
# tool that submits a fix - spelled here for the reason
# `tests/e2e/framework/argus.py` spells the first: neither is on a front door
# this suite may import from.
TOOL_USE_TYPE: Final = "tool_use"
SUBMIT_TOOL_NAME: Final = "submit_fix"

# The fields of a stored Anthropic body this file reads.
CONTENT_FIELD: Final = "content"
TYPE_FIELD: Final = "type"
NAME_FIELD: Final = "name"
INPUT_FIELD: Final = "input"

REQUEST_TIMEOUT_SECONDS: Final = 30.0


@pytest.fixture
def anthropic_double() -> Iterator[httpx2.Client]:
    with httpx2.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL,
                       timeout=REQUEST_TIMEOUT_SECONDS) as control:
        control.post("/double-control/reset").raise_for_status()
        yield control
        control.post("/double-control/reset").raise_for_status()


@pytest.fixture
def github_double() -> Iterator[httpx2.Client]:
    with httpx2.Client(base_url=GITHUB_DOUBLE_BASE_URL,
                       timeout=REQUEST_TIMEOUT_SECONDS) as control:
        control.post("/double-control/reset").raise_for_status()
        yield control
        control.post("/double-control/reset").raise_for_status()


@pytest.mark.integration
def test_a_fix_that_rewrites_a_large_file_reaches_the_branch_whole(
    anthropic_double: httpx2.Client, github_double: httpx2.Client
) -> None:
    settings = get_settings()
    dont_care_incident_id = "6b1f2c4e-0d3a-4c6e-9f1a-2b7d8e5c4a10"

    with write_mcp(WriteMcpEndpoint.of(settings)) as write:
        Scenario() \
            .given(
                calling(lambda: _the_model_answers(anthropic_double,
                                                   RECORDED_LARGE_FIX,
                                                   RECORDED_ANSWER_NO))
            ) \
            .when(
                lambda: propose_fix(
                    _a_hypothesis_about(dont_care_incident_id),
                    dont_care_incident_id,
                    settings=FixSettings.of(settings),
                    search=_nothing_found,
                    search_by_meaning=_nothing_found,
                    index_notice=_nothing_to_say,
                    list_files=_no_files,
                    read_file=_an_empty_file,
                    write_branch=partial(commit_to_new_branch, client=write),
                    open_pull_request=partial(open_pull_request, client=write)
                )
            ) \
            .then(
                all_of(
                    _a_pull_request_was_opened(),
                    _the_branch_holds_what_was_submitted(_the_patch_in(RECORDED_LARGE_FIX))
                )
            )


def _the_model_answers(double: httpx2.Client, *answers: str) -> None:
    """Queues each answer once, in order - the first call gets the first."""
    for answer in answers:
        double.post("/double-control/seed", json={"recording": answer}).raise_for_status()


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


# The read side, which nothing in this case reaches: the model's first answer is
# the submission. Empty rather than raising, because a read that raised would be
# answered to the model as a failed tool call - and the test would fail on the
# queue running dry, a step later and for a reason that reads like the double's.
def _nothing_found(_asked: str, _ref: str, /) -> list[str]:
    return []


def _nothing_to_say(_ref: str, /) -> str:
    return ""


def _no_files(_ref: str, /) -> list[str]:
    return []


def _an_empty_file(_path: str, _ref: str, /) -> str:
    return ""


def _the_patch_in(recording: str) -> dict[str, str]:
    """Every file the recorded answer submitted, as Code-Fix writes it to a branch.

    Read through `SubmittedFix`, as the grader reads it, rather than out of the
    JSON by hand: what reaches the branch is the patch the agent makes of the
    answer, and a second reading of it kept here would be one more to drift.
    """
    answer = recordings.load(recording)
    submitted = next(
        block[INPUT_FIELD] for block in answer[CONTENT_FIELD]
        if block.get(TYPE_FIELD) == TOOL_USE_TYPE and block.get(NAME_FIELD) == SUBMIT_TOOL_NAME
    )

    return SubmittedFix.model_validate(submitted).patch()


def _a_pull_request_was_opened() -> Assertion[ProposedFix]:
    def assertion(proposed: ProposedFix) -> bool:
        if proposed.pull_request is None:
            raise AssertionError(
                f"Expected a pull request, and Code-Fix opened none: "
                f"{proposed.explanation}"
            )

        return True

    return assertion


def _the_branch_holds_what_was_submitted(patch: dict[str, str]) -> Assertion[ProposedFix]:
    """Every file the model submitted is on the branch, exactly as submitted.

    Compared against the branch rather than against anything Argus said about
    itself, and file by file: the way this goes wrong is a file cut short
    somewhere between the answer and the repository, and the message says which
    file and by how much.
    """
    def assertion(proposed: ProposedFix) -> bool:
        if proposed.pull_request is None:
            raise AssertionError("No pull request, so no branch to read a fix from.")

        branch = proposed.pull_request.branch
        written = {path: _the_text_of(path, branch) for path in patch}
        differing = {
            path: (len(submitted), len(written[path]))
            for path, submitted in patch.items()
            if written[path] != submitted
        }

        if differing:
            raise AssertionError(
                f"Expected branch [{branch}] to hold every file the model "
                f"submitted as submitted, and these differ (submitted length, "
                f"written length): {differing}."
            )

        return True

    return assertion


def _the_text_of(path: str, branch: str) -> str:
    """One file as the branch holds it, decoded the way the API sends it."""
    settings = get_settings()
    response = httpx2.get(
        f"{GITHUB_DOUBLE_BASE_URL}/repos/{settings.github_repository}/contents/{path}",
        params={"ref": branch},
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    held: dict[str, Any] = response.json()

    return base64.b64decode(held["content"]).decode()
