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

Three runs per patch, and a fourth shared by all of them that makes the rest
readable:

1. The shop's own suite, before anything is written. It must pass. Everything
   after this is attributed to what was written, and that attribution is only
   sound if the service was sound first. Run once for the whole session: every
   patch is graded against the same commit of the shop, so a second run would
   be asked the same question about the same files.

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

A patch whose every file is configuration may come without a test, as Code-Fix
lets it: a test for a values file reads the value back, which proves nothing
about what the value does. Run 2 is skipped for it, having nothing to run, and
run 3 still has to pass - a setting that breaks the shop's suite is graded wrong.

The suite is `tests/io_shop`, never `tests`: the harness suite beside it asserts
the planted faults are still present, so every working fix breaks it by design.

Nothing is written into the shop's own checkout. Each patch, and the baseline,
gets a throwaway `git worktree` of the shop's HEAD, and the patches are graded
side by side, one worktree each, so no patch can see another's files. The shop
need only be there: uncommitted work in it is neither graded nor touched, which
is why a dirty tree is no longer refused.

Every worktree runs in the shop's one environment, synced from HEAD's lock. A
patch that rewrites the shop's `pyproject.toml` or `uv.lock` would be graded
without the dependencies it asks for, so it fails on that by name, listed
before whatever the suite then reports.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario
from codefix_agent import SubmittedFix, changes_only_configuration
from pydantic import ValidationError

from tests.e2e.framework.argus import THE_RECORDINGS_THAT_MUST_CARRY_A_FIX

# tests/eval/test_recorded_fixes_hold_up.py -> the repository root.
ARGUS_REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDINGS_DIR = ARGUS_REPO_ROOT / "test_support" / "anthropic_double" / "recordings"

# The Target Service's own checkout, beside this one. Its tests are the grader,
# and that is the point of them: they are the shop's own, written against the
# shop, and neither Argus nor the model had a hand in them.
THE_SHOP = ARGUS_REPO_ROOT.parent / "Argus-Demo-Target-App"

# The interpreter of the shop's own virtual environment, which is what runs its
# tests. Where a virtual environment keeps it is the platform's choice, not
# uv's.
THE_SHOPS_INTERPRETER = (
    THE_SHOP / ".venv" / "Scripts" / "python.exe" if sys.platform == "win32"
    else THE_SHOP / ".venv" / "bin" / "python"
)

# The modes whose corpora are graded. `both` is what a deployment runs and what CI
# replays, and `grep` is recorded against the same prompts; `meaning`'s recordings
# predate this, and it is not recorded.
THE_MODES = ("both", "grep")

SUBMIT_TOOL_NAME = "submit_fix"
TOOL_USE_TYPE = "tool_use"

# Where the shop keeps its tests. The split has to be the path rather than the
# filename: a module called `test_something.py` under `src/` would be source,
# whatever it is named.
TESTS_DIRECTORY = "tests/"
THE_SHOPS_SUITE = f"{TESTS_DIRECTORY}io_shop"

# The files that say what the shop's environment holds. Every run uses the one
# environment, synced from HEAD's lock, so a patch that changes either would be
# graded without what it asks for - a new dependency would read as the fix
# failing.
THE_SHOPS_ENVIRONMENT_FILES = ("pyproject.toml", "uv.lock")

# Where the shop keeps its packages - the directory its editable install points
# at, and so the one each worktree has to put ahead of it.
SOURCE_DIRECTORY = "src"

# Python's own variables. The first is how a worktree's `src/` is imported ahead
# of the editable install, which is a `.pth` line and so lands after
# site-packages, behind anything on this. The second keeps a run from leaving
# bytecode behind for the next run in the same worktree: a module the patch
# rewrites within the second, at the same length, would otherwise be read from
# the bytecode of the version it replaced.
IMPORT_PATH_VARIABLE = "PYTHONPATH"
NO_BYTECODE_VARIABLE = "PYTHONDONTWRITEBYTECODE"

# The baseline's worktree. Not a scenario's name, which always opens with a mode.
THE_BASELINES_CHECKOUT = "before-anything"

# `-rEf` prints one `FAILED <node id>` line per failure and one `ERROR <file>`
# per collection error, which is all of pytest's output this reads. Both are
# matched, and kept apart: which one a run produced is what tells a reader
# whether a test disagreed with the service or could not be imported against it.
A_FAILED_TEST = re.compile(r"^FAILED (\S+)", re.MULTILINE)
A_COLLECTION_ERROR = re.compile(r"^ERROR (\S+)", re.MULTILINE)

A_WHOLE_SUITE_SECONDS = 900

# One grade per core. Each grade is a pytest process at a time, single-threaded,
# so more than this only queues them for the processor instead of the pool.
A_GRADE_PER_CORE = os.cpu_count() or 1

