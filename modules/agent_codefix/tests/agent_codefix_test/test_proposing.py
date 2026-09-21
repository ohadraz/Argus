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
    FixDeclined,
    FixNotAnswered,
    FixSettings,
    IndexNotice,
    MeaningSearcher,
    PullRequestOpener,
    SourceSearcher,
    propose_fix,
)
from argus_core.llm import (
    AnswerTruncated,
    ModelDidNotAnswer,
    ModelRefused,
    a_conversation_recorded_for,
)
from argus_core.models import (
    Ask,
    CodeSearch,
    Effort,
    Evidence,
    FailureMode,
    Hypothesis,
    OpenedPullRequest,
    ToolCall,
    ToolDefinition,
    ToolResults,
    Transcript,
    Turn,
)
from argus_core.replay import Recorder
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting

DONT_CARE_INCIDENT = "incident-41"

def a_hypothesis(summary: str, *claims: str) -> Hypothesis:
    """What the investigation concluded, as Code-Fix is handed it.

    Above the constants rather than below with the other helpers, because one
    of those constants is built from it and a module runs top to bottom.

    The whole finding rather than its sentence: the evidence is where the log
    line lives, and a log line from this shop names the file and the line the
    fault was raised on. A summary alone makes the agent search for what it was
    already told.
    """
    return Hypothesis(
        incident_id=DONT_CARE_INCIDENT,
        summary=summary,
        failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
        confidence=0.9,
        supporting_evidence=[Evidence(claim=claim, at=None) for claim in claims]
    )

DONT_CARE_HYPOTHESIS = a_hypothesis("the monthly spend figure divides by an empty month")
SOME_PATH = "src/io_shop/spend_summary.py"
SOME_SOURCE = "def average_spend_per_item_this_month(account):\n    ...\n"
SOME_FIXED_SOURCE = "def average_spend_per_item_this_month(account):\n    return 0\n"

SOME_MODEL = "claude-sonnet-5"
SOME_EFFORT: Effort = "medium"
SOME_MAX_OUTPUT_TOKENS = 128_000

# Past every bound a test can set, so the two bounds a test did not name stay
# out of the way of the one it did.
ROOM_TO_SPARE_IN_TOKENS = 1_000_000
ROOM_TO_SPARE_IN_SECONDS = 3600.0

# What a turn costs where the test is not about cost. Zero rather than a
# plausible number, so a bound is only ever reached by a test that asked.
NO_TOKENS = 0

# The words the warning has to carry, not the sentence it carries them in -
# a test pinning the whole wording breaks whenever the prose is improved,
# and what matters is that the model was told which turn it is on.
THE_LAST_CALL_WARNING = "last call"


@pytest.mark.unit
def test_the_model_is_told_what_the_investigation_concluded() -> None:
    # Code-Fix does not investigate again. The cause is settled by the time it
    # is called, and a model asked to find it a second time would spend its
    # reading budget rediscovering what it was already handed.
    some_hypothesis = a_hypothesis("average_spend_per_item_this_month divides by zero")
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
                _the_model_was_told(model, some_hypothesis.summary)
            )
        )


