import contextlib
import ctypes
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Final

import nox

# fixes warning message:
#    warning: `VIRTUAL_ENV=.nox/e2e` does not match the project environment 
#    path `.venv` and will be ignored
# 
# every session dispatches real work `uv run ...`, which manages its own 
# environment (the project's `.venv`) - nox's own per-session venv is never 
# used, so skip creating it entirely.
nox.options.default_venv_backend = "none"


EXCLUDED_FROM_TESTS: set[str] = {
    "argus_testkit", "anthropic_double", "slack_double", "github_double"
}


def _discover_modules() -> list[str]:
    """
    Any subdirectory of `modules/` containing a `pyproject.toml` is a module.
    Modules named in `EXCLUDED_FROM_TESTS` are left out - they carry no tests.
    """
    current_dir = Path(__file__).parent

    if not (current_dir / "modules").exists():
        return []

    modules_dir = current_dir / "modules"

    return sorted(
        path.name for path in modules_dir.iterdir()
        if path.is_dir()
        and (path / "pyproject.toml").exists()
        and path.name not in EXCLUDED_FROM_TESTS
    )


MODULES: list[str] = _discover_modules()

# Every value `CODE_SEARCH` takes - `argus_core.models.CodeSearch`, spelled out
# rather than imported. This file is read before anything is installed, and a
# task runner that cannot list its own sessions until the workspace resolves is
# the one thing that cannot be used to fix a workspace that does not.
#
# The order is the order a sweep of all three runs in, and it is deliberate:
# `grep` is the cheapest stack to bring up - no store, no model to load - so a
# mode-independent breakage is reported minutes before the other two have
# embedded anything.
_SEARCHING_BY_GREP_ALONE: Final = "grep"
_CODE_SEARCH_MODES: Final[tuple[str, ...]] = (
    _SEARCHING_BY_GREP_ALONE, "meaning", "both"
)


@nox.session
def lint(session: nox.Session) -> None:
    """ 
    Registers `lint` as a nox session, i.e., runnable via `uv run python -m nox -s lint`.
    Runs ruff linter on the entire workspace.
    """
    session.run("uv", "run", "python", "-m", "ruff", "check", ".", external=True)

@nox.session
def typecheck(session: nox.Session) -> None:
    """
    Registers `typecheck` as a nox session, i.e., runnable via `uv run python -m nox -s typecheck`.
    Runs mypy --strict (via pyproject.toml's `[tool.mypy]`) on the entire modules/
    directory and on the cross-module suites in tests/. Both, because a test is
    code: the assertions a suite makes about a type are worth as much as the
    type, and a helper that quietly stopped matching what it stands in for is a
    test passing for the wrong reason. Each module ships a `py.typed`, which is
    what lets a suite outside `modules/` see its types rather than an opaque
    `Any`. Skips gracefully if no modules exist yet. Uses `--all-packages` so
    every workspace member's dependencies are installed regardless of what a prior
    plain `uv sync`/`uv run` happened to resolve (without it, mypy can spuriously
    report "Cannot find implementation or library stub" for a dependency that's
    declared but wasn't actually installed into the shared venv yet).
    """
    if not MODULES:
        session.skip("no modules/ yet - nothing to type-check")
    session.run(
        "uv", "run", "--all-packages", "python", "-m", "mypy", "modules", "tests",
        external=True
    )

@nox.session
@nox.parametrize("module", MODULES)
def test_module(session: nox.Session, module: str) -> None:
    """
    Registers `test_module` as a nox session, parametrized once per discovered module,
    i.e., runnable via `uv run python -m nox -s "test_module(module='<name>')"`
    for one module, or `-s test_module` for all of them. The parametrization
    has to be named: a trailing `-- <name>` becomes `session.posargs`, which
    this session never reads, so it would silently run every module.
    Runs that module's `unit`, `component` and `integration` tests in isolation, using
    only its own declared dependencies (via `uv run --package`). `component` is in the
    filter rather than left to `test_all`: a marker a session does not select is a
    marker whose tests quietly never run.

    Runs against a database of this module's own, and a Slack double port of its
    own, so it can run beside `e2e_replay` - or beside another module's suite -
    rather than stop the database either of them is using or lose the bind to
    the double either of them is talking to. The conftests that bring postgres
    and the double up inherit this environment; none of them is handed one.
    """
    os.environ.update(
        _a_database_for(module) | _a_slack_double_for(module) | _a_qdrant_for(module)
    )
    session.run(
        # Its own declared dependencies, and deliberately not `--all-extras`.
        # Installing every optional dependency would make this pass for the one
        # reason it must not: the extras exist so that a caller who does not
        # reach the store does not install an ONNX runtime, and a suite that
        # takes the lot can no longer tell a module that declared what it
        # imports from one that never did. What a module's tests need, that
        # module's `dev` group names.
        "uv", "run", "--package", f"argus-{module}",
        "python", "-m", "pytest", f"modules/{module}/tests",
        "-m", "unit or component or integration", "-v",
        external=True
    )

@nox.session
def test_all(session: nox.Session) -> None:
    """
    Registers `test_all` as a nox session, i.e., runnable via
    `uv run python -m nox -s test_all` (fail-fast, default), or with
    `-- --ci` / `-- --aggregate` appended to continue past failures and
    report every failure at the end.
    Runs every discovered module's full test suite. Fail-fast stops at the first
    failing module - fast local feedback. --ci mode runs every module regardless
    of earlier failures, then fails the session with a summary if any failed -
    full-picture visibility, intended for CI.

    On a database of its own and a Slack double port of its own, for the reason
    `test_module` has each - and not the same ones, since running both at once
    is the case that would otherwise have each stopping the other's.
    """
    os.environ.update(_TEST_ALL_STACK)
    ci_mode = "--ci" in session.posargs or "--aggregate" in session.posargs
    failed_modules: list[str] = []

    for module in MODULES:
        try:
            session.run(
                "uv", "run", "--package", f"argus-{module}",
                "python", "-m", "pytest", f"modules/{module}/tests", "-v", external=True
            )
        except Exception:
            if not ci_mode:
                raise  # fail-fast: propagate immediately, stop the loop
            failed_modules.append(module)

    if failed_modules:
        session.error(f"Failed modules: {', '.join(failed_modules)}")

@nox.session
def sweep(session: nox.Session) -> None:
    """
    Registers `sweep` as a nox session, i.e., runnable via
    `uv run python -m nox -s sweep`.
    Runs every free suite at once - `lint`, `typecheck`, the three guards,
    `test_all`, `integration` and `e2e_replay` - each in its own process, and
    stops the lot the moment one of them fails.

    They can share a machine because none of them shares infrastructure: each
    brings up a database under a compose project of its own, and the doubles and
    stores they publish bind ports of their own (`_INTEGRATION_STACK`,
    `_MODULE_SUITE_STACK`). A project is not enough on its own - it decides
    whose container a container is, and the published port is still the host's
    one address - which is what a vector store on the default 6333 in both
    `test_all` and `e2e_replay` cost before either had a port here.
    Sequentially this is the better part of half an hour, almost all of it
    `e2e_replay` waiting on walks.

    Stopping the rest on the first failure is the point rather than a
    convenience. The answer to "is this branch good" is already known once one
    suite says no, and eighteen further minutes of e2e output would bury the
    thing that actually broke.
    """
    running = {name: _start_service(["-m", "nox", "-s", name]) for name in _SWEEP}

    try:
        broke = _the_first_to_fail(running)
    finally:
        stopped = _stop_the_rest(running)
        _clean_up_after(stopped)

    if broke is not None:
        session.error(
            f"{broke} failed"
            + (f"; {', '.join(stopped)} stopped without a verdict" if stopped else "")
        )


# The replayed e2e run a push makes, by the id nox generates for it. Spelled
# once because two places have to name the same parametrized session - what a
# sweep starts, and which compose project it has to clean up after - and a
# parametrization named differently in either is a session nox cannot find or a
# stack nothing removes.
_E2E_REPLAY_IN_PRODUCTION_MODE: Final[str] = "e2e_replay(mode='both')"

# What a sweep runs. Every suite that costs nothing and needs no key - the same
# set CI runs on a push, which is what makes a green sweep mean something
# before the push rather than after it.
#
# One mode of `e2e_replay`, not three: a sweep answers "is this branch good"
# before a push, and a push runs `both`. The other two modes are the nightly's,
# where three stacks in sequence cost an hour nobody is waiting through.
_SWEEP = ["lint", "typecheck", "guard_layering", "guard_e2e_boundary",
          "guard_module_docstrings", "guard_exports", "test_all", "integration",
          _E2E_REPLAY_IN_PRODUCTION_MODE]

# How often a sweep looks at its children. Long enough that watching is free,
# short enough that a failure stops the others while they still have most of
# their work ahead of them.
_SECONDS_BETWEEN_SWEEP_LOOKS = 2.0


