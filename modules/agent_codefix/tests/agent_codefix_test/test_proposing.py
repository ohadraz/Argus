"""Proposing a permanent fix for the cause an incident was traced to (§7.4).

The loop: the model is handed what the investigation concluded, reads as much of
the repository as it needs, and submits a patch. What happens to that patch is
not the model's - this module writes it to a branch and opens a draft pull
request, and there is no arrangement of tool calls that gets it any further.

Two things are asserted hardest. That a fix proposing no files opens nothing -
"the fault is not in the code" is a real conclusion and must not arrive as an
empty pull request - and that a repository which refused the work is never
reported as a proposal, because the incident would then end on a link to
nothing.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from agent_codefix.proposing import (
    BranchWriter,
    FileLister,
    FileReader,
    FixSettings,
    PullRequestOpener,
    propose_fix,
)
from argus_core.models import (
    Ask,
    OpenedPullRequest,
    ToolCall,
    ToolDefinition,
    ToolResults,
    Transcript,
    Turn,
)
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting

DONT_CARE_HYPOTHESIS = "the monthly spend figure divides by an empty month"
DONT_CARE_INCIDENT = "incident-41"
SOME_PATH = "src/io_shop/spend_summary.py"
SOME_SOURCE = "def average_spend_per_item_this_month(account):\n    ...\n"
SOME_FIXED_SOURCE = "def average_spend_per_item_this_month(account):\n    return 0\n"


@pytest.mark.unit
def test_the_model_is_told_what_the_investigation_concluded() -> None:
    # Code-Fix does not investigate again. The cause is settled by the time it
    # is called, and a model asked to find it a second time would spend its
    # reading budget rediscovering what it was already handed.
    some_hypothesis = "average_spend_per_item_this_month divides by zero"
    repository = a_repository()
    model = a_model_that(submits_a_fix_touching(SOME_PATH))

    Scenario() \
        .when(
            lambda: propose_fix(
                some_hypothesis,
                DONT_CARE_INCIDENT,
                settings=some_settings(),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(
            all_of(
                _the_model_was_told(model, some_hypothesis)
            )
        )


@pytest.mark.unit
def test_a_request_to_list_the_repository_is_answered_with_its_files() -> None:
    repository = a_repository(holding=["src/io_shop/spend_summary.py", "README.md"])
    model = a_model_that(
        asks_to_list_files(), submits_a_fix_touching(SOME_PATH)
    )

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(
            all_of(
                _the_model_was_told(model, "src/io_shop/spend_summary.py"),
                _the_model_was_told(model, "README.md")
            )
        )


@pytest.mark.unit
def test_a_request_to_read_a_file_is_answered_with_its_source() -> None:
    repository = a_repository(whose_source_is=SOME_SOURCE)
    model = a_model_that(
        asks_to_read(SOME_PATH), submits_a_fix_touching(SOME_PATH)
    )

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(
            all_of(
                _the_model_was_told(model, SOME_SOURCE)
            )
        )


@pytest.mark.unit
def test_a_file_that_is_not_there_is_reported_back_rather_than_ending_the_work() -> None:
    # A model guessing at a path is a model doing its job badly for one turn,
    # not a fix that failed. Ending the loop on it would throw away every file
    # it had read correctly up to then.
    repository = a_repository()
    repository.read_file.side_effect = [
        FileNotFoundError("no such path"), SOME_SOURCE
    ]
    model = a_model_that(
        asks_to_read("src/io_shop/spend_sumary.py"),
        asks_to_read(SOME_PATH),
        submits_a_fix_touching(SOME_PATH)
    )

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(
            all_of(
                _a_pull_request_was_opened(repository)
            )
        )


@pytest.mark.unit
def test_a_submitted_fix_is_written_to_a_branch_of_this_incidents_own() -> None:
    # Named for the incident so that two incidents fixing the same file do not
    # write over each other's proposal, and so a branch found later says which
    # incident produced it.
    some_incident = "incident-41"
    repository = a_repository()
    model = a_model_that(submits_a_fix_touching(SOME_PATH))

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                some_incident,
                settings=some_settings(base_branch="main"),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(
            all_of(
                _the_branch_written_mentions(repository, some_incident),
                _the_branch_was_cut_from(repository, "main"),
                _the_patch_written_was(repository, {SOME_PATH: SOME_FIXED_SOURCE})
            )
        )


@pytest.mark.unit
def test_the_proposal_carries_the_models_own_words() -> None:
    # A human is the entire audience for a draft nobody may merge. A title this
    # module invented would be a proposal with its reasoning stripped off.
    some_summary = "guard the monthly divisor"
    some_explanation = "Most shoppers bought nothing this month, so the list is empty."
    repository = a_repository()
    model = a_model_that(
        submits_a_fix_touching(
            SOME_PATH, summary=some_summary, explanation=some_explanation
        )
    )

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(
            all_of(
                _the_proposal_was_titled(repository, some_summary),
                _the_proposal_explained(repository, some_explanation)
            )
        )


@pytest.mark.unit
def test_what_comes_back_is_where_the_proposal_can_be_read() -> None:
    some_pull_request = OpenedPullRequest(
        number=41,
        url="https://github.invalid/io-shop/target/pull/41",
        branch="argus/fix-incident-41"
    )
    repository = a_repository()
    repository.open_pull_request.return_value = some_pull_request
    model = a_model_that(submits_a_fix_touching(SOME_PATH))

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(
            all_of(
                _what_came_back_is(some_pull_request)
            )
        )


@pytest.mark.unit
def test_a_fix_proposing_no_files_writes_nothing_and_proposes_nothing() -> None:
    # "The fault is not in the code" is a conclusion, and a real one - the flag
    # scenarios are caused by code that is working as written. An empty pull
    # request would send a human to read a diff with nothing in it.
    repository = a_repository()
    model = a_model_that(submits_a_fix_touching())

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(
            all_of(
                _nothing_was_proposed(),
                _no_branch_was_written(repository)
            )
        )


@pytest.mark.unit
def test_a_model_that_never_submits_proposes_nothing() -> None:
    # Bounded, like the investigation is. A model reading file after file
    # without ever answering is a run that has to end somewhere, and it ends
    # having proposed nothing rather than by reading the repository forever.
    repository = a_repository()
    model = a_model_that(*[asks_to_list_files()] * 4)

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(max_turns=3),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(
            all_of(
                _nothing_was_proposed(),
                _no_branch_was_written(repository)
            )
        )


@pytest.mark.unit
def test_a_repository_that_refused_the_work_is_not_reported_as_a_proposal() -> None:
    # Raised rather than answered with nothing. "No fix was found" and "the fix
    # could not be pushed" reach the same human and only one of them would be
    # true - and the second is a thing somebody can go and fix.
    #
    # The failure is whatever the port raised, not a type named here. What
    # opens a pull request in production is a tool on another process, so what
    # arrives is the transport's - and a loop catching a specific exception
    # would swallow every other way that call can fail.
    some_refusal = RuntimeError("the repository refused the pull request")
    repository = a_repository()
    repository.open_pull_request.side_effect = some_refusal
    model = a_model_that(submits_a_fix_touching(SOME_PATH))

    Scenario() \
        .when(
            attempting(
                lambda: propose_fix(
                    DONT_CARE_HYPOTHESIS,
                    DONT_CARE_INCIDENT,
                    settings=some_settings(),
                    converse=model.converse,
                    **repository.ports()
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(RuntimeError)
            )
        )


def _the_model_was_told(model: _Model, said: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if said not in model.everything_it_was_told():
            raise AssertionError(
                f"Expected the model to have been told [{said!r}]; it was not."
            )

        return True

    return assertion


def _the_branch_written_mentions(repository: _Repository, incident: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        written = repository.write_branch.call_args.kwargs["branch"]

        if incident not in written:
            raise AssertionError(
                f"Expected a branch naming [{incident}], got [{written}]."
            )

        return True

    return assertion


def _the_branch_was_cut_from(repository: _Repository, base: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        cut_from = repository.write_branch.call_args.kwargs["base_branch"]

        if cut_from != base:
            raise AssertionError(f"Expected a branch off [{base}], got [{cut_from}].")

        return True

    return assertion


def _the_patch_written_was(repository: _Repository,
                           patch: dict[str, str]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        written = repository.write_branch.call_args.kwargs["files"]

        if written != patch:
            raise AssertionError(f"Expected the patch {patch}, got {written}.")

        return True

    return assertion


def _the_proposal_was_titled(repository: _Repository, title: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        proposed = repository.open_pull_request.call_args.kwargs["title"]

        if title not in proposed:
            raise AssertionError(
                f"Expected the proposal titled with [{title!r}], got [{proposed!r}]."
            )

        return True

    return assertion


def _the_proposal_explained(repository: _Repository, explanation: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        body = repository.open_pull_request.call_args.kwargs["body"]

        if explanation not in body:
            raise AssertionError(
                f"Expected the proposal to carry [{explanation!r}], got [{body!r}]."
            )

        return True

    return assertion


def _a_pull_request_was_opened(repository: _Repository) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if not repository.open_pull_request.call_args_list:
            raise AssertionError("Expected a pull request to be opened, none was.")

        return True

    return assertion


def _no_branch_was_written(repository: _Repository) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if repository.write_branch.call_args_list:
            raise AssertionError(
                f"Expected nothing written, got "
                f"{repository.write_branch.call_count} branch writes."
            )

        if repository.open_pull_request.call_args_list:
            raise AssertionError(
                f"Expected nothing proposed, got "
                f"{repository.open_pull_request.call_count} pull requests."
            )

        return True

    return assertion


def _nothing_was_proposed() -> Assertion[Any]:
    def assertion(proposed: Any) -> bool:
        if proposed is not None:
            raise AssertionError(f"Expected no proposal, got [{proposed}].")

        return True

    return assertion


def _what_came_back_is(pull_request: OpenedPullRequest) -> Assertion[Any]:
    def assertion(came_back: Any) -> bool:
        if came_back != pull_request:
            raise AssertionError(f"Expected [{pull_request}], got [{came_back}].")

        return True

    return assertion


def asks_to_list_files() -> Turn:
    return _a_turn_calling("list_repository_files", {})


def asks_to_read(path: str) -> Turn:
    return _a_turn_calling("read_repository_file", {"path": path})


def submits_a_fix_touching(*paths: str,
                           summary: str = "a summary",
                           explanation: str = "an explanation") -> Turn:
    return _a_turn_calling("submit_fix", {
        "summary": summary,
        "explanation": explanation,
        "files": [
            {"path": path, "content": SOME_FIXED_SOURCE} for path in paths
        ]
    })


def _a_turn_calling(tool: str, arguments: dict[str, Any]) -> Turn:
    return Turn(
        text="",
        tool_calls=[ToolCall(id=f"call-{tool}", name=tool, arguments=arguments)],
        input_tokens=0,
        output_tokens=0
    )


class _Model:
    """A scripted conversation: one prepared turn per time it is asked.

    A stub rather than a mock, because what a test says about it is what the
    model *did*, and a scripted sequence says that in the order the loop drives
    it. Runs out deliberately - a loop asking for more turns than a test
    prepared is a loop that did not stop when it should have, and a stub that
    repeated its last turn forever would hide that behind a hang.
    """

    def __init__(self, turns: list[Turn]) -> None:
        self.turns = list(turns)
        self.transcripts: list[Transcript] = []

    def converse(self, transcript: Transcript, tools: list[ToolDefinition]) -> Turn:
        self.transcripts.append(list(transcript))

        if not self.turns:
            raise AssertionError("The loop asked for more turns than were scripted.")

        return self.turns.pop(0)

    def everything_it_was_told(self) -> str:
        """Every word put to the model across the whole conversation.

        One string rather than a structure: what a test here cares about is
        whether a fact reached the model at all, not which message carried it -
        and an assertion naming a message index would break whenever the
        conversation gained a line.
        """
        said: list[str] = []

        for transcript in self.transcripts:
            for exchange in transcript:
                if isinstance(exchange, Ask):
                    said.append(exchange.text)
                elif isinstance(exchange, ToolResults):
                    said.extend(result.content for result in exchange.results)

        return "\n".join(said)


def a_model_that(*turns: Turn) -> _Model:
    return _Model(list(turns))


class _Repository:
    """The four ports the loop reaches the repository through.

    Spec'd against the `Protocol`s rather than against the client functions
    those are implemented by: a client function takes the connection it is asked
    over, and the loop is asked about a repository. The same reasoning that puts
    `Protocol`s in the investigator's `retrieval` instead of specing against
    `get_log_lines`.
    """

    def __init__(self, holding: list[str], whose_source_is: str) -> None:
        self.list_files: Any = create_autospec(
            FileLister, instance=True, return_value=holding
        )
        self.read_file: Any = create_autospec(
            FileReader, instance=True, return_value=whose_source_is
        )
        self.write_branch: Any = create_autospec(
            BranchWriter, instance=True, return_value="a-branch"
        )
        self.open_pull_request: Any = create_autospec(
            PullRequestOpener,
            instance=True,
            return_value=OpenedPullRequest(
                number=1,
                url="https://github.invalid/dont-care/dont-care/pull/1",
                branch="a-branch"
            )
        )

    def ports(self) -> dict[str, Any]:
        """The four seams, as the keywords `propose_fix` takes them by.

        Handed over as one mapping because every test needs all four and only
        ever cares about one - naming the other three at ten call sites would
        bury the line each test is actually about.
        """
        return {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "write_branch": self.write_branch,
            "open_pull_request": self.open_pull_request
        }


def a_repository(holding: list[str] | None = None,
                 whose_source_is: str = SOME_SOURCE) -> _Repository:
    return _Repository(holding or [SOME_PATH], whose_source_is)


def some_settings(base_branch: str = "main", max_turns: int = 12) -> FixSettings:
    """What the fix loop is bounded and aimed by.

    `base_branch` is what a fix is cut from and proposed onto - the branch that
    is actually deployed. `max_turns` bounds the reading, for the reason the
    investigation's budgets exist: a bound the model could talk its way past is
    not a bound.
    """
    return FixSettings(github_base_branch=base_branch, codefix_max_turns=max_turns)