@pytest.mark.unit
def test_the_model_is_told_the_evidence_the_conclusion_rests_on() -> None:
    # The summary says what broke; the evidence says where. This shop's own
    # error boundary records the innermost frame, so a log line among the
    # evidence names the file and the line - and an agent handed only the
    # sentence goes searching for a location it was already holding.
    a_log_line_naming_the_fault = (
        "ERROR io-shop: account page request failed - ZeroDivisionError: "
        "division by zero at src/io_shop/spend_summary.py:32"
    )
    some_hypothesis = a_hypothesis(
        "the monthly figure divides by an empty month", a_log_line_naming_the_fault
    )
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
                _the_model_was_told(model, a_log_line_naming_the_fault),
                _the_model_was_not_told_a_repr(model)
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
def test_a_search_is_answered_with_where_the_cause_appears() -> None:
    # The tool that turns a named cause into a place to look. Without it the
    # model has a flag name and forty paths, and the only way to connect them
    # is to open files and hope - which is exactly what it did, for twelve
    # turns, without ever reaching the file the fault was in.
    where_the_flag_is = "src/io_shop/spend_summary.py:8: behind monthly-spend-feature"
    repository = a_repository(where=[where_the_flag_is])
    model = a_model_that(
        asks_to_search_for("monthly-spend-feature"),
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
        .then(_the_model_was_told(model, where_the_flag_is))


@pytest.mark.unit
def test_a_search_is_made_at_the_branch_the_fix_is_cut_from() -> None:
    # The deployed branch, as every other read here is. A search against
    # anything else finds the cause in code nobody is running, and the fix is
    # written against a file that has since moved.
    the_deployed_branch = "release"
    repository = a_repository()
    model = a_model_that(
        asks_to_search_for("dont care"), submits_a_fix_touching(SOME_PATH)
    )

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(base_branch=the_deployed_branch),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(_the_search_was_made_at(repository, the_deployed_branch))


@pytest.mark.unit
def test_the_model_is_told_to_search_before_it_reads() -> None:
    # An instruction rather than a hope. A model given three tools and no order
    # to use them in reaches for the one it is most used to, and a listing is
    # the familiar one - so the opening message says which is first, and the
    # tool that costs a whole reading budget says it is not.
    repository = a_repository()
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
        .then(_the_model_was_told(model, "search"))


@pytest.mark.unit
def test_the_model_is_told_that_a_change_which_exposed_a_fault_is_not_the_fault() -> None:
    # The failure this instruction exists to stop, seen in a live run: the
    # model searched, found the code, read it, and submitted nothing - because
    # a flag being switched on reads as "the cause was a configuration change,
    # so there is nothing here to fix". It is the wrong conclusion and an
    # attractive one, and the whole point of the step is the opposite: a flag
    # that broke the service exposed code that could not survive it, and the
    # job is to make it safe to switch back on.
    #
    # Reverting bought time. It is not a fix, and an agent that treats it as
    # one leaves the fault in place behind a toggle nobody dares move.
    repository = a_repository()
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
        .then(all_of(
            _the_model_was_told(model, "exposed"),
            _the_model_was_told(model, "safe to turn back on")
        ))


def _the_search_was_made_at(repository: _Repository,
                            ref: str) -> Assertion[OpenedPullRequest | None]:
    """The search ran against the branch a fix is cut from."""
    def assertion(dont_care_result: OpenedPullRequest | None) -> bool:
        asked = repository.search.call_args

        if asked is None or asked.args[1:2] != (ref,):
            raise AssertionError(
                f"Expected a search at ref [{ref}], got [{asked}]."
            )

        return True

    return assertion


@pytest.mark.unit
def test_a_search_by_meaning_is_answered_with_the_passages_it_found() -> None:
    # The channel for a cause with no name to search for. An investigation
    # concluding "the discount is divided by a count that can be zero" gives
    # substring search nothing to match on - the repository may not say
    # `discount` anywhere - and this finds the code that behaves that way.
    the_passage = f"{SOME_PATH}:14-16\n    return total / len(purchases)"
    repository = a_repository(reading_like=[the_passage])
    model = a_model_that(
        asks_to_search_by_meaning_for("divides by a count that can be zero"),
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
        .then(_the_model_was_told(model, the_passage))


@pytest.mark.unit
def test_a_search_by_meaning_that_matched_nothing_says_so() -> None:
    # Said rather than left as an empty answer, for the reason the substring
    # channel says it: a model handed nothing reads it as a tool that failed
    # and asks again in the same words, where one told the index holds nothing
    # like that describes the fault differently - which is the move that finds
    # the file.
    repository = a_repository(reading_like=[])
    model = a_model_that(
        asks_to_search_by_meaning_for("dont care"),
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
        .then(_the_model_was_told(model, "reads like that"))


@pytest.mark.unit
def test_a_search_by_meaning_is_made_at_the_branch_the_fix_is_cut_from() -> None:
    # The deployed branch, as every other read here is. The index may describe
    # an older commit and says so itself; what must not happen is this channel
    # quietly asking about a different branch than the one being patched.
    the_deployed_branch = "release"
    repository = a_repository()
    model = a_model_that(
        asks_to_search_by_meaning_for("dont care"),
        submits_a_fix_touching(SOME_PATH)
    )

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(base_branch=the_deployed_branch),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(_the_meaning_search_was_made_at(repository, the_deployed_branch))


@pytest.mark.unit
def test_an_index_that_could_not_be_searched_does_not_end_the_work() -> None:
    # A store that is down is one turn wasted, not a fix abandoned. The model
    # is told what failed, in words, and still has substring search, listing
    # and reading - so the run continues and the failure is something it can
    # act on rather than an exception the loop dies on.
    repository = a_repository()
    repository.search_by_meaning.side_effect = ConnectionError("no route to the store")
    model = a_model_that(
        asks_to_search_by_meaning_for("dont care"),
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
                _the_model_was_told(model, "no route to the store"),
                _a_pull_request_was_opened(repository)
            )
        )


@pytest.mark.unit
def test_a_deployment_with_an_index_offers_both_ways_of_searching() -> None:
    # They answer different questions and are worth having together: one
    # matches characters, the other meaning. A cause that has a name is found
    # faster by the first, and one that only has a description is found at all
    # by the second.
    repository = a_repository()
    model = a_model_that(submits_a_fix_touching(SOME_PATH))

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(retrieval=CodeSearch.BOTH),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(
            all_of(
                _the_model_was_offered(model, "search_repository"),
                _the_model_was_offered(model, "search_repository_by_meaning"),
                _the_model_was_offered(model, "read_repository_file"),
                _the_model_was_offered(model, "submit_fix")
            )
        )


@pytest.mark.unit
def test_a_deployment_with_no_index_offers_no_tool_that_cannot_answer() -> None:
    # A tool that is offered will be called, and one backed by an index nobody
    # built answers nothing for every description - which a model reads as a
    # fact about the code rather than about the deployment.
    repository = a_repository()
    model = a_model_that(submits_a_fix_touching(SOME_PATH))

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(retrieval=CodeSearch.GREP),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(
            all_of(
                _the_model_was_offered(model, "search_repository"),
                _the_model_was_not_offered(model, "search_repository_by_meaning")
            )
        )


@pytest.mark.unit
def test_a_run_of_meaning_alone_offers_no_substring_search() -> None:
    # What the benchmark's retriever comparison (§21) needs: one channel at a
    # time, over the same incidents, or the answer is about having both.
    repository = a_repository()
    model = a_model_that(submits_a_fix_touching(SOME_PATH))

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(retrieval=CodeSearch.MEANING),
                converse=model.converse,
                **repository.ports()
            )
        ) \
        .then(
            all_of(
                _the_model_was_offered(model, "search_repository_by_meaning"),
                _the_model_was_not_offered(model, "search_repository")
            )
        )