# `git worktree add` and `remove` write the shop's own `.git`, and two at once
# can find each other's lock there. They are a fraction of a grade, so they
# take turns and the test runs between them do not.
ONE_WORKTREE_CHANGE_AT_A_TIME = threading.Lock()


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


@dataclass(frozen=True)
class Checkouts:
    """The commit of the shop every run is graded against, and where its
    worktrees go.

    One commit, read once: a commit made in the shop while this runs would
    otherwise leave the baseline and the grades describing different services.
    """

    commit: str
    under: Path


def _pytest_in(checkout: Path, *arguments: str) -> Ran:
    """Runs the shop's suite in one of its worktrees, with its own interpreter.

    The shop's interpreter rather than one of the worktree's own: its virtual
    environment is what runs its tests, and building one per worktree would cost
    more than every test in it. That environment's editable install points at
    the shop's real `src/`, so the worktree's `src/` is put first on the import
    path - without it, every patch would be graded against the unpatched source.
    """
    inherited = os.environ.get(IMPORT_PATH_VARIABLE)
    run = subprocess.run(
        [str(THE_SHOPS_INTERPRETER), "-m", "pytest", *arguments, "-q", "--tb=no", "-rEf"],
        cwd=checkout, capture_output=True, text=True, timeout=A_WHOLE_SUITE_SECONDS,
        env={
            **os.environ,
            IMPORT_PATH_VARIABLE: os.pathsep.join(
                [str(checkout / SOURCE_DIRECTORY), *([inherited] if inherited else [])]
            ),
            NO_BYTECODE_VARIABLE: "1"
        }
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

    for recording in (path for mode in THE_MODES
                      for path in RECORDINGS_DIR.glob(f"{mode}-*.json")):
        corpora.setdefault(re.sub(r"-\d+$", "", recording.stem), []).append(recording)

    return {
        scenario: sorted(paths, key=_the_answer_number_of)
        for scenario, paths in sorted(corpora.items())
    }


def _the_patch_in(corpus: list[Path]) -> dict[str, str]:
    """The fix this walk submitted, as the agent would write it to the branch.

    Empty for a walk that proposed no fix - one that escalated, or concluded the
    cause was not in the code. That is a walk with nothing to grade rather than a
    walk that failed.

    Read through `SubmittedFix` rather than out of the JSON, and that is the
    whole of what this grades: a human reviews the files that reach the branch,
    so the question is whether *those* hold up. A copy of the agent's leniency
    lived here and answered a different question - what the model said - and the
    two part company the moment anything in the agent repairs a malformed
    answer, which is the day a patch that lands correct would be graded on the
    mangled text it arrived as.

    Not a loss of independence. What must not grade this agent is the model, and
    the model is nowhere in here; the writer is deterministic production code
    with a suite of its own.

    The last submission rather than the first. A walk submits more than once
    when the handler bounces an answer that carried no files and the model
    tries again, and the one that reached the branch is the one the walk ended
    on.
    """
    submitted: dict[str, str] = {}

    for recording in corpus:
        body = json.loads(recording.read_text(encoding="utf-8"))

        for block in body.get("content", []):
            if block.get("type") != TOOL_USE_TYPE or block.get("name") != SUBMIT_TOOL_NAME:
                continue

            try:
                submitted = SubmittedFix.model_validate(block.get("input", {})).patch()
            except ValidationError:
                submitted = {}

    return submitted


def the_scenarios_that_proposed_a_fix() -> list[str]:
    """Which recorded walks there is anything to grade in.

    Read at collection time so each scenario is its own case: a corpus that
    stopped holding up should name itself in the failure, not be one line of a
    table nobody reads to the end.
    """
    return [scenario for scenario, corpus in _every_corpus().items()
            if _the_patch_in(corpus)]


def _git_in_the_shop(*arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(THE_SHOP), *arguments],
        capture_output=True, text=True, check=True
    ).stdout.strip()


@contextmanager
def _a_worktree_of(shop: Checkouts, name: str) -> Iterator[Path]:
    """A checkout of the shop's commit of its own, gone again on the way out.

    Detached, so no branch is made in the shop for it. Removed with `--force`
    because a grade leaves the patch's files in it, and pruned after, so a
    removal that failed - a file still held open on Windows - leaves no entry
    behind in the shop's `.git` once the directory under it is cleaned up.
    """
    checkout = shop.under / name

    with ONE_WORKTREE_CHANGE_AT_A_TIME:
        _git_in_the_shop("worktree", "add", "--detach", str(checkout), shop.commit)

    try:
        yield checkout
    finally:
        with ONE_WORKTREE_CHANGE_AT_A_TIME:
            subprocess.run(
                ["git", "-C", str(THE_SHOP), "worktree", "remove", "--force", str(checkout)],
                capture_output=True, check=False
            )
            _git_in_the_shop("worktree", "prune")


