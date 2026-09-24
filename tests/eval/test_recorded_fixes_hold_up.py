"""Whether the fixes Code-Fix actually proposed work, run against the shop's tests.

Code-Fix proposes statically - no sandbox, no test runner - so it never learns
whether its patch works, and until now neither did anybody else before a human
read the pull request. This is where that is found out: after the fact, for
nothing, against patches that were paid for once already and are committed.

Modelless, and so unlike everything else in this directory. The other evals here
call the real API and score judgement; this one calls nothing. Its inputs are the
recordings in this repository and the Target Service in its own, both committed,
which is why no result is written down - a verdict for any past commit is had by
checking that commit out and running this again.

Three runs per patch, and the first is what makes the second readable:

1. The shop's own suite, before anything is written. It must pass. Everything
   after this is attributed to what was written, and that attribution is only
   sound if the service was sound first.

2. The patch's *test* files alone, against the unfixed shop. They must not pass.
   A failing assertion and an import error both count: a fix that adds a module,
   a class or a constant leaves its test unable to import until it is applied,
   which is most real fixes rather than an edge case. What both rule out is the
   submission this exists to catch - a test that passes either way, and so
   demonstrates nothing. This is the submit tool's "bring the test that exposes
   the bug", and nothing verified it before.

3. The whole patch. The shop's entire suite must pass - the new tests and every
   test that passed without them - and the tests that failed in run 2 are asked
   for again by name, so a patch cannot pass by deleting the test it was failing.

The suite is `tests/io_shop`, never `tests`: the harness suite beside it asserts
the planted faults are still present, so every working fix breaks it by design.

The shop is written to and put back with git. It is refused outright when that
tree is dirty: this overwrites files there, and uncommitted work would be
restored to the last commit along with them.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario

from tests.e2e.framework.argus import THE_RECORDINGS_THAT_MUST_CARRY_A_FIX

# tests/eval/test_recorded_fixes_hold_up.py -> the repository root.
ARGUS_REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDINGS_DIR = ARGUS_REPO_ROOT / "modules" / "anthropic_double" / "recordings"

# The Target Service's own checkout, beside this one. Its tests are the grader,
# and that is the point of them: they are the shop's own, written against the
# shop, and neither Argus nor the model had a hand in them.
THE_SHOP = ARGUS_REPO_ROOT.parent / "Argus-Demo-Target-App"

# The mode whose corpus is graded. `both` is what a deployment runs and what CI
# replays; the other two are the benchmark's arrangement and their recordings
# predate this.
THE_MODE = "both"

SUBMIT_TOOL_NAME = "submit_fix"
TOOL_USE_TYPE = "tool_use"
FILES_FIELD = "files"
PATH_FIELD = "path"
CONTENT_FIELD = "content"

# Where the shop keeps its tests. The split has to be the path rather than the
# filename: a module called `test_something.py` under `src/` would be source,
# whatever it is named.
TESTS_DIRECTORY = "tests/"

# `-rEf` prints one `FAILED <node id>` line per failure and one `ERROR <file>`
# per collection error, which is all of pytest's output this reads. Both are
# matched, and kept apart: which one a run produced is what tells a reader
# whether a test disagreed with the service or could not be imported against it.
A_FAILED_TEST = re.compile(r"^FAILED (\S+)", re.MULTILINE)
A_COLLECTION_ERROR = re.compile(r"^ERROR (\S+)", re.MULTILINE)

A_WHOLE_SUITE_SECONDS = 900


@dataclass(frozen=True)
class Ran:
    """One run of the shop's tests, said as what a reader of it needs.

    `errors` is separate from `failures` because the two mean opposite things
    here. A failure is the evidence a red pass is looking for; an error is a file
    that did not run, which is evidence of nothing.
    """

    passed: bool
    failures: tuple[str, ...]
    errors: tuple[str, ...]
    output: str


def _pytest_in_the_shop(*arguments: str) -> Ran:
    """Runs the shop's suite where it lives, with its own interpreter.

    In place rather than in a copy: the shop's virtual environment is what runs
    its tests, and the package it installed points at the real `src/`, so a copy
    would be graded against the source it was copied from.
    """
    run = subprocess.run(
        ["uv", "run", "python", "-m", "pytest", *arguments, "-q", "--tb=no", "-rEf"],
        cwd=THE_SHOP, capture_output=True, text=True, timeout=A_WHOLE_SUITE_SECONDS
    )
    said = run.stdout + run.stderr

    return Ran(
        passed=run.returncode == 0,
        failures=tuple(A_FAILED_TEST.findall(said)),
        errors=tuple(A_COLLECTION_ERROR.findall(said)),
        output=said
    )


def _the_answer_number_of(recording: Path) -> int:
    numbered = re.search(r"-(\d+)$", recording.stem)

    return int(numbered.group(1)) if numbered else 1


def _every_corpus() -> dict[str, list[Path]]:
    """Each scenario's recordings, in the order the double serves them.

    Sorted by the trailing number rather than as text, where `-10` would come
    before `-2` and the walk would be read shuffled.
    """
    corpora: dict[str, list[Path]] = {}

    for recording in RECORDINGS_DIR.glob(f"{THE_MODE}-*.json"):
        corpora.setdefault(re.sub(r"-\d+$", "", recording.stem), []).append(recording)

    return {
        scenario: sorted(paths, key=_the_answer_number_of)
        for scenario, paths in sorted(corpora.items())
    }


def _the_patch_in(corpus: list[Path]) -> dict[str, str]:
    """The fix this walk submitted, as path to whole contents, or nothing at all.

    Empty for a walk that proposed no fix - one that escalated, or concluded the
    cause was not in the code. That is a walk with nothing to grade rather than a
    walk that failed.

    A `files` argument that arrived as a string is read for the array inside it,
    the way the agent's own reader does: a model asked for a large array
    sometimes sends its JSON as text, and grading those walks as "proposed
    nothing" would skip exactly the answers worth grading.
    """
    for recording in corpus:
        body = json.loads(recording.read_text(encoding="utf-8"))

        for block in body.get("content", []):
            if block.get("type") != TOOL_USE_TYPE or block.get("name") != SUBMIT_TOOL_NAME:
                continue

            submitted = block.get("input", {}).get(FILES_FIELD)

            if isinstance(submitted, str):
                try:
                    submitted = json.loads(submitted)
                except ValueError:
                    return {}

            if not isinstance(submitted, list):
                return {}

            return {
                entry[PATH_FIELD]: entry[CONTENT_FIELD]
                for entry in submitted
                if isinstance(entry, dict)
                and isinstance(entry.get(PATH_FIELD), str)
                and isinstance(entry.get(CONTENT_FIELD), str)
            }

    return {}


def the_scenarios_that_proposed_a_fix() -> list[str]:
    """Which recorded walks there is anything to grade in.

    Read at collection time so each scenario is its own case: a corpus that
    stopped holding up should name itself in the failure, not be one line of a
    table nobody reads to the end.
    """
    return [scenario for scenario, corpus in _every_corpus().items()
            if _the_patch_in(corpus)]


def _the_shop_is_clean() -> bool:
    status = subprocess.run(
        ["git", "-C", str(THE_SHOP), "status", "--porcelain"],
        capture_output=True, text=True, check=True
    )

    return not status.stdout.strip()


def _put_the_shop_back() -> None:
    """Restores the shop to its last commit, files the patch added included.

    `clean -fd` and never `-fdx`: the virtual environment is ignored by git, and
    `-x` would delete the interpreter the next run needs.
    """
    subprocess.run(["git", "-C", str(THE_SHOP), "checkout", "--", "."], check=True)
    subprocess.run(["git", "-C", str(THE_SHOP), "clean", "-fd"], check=True)


def _write_into_the_shop(patch: dict[str, str]) -> None:
    for path, content in patch.items():
        written = THE_SHOP / path
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(content, encoding="utf-8")


@dataclass(frozen=True)
class Graded:
    """What one recorded patch turned out to be worth.

    Three runs rather than two. `the_same_tests_again` is the failing nodes from
    the red pass, put again with the fix in place: the suite passing as a whole
    does not say those particular tests do, because a patch that deleted the test
    that had been failing would also pass.
    """

    scenario: str
    tests: tuple[str, ...]
    before_anything: Ran
    without_the_fix: Ran
    with_the_fix: Ran
    the_same_tests_again: Ran | None


def _graded(scenario: str) -> Graded:
    """One patch, put to the shop twice, with the shop's own state read first.

    The baseline is what lets the second run be read at all. A fix routinely adds
    a module, a class or a constant, so its test cannot import against the
    unfixed service - and an import error there is evidence about the patch only
    if the service was importing cleanly a moment earlier. Establish that first,
    and every failure and error afterwards belongs to what was written.

    Restored between the runs and again on the way out, so one pass is not
    grading the last one's leftovers and the next scenario is not grading this
    one's.
    """
    patch = _the_patch_in(_every_corpus()[scenario])
    tests = tuple(path for path in patch if path.startswith(TESTS_DIRECTORY))

    try:
        # Before anything is written. Whatever this says is true of the shop
        # rather than of the patch, which is the only reason the next run means
        # anything.
        before_anything = _pytest_in_the_shop(f"{TESTS_DIRECTORY}io_shop")

        _write_into_the_shop({path: patch[path] for path in tests})
        # The patch's own test files and nothing else. Running the whole suite
        # here would answer a different question - whether anything in the shop
        # fails - and a pre-existing failure would answer it for us.
        without_the_fix = _pytest_in_the_shop(*tests)
        _put_the_shop_back()

        _write_into_the_shop(patch)
        # `tests/io_shop` and not `tests`: the harness suite beside it asserts
        # the faults are still there, so a fix that works fails it.
        with_the_fix = _pytest_in_the_shop(f"{TESTS_DIRECTORY}io_shop")
        # By node id, so the answer is about those tests rather than about the
        # suite. Skipped when nothing failed - there is then no claim to check,
        # and the assertion about the red pass has already said so.
        the_same_tests_again = (
            _pytest_in_the_shop(*without_the_fix.failures)
            if without_the_fix.failures else None
        )
    finally:
        _put_the_shop_back()

    return Graded(scenario, tests, before_anything, without_the_fix,
                  with_the_fix, the_same_tests_again)


@pytest.mark.eval
@pytest.mark.parametrize("scenario", the_scenarios_that_proposed_a_fix())
def test_a_recorded_fix_is_demonstrated_by_its_own_test_and_breaks_nothing(
    scenario: str
) -> None:
    # Free, and the only case in this directory that is. It reads recordings and
    # runs somebody else's test suite; no model is called and nothing is
    # recorded, because both inputs are committed and the verdict is therefore
    # recomputable at any commit.
    if not THE_SHOP.is_dir():
        pytest.skip(f"the Target Service is not checked out at {THE_SHOP}")

    if not _the_shop_is_clean():
        pytest.fail(
            f"Expected a clean tree at {THE_SHOP}; it has uncommitted changes. This "
            f"grades by overwriting files there and putting them back with git, so "
            f"it will not run over unfinished work."
        )

    Scenario() \
        .given(scenario) \
        .when(lambda: _graded(scenario)) \
        .then(all_of(
            _it_brought_a_test(),
            _the_service_was_sound_to_begin_with(),
            _its_test_does_not_pass_without_the_fix(),
            _the_whole_suite_passes_with_the_fix(),
            _the_tests_that_failed_are_the_ones_that_pass()
        ))


@pytest.mark.eval
def test_every_walk_that_should_have_proposed_a_fix_did() -> None:
    # The gap the case above cannot see. It grades the patches that exist, so a
    # scenario that stopped proposing one simply stops being collected - the run
    # gets shorter, stays green, and nobody is told that the agent went quiet on
    # a case it used to answer.
    #
    # Read against the declaration the recorder refuses on, so there is one list
    # rather than two drifting apart. A scenario absent from it proposes no fix
    # by design - a misconfigured cache is rolled back, not patched - and is not
    # a failure here.
    if not RECORDINGS_DIR.is_dir():
        pytest.skip(f"no recordings to grade at {RECORDINGS_DIR}")

    proposed = {scenario.removeprefix(f"{THE_MODE}-")
                for scenario in the_scenarios_that_proposed_a_fix()}
    recorded = {scenario.removeprefix(f"{THE_MODE}-") for scenario in _every_corpus()}

    Scenario() \
        .given(recorded) \
        .when(lambda: proposed) \
        .then(_every_walk_that_had_to_propose_one_is_here(recorded))


def _every_walk_that_had_to_propose_one_is_here(
    recorded: set[str]
) -> Assertion[set[str]]:
    """That no scenario quietly stopped submitting a fix.

    Measured against what was actually recorded, so a corpus that has not been
    captured for a scenario yet is not reported as that scenario going silent -
    those are different afternoons, and only one of them is about the agent.
    """
    def assertion(proposed: set[str]) -> bool:
        went_quiet = sorted(
            (THE_RECORDINGS_THAT_MUST_CARRY_A_FIX & recorded) - proposed
        )

        if went_quiet:
            raise AssertionError(
                f"Expected every walk that must carry a fix to have proposed one; "
                f"{went_quiet} did not. Either the agent stopped answering on "
                f"those, or they no longer belong in "
                f"THE_RECORDINGS_THAT_MUST_CARRY_A_FIX."
            )

        return True

    return assertion


def _it_brought_a_test() -> Assertion[Graded]:
    """That the patch carried a test at all.

    Its own assertion rather than folded into the next, because "brought no
    test" and "brought a test that proves nothing" are different things for a
    reader to go and do something about.
    """
    def assertion(graded: Graded) -> bool:
        if not graded.tests:
            raise AssertionError(
                f"Expected [{graded.scenario}] to have brought a test with its fix; "
                f"it submitted no file under [{TESTS_DIRECTORY}]."
            )

        return True

    return assertion


def _the_service_was_sound_to_begin_with() -> Assertion[Graded]:
    """That the shop was passing its own tests before the patch was written in.

    The premise the next assertion rests on. Without it, an error after the
    patch's test is written could be the shop's and not the patch's, and the
    grader would be reporting somebody else's breakage as evidence about a fix.
    """
    def assertion(graded: Graded) -> bool:
        if not graded.before_anything.passed:
            raise AssertionError(
                f"Expected the service to pass its own tests before "
                f"[{graded.scenario}]'s patch was written in; it did not. "
                f"Failures {list(graded.before_anything.failures)}, errors "
                f"{list(graded.before_anything.errors)}. Nothing about the patch "
                f"can be concluded from a service that was already "
                f"broken.\n{graded.before_anything.output}"
            )

        return True

    return assertion


def _its_test_does_not_pass_without_the_fix() -> Assertion[Graded]:
    """That the test needs the fix, whichever way it says so.

    A failing assertion and an import error both count, and the second is not the
    lesser case it looks like: a fix that adds a module, a class or a constant
    leaves its test unable to import against the unfixed service, which is most
    real fixes rather than an edge. Refusing those would mark correct work wrong.

    What both rule out is the submission this exists to catch - a test that
    passes whether or not the fix is applied, and so demonstrates nothing. The
    baseline above is what makes an error admissible: the service was importing
    cleanly a moment ago, so this one arrived with the test.
    """
    def assertion(graded: Graded) -> bool:
        if graded.without_the_fix.passed:
            raise AssertionError(
                f"Expected [{graded.scenario}]'s test not to pass against the "
                f"service without its fix; it passed, so it demonstrates nothing "
                f"about the fault.\n{graded.without_the_fix.output}"
            )

        return True

    return assertion


def _the_whole_suite_passes_with_the_fix() -> Assertion[Graded]:
    """That the fix works and cost nothing else.

    The shop's own suite, and only it. `tests/target_app/` beside it tests the
    harness that stages the scenarios, and those tests assert the faults are
    present - that a flag-on minute reads as degraded, that the statement panel
    fails in the file the fix has to touch. A working fix breaks every one of
    them, by design, so grading against them marks a correct answer wrong.

    The whole of `tests/io_shop`, though, not the touched files: a fix that
    satisfies one module and breaks the ones calling it is this job's
    """
    def assertion(graded: Graded) -> bool:
        if not graded.with_the_fix.passed:
            raise AssertionError(
                f"Expected the service's suite to pass with [{graded.scenario}]'s "
                f"fix applied; it failed: {list(graded.with_the_fix.failures)}. "
                f"Output:\n{graded.with_the_fix.output}"
            )

        return True

    return assertion


def _the_tests_that_failed_are_the_ones_that_pass() -> Assertion[Graded]:
    """That the fix answered the failure its own test reported.

    The suite passing with the patch applied is not by itself proof: it would
    also pass if the patch quietly deleted the test that had been failing. So
    the nodes that failed in the red pass are required to be present and passing
    in the green one.
    """
    def assertion(graded: Graded) -> bool:
        ran_again = graded.the_same_tests_again

        if ran_again is None:
            return True

        if not ran_again.passed:
            raise AssertionError(
                f"Expected the tests that failed without [{graded.scenario}]'s fix "
                f"to pass with it, asked for by name: "
                f"{list(graded.without_the_fix.failures)}. What came back: "
                f"failures {list(ran_again.failures)}, errors "
                f"{list(ran_again.errors)}.\n{ran_again.output}"
            )

        return True

    return assertion