@pytest.mark.unit
def test_an_index_that_is_behind_is_said_before_the_model_reads_anything() -> None:
    # Told rather than left to find out. The index is built off any incident's
    # path, so it can describe an older commit than the one being fixed - and a
    # model that learns that from a patch against a file that has moved has
    # learned it after the work was done.
    what_the_index_says = (
        "the passages retrievable here describe commit 3f1b9d2, and the "
        "deployed branch is at 77296ac"
    )
    repository = a_repository(whose_index_says=what_the_index_says)
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
        .then(_the_model_was_told(model, what_the_index_says))


@pytest.mark.unit
def test_an_index_that_is_current_adds_nothing_to_what_the_model_is_told() -> None:
    # A warning printed every run is a warning nobody reads, which is how the
    # run where it was true goes unnoticed. Current means silent.
    repository = a_repository(whose_index_says="")
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
        .then(_the_model_was_not_told(model, "index"))


def _the_meaning_search_was_made_at(repository: _Repository,
                                    ref: str) -> Assertion[OpenedPullRequest | None]:
    """The search by meaning ran against the branch a fix is cut from."""
    def assertion(dont_care_result: OpenedPullRequest | None) -> bool:
        asked = repository.search_by_meaning.call_args

        if asked is None or asked.args[1:2] != (ref,):
            raise AssertionError(
                f"Expected a search by meaning at ref [{ref}], got [{asked}]."
            )

        return True

    return assertion