def _the_first_to_fail(running: dict[str, subprocess.Popen[bytes]]) -> str | None:
    """The name of the first suite to exit non-zero, or `None` if all passed.

    Removes each suite from `running` as it finishes, so what is left when this
    returns is exactly what still has to be stopped - and a suite that finished
    on its own is never signalled, which would otherwise report a passing suite
    as killed.
    """
    while running:
        for name, process in list(running.items()):
            if process.poll() is None:
                continue

            del running[name]

            if process.returncode != 0:
                return name

        time.sleep(_SECONDS_BETWEEN_SWEEP_LOOKS)

    return None


def _stop_the_rest(running: dict[str, subprocess.Popen[bytes]]) -> list[str]:
    """Stops whatever is still going, and says what it stopped.

    Named rather than counted, because the distinction matters in the report: a
    suite that was stopped has no verdict, and a log ending mid-run must not be
    read as a second failure.
    """
    for process in running.values():
        _stop_service(process)

    return list(running)


def _clean_up_after(suites: list[str]) -> None:
    """Removes the containers the killed suites never got to remove themselves.

    The other half of the job object, and not something it can do: a job holds
    processes, and a compose container is a child of the docker daemon rather
    than of anything here. Killing the suite that started one leaves it running
    with nothing left that knows about it.

    Only the suites that were stopped. One that finished on its own ran its own
    teardown, and tearing down again would be this function guessing at a state
    it was not there for.

    `down -v` rather than the `stop` a healthy run ends with, because the
    leftovers of a killed run are of unknown state - a schema half-applied, a
    fixture interrupted between two writes - and the next run brings its own
    database up anyway. Failures are reported and not raised: this already runs
    on the way out of a failing sweep, and a cleanup that turned into the
    reported failure would bury the suite that actually broke.
    """
    for suite in suites:
        project = _SWEEP_PROJECTS.get(suite)

        if project is None:
            continue

        removed = subprocess.run(
            ["docker", "compose", *project, "down", "-v"],
            capture_output=True, check=False
        )

        if removed.returncode != 0:
            print(f"could not remove the containers [{suite}] left behind: "
                  f"{removed.stderr.decode(errors='replace').strip()}")


@nox.session
def schema(session: nox.Session) -> None:
    """
    Registers `schema` as a nox session, i.e., runnable via
    `uv run python -m nox -s schema`.
    Applies Argus's database schema to whatever database the environment names,
    by throwing away what is there and applying `argus_core.schema`'s DDL from
    nothing. It is destructive and that is the design: Argus keeps no migration
    history, so the DDL is the whole statement of what the database holds, and
    an edit to it reaches a database only by replacing it.

    A wrapper around `python -m argus_core.schema` rather than the job itself.
    The e2e stack applies the schema too, as does anyone with a bare checkout
    and a postgres container, and only some of those are nox.
    """
    session.run("uv", "run", "python", "-m", "argus_core.schema", external=True)

@nox.session
def index(session: nox.Session) -> None:
    """
    Registers `index` as a nox session, i.e., runnable via
    `uv run python -m nox -s index`.
    Runs the reconciler that keeps the index of the Target Service's source
    describing what is deployed: every pass compares the commit the stored
    passages were built from with the commit the repository is at, and closes
    the gap. It runs until killed, and most of its passes find nothing to do.

    Needs postgres and Qdrant up, and reaches GitHub. The first pass on an
    empty store is the backfill and is the slow one - it reads the repository
    whole and embeds every passage; the passes after it embed only what
    changed, because a passage's id is derived from what it says.

    A session rather than only a compose service, because an index is the one
    piece of Argus somebody wants to build against a local checkout without
    bringing a stack up.
    """
    session.run(
        "uv", "run", "python", "-m", "code_index.reconciling", external=True
    )

@nox.session
def guard_layering(session: nox.Session) -> None:
    """
    Registers `guard_layering` as a nox session, i.e., runnable via
    `uv run python -m nox -s guard_layering`.
    Fails if a module imports something its layer may not know about, per the
    import-linter contracts in the root `pyproject.toml`: the kernel depends on
    nothing here, the incident record knows only the kernel, the page serves
    HTML without installing an agent, no agent knows another agent, and the
    kernel is reached through its front doors rather than by module path.

    It also holds the suites to the last two rules, which the contracts cannot:
    import-linter analyzes the packages named in `root_packages`, and a test
    package is not one of them - which is how one agent's suite came to build
    a double out of another agent's code while every contract held.

    A guard rather than a note in `CLAUDE.md`, because the note was there while
    `argus_incidents` depended on an agent - a documented invariant nothing
    checks is one nobody finds out about.
    """
    session.run("uv", "run", "python", "scripts/guard_layering.py", external=True)

@nox.session
def guard_e2e_boundary(session: nox.Session) -> None:
    """
    Registers `guard_e2e_boundary` as a nox session, i.e., runnable via
    `uv run python -m nox -s guard_e2e_boundary`.
    Fails if any test under modules/*/tests/ carries the `e2e` pytest marker -
    those need the docker-compose stack that only `uv run python -m nox -s e2e`
    brings up, and only for root tests/e2e/.
    """
    session.run("uv", "run", "python", "scripts/guard_e2e_boundary.py", external=True)

@nox.session
def guard_module_docstrings(session: nox.Session) -> None:
    """
    Registers `guard_module_docstrings` as a nox session, i.e., runnable via
    `uv run python -m nox -s guard_module_docstrings`.
    Fails if a module's prose sits below its imports, where it is a no-op
    expression rather than a docstring: `__doc__` stays `None`, and `help()`,
    pydoc and every editor hover show a module that says nothing about itself.

    It asks only that prose already written is readable, never that a module
    write some. Ruff's `D100` is the other question and the wrong one here -
    most modules are a type or two whose own docstrings say everything, and
    demanding a header on each would buy filler.
    """
    session.run("uv", "run", "python", "scripts/guard_module_docstrings.py", external=True)

@nox.session
def guard_written_columns(session: nox.Session) -> None:
    """
    Registers `guard_written_columns` as a nox session, i.e., runnable via
    `uv run python -m nox -s guard_written_columns`.
    Fails if a column the migration chain declares is set by no INSERT, no
    UPDATE and no DEFAULT anywhere in `modules/*/src`. A column only readers
    know about is always NULL, and nothing in the system can tell that from a
    value that happens to be missing - which is what `action.subject` did for
    the whole of its life, while every test passed on builders that populated
    what production never wrote.

    The static half of a two-part rule. This says a writer exists; the
    per-table tests say a writer ran and the value came back. It has no
    exemption list on purpose, and a statement whose columns it cannot resolve
    fails rather than passes - a guard that waves through what it cannot read
    rebuilds the hole it was written to close.
    """
    session.run("uv", "run", "python", "scripts/guard_written_columns.py", external=True)

@nox.session
def guard_exports(session: nox.Session) -> None:
    """
    Registers `guard_exports` as a nox session, i.e., runnable via
    `uv run python -m nox -s guard_exports`.
    Fails if a package's `__all__` offers a name nothing outside that package
    imports or names in an annotation. A door wider than anyone walks through
    is a door nobody can read: every spare name is a promise somebody may be
    keeping, and the surface a caller actually has becomes unfindable inside
    the list that declares it.

    Annotations count, which is the whole care of it. A type alias or a
    parameter's type is part of the surface by being nameable rather than by
    being called, and a sweep that looked for calls once reported nine names of
    which five were right as they were. A name kept for a caller who has not
    arrived is kept in the script's own list, with the reason beside it.
    """
    session.run("uv", "run", "python", "scripts/guard_exports.py", external=True)

@nox.session
def contract(session: nox.Session) -> None:
    """
    Registers `contract` as a nox session, i.e., runnable via `uv run python -m nox -s contract`.
    Runs the Anthropic contract tests, which check that the recording the
    suites replay still matches what the real API answers. Brings up the
    Anthropic double, because half of each comparison is a replayed recording;
    the other half talks to the real API and skips itself when no key is
    configured.

    One party per session rather than the whole directory, because each party
    is paid for separately: a workspace's contract has nothing to say about a
    model's, and a run that wanted one should not have to spend on the other.
    `contract_slack` is the other half.
    """
    _contract_against(session, _ANTHROPIC_DOUBLE, "tests/contract/anthropic")


@nox.session
def contract_slack(session: nox.Session) -> None:
    """
    Registers `contract_slack` as a nox session, i.e., runnable via
    `uv run python -m nox -s contract_slack`.
    Runs the Slack contract tests, which check that the double the suites post
    at still answers as the real workspace does. Brings up the Slack double for
    the same reason `contract` brings up the Anthropic one: one half of each
    comparison is the stand-in.

    Reaches a **real workspace**, so it needs `SLACK_BOT_TOKEN` and a channel to
    post in, and it posts messages somebody can see. Kept out of `contract` so
    that the Anthropic contract - which costs cents and needs no workspace - can
    run without a Slack credential anywhere near it.
    """
    _contract_against(session, _SLACK_DOUBLE, "tests/contract/slack")