def _write_into(checkout: Path, patch: dict[str, str]) -> None:
    for path, content in patch.items():
        written = checkout / path
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
    configuration_only: bool
    # Which of the shop's environment files the patch rewrites, which nothing
    # here installs.
    environment_files: tuple[str, ...]
    before_anything: Ran
    # `None` where the patch brought no test to run.
    without_the_fix: Ran | None
    with_the_fix: Ran
    the_same_tests_again: Ran | None


def _graded(scenario: str, before_anything: Ran, shop: Checkouts) -> Graded:
    """One patch, put to a worktree of the shop twice, read against the shop's
    own state.

    The baseline is what lets the second run be read at all. A fix routinely adds
    a module, a class or a constant, so its test cannot import against the
    unfixed service - and an import error there is evidence about the patch only
    if the service was importing cleanly at the same commit. That is established
    once, before any patch is written, and every failure and error here belongs
    to what was written.

    The tests first and the rest of the patch over them, in the one worktree:
    the tests are written again unchanged, so what the second run sees is the
    whole patch and nothing else. The worktree is this patch's alone, so no
    other grade is reading its leftovers.
    """
    patch = _the_patch_in(_every_corpus()[scenario])
    tests = tuple(path for path in patch if path.startswith(TESTS_DIRECTORY))

    with _a_worktree_of(shop, scenario) as checkout:
        without_the_fix = None
        if tests:
            _write_into(checkout, {path: patch[path] for path in tests})
            # The patch's own test files and nothing else. Running the whole
            # suite here would answer a different question - whether anything in
            # the shop fails - and a pre-existing failure would answer it for us.
            without_the_fix = _pytest_in(checkout, *tests)

        _write_into(checkout, patch)
        # `tests/io_shop` and not `tests`: the harness suite beside it asserts
        # the faults are still there, so a fix that works fails it.
        with_the_fix = _pytest_in(checkout, THE_SHOPS_SUITE)
        # By node id, so the answer is about those tests rather than about the
        # suite. Skipped when nothing failed - there is then no claim to check,
        # and the assertion about the red pass has already said so.
        the_same_tests_again = (
            _pytest_in(checkout, *without_the_fix.failures)
            if without_the_fix is not None and without_the_fix.failures else None
        )

    environment_files = tuple(path for path in patch if path in THE_SHOPS_ENVIRONMENT_FILES)

    return Graded(scenario, tests, changes_only_configuration(patch), environment_files,
                  before_anything, without_the_fix, with_the_fix, the_same_tests_again)


@pytest.fixture(scope="session")
def the_shop() -> Iterator[Checkouts]:
    """The shop's HEAD, its environment in step with its lock, and a directory
    for the worktrees that is gone when the session is.

    The environment is synced as `uv run` would have before each run - minimally,
    keeping anything else installed there - and from the lock as it stands, so
    the shop's tree is not written even when its lock is behind. A fresh CI
    checkout has no environment at all, and this is what makes one.
    """
    if not THE_SHOP.is_dir():
        pytest.skip(f"the Target Service is not checked out at {THE_SHOP}")

    synced = subprocess.run(
        ["uv", "sync", "--project", str(THE_SHOP), "--frozen", "--inexact"],
        capture_output=True, text=True, check=False
    )
    if synced.returncode != 0:
        pytest.fail(
            f"Expected `uv sync` to make the shop's environment at [{THE_SHOP}]; it "
            f"exited [{synced.returncode}]:\n{synced.stderr}"
        )

    with TemporaryDirectory(prefix="grade-fixes-", ignore_cleanup_errors=True) as under:
        yield Checkouts(_git_in_the_shop("rev-parse", "HEAD"), Path(under))

    _git_in_the_shop("worktree", "prune")


@pytest.fixture(scope="session")
def the_shop_before_anything(the_shop: Checkouts) -> Ran:
    """The shop's own suite at the graded commit, before anything is written.

    Whatever this says is true of the shop rather than of any patch, which is the
    only reason the runs after it mean anything.
    """
    with _a_worktree_of(the_shop, THE_BASELINES_CHECKOUT) as checkout:
        return _pytest_in(checkout, THE_SHOPS_SUITE)