def _the_model_was_offered(model: _Model, tool: str) -> Assertion[Any]:
    """A tool the model could reach for, which is the whole of what it has."""
    def assertion(dont_care_result: Any) -> bool:
        offered = {
            definition.name
            for definitions in model.tools_offered
            for definition in definitions
        }

        if tool not in offered:
            raise AssertionError(f"Expected [{tool}] to be offered, got {offered}.")

        return True

    return assertion


def _the_model_was_not_offered(model: _Model, tool: str) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        offered = {
            definition.name
            for definitions in model.tools_offered
            for definition in definitions
        }

        if tool in offered:
            raise AssertionError(f"Expected [{tool}] not to be offered, got {offered}.")

        return True

    return assertion


def _the_model_was_not_told(model: _Model, said: str) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        everything = model.everything_it_was_told()

        if said in everything:
            raise AssertionError(
                f"Expected the model not to be told [{said}], and it was: "
                f"{everything}"
            )

        return True

    return assertion


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
def test_a_model_that_never_submits_says_so_rather_than_proposing_nothing() -> None:
    # Bounded, like the investigation is: a model reading file after file
    # without ever answering is a run that has to end somewhere. What it must
    # not do is end looking like an answer.
    #
    # "I read the code and there is nothing to change" and "I never finished
    # reading" reach the same human and only one of them is a conclusion. Told
    # apart here because nothing downstream can tell them apart afterwards - a
    # live run spent twelve turns exploring, returned nothing, and was recorded
    # as having found no fix, which was a statement about the budget dressed as
    # a verdict on the code.
    repository = a_repository()
    model = a_model_that(*[asks_to_list_files()] * 4)

    Scenario() \
        .when(
            attempting(
                lambda: propose_fix(
                    DONT_CARE_HYPOTHESIS,
                    DONT_CARE_INCIDENT,
                    settings=some_settings(max_tool_calls=3),
                    converse=model.converse,
                    **repository.ports()
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(FixNotAnswered),
                _no_branch_was_written(repository)
            )
        )


@pytest.mark.unit
def test_a_model_that_declines_says_so_rather_than_looking_like_a_broken_repository() -> None:
    # A refusal is a complete answer that says no, and it is the one outcome
    # more turns cannot fix: the same question over the same code is declined
    # again. Its own failure, because the next move is its own - not a wider
    # budget, not a repository to go and repair, and certainly not "the code
    # is fine", which is what a reader concludes from no pull request and no
    # reason.
    #
    # Uncaught, this reached the walk's broad handler and was reported as a
    # fix that could not be proposed - the same sentence a GitHub outage
    # produces. Two very different afternoons, told apart nowhere.
    repository = a_repository()
    model = a_model_that_declines()

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
            an_error_was_raised(FixDeclined)
        )


@pytest.mark.unit
def test_an_answer_cut_short_is_a_fix_that_did_not_finish() -> None:
    # Reported as not having finished rather than as not having been
    # possible, because that is what it is: a bound was too small. The bound
    # is room rather than turns, which is the one thing the detail has to
    # say - at a 128,000 ceiling an answer that still did not fit is a fix
    # too large to write as whole files, and no amount of extra turns or
    # repair changes that.
    repository = a_repository()
    model = a_model_that_is_cut_short()

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
            an_error_was_raised(FixNotAnswered)
        )


@pytest.mark.unit
def test_a_fix_that_reads_expensively_is_stopped_by_what_it_spent() -> None:
    # Code-Fix was bounded on turns and nothing else, which bounds the
    # cheapest axis there is. Its reading is whole files and its answers are
    # whole files, so a run can be frugal in turns and ruinous in tokens -
    # measured, a run that reads the three largest files in the Target
    # Service carries 47,950 tokens of source for every remaining turn.
    #
    # Stopped as not having finished, because that is what a bound is: the
    # looking stopped, and no verdict on the code was reached.
    a_generous_number_of_calls = 99
    some_token_bound = 5_000
    repository = a_repository()
    model = a_model_that(*[asks_to_list_files(costing=some_token_bound)] * 3)

    Scenario() \
        .when(
            attempting(
                lambda: propose_fix(
                    DONT_CARE_HYPOTHESIS,
                    DONT_CARE_INCIDENT,
                    settings=some_settings(
                        max_tool_calls=a_generous_number_of_calls,
                        max_tokens=some_token_bound
                    ),
                    converse=model.converse,
                    **repository.ports()
                )
            )
        ) \
        .then(
            an_error_was_raised(FixNotAnswered)
        )