def _contract_against(session: nox.Session,
                      double: tuple[str, list[str], str],
                      tests: str) -> None:
    """Brings one double up, runs the tests that compare it with the real thing.

    Shared by the two contract sessions so the only difference between them is
    which party is being checked - the double, and the directory holding the
    comparisons. Anything after `--` goes to pytest, as everywhere else here.
    """
    name, module_args, ready_url = double
    double_process = _start_service(module_args)
    try:
        _wait_for_http(name, ready_url)
        session.run(
            "uv", "run", "python", "-m", "pytest", tests, "-v",
            *session.posargs, external=True
        )
    finally:
        _stop_service(double_process)

@nox.session
def integration(session: nox.Session) -> None:
    """
    Registers `integration` as a nox session, i.e., runnable via
    `uv run python -m nox -s integration`.
    Runs the cross-module tests in root `tests/integration/`, with the Anthropic
    double up so the real LLM adapter is exercised end to end against recorded
    responses. Postgres comes up too, but from the suite's own `conftest.py`
    rather than from here: it is the one dependency the tests state for
    themselves, and a session that started it would be starting it for the
    files that do not need it as well.

    Free and keyless by design, which is why it is separate from `e2e` rather
    than a step inside it: every answer is replayed from a stored recording, so
    this runs on every push without a key and without spending a token. `e2e`
    still runs these too - it brings up the whole stack anyway - but nothing
    about them needs it to.

    Its database and its double are its own (`_INTEGRATION_STACK`), so this can
    run beside an `e2e` or `e2e_replay` session rather than behind it. Set on
    this process's environment rather than passed to each call, because the
    `conftest` that starts postgres is the one thing here that cannot be handed
    an environment of its own - it inherits this one.
    """
    os.environ.update(_INTEGRATION_STACK)
    name, _, _ = _ANTHROPIC_DOUBLE
    double_process = _start_service(
        ["-m", "uvicorn", "anthropic_double.server:app",
         "--port", _INTEGRATION_ANTHROPIC_DOUBLE_PORT])
    try:
        _wait_for_http(name, f"{_INTEGRATION_ANTHROPIC_DOUBLE_BASE_URL}/health")
        session.run(
            "uv", "run", "python", "-m", "pytest", "tests/integration", "-v",
            external=True,
            # Said here rather than left to a developer's `.env`, which is what
            # "keyless by design" has to mean: a machine holding neither
            # variable would otherwise build a client against the real API and
            # fail on a 401, and one holding a real key would *succeed* against
            # it - a suite that spends tokens on a push, silently.
            #
            # The key is a placeholder the double never reads; the SDK simply
            # refuses to construct a client without one.
            env={
                "ANTHROPIC_BASE_URL": _INTEGRATION_ANTHROPIC_DOUBLE_BASE_URL,
                "ANTHROPIC_API_KEY": "the-double-never-reads-this"
            }
        )
    finally:
        _stop_service(double_process)

@nox.session(name="eval")
def eval_(session: nox.Session) -> None:
    """
    Registers `eval` as a nox session, i.e., runnable via `uv run python -m nox -s eval`.
    Runs the evals: fixed evidence against the real model, scored as a pass
    rate over what it concludes and what it chose to read to conclude it. These
    judge the *model*, not Argus's plumbing, so they need a real
    `ANTHROPIC_API_KEY` and spend tokens on every run - a whole tool-use
    investigation per sample - which is why they are their own session and
    never part of `test_all`.

    The function is `eval_` because `eval` is a Python builtin. nox does not
    strip the underscore, so the session name is set explicitly on the
    decorator - otherwise `uv run python -m nox -s eval` would not find it.
    """
    session.run("uv", "run", "python", "-m", "pytest", "tests/eval", "-v", external=True)

def _venv_python_binary() -> str:
    """Path to the workspace venv's own Python interpreter - uvicorn is run
    via `-m uvicorn` (not the `uvicorn` console-script entry point, and not
    `uv run uvicorn ...`) so the process this session starts *is* the
    interpreter running uvicorn, not a wrapper that spawns it as a child.
    That wrapper hop is what breaks signal delivery on shutdown (§ below) -
    it also avoids Windows Smart App Control blocking the locally generated,
    unsigned `uvicorn.exe` console-script stub (the interpreter binary itself
    is signed and doesn't get flagged)."""
    venv_bin = "Scripts" if sys.platform == "win32" else "bin"
    exe = "python.exe" if sys.platform == "win32" else "python"
    return str(Path(".venv") / venv_bin / exe)


# A Windows job object's flag for "kill everything in here when the last handle
# to it closes", and the information class that carries it. Spelled out rather
# than imported because Python exposes no job-object API at all - `ctypes` is
# the whole of the binding, and these two numbers are the header file's.
_KILL_ON_JOB_CLOSE: Final = 0x2000
_EXTENDED_LIMIT_INFORMATION: Final = 9

# What is needed to put a process into a job and, having failed, to be able to
# stop it anyway.
_PROCESS_SET_QUOTA: Final = 0x0100
_PROCESS_TERMINATE: Final = 0x0001


class _BasicLimits(ctypes.Structure):
    """`JOBOBJECT_BASIC_LIMIT_INFORMATION`, of which one field is wanted.

    `c_uint32` rather than `wintypes.DWORD` so this module still imports on
    POSIX: `ctypes.wintypes` raises on any other platform, and a noxfile that
    cannot be imported is a repo with no sessions at all.
    """

    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32)
    ]


class _IoCounters(ctypes.Structure):
    """`IO_COUNTERS`, which nothing here reads - it is declared because it sits
    between the two halves of the extended struct that does get written."""

    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount"
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    """`JOBOBJECT_EXTENDED_LIMIT_INFORMATION` - the shape the kill flag is set
    through, whole, because the call is checked against its size."""

    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t)
    ]