@pytest.fixture(scope="session")
def every_grade(
    request: pytest.FixtureRequest, the_shop: Checkouts, the_shop_before_anything: Ran
) -> dict[str, Future[Graded]]:
    """Every selected scenario graded, side by side, each in a worktree of its own.

    The scenarios of the cases this session will run rather than every one
    recorded, so a run narrowed to one scenario grades that one.

    Futures rather than the grades, so a grade that raised - a run that timed
    out, a worktree git would not make - fails its own scenario's case and no
    other's. All of them are done by the time this returns: leaving the pool
    waits for every one.
    """
    scenarios = sorted({
        str(item.callspec.params["scenario"]) for item in request.session.items
        if isinstance(item, pytest.Function)
        and item.originalname
        == test_a_recorded_fix_is_demonstrated_by_its_own_test_and_breaks_nothing.__name__
    })

    with ThreadPoolExecutor(max_workers=max(1, min(len(scenarios), A_GRADE_PER_CORE))) as pool:
        return {
            scenario: pool.submit(_graded, scenario, the_shop_before_anything, the_shop)
            for scenario in scenarios
        }


@pytest.mark.eval
@pytest.mark.parametrize("scenario", the_scenarios_that_proposed_a_fix())
def test_a_recorded_fix_is_demonstrated_by_its_own_test_and_breaks_nothing(
    scenario: str, every_grade: dict[str, Future[Graded]]
) -> None:
    # Free, and the only case in this directory that is. It reads recordings and
    # runs somebody else's test suite; no model is called and nothing is
    # recorded, because both inputs are committed and the verdict is therefore
    # recomputable at any commit.
    Scenario() \
        .given(scenario) \
        .when(every_grade[scenario].result) \
        .then(all_of(
            _it_asks_for_no_environment_of_its_own(),
            _it_brought_a_test(),
            _the_service_was_sound_to_begin_with(),
            _its_test_does_not_pass_without_the_fix(),
            _the_whole_suite_passes_with_the_fix(),
            _the_tests_that_failed_are_the_ones_that_pass()
        ))


@pytest.mark.eval
@pytest.mark.parametrize("mode", THE_MODES)
def test_every_walk_that_should_have_proposed_a_fix_did(mode: str) -> None:
    # The gap the case above cannot see. It grades the patches that exist, so a
    # scenario that stopped proposing one simply stops being collected - the run
    # gets shorter, stays green, and nobody is told that the agent went quiet on
    # a case it used to answer.
    #
    # Read against the declaration the recorder refuses on, so there is one list
    # rather than two drifting apart. A scenario absent from it proposes no fix
    # by design - a misconfigured cache is rolled back, not patched - and is not
    # a failure here.
    #
    # Each mode on its own: a walk that answered in one says nothing about the other.
    if not RECORDINGS_DIR.is_dir():
        pytest.skip(f"no recordings to grade at {RECORDINGS_DIR}")

    proposed = {scenario.removeprefix(f"{mode}-")
                for scenario in the_scenarios_that_proposed_a_fix()
                if scenario.startswith(f"{mode}-")}
    recorded = {scenario.removeprefix(f"{mode}-") for scenario in _every_corpus()
                if scenario.startswith(f"{mode}-")}

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


def _it_asks_for_no_environment_of_its_own() -> Assertion[Graded]:
    """That the patch leaves the shop's dependencies as they were.

    Every run uses the shop's one environment, synced from HEAD's lock, and
    nothing here installs what a patch adds to it. A patch that needs a new
    dependency would fail the suite for want of it and read as a broken fix, so
    this failure is listed first, naming what actually went unchecked, and the
    suite's own failures are reported after it.
    """
    def assertion(graded: Graded) -> bool:
        if graded.environment_files:
            raise AssertionError(
                f"Expected [{graded.scenario}]'s patch to leave the shop's "
                f"environment alone; it rewrites {list(graded.environment_files)}. "
                f"This grader does not install a patch's dependencies, so it "
                f"cannot tell this fix from a broken one."
            )

        return True

    return assertion


def _it_brought_a_test() -> Assertion[Graded]:
    """That the patch carried a test at all, unless every file it changes is
    configuration.

    Its own assertion rather than folded into the next, because "brought no
    test" and "brought a test that proves nothing" are different things for a
    reader to go and do something about.
    """
    def assertion(graded: Graded) -> bool:
        if not graded.tests and not graded.configuration_only:
            raise AssertionError(
                f"Expected [{graded.scenario}] to have brought a test with its fix, "
                f"which changes more than configuration; it submitted no file under "
                f"[{TESTS_DIRECTORY}]."
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
    cleanly at this commit, so this one arrived with the test.
    """
    def assertion(graded: Graded) -> bool:
        if graded.without_the_fix is None:
            return True

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

        if not ran_again.passed and graded.without_the_fix is not None:
            raise AssertionError(
                f"Expected the tests that failed without [{graded.scenario}]'s fix "
                f"to pass with it, asked for by name: "
                f"{list(graded.without_the_fix.failures)}. What came back: "
                f"failures {list(ran_again.failures)}, errors "
                f"{list(ran_again.errors)}.\n{ran_again.output}"
            )

        return True

    return assertion