@pytest.mark.unit
def test_a_model_on_its_last_call_is_told_so_before_it_spends_it() -> None:
    # The difference between an answer and a run thrown away. A model that
    # does not know it is on its last call spends it asking for one more
    # file, and everything it read up to then goes in the bin as "no fix
    # proposed" - which reads as a verdict on code nobody finished looking
    # at. Code-Fix is where that costs most: it is the agent that reads whole
    # files, so the turns being discarded are the expensive ones.
    two_calls = 2
    repository = a_repository()
    model = a_model_that(asks_to_list_files(), asks_to_read(SOME_PATH))

    Scenario() \
        .when(
            attempting(
                lambda: propose_fix(
                    DONT_CARE_HYPOTHESIS,
                    DONT_CARE_INCIDENT,
                    settings=some_settings(max_tool_calls=two_calls),
                    converse=model.converse,
                    **repository.ports()
                )
            )
        ) \
        .then(
            _the_model_was_told(model, THE_LAST_CALL_WARNING)
        )


@pytest.mark.unit
def test_a_model_that_submits_no_files_has_answered() -> None:
    # The other half of the same distinction, and a real conclusion: the code
    # was read and there is nothing in it to change. No branch, no proposal,
    # and no failure either - a human acts on this.
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


@pytest.mark.unit
def test_the_conversation_a_real_fix_has_is_recorded_against_its_incident() -> None:
    # Code-Fix was the one agent whose calls went nowhere, and it cost three
    # diagnoses in a row: a rejected request, an empty patch and a model that
    # declined, none of which left a transcript to read. What it spends is the
    # largest of any agent here - a repository in the context, resent every
    # turn - so an incident that cannot say what its fix cost cannot be costed
    # at all.
    #
    # Built here rather than bound by `fixes_over`, for the reason the
    # investigation's is: a recorded conversation needs the incident, and the
    # incident is not known until the fix is asked for.
    some_incident_id = "an-incident-being-fixed"
    conversations = create_autospec(a_conversation_recorded_for, instance=False)
    conversations.return_value = a_model_that(
        submits_a_fix_touching(SOME_PATH)
    ).converse
    recorder = create_autospec(Recorder, instance=True)

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                some_incident_id,
                settings=some_settings(),
                recorder=recorder,
                conversations=conversations,
                **a_repository().ports()
            )
        ) \
        .then(_the_conversation_was_recorded_for(conversations,
                                                 some_incident_id,
                                                 recorder))


@pytest.mark.unit
def test_a_scripted_conversation_never_reaches_the_real_client() -> None:
    # The seam that keeps every test above offline. A caller injecting a
    # conversation must not touch the construction behind it, or a unit test
    # would read configuration and build a vendor SDK to ask a double a
    # question.
    conversations = create_autospec(a_conversation_recorded_for, instance=False)

    Scenario() \
        .when(
            lambda: propose_fix(
                DONT_CARE_HYPOTHESIS,
                DONT_CARE_INCIDENT,
                settings=some_settings(),
                converse=a_model_that(submits_a_fix_touching(SOME_PATH)).converse,
                conversations=conversations,
                **a_repository().ports()
            )
        ) \
        .then(_no_conversation_was_built(conversations))


def _the_conversation_was_recorded_for(
    conversations: Any, incident_id: str, recorder: Any
) -> Assertion[OpenedPullRequest | None]:
    """The transcript is filed against the incident that caused it."""
    def assertion(dont_care_result: OpenedPullRequest | None) -> bool:
        asked = conversations.call_args

        if asked is None or asked.args != (incident_id, recorder):
            raise AssertionError(
                f"Expected a conversation built for [{incident_id}] with the "
                f"recorder, got [{asked}]."
            )

        return True

    return assertion