def _kernel32() -> ctypes.CDLL:
    """`kernel32`, with the calls made here typed and their errors kept.

    Its own instance rather than the shared `ctypes.windll.kernel32`. `restype`
    is set on the library object, so the shared one carries whatever every
    other caller in the process has set on it - and `use_last_error`, which is
    what lets a failure below say more than that it failed, cannot be turned on
    for it at all.

    Both handle-returning calls are typed because the default `restype` is a C
    `int`, which truncates a 64-bit handle. That does not fail where it
    happens: it fails later, as a job or a process that does not exist.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.OpenProcess.restype = ctypes.c_void_p

    return kernel32


def _nothing_will_stop_them_because(complaint: str) -> None:
    """Says the kill-with-the-parent arrangement failed, and carries on anyway.

    Said rather than raised: this is a guarantee about the abnormal paths, and
    a run refusing to start because it could not arrange its own cleanup would
    have traded a leak for an outage. The ordinary teardown still runs.

    Said at all, though, because this is the one failure with no symptom. A job
    that never took its kill flag, a service that never joined one, a reaper
    that never heard about it - each behaves exactly like the working version
    right up until the run that is killed, and then leaks the whole stack,
    having reported nothing at the point where it could still have been
    understood.
    """
    print(f"[teardown] {complaint}. Services started by this run may outlive "
          "it if it is killed outright.")


def _the_last_windows_error() -> str:
    """What the Win32 call that just failed had to say for itself."""
    return str(ctypes.WinError(ctypes.get_last_error()))


def _a_job_that_kills_what_it_holds() -> int | None:
    """A job object every service this process starts is put into, or `None`
    where there is no such thing.

    Teardown that has to survive a kill cannot live in the process being
    killed. A `finally` runs on the paths Python is still alive for and on no
    others - and the paths that leak are exactly the others: a sweep stopping a
    failing run's siblings, a closed terminal, a second Ctrl+C. A job's handles
    close when the process holding them ends *however* it ends, so the children
    go with it without anything having to run.

    Signals cannot do this job. `CTRL_BREAK_EVENT` reaches a process group, and
    a service started in a group of its own - which is how it is startable at
    all here - is in a different one; a child that installs no handler for it
    dies at `0xC000013A` with no `finally` of its own. A job is not delivered
    to and not handled, so neither applies.

    Windows only, and deliberately not emulated elsewhere: POSIX has no
    primitive a grandchild calling `setsid` cannot leave, and the one caller
    that needs this - `sweep` - is a local tool that CI never runs.
    """
    if sys.platform != "win32":
        return None

    kernel32 = _kernel32()
    job = kernel32.CreateJobObjectW(None, None)

    if not job:
        _nothing_will_stop_them_because(
            f"no job object could be created: {_the_last_windows_error()}"
        )
        return None

    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE

    # A job that would not take the flag is not the thing this returns. It
    # would hold every service faithfully and let them all go on living, which
    # is the failure this whole file is about wearing the look of the fix.
    if not kernel32.SetInformationJobObject(
        ctypes.c_void_p(job),
        _EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits)
    ):
        _nothing_will_stop_them_because(
            "the job object would not take its kill-on-close flag: "
            f"{_the_last_windows_error()}"
        )
        kernel32.CloseHandle(ctypes.c_void_p(job))
        return None

    return int(job)


# One per nox process, created on import so that it is already there before
# anything is started. Held for the process's lifetime and never closed by
# hand: closing it is what kills the children, so the close that matters is the
# one the operating system does when this process ends.
_CHILD_JOB = _a_job_that_kills_what_it_holds()


def _held_by_this_process(pid: int) -> None:
    """Puts one started service into this process's job, if there is one.

    Complains rather than raises where it cannot - see
    `_nothing_will_stop_them_because` for which way that trade runs, and why
    saying nothing is not the same as not raising.

    Opened by pid rather than through `Popen`'s own handle, which is private to
    it. The two rights asked for are the least that lets a process be adopted
    and, failing that, stopped.
    """
    if _CHILD_JOB is None or sys.platform != "win32":
        return

    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(
        _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid
    )

    if not handle:
        _nothing_will_stop_them_because(
            f"process [{pid}] could not be opened: {_the_last_windows_error()}"
        )
        return

    try:
        if not kernel32.AssignProcessToJobObject(
            ctypes.c_void_p(_CHILD_JOB), ctypes.c_void_p(handle)
        ):
            _nothing_will_stop_them_because(
                f"process [{pid}] could not be put into the job: "
                f"{_the_last_windows_error()}"
            )
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


# Where POSIX's half of this lives, and the one thing the reaper needs to be:
# a process this one does not take with it. Started in a session of its own for
# exactly that reason - a signal aimed at this run's process group must not
# reach the thing whose job is to outlive it.
_REAPER_SCRIPT: Final = "scripts/reap_orphans.py"

_REAPER: subprocess.Popen[bytes] | None = None

# Whether starting one has been attempted at all, which is not the same as
# having one. A reaper that could not be started is a complaint worth making
# once; asked again per service, it would be five identical lines burying
# whatever the run was actually doing.
_REAPER_ATTEMPTED = False


def _the_reaper() -> subprocess.Popen[bytes] | None:
    """The process that stops this run's services when this run cannot.

    POSIX's answer to the job object, and the same guarantee: it holds the read
    end of a pipe whose only writer is this process, so it learns that this
    process has ended - however it ended - by reading EOF. See
    `scripts/reap_orphans.py` for why a pipe rather than `PR_SET_PDEATHSIG`,
    which is Linux's alone and would leave a repo with contributors on macOS
    holding a guarantee that quietly does not apply to them.

    One per run, started on first use rather than on import: most sessions
    (`lint`, `typecheck`, `guard_e2e_boundary`) start no service at all, and a
    process spawned to watch nothing is a process to explain.

    `None` on Windows, which has the better mechanism, and `None` again if the
    reaper cannot be started - the complaint is made once, where it can still
    be read, rather than at every service after it.
    """
    global _REAPER, _REAPER_ATTEMPTED

    if sys.platform == "win32" or _REAPER_ATTEMPTED:
        return _REAPER

    _REAPER_ATTEMPTED = True

    try:
        _REAPER = subprocess.Popen(
            [_venv_python_binary(), _REAPER_SCRIPT],
            stdin=subprocess.PIPE,
            start_new_session=True
        )
    except OSError as error:
        _nothing_will_stop_them_because(f"no reaper could be started: {error}")

    return _REAPER


def _told_the_reaper(entry: str) -> None:
    """Passes one line to the reaper, if there is one listening.

    `+<pid>` when a service starts and `-<pid>` when it stops, so that what the
    reaper is left holding at EOF is exactly what this run did not get to stop.
    Flushed on every line: a pipe this run never gets to close is also a pipe
    whose buffer nobody flushes, and a service recorded only in that buffer is
    one the reaper never hears about.
    """
    reaper = _the_reaper()

    if reaper is None or reaper.stdin is None:
        return

    try:
        reaper.stdin.write(f"{entry}\n".encode())
        reaper.stdin.flush()
    except OSError as error:
        _nothing_will_stop_them_because(f"the reaper would not take [{entry}]: {error}")


def _kept_from_outliving_this_process(pid: int) -> None:
    """Arranges for one just-started service to end when this run does.

    Two mechanisms, one per platform family, because the platforms genuinely
    differ: Windows has a job object that kills its members when the last
    handle closes, and POSIX has no such thing but does have a pipe, which
    reaches EOF on exactly the same event. Both are arranged from outside the
    service and need nothing of it.
    """
    if sys.platform == "win32":
        _held_by_this_process(pid)
    else:
        _told_the_reaper(f"+{pid}")


def _start_service(
    module_args: list[str], env: dict[str, str] | None = None
) -> subprocess.Popen[bytes]:
    """Starts one local service as a child of this session, via the venv's Python.

    CREATE_NEW_PROCESS_GROUP is required on Windows for CTRL_BREAK_EVENT (the
    graceful-shutdown signal `_stop_service` sends) to be deliverable to the
    child at all.

    The child is arranged to die with this process as soon as it exists - into
    a job object on Windows, onto the reaper's list on POSIX - so that it is
    stopped by this run ending even where nothing here gets to stop it. See
    `_kept_from_outliving_this_process`. Arranged after the spawn rather than
    before, because holding it suspended to close that window would be a
    second, larger piece of the same binding; what fits in the gap is the few
    microseconds before a Python interpreter has finished starting.

    `env` overrides settings for *this* service only, which is how one process
    in the stack can be pointed somewhere the others are not - `e2e_replay`
    uses it to aim `argus_web` at the Anthropic double. It is merged into a
    copy of the session's own environment rather than replacing it: a child
    started with only the overrides would lose `PATH`, `SYSTEMROOT` and the
    database URL, and would fail in ways that look nothing like the cause.

    Every service writes UTF-8 whatever the machine's codepage is. Argus
    narrates an incident in the model's own words, and a model writes arrows,
    dashes and quotation marks that a Windows ANSI codepage has no encoding
    for - on a Hebrew-locale machine that is `cp1255`. Those words reach a
    stream: the relay logs every line it delivers, and a walk logs what each
    agent concluded. A log call that raises `UnicodeEncodeError` takes down
    whatever was mid-sentence, and it does so on the incidents worth reading.
    The narration is not the place to negotiate with the console: the console
    is set to accept what Argus says.
    """
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

    process = subprocess.Popen(
        [_venv_python_binary(), *module_args],
        creationflags=creationflags,
        # The POSIX half of the same idea, and the reason both are set here
        # rather than at one call site: a child of its own gets signalled
        # together with everything it spawned. A child that is itself a runner
        # - a nox session driving pytest and docker - survives a signal aimed
        # at it alone, and its grandchildren carry on holding the ports the
        # next run needs.
        start_new_session=sys.platform != "win32",
        # Unbuffered for the same reason it is UTF-8: a child's stdout here is
        # whatever the session inherited, and a redirected session is a file
        # rather than a console - which Python block-buffers at 8KB. A suite
        # that prints a few lines a minute then says nothing for twenty, and a
        # run killed before it flushed says nothing at all.
        env={**os.environ,
             "PYTHONIOENCODING": "utf-8",
             "PYTHONUNBUFFERED": "1",
             **(env or {})}
    )
    _kept_from_outliving_this_process(process.pid)

    return process


def _stop_service(process: subprocess.Popen[bytes], timeout: float = 10.0) -> None:
    """Graceful shutdown via the signal uvicorn's own asyncio server already
    handles - SIGTERM on POSIX, `CTRL_BREAK_EVENT` on Windows (Windows has no
    deliverable SIGTERM equivalent for an arbitrary child process). Falls
    back to a hard kill only if the process hasn't exited within `timeout`.

    Retires the pid from the reaper's list on the way out, which is the half of
    that arrangement without which it would be dangerous. A pid is only unique
    while its process lives; an e2e run lasts twenty minutes, and a reaper still
    holding the number of a service stopped in its first minute would, at the
    end, kill whatever had since been given that number.
    """
    _told_the_reaper(f"-{process.pid}")

    if sys.platform == "win32":
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        # The whole group, not the one process. `terminate()` would reach the
        # child alone, and a child that spawned its own - pytest, docker - would
        # leave them running with nothing left to stop them by.
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            process.kill()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)

        process.wait()


def _refuse_a_stack_that_is_already_up() -> None:
    """Fails before anything is started if a previous stack still holds a port.

    A leaked service is the worst kind of leftover, because nothing downstream
    notices it. `_start_service` launches the replacement, uvicorn dies on the
    bind, and `_wait_for_http` then finds the *old* process listening and calls
    it ready - so the suite runs against code from another checkout and a
    database that has since been dropped and recreated underneath it. Every
    failure that produces points somewhere other than the cause.

    The teardown stops whatever this session started, so this can only trigger
    after a run that was killed outright - a second Ctrl+C, a closed terminal -
    which is exactly when nobody is left to remember it happened.
    """
    for name, _, ready_url in _LOCAL_SERVICES:
        # A service holding no port cannot be found this way. The worker is the
        # one of those, and a leaked one is far less dangerous than a leaked
        # server: it competes for runs through the same claim any second worker
        # does, rather than answering as though it were this run's.
        if ready_url is None:
            continue

        port = urllib.parse.urlparse(ready_url).port
        with socket.socket() as probe:
            probe.settimeout(1.0)
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                continue

        raise RuntimeError(
            f"port {port} is already in use, so [{name}] cannot start - a stack "
            f"from an earlier run is still up. Stop it first: "
            f"{_how_to_free(port)}"
        )


def _how_to_free(port: int) -> str:
    """The command that stops whatever is listening, for the shell the reader
    is actually in.

    Named separately because the refusal above is the one message a contributor
    meets before anything else works, and a Windows one-liner offered to
    somebody on macOS reads as a repo that was never run there.
    """
    if sys.platform == "win32":
        return (f"Get-NetTCPConnection -State Listen -LocalPort {port} | "
                f"ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force }}")

    return f"lsof -ti tcp:{port} | xargs kill -9"


def _wait_for_http(name: str, url: str, timeout: float = 30.0) -> None:
    """Blocks until `url` answers at all, or `timeout` elapses.

    Any HTTP response counts as ready, including an error one - `read_mcp`'s
    `/mcp` rejects a bare GET, and that rejection is itself proof the server is
    listening. Only a connection-level failure means "not up yet".
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1.0)
            return
        except urllib.error.HTTPError:
            return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.5)
    raise TimeoutError(f"{name} did not become ready within the timeout")


# The services `e2e` runs locally rather than in docker-compose (design.md's
# decision), in start order: name, how to launch it, and the URL that proves
# it is listening. Torn down in reverse.
#
# `anthropic_double` is here for the *integration* tests, which run in the same
# session: they exercise the real adapter against a recorded response, with no
# API key. The e2e tests in the same run still talk to the real Anthropic API -
# nothing points `argus_web` at the double.
# Kept in step with `anthropic_double.server.DEFAULT_BASE_URL` by hand rather
# than imported: this file is read by nox before anything is necessarily
# installed, and a noxfile that fails to import takes every session with it.
_ANTHROPIC_DOUBLE_BASE_URL = "http://localhost:8091"
_SLACK_DOUBLE_BASE_URL = "http://localhost:8094"
_GITHUB_DOUBLE_BASE_URL = "http://localhost:8096"

# Where the sessions that can run beside an e2e stack put the things that would
# otherwise collide with it. Every collision is a port or a database: a second
# double dies on the bind, and a second suite emptying tables between tests
# would truncate the other run's incident mid-walk.
#
# Not 5433, which reads as "the second postgres" and is already the flag
# provider's database in the e2e stack. Far enough from both that nothing else
# here claims them.
_INTEGRATION_POSTGRES_PORT = "5544"
_TEST_ALL_POSTGRES_PORT = "5545"
# Where one module's own database goes, counted from the module's place in
# `MODULES`. Derived rather than listed, because a module is discovered rather
# than declared and a table of ports would be one more place to remember to add
# it to. Adding a module shifts the numbers after it, which costs nothing: no
# port here outlives the session that publishes it.
_MODULE_SUITE_PORT_BASE = 5546
_INTEGRATION_ANTHROPIC_DOUBLE_PORT = "8093"
_INTEGRATION_ANTHROPIC_DOUBLE_BASE_URL = f"http://localhost:{_INTEGRATION_ANTHROPIC_DOUBLE_PORT}"
# Where a module suite's own Slack double listens, for the reason its database
# has a port of its own: `agent_communicator`'s component conftest runs the
# double in-process, and the e2e stack runs one on 8094. Two of those at once -
# which is exactly what a sweep is - and the second dies on the bind, so a suite
# that had nothing to do with Slack takes down the run that did.
_TEST_ALL_SLACK_DOUBLE_PORT = "8095"
_MODULE_SUITE_SLACK_PORT_BASE = 8100
# Where a suite's own vector store listens, for the reason its database and its
# Slack double have ports of their own. Two module suites want one - the code
# index and long-term memory - and the e2e stack runs a third on 6333, so a
# sweep is three stores at once and the second to bind dies. A compose project
# of one's own is not enough here: it makes the *container* somebody else's, and
# the published port is still the host's one address.
_TEST_ALL_QDRANT_PORT = "6343"
_MODULE_SUITE_QDRANT_PORT_BASE = 6350


def _a_database_of_its_own(project: str, port: str) -> dict[str, str]:
    """The environment that puts one session's postgres beside the others'.

    A compose project as well as a port, because a project is what owns a
    container: `docker compose up postgres` under the default name adopts - or
    restarts, or stops - whichever database is already running under it rather
    than starting a second one. That is how a module suite finishing its run
    stops the database an `e2e_replay` is halfway through using.

    Both halves of the port, said once. Compose reads `ARGUS_POSTGRES_PORT` for
    the host side of its mapping and `argus_core.config` reads `DATABASE_PORT`
    for where to connect, and a session where those two disagree comes up
    healthy and connects to nothing.
    """
    return {
        "COMPOSE_PROJECT_NAME": project,
        "ARGUS_POSTGRES_PORT": port,
        "DATABASE_PORT": port
    }


_INTEGRATION_STACK = _a_database_of_its_own(
    "argus-integration", _INTEGRATION_POSTGRES_PORT
) | {"ANTHROPIC_DOUBLE_PORT": _INTEGRATION_ANTHROPIC_DOUBLE_PORT}

# The module suites bring up a database of their own - four of them do, from
# their own conftests, which is what a `component` test needing real postgres
# looks like. No Anthropic double: every module suite that reaches a model
# reaches a stub it constructs itself. A Slack double, though, is a real server
# on a real port, because an SDK is what does the reaching - so it gets a port
# of its own here for the same reason the database does.
_TEST_ALL_STACK = _a_database_of_its_own("argus-modules", _TEST_ALL_POSTGRES_PORT) | {
    "SLACK_DOUBLE_PORT": _TEST_ALL_SLACK_DOUBLE_PORT,
    "ARGUS_QDRANT_PORT": _TEST_ALL_QDRANT_PORT
}

# How to name each swept suite's containers to `docker compose`, for the three
# that have any. Read only when a suite had to be killed: it is what lets the
# sweep finish a teardown that never ran, and the reason a suite's project has
# to be stated somewhere a *different* process can find it.
#
# `e2e_replay` is named by saying nothing. It sets no project of its own, and
# neither does a sweep, so a `docker compose` run from here lands on the same
# default that child's did - derived by compose, from the directory both ran
# in. Deriving it here instead would be compose's own rule for turning a
# directory name into a project name, copied by hand and true until a checkout
# is named something that rule spells differently.
_SWEEP_PROJECTS: Final[dict[str, tuple[str, ...]]] = {
    "test_all": ("-p", _TEST_ALL_STACK["COMPOSE_PROJECT_NAME"]),
    "integration": ("-p", _INTEGRATION_STACK["COMPOSE_PROJECT_NAME"]),
    _E2E_REPLAY_IN_PRODUCTION_MODE: ()
}


def _a_database_for(module: str) -> dict[str, str]:
    """One module's own database, so two module suites can run at once.

    A module rather than the session, because `test_module` is parametrized:
    two of them in flight are two processes each bringing postgres up and each
    stopping it afterwards, and the one that finishes first stops the other's.

    A module nobody discovered has no place to count from, which would silently
    become somebody else's port. Nothing can ask for one - the parametrization
    comes from `MODULES` - so this says so rather than defending against it.
    """
    return _a_database_of_its_own(
        f"argus-module-{module}",
        str(_MODULE_SUITE_PORT_BASE + MODULES.index(module))
    )


def _a_slack_double_for(module: str) -> dict[str, str]:
    """One module's own Slack double, counted the way its database is.

    Set for every module rather than for the one that runs a double, because
    which module that is is a fact about a conftest rather than about this file,
    and a port nobody listens on costs nothing.
    """
    return {
        "SLACK_DOUBLE_PORT": str(_MODULE_SUITE_SLACK_PORT_BASE + MODULES.index(module))
    }


def _a_qdrant_for(module: str) -> dict[str, str]:
    """One module's own vector store, counted the way its database is.

    Set for every module rather than for the two that open one, for the reason
    the Slack double is: which modules those are is a fact about their conftests
    rather than about this file, and a port nobody binds costs nothing.

    The port alone. Both conftests that want a store derive its URL from this
    and fall back to 6333, so a port published here and not read there would
    move the container and leave the client talking to whatever else holds the
    default.
    """
    return {
        "ARGUS_QDRANT_PORT": str(_MODULE_SUITE_QDRANT_PORT_BASE + MODULES.index(module))
    }