def _no_conversation_was_built(conversations: Any
                               ) -> Assertion[OpenedPullRequest | None]:
    def assertion(dont_care_result: OpenedPullRequest | None) -> bool:
        if conversations.called:
            raise AssertionError(
                f"Expected no conversation to be built, got "
                f"[{conversations.call_args}]."
            )

        return True

    return assertion


def _the_model_was_told(model: _Model, said: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if said not in model.everything_it_was_told():
            raise AssertionError(
                f"Expected the model to have been told [{said!r}]; it was not."
            )

        return True

    return assertion


def _the_model_was_not_told_a_repr(model: _Model) -> Assertion[Any]:
    """The finding said in words, not printed as an object.

    A hypothesis rendered into an f-string carries every claim with it, so a
    test asking only whether the evidence reached the model passes against a
    prompt that is a pydantic repr. This is what tells the two apart.
    """
    def assertion(_: Any) -> bool:
        told = model.everything_it_was_told()

        for leaked in ("supporting_evidence=", "Hypothesis(", "failure_mode="):
            if leaked in told:
                raise AssertionError(
                    f"Expected the model told prose, it was told [{leaked}]."
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


def asks_to_list_files(costing: int = NO_TOKENS) -> Turn:
    return _a_turn_calling("list_repository_files", {}, costing)


def asks_to_search_for(query: str) -> Turn:
    return _a_turn_calling("search_repository", {"query": query})


def asks_to_read(path: str) -> Turn:
    return _a_turn_calling("read_repository_file", {"path": path})


def asks_to_search_by_meaning_for(description: str) -> Turn:
    return _a_turn_calling(
        "search_repository_by_meaning", {"description": description}
    )


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


def _a_turn_calling(tool: str,
                    arguments: dict[str, Any],
                    costing: int = NO_TOKENS) -> Turn:
    """One turn asking for one thing, costing nothing unless a test says so.

    Free by default so that a bound is only ever reached by a test that asked
    for one - the same reason the investigator's turns are free. Costed where
    it matters, which is the reading: Code-Fix reads whole files, so what a
    turn costs is most of what a run costs, and until now no turn here could
    cost anything at all.
    """
    return Turn(
        text="",
        tool_calls=[ToolCall(id=f"call-{tool}", name=tool, arguments=arguments)],
        input_tokens=costing,
        output_tokens=NO_TOKENS
    )


class _Model:
    """A scripted conversation: one prepared turn per time it is asked.

    A stub rather than a mock, because what a test says about it is what the
    model *did*, and a scripted sequence says that in the order the loop drives
    it. Runs out deliberately - a loop asking for more turns than a test
    prepared is a loop that did not stop when it should have, and a stub that
    repeated its last turn forever would hide that behind a hang.
    """

    def __init__(self, turns: list[Turn | ModelDidNotAnswer]) -> None:
        self.turns = list(turns)
        self.transcripts: list[Transcript] = []
        self.tools_offered: list[list[ToolDefinition]] = []

    def converse(self, transcript: Transcript, tools: list[ToolDefinition]) -> Turn:
        self.transcripts.append(list(transcript))
        self.tools_offered.append(list(tools))

        if not self.turns:
            raise AssertionError("The loop asked for more turns than were scripted.")

        answered = self.turns.pop(0)

        # A turn that is an exception is raised rather than returned, because
        # that is what the seam does with it: a turn the model did not finish
        # carries nothing to hand back, and what the loop does about it is the
        # point of the tests that script one.
        if isinstance(answered, ModelDidNotAnswer):
            raise answered

        return answered

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


def a_model_that_declines() -> _Model:
    """A model whose first turn is a complete answer saying no.

    Its own builder rather than a turn, because a refusal is not a turn: the
    adapter raises it, so what a loop meets is an exception where a `Turn`
    would have been. A test scripting one as content would be checking how
    the loop reads words the model never sent in that shape.
    """
    return _Model([ModelRefused("the model declined to answer")])


def a_model_that_is_cut_short() -> _Model:
    """A model whose first turn ran out of room before it finished.

    Costed, because a turn stopped at its cap generated every token of that
    cap and was billed for all of them - and Code-Fix's cap is the largest in
    the system, so this is the most expensive way a fix can fail.
    """
    return _Model([
        AnswerTruncated(
            "the model ran out of room before finishing its turn",
            billed=Turn(
                text="", tool_calls=[], input_tokens=0, output_tokens=128_000
            )
        )
    ])


class _Repository:
    """The ports the loop reaches the repository through.

    Spec'd against the `Protocol`s rather than against the client functions
    those are implemented by: a client function takes the connection it is asked
    over, and the loop is asked about a repository. The same reasoning that puts
    `Protocol`s in the investigator's `retrieval` instead of specing against
    `get_log_lines`.
    """

    def __init__(self,
                 holding: list[str],
                 whose_source_is: str,
                 found: list[str],
                 reading_like: list[str],
                 whose_index_says: str) -> None:
        self.list_files: Any = create_autospec(
            FileLister, instance=True, return_value=holding
        )
        self.search: Any = create_autospec(
            SourceSearcher, instance=True, return_value=found
        )
        self.search_by_meaning: Any = create_autospec(
            MeaningSearcher, instance=True, return_value=reading_like
        )
        self.index_notice: Any = create_autospec(
            IndexNotice, instance=True, return_value=whose_index_says
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
        """The seams, as the keywords `propose_fix` takes them by.

        Handed over as one mapping because every test needs all of them and
        only ever cares about one - naming the rest at ten call sites would
        bury the line each test is actually about.
        """
        return {
            "list_files": self.list_files,
            "search": self.search,
            "search_by_meaning": self.search_by_meaning,
            "index_notice": self.index_notice,
            "read_file": self.read_file,
            "write_branch": self.write_branch,
            "open_pull_request": self.open_pull_request
        }


def a_repository(holding: list[str] | None = None,
                 whose_source_is: str = SOME_SOURCE,
                 where: list[str] | None = None,
                 reading_like: list[str] | None = None,
                 whose_index_says: str = "") -> _Repository:
    """The repository as the loop sees it - indexed, and current unless said.

    `whose_index_says` empty is an index describing the commit being fixed,
    which is the ordinary state and the one that must add nothing to what the
    model is told.
    """
    return _Repository(
        holding or [SOME_PATH],
        whose_source_is,
        where if where is not None else [f"{SOME_PATH}:8: the flag is read here"],
        reading_like if reading_like is not None else [
            f"{SOME_PATH}:4-9\n{SOME_SOURCE}"
        ],
        whose_index_says
    )


def some_settings(base_branch: str = "main",
                  max_tool_calls: int = 12,
                  retrieval: CodeSearch = CodeSearch.BOTH,
                  model: str = SOME_MODEL,
                  effort: Effort = SOME_EFFORT,
                  max_output_tokens: int = SOME_MAX_OUTPUT_TOKENS,
                  max_tokens: int = ROOM_TO_SPARE_IN_TOKENS,
                  max_seconds: float = ROOM_TO_SPARE_IN_SECONDS
                  ) -> FixSettings:
    """What the fix loop is bounded and aimed by.

    `base_branch` is what a fix is cut from and proposed onto - the branch that
    is actually deployed.

    The three bounds exist for the reason the investigation's do: they fail
    differently and none implies the others. An agent reading whole files is
    cheap in calls and ruinous in tokens, which is exactly the case a call
    count alone cannot see. Generous by default, so that a bound binding in a
    test which never mentioned one would be the test's own doing.

    `retrieval` is which ways of finding code the model is offered. Both by
    default, because a deployment that has an index should use it - and because
    the tests that care which are offered say so, where the rest are about what
    happens once something has been found.

    `model` and `effort` are which model writes the fix and how hard it is
    asked to think. Deliberately not the production defaults: a test asserting
    that the configured model is the one asked for would pass against a loop
    ignoring the setting entirely, if the setting happened to name what the
    code would have reached for anyway.
    """
    return FixSettings(
        github_base_branch=base_branch,
        codefix_max_tool_calls=max_tool_calls,
        codefix_max_tokens=max_tokens,
        codefix_max_seconds=max_seconds,
        code_search=retrieval,
        codefix_model=model,
        codefix_effort=effort,
        codefix_max_output_tokens=max_output_tokens
    )