# Settings every process in an e2e run shares - the services started here and
# the pytest process asserting on them. One place, because the two derive
# different things from the same number: `agent_mitigation` waits this long for
# the service to recover, and the suite's own timeouts are computed from it. If
# they disagreed, the suite would either give up before Argus did or wait long
# after it had.
#
# The configured default, said out loud rather than left implicit: the suite
# computes its own timeouts from this number, and reading it from `.env` would
# make how long a run takes depend on the machine it runs on.
#
# It used to be double this, on the belief that a GitHub runner needed the
# room. It never did. What made a working mitigation read as refuted was a
# fixture that froze telemetry at the instant of the revert, so the first clean
# minute could be dropped for having no elapsed seconds - fixed in the demo
# app, and no width of window could have helped, since the evidence stopped
# arriving a minute after the change either way.
#
# Eight nightly runs since say the same thing: a mitigation that confirms is
# confirmed within seconds of the first whole minute, and the whole case -
# intake, investigation, revert, verdict - finishes in 22-81s. The window is
# only ever paid in full where recovery never comes, which is why halving it
# takes about six minutes off a run and nothing off what a green run means.
_E2E_SETTINGS = {
    "MITIGATION_VERIFICATION_TIMEOUT_SECONDS": "180",
    # What the shop took, read from the Target Service's own Stripe-shaped
    # endpoint instead of from Stripe - the arrangement `e2e_replay` has with
    # the Anthropic double, one address below the vendor's SDK, so the SDK's
    # request building, paging and object model all still run.
    #
    # The key is a fixture value and the endpoint accepts any: what matters is
    # that it is *set*, because an empty credential makes the source report it
    # could not answer, and the estimate would then be absent by configuration
    # rather than by measurement.
    "STRIPE_API_KEY": "sk_test_argus_demo",
    "STRIPE_BASE_URL": "http://localhost:8080/stripe",
    # Who responded, read from the Target Service's own PagerDuty-shaped
    # endpoints on the same terms: a fixture token that only has to be set, and
    # one address below the vendor's SDK.
    "PAGERDUTY_API_KEY": "pd_test_argus_demo",
    # HTTPS, and unverified, because the SDK will not accept anything else: it
    # refuses a plain-HTTP base URL outright. The Target Service answers TLS on
    # a second port of the same process for exactly this, with a certificate it
    # mints at startup - so the certificate is worth nothing and is not checked.
    "PAGERDUTY_BASE_URL": "https://localhost:8443/pagerduty",
    "PAGERDUTY_VERIFY_TLS": "false",
    # What those responders' titles are worth, read from the Target Service's
    # own HR-shaped endpoint on the same terms again. A fixture token that only
    # has to be set: an empty credential makes the source report that it could
    # not answer, and the response cost would then be absent by configuration
    # rather than because a title had no band.
    "HR_API_KEY": "hr_test_argus_demo",
    "HR_BASE_URL": "http://localhost:8080/bamboohr",
    # What a currency is worth, read from the Target Service's own
    # Frankfurter-shaped endpoint. The last source that was still reaching a
    # live third party over the internet, and the only one that could fail a
    # run for weather: the first case of a shard has no rates held to fall back
    # on, so one hiccup there is one red run. No key, because the provider
    # needs none and the stand-in asks for none.
    "EXCHANGE_RATE_BASE_URL": "http://localhost:8080/frankfurter",
    # How long the reconciler sleeps between passes. Short, because an e2e case
    # that pushes waits for the index to catch up with it - and the default is
    # a minute, which is the right pause for a deployment and a minute of a
    # suite sitting on a row that is already decided. What it does *not* do is
    # make the index arrive sooner than a suite can observe: a pass costs what
    # it costs, and this only stops the wait being mostly sleep.
    "CODE_INDEX_INTERVAL_SECONDS": "5",
    # Where Argus answers, which is what a message in a channel links back to.
    # Set for every stack rather than only the suites: a demo whose postmortem
    # linked nowhere would be a demo of the one thing a reader in a channel
    # actually wants to click.
    "ARGUS_BASE_URL": "http://localhost:8000",
    # Long-term memory, on. Named here rather than left to the default so that
    # it is a decision the stack states: what the benchmark (spec 21) compares
    # is a run with memory against a run without, and a setting nobody writes
    # down is a variable nobody can turn.
    "INCIDENT_MEMORY_ENABLED": "true",
    # A collection of its own per stack, so a suite never recalls an incident a
    # demo left behind. The corpus a case wants is the one its own `given` put
    # there, and a record surviving into the next run is the flakiness nobody
    # can reproduce.
    "INCIDENT_MEMORY_COLLECTION": "incidents_remembered_under_test"
}

# Where the relay posts when a suite is running, and where "Slack" is. The
# double stands in for the workspace for the reason it does everywhere else: no
# credential, no workspace to clutter, and the real adapter, the real client
# and the real argument encoding still run. `e2e` shares this with
# `e2e_replay` - what separates those two is which answers the *model* gives,
# and Slack has nothing to do with that.
#
# Not shared with `stack`, which is a demo somebody is watching: that one posts
# wherever `.env` says, because a demo of an incident reaching a human is not a
# demo if the human is a test double.
_SLACK_AT_THE_DOUBLE = {
    # The channel is a fixture name the double accepts as it accepts any. What
    # matters is that it is set: a relay with nowhere to post does not start,
    # and an empty channel would make the whole stack silent by configuration.
    "SLACK_BASE_URL": _SLACK_DOUBLE_BASE_URL,
    "SLACK_WAR_ROOM_CHANNEL": "C-argus-incidents",
    # A placeholder the double never reads; the SDK refuses to build a client
    # without one.
    "SLACK_BOT_TOKEN": "xoxb-the-double-never-reads-this",
    # Short, because an e2e test waits on what a person would see: the pause is
    # paid on every pass that found nothing, and a suite spending two seconds
    # per look is a suite that reports a message as missing before it was sent.
    "SLACK_RELAY_POLL_SECONDS": "0.5"
}

# Where both tiers find "GitHub" when a suite is running. The one double
# standing in for a service Argus writes to, which is why this is not a
# convenience: a pull request opened by a suite is a real pull request, numbered
# out of a counter that never goes back, and `e2e_replay` runs on every push.
#
# Not shared with `stack`, for the reason Slack is not: a demo of Argus handing
# work to a person is not a demo if the pull request it hands over is a fixture.
_GITHUB_AT_THE_DOUBLE = {
    "GITHUB_API_URL": _GITHUB_DOUBLE_BASE_URL,
    # Fixture names the double accepts as it accepts any. Set rather than left
    # empty because both tiers refuse to start without a repository to address.
    "GITHUB_REPOSITORY": "ohadraz/repository",
    # Placeholders the double never reads, one per tier - the split is the point
    # of two tokens (spec §12.1) and a suite that collapsed them would stop
    # noticing if the read tier were handed the credential that can write.
    "GITHUB_TOKEN": "the-double-never-reads-this",
    "GITHUB_READ_TOKEN": "the-double-never-reads-this-either",
    # The same scoping a deployment sets, so the suite exercises the filter
    # rather than a repository that happens to hold only service files.
    "GITHUB_SOURCE_PATHS": "src/io_shop,tests/io_shop",
    # What a push must be signed with to be believed. A fixture secret, and the
    # suite signs with this one - which is the whole of what the case proves:
    # the endpoint is open to the internet, and a delivery nobody signed moves
    # nothing. Set here rather than in `_E2E_SETTINGS` so a demo keeps the
    # secret its own webhook is configured with, and real deliveries still
    # verify.
    "GITHUB_WEBHOOK_SECRET": "the-suite-signs-its-pushes-with-this"
}

_ANTHROPIC_DOUBLE: tuple[str, list[str], str] = (
    "anthropic_double",
    ["-m", "anthropic_double.server"],
    f"{_ANTHROPIC_DOUBLE_BASE_URL}/health"
)

_SLACK_DOUBLE: tuple[str, list[str], str] = (
    "slack_double",
    ["-m", "slack_double.server"],
    f"{_SLACK_DOUBLE_BASE_URL}/health"
)

_GITHUB_DOUBLE: tuple[str, list[str], str] = (
    "github_double",
    ["-m", "github_double.server"],
    f"{_GITHUB_DOUBLE_BASE_URL}/health"
)

_LOCAL_SERVICES: list[tuple[str, list[str], str | None]] = [
    ("read_mcp", ["-m", "read_mcp_server.server"], "http://localhost:8090/mcp"),
    # Its own process, not a second module inside `read_mcp`: the tier split
    # (spec §12.1, §13) is what makes "read-only" a property of a running
    # process rather than a convention, and a stack that started only one of
    # them would be testing the convention.
    ("write_mcp", ["-m", "write_mcp_server.server"], "http://localhost:8092/mcp"),
    _ANTHROPIC_DOUBLE,
    # Slack, for a stack that has no workspace and wants none. Up before the
    # relay, which posts to it from its first pass.
    _SLACK_DOUBLE,
    # GitHub, for a stack that has no repository and must not touch one. The
    # only double here standing in for a service Argus *writes* to, which is
    # what makes it necessary rather than tidy: without it a free, keyless,
    # offline suite opened a real draft pull request on every run, and a pull
    # request number, once spent, is spent for good.
    _GITHUB_DOUBLE,
    (
        # Bound to every interface, not just loopback: the Target Environment's
        # monitoring posts its alerts from inside a container, and a server
        # listening only on `127.0.0.1` is not reachable from there however the
        # container spells the host.
        "argus_web",
        ["-m", "uvicorn", "argus_web.app:app", "--host", "0.0.0.0", "--port", "8000"],
        "http://localhost:8000/openapi.json"
    ),
    (
        # What actually walks an incident. `argus_web` only writes the run down
        # and answers the alert, so a stack without this accepts every alert and
        # investigates none - and the suite's first assertion about a status
        # would be the thing that reported it.
        #
        # Started last, so that the queue it reads is served by processes that
        # are already up: a run claimed before the MCP servers answer fails for
        # a reason that has nothing to do with the incident.
        #
        # No readiness URL: it listens on nothing. What it is ready for is
        # visible only in the queue, and a run appearing there is the suite's
        # own first step rather than something to wait for here.
        "worker",
        ["-m", "orchestrator.worker"],
        None
    ),
    (
        # What keeps the index describing what is deployed. The stack has
        # already made one pass to completion before any service started, so
        # this is only ever catching up with what happens during the run - a
        # push the suite makes, or a fix branch nobody deployed and it
        # correctly ignores.
        #
        # No readiness URL: it listens on nothing, and what it is ready for is
        # a row in the database rather than a port. The pass that mattered was
        # the one before the services.
        "reconciler",
        ["-m", "code_index.reconciling"],
        None
    ),
    (
        # What tells a human anything. It follows the event log rather than
        # being called by the walk, so a stack without it walks incidents that
        # nobody outside the dashboard ever hears about.
        #
        # No readiness URL: it listens on nothing either. What it is ready for
        # shows up in Slack, and a message arriving there is what a suite is
        # asserting in the first place.
        "relay",
        ["-m", "agent_communicator.watching"],
        None
    )
]


def _the_services_for(slack_stands_in: bool) -> list[tuple[str, list[str], str | None]]:
    """The local services to start, minus the ones this run has no use for.

    Two doubles move together, on the one flag that says whether this is a
    suite or a demo. A suite wants both - no workspace to clutter, no
    repository to leave branches on. A demo wants neither: an incident reaching
    a person and a fix a person can open are the two things being demonstrated,
    and both are stand-ins if either double is in the way.

    Starting an unwanted double is not harmless. It leaves a process on a port
    nobody talks to, which is the kind of leftover somebody later mistakes for
    the thing under test.
    """
    if slack_stands_in:
        return _LOCAL_SERVICES

    standing_in = (_SLACK_DOUBLE, _GITHUB_DOUBLE)

    return [service for service in _LOCAL_SERVICES if service not in standing_in]


# The processes that stand in for somebody else's service. They come up before
# anything of Argus's does, and before the index is built: what they stand in
# for is exactly what the rest of the stack reads.
_THE_STAND_INS: Final = (_ANTHROPIC_DOUBLE, _SLACK_DOUBLE, _GITHUB_DOUBLE)


def _start_each_of(services: list[tuple[str, list[str], str | None]],
                   service_env: dict[str, dict[str, str]],
                   started: list[subprocess.Popen[bytes]]) -> None:
    """Starts these services, waits for the ones that listen, and records them.

    Appends to the caller's list rather than answering with its own, because
    what has to be torn down is everything started so far - including the half
    that was up when the next one failed.
    """
    for name, module_args, ready_url in services:
        started.append(_start_service(module_args, env=service_env.get(name)))
        # A service that listens on nothing is waited for by nothing: the
        # worker's readiness shows up in the queue it drains, not on a port.
        if ready_url is not None:
            _wait_for_http(name, ready_url)


def _run_against_the_stack(
    session: nox.Session,
    test_paths: list[str],
    service_env: dict[str, dict[str, str]] | None = None,
    command: list[str] | None = None,
    slack_stands_in: bool = True
) -> None:
    """Brings the whole stack up, runs `test_paths` against it, tears it down.

    Shared by `e2e` and `e2e_replay` so the two cannot drift on anything except
    the one difference that distinguishes them - which service, if any, is
    started pointed somewhere else. `service_env` maps a name in
    `_LOCAL_SERVICES` to the settings that service alone should see.

    Brings up docker-compose's `postgres` service plus the whole Target
    Environment - the Target Service, the feature-flag provider and that
    provider's database, `include`d from the sibling repo's own compose file -
    and every local process in `_LOCAL_SERVICES` that this run has a use for
    (none containerized - design.md's decision). Everything, which is why no service
    is named: this is the one caller that wants the lot. A suite needing only
    the database names it instead - see `docker-compose.yml`. Teardown runs even
    if the tests fail, so nothing is left running.

    The schema is applied here, once the database answers and before the first
    service starts. No Argus process applies it, so the order the services come
    up in stops being something this function has to get right.

    Teardown passes `-v` so Postgres's volume goes with the container. Not for
    the schema's sake - the job replaces that on every run either way - but
    because an e2e run should start from no rows as well as no tables, and a
    volume nothing removes is a volume nothing ever collects.
    """
    service_env = service_env or {}
    # Before docker, before anything: a stack left running by a killed run does
    # not announce itself, and every symptom it causes points elsewhere.
    _refuse_a_stack_that_is_already_up()
    started: list[subprocess.Popen[bytes]] = []
    # Set on the session's own environment rather than passed to each call:
    # every child here inherits it - the services that do the waiting and the
    # pytest process that times them - which is the only way the two cannot
    # disagree about how long Argus waits.
    os.environ.update(_E2E_SETTINGS)
    # A suite posts at the doubles; a demo posts wherever `.env` says. Set here
    # rather than defaulted into `_E2E_SETTINGS`, so that a stack somebody is
    # watching cannot be silently pointed away from the workspace - or the
    # repository - they are watching it in.
    if slack_stands_in:
        os.environ.update(_SLACK_AT_THE_DOUBLE | _GITHUB_AT_THE_DOUBLE)
    try:
        # `--build` because the Target Service image is built from a sibling
        # working copy, not pulled: without it Compose reuses whatever was
        # built last, and a scenario edited in that repo ships stale to the
        # one suite whose whole job is to exercise the real thing. That failure
        # is silent in the worst way - the run goes green against yesterday's
        # fixture, or 404s on an endpoint the source plainly has.
        session.run(
            "docker", "compose", "up", "-d", "--wait", "--build", external=True
        )
        # Before the first service and after the database is answering, which is
        # the whole of why it is a step of its own: no Argus process applies the
        # schema, so none of them can be the one that has to start first.
        session.run(
            "uv", "run", "python", "-m", "argus_core.schema", external=True
        )
        services = _the_services_for(slack_stands_in)
        # The stand-ins before the index, because the index reads a repository
        # and for a suite the repository is the GitHub double. A pass made
        # before it answers fails on a refused connection - the stack's own
        # ordering, reported as a repository that could not be read.
        _start_each_of(
            [service for service in services if service in _THE_STAND_INS],
            service_env,
            started
        )
        # And the index, in the schema's slot and for the same reason. Code-Fix
        # searches the repository by meaning from its first turn, so a stack
        # that started Argus and let the reconciler catch up in its own time
        # would have the first run of a suite race the first pass - and
        # whichever won would decide what the model was handed. One pass to
        # completion here; the loop among the services keeps it current after
        # that.
        session.run(
            "uv", "run", "python", "-m", "code_index.reconciling", "--once",
            external=True
        )
        _start_each_of(
            [service for service in services if service not in _THE_STAND_INS],
            service_env,
            started
        )
        # Anything after `--` goes to pytest, so a single failing case can be
        # re-run against the stack (`-- -k fallback`) instead of the whole
        # suite. Bringing the stack up is the slow part of a green run and the
        # cheap part of a debugging one.
        session.run(
            *(command or ["uv", "run", "python", "-m", "pytest", *test_paths, "-v"]),
            *session.posargs, external=True
        )
    except Exception:
        # What the containers said, and only when something went wrong. The
        # local services write to this session's own output and are therefore
        # already in the log; the Target Service and the flag provider write
        # into Docker, where a torn-down stack takes them with it. A failure
        # explained by what the shop was serving is otherwise reconstructed by
        # simulation, which is how a fixture bug spent a day looking like an
        # agent bug.
        #
        # Before the teardown below, because `down -v` is what destroys them.
        _the_containers_said_this(session)
        raise
    finally:
        # Before the services stop, because the cleanup talks to the repository
        # over the network and not to anything in this stack - but after the
        # work, so a demo is cleaned up only once it is over.
        #
        # Only where the repository is real. A suite proposes to the double,
        # whose whole repository goes when its process does, and calling this
        # against it would be a request to a port that is about to close.
        if not slack_stands_in:
            _put_the_repository_back(session)
        for process in reversed(started):
            _stop_service(process)
        session.run("docker", "compose", "down", "-v", external=True)


def _put_the_repository_back(session: nox.Session) -> None:
    """Closes the pull requests the run opened and deletes the branches under them.

    The half of the reset that is not in the Target Environment: the shop puts
    its own scenario back, and what Argus left on somebody's repository is left
    until this runs. A rehearsal is otherwise a dozen open proposals, and the
    demo everybody watches opens number thirteen.

    Never fails the session. This is a teardown, where the interesting failure
    is the one that already happened - and a demo that went perfectly is not
    made worse by a branch that outlived it.
    """
    with contextlib.suppress(Exception):
        session.run(
            "uv", "run", "python", "-m", "scripts.clean_the_repository",
            external=True, success_codes=[0, 1]
        )


def _the_containers_said_this(session: nox.Session) -> None:
    """Dumps the stack's own logs, and never fails the session by trying.

    Every line each container has, rather than a tail: this prints only where
    something already failed, and a cap is a guess about which minute explains
    it. The Target Service alone logs a health probe every two seconds, so any
    round number is a truncation that hides the cause and looks like the whole
    story.

    A teardown that raised while explaining a failure would replace the failure
    with itself - so a `docker` that cannot answer here is passed over in
    silence, having nothing to add.
    """
    with contextlib.suppress(Exception):
        session.run(
            "docker", "compose", "logs", "--no-color", "--tail", "all",
            external=True, success_codes=[0, 1]
        )


@nox.session
def e2e(session: nox.Session) -> None:
    """
    Registers `e2e` as a nox session, i.e., runnable via `uv run python -m nox -s e2e`.
    Runs the end-to-end suite against the full local stack, with the worker
    talking to the **real Anthropic API**.

    This is the paid, manual, pre-merge run: it needs `ANTHROPIC_API_KEY` and
    spends tokens on every incident it drives. It is the only suite in which a
    real model reads real retrieved evidence and reaches a conclusion end to
    end, which is what makes it worth the money before a merge that changes the
    investigation path.

    `tests/integration` used to run here too, in the same pytest process. It
    does not any more, and the reason is the database: that suite brings
    postgres up, empties it between cases and stops it at the end, and under
    this session it was doing all of that to the stack's own database with the
    worker still attached. The visible symptom was a worker dying in a
    traceback after everything had passed; the invisible one would have been a
    truncate landing mid-walk. It costs nothing and needs no key, so it runs in
    `sweep` and in CI on a compose project of its own.

    For the free counterpart that checks the same pipeline with every model
    answer replayed from a recording, see `e2e_replay` - that is the one CI
    runs on every push.
    """
    _run_against_the_stack(session, ["tests/e2e"])


@nox.session
@nox.parametrize("mode", _CODE_SEARCH_MODES)
def e2e_replay(session: nox.Session, mode: str) -> None:
    """
    Registers `e2e_replay` as a nox session, parametrized once per way of
    finding code, i.e., runnable via
    `uv run python -m nox -s "e2e_replay(mode='both')"` for one mode, or
    `-s e2e_replay` for all three. The parametrization has to be named, as
    `test_module`'s does: a trailing `-- <mode>` becomes `session.posargs`,
    which this session hands to pytest.
    Runs the end-to-end suite against the full local stack with `argus_web`
    pointed at the Anthropic double, so **every model answer is replayed from a
    recording committed to this repo**. No API key, no tokens, no cost - which
    is exactly why this is the version CI runs on every push.

    `mode` is `CODE_SEARCH`, and it decides far more than which tools the model
    is offered: under `grep` the read tier registers no retrieval-by-meaning
    tool and opens no store, and the stack's index pass exits before building
    anything. So each mode is a different stack, walking a different graph, and
    each answers from **its own recordings** - stored under names this mode
    prefixes (`grep-feature-flag-toggle`, `both-feature-flag-toggle`). The
    double is a queue seeded by name and never inspects the request, so a
    `both` sequence replayed under `grep` would hand the model a call to a tool
    it was never offered, and the failure would read as an agent bug.

    `both` is what a push runs, being what a deployment runs. The other two are
    the benchmark's arrangement (§21) and run in the nightly, where an hour is
    cheap.

    What a green run proves: the pipeline works. An alert reaches the webhook,
    the orchestrator's graph drives it, all three retrieval channels answer
    over MCP, the Argo CD adapter maps a real vendor response, the real
    Anthropic adapter parses a real Anthropic body, and the incident lands in
    a terminal status with its hypothesis persisted.

    What it does **not** prove: that the model reaches the right conclusion.
    The answer was decided when the recording was made. Judgement is measured
    by `nox -s eval`, against thresholds derived from fifty samples per case -
    never from one replayed answer here.

    Selecting the double is one setting (`anthropic_base_url`), passed to the
    **worker** alone - the process that walks the graph, and so the only one
    that talks to a model at all. `argus_web` receives alerts and makes no
    model call, so aiming it at the double aims nothing: the walk would reach
    the real API, spend real tokens, and still report itself as a replayed run.
    Nothing in the production path knows this session exists: a pipeline that
    behaves differently when observed is not the pipeline.
    """
    # On the session's own environment, for the reason `_run_against_the_stack`
    # sets the rest there: the index pass, the read tier, the worker and the
    # pytest process that seeds the double all have to agree about which mode
    # this run is, and only an inherited setting cannot disagree.
    os.environ["CODE_SEARCH"] = mode
    _run_against_the_stack(
        session,
        _the_cases_for(mode),
        service_env={"worker": {"ANTHROPIC_BASE_URL": _ANTHROPIC_DOUBLE_BASE_URL}}
    )


# The cases about the index and the push that moves its watermark. Named here
# because the session, not the suite, is what knows which mode is running.
_CASES_ABOUT_THE_INDEX: Final = "tests/e2e/test_the_index_follows_the_repository.py"


def _the_cases_for(mode: str) -> list[str]:
    """The suite, less what this mode has no index for.

    Left uncollected rather than skipped inside the case. A skip is a result,
    and a run that reports the same two every time teaches a reader to read past
    the line that will one day say something else. Under `grep` there is no
    store, no watermark and no push to move one - those cases are not pending
    against this stack, they are about a mechanism it does not have.
    """
    if mode != _SEARCHING_BY_GREP_ALONE:
        return ["tests/e2e"]

    return ["tests/e2e", f"--ignore={_CASES_ABOUT_THE_INDEX}"]


@nox.session
@nox.parametrize("mode", _CODE_SEARCH_MODES)
def record(session: nox.Session, mode: str) -> None:
    """
    Registers `record` as a nox session, parametrized once per way of finding
    code, i.e., runnable via
    `uv run python -m nox -s "record(mode='both')" -- <name> [<name> ...]` -
    for example `-- flag-toggle-red-herring`, or `-- all` for every recording
    the offline suites rest on.
    Brings the same stack up as `e2e_replay`, but instead of running tests it
    drives **a real incident per name** through the Anthropic double in record
    mode, so the model's actual answers are stored as replayable recordings.

    Names alone: what each recording stages and which alert it fires is a
    mapping inside the script, because the world a recording was captured in
    has to be the world the case replaying it arranges. However many names are
    given, the stack is built, brought up and torn down **once** - it is the
    slow part of a run, and nothing about it differs per recording.

    Paid, and deliberately manual: it needs `ANTHROPIC_API_KEY`, spends tokens
    on one investigation per name, and overwrites the recordings it names. It
    exists because a recording is the one piece of evidence the offline suites
    rest on, and a recording captured by hand is one whose request nobody can
    prove matched what the adapter sends.

    The worker is pointed at the double exactly as in `e2e_replay` - which is
    what puts the double in the path at all - and the double forwards the call
    upstream because it was told to record rather than seeded.

    Parametrized by mode for the reason `e2e_replay` is: a recording is a queue
    of answers to a walk that was offered a particular set of tools, so a mode
    is not a label on the recording - it is the world it was captured in. The
    stack this brings up is the stack that mode runs, and the script stores
    what it captures under that mode's names. `grep` needs no run of its own
    unless its recordings are being refreshed: what is stored there is the walk
    Code-Fix took before retrieval by meaning existed.
    """
    os.environ["CODE_SEARCH"] = mode
    _run_against_the_stack(
        session,
        test_paths=[],
        service_env={"worker": {"ANTHROPIC_BASE_URL": _ANTHROPIC_DOUBLE_BASE_URL}},
        # `-m`, not the path: the script reuses the e2e suite's own world-reset
        # rather than keeping a second copy of it, and only the module form puts
        # the repo root on the path for `tests.` to resolve.
        command=["uv", "run", "python", "-m", "scripts.record_incident"]
    )


@nox.session
def stack(session: nox.Session) -> None:
    """
    Registers `stack` as a nox session, i.e., runnable via
    `uv run python -m nox -s stack`.
    Brings the same stack up as `e2e` and then holds it open instead of running
    tests, so the shop's console and Argus's own page can be watched side by
    side. Enter brings it down, and teardown is the same one the suites use -
    nothing is left running.

    Talks to the **real Anthropic API**, so it needs `ANTHROPIC_API_KEY` and
    spends tokens on every incident staged from the console. That is the point:
    a replayed answer was decided before anyone was watching, so a demo running
    on recordings shows the pipeline moving and proves nothing about the
    reasoning it is being watched for.
    """
    _run_against_the_stack(
        session,
        test_paths=[],
        command=["uv", "run", "python", "scripts/hold_the_stack.py"],
        # Slack as configured, which for a demo means the real workspace: the
        # thing being demonstrated is an incident reaching a person, and it
        # reaches nobody at a double.
        slack_stands_in=False
    )
