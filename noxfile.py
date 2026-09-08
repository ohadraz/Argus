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


EXCLUDED_FROM_TESTS: set[str] = {"argus_testkit", "anthropic_double"}


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

    Runs against a database of this module's own, so it can run beside
    `e2e_replay` - or beside another module's suite - rather than stop the
    database either of them is using. The conftests that bring postgres up
    inherit this environment; none of them is handed one.
    """
    os.environ.update(_a_database_for(module))
    session.run(
        "uv", "run", "--package", f"argus-{module}",
        "python", "-m", "pytest", f"modules/{module}/tests",
        "-m", "unit or component or integration", "-v",
        external=True,
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

    On a database of its own, for the reason `test_module` has one - and not
    the same one, since running both at once is the case that would otherwise
    have each stopping the other's.
    """
    os.environ.update(_TEST_ALL_STACK)
    ci_mode = "--ci" in session.posargs or "--aggregate" in session.posargs
    failed_modules: list[str] = []

    for module in MODULES:
        try:
            session.run(
                "uv", "run", "--package", f"argus-{module}",
                "python", "-m", "pytest", f"modules/{module}/tests", "-v", external=True,
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
    Runs every free suite at once - `lint`, `typecheck`, `guard_e2e_boundary`,
    `test_all`, `integration` and `e2e_replay` - each in its own process, and
    stops the lot the moment one of them fails.

    They can share a machine because none of them shares infrastructure: each
    brings up a database under a compose project of its own, and the two that
    want an Anthropic double bind different ports (`_INTEGRATION_STACK`,
    `_MODULE_SUITE_STACK`). Sequentially this is the better part of half an
    hour, almost all of it `e2e_replay` waiting on walks.

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


# What a sweep runs. Every suite that costs nothing and needs no key - the same
# set CI runs on a push, which is what makes a green sweep mean something
# before the push rather than after it.
_SWEEP = ["lint", "typecheck", "guard_e2e_boundary", "test_all", "integration",
          "e2e_replay"]

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
def contract(session: nox.Session) -> None:
    """
    Registers `contract` as a nox session, i.e., runnable via `uv run python -m nox -s contract`.
    Runs the top-level contract tests, which check that a test double still
    matches the third party it stands in for. Brings up the Anthropic double,
    because half of each comparison is a replayed recording; the other half
    talks to the real API and skips itself when no key is configured.
    """
    name, module_args, ready_url = _ANTHROPIC_DOUBLE
    double_process = _start_service(module_args)
    try:
        _wait_for_http(name, ready_url)
        session.run("uv", "run", "python", "-m", "pytest", "tests/contract", "-v", external=True)
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
    for - on a Hebrew-locale machine that is `cp1255`, and the `print` inside
    the Communicator then raises `UnicodeEncodeError` in the middle of a node
    and takes the whole walk down. The narration is not the place to negotiate
    with the console: the console is set to accept what Argus says.
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
             **(env or {})},
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
# looks like. No double: every module suite that reaches a model reaches a stub
# it constructs itself.
_TEST_ALL_STACK = _a_database_of_its_own("argus-modules", _TEST_ALL_POSTGRES_PORT)

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
    "e2e_replay": ()
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

# Settings every process in an e2e run shares - the services started here and
# the pytest process asserting on them. One place, because the two derive
# different things from the same number: `agent_mitigation` waits this long for
# the service to recover, and the suite's own timeouts are computed from it. If
# they disagreed, the suite would either give up before Argus did or wait long
# after it had.
#
# Six minutes, where the configured default is three. Recovery is judged on
# the first whole minute after an action, so the window has to outlast that
# minute's bucket and the scrape that publishes it. Two minutes covers that on
# an idle machine and does not on a loaded one - a build running beside the
# stack, or a CI runner - and the failure it produces is the worst kind: Argus
# reports a mitigation that worked as refuted, walks another round, and asks
# the double for an answer nobody recorded. The suite then fails pointing at
# the recording.
#
# Four was measured to be too short on a GitHub runner, which is the slowest
# machine this suite runs on and the only one nobody is watching.
#
# A walk pays this wait once per attempt, so the extra time lands only on the
# cases that genuinely wait it out - a refuted action, an escalation with
# nothing left to try. Wall-clock is the cheaper of the two things to spend
# here; the other is trust in what a red run means.
_E2E_SETTINGS = {
    "MITIGATION_VERIFICATION_TIMEOUT_SECONDS": "360",
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
    "HR_BASE_URL": "http://localhost:8080/bamboohr"
}

_ANTHROPIC_DOUBLE: tuple[str, list[str], str] = (
    "anthropic_double",
    ["-m", "anthropic_double.server"],
    f"{_ANTHROPIC_DOUBLE_BASE_URL}/health",
)

_LOCAL_SERVICES: list[tuple[str, list[str], str | None]] = [
    ("read_mcp", ["-m", "read_mcp_server.server"], "http://localhost:8090/mcp"),
    # Its own process, not a second module inside `read_mcp`: the tier split
    # (spec §12.1, §13) is what makes "read-only" a property of a running
    # process rather than a convention, and a stack that started only one of
    # them would be testing the convention.
    ("write_mcp", ["-m", "write_mcp_server.server"], "http://localhost:8092/mcp"),
    _ANTHROPIC_DOUBLE,
    (
        # Bound to every interface, not just loopback: the Target Environment's
        # monitoring posts its alerts from inside a container, and a server
        # listening only on `127.0.0.1` is not reachable from there however the
        # container spells the host.
        "argus_web",
        ["-m", "uvicorn", "argus_web.app:app", "--host", "0.0.0.0", "--port", "8000"],
        "http://localhost:8000/openapi.json",
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
        None,
    ),
]


def _run_against_the_stack(
    session: nox.Session,
    test_paths: list[str],
    service_env: dict[str, dict[str, str]] | None = None,
    command: list[str] | None = None,
) -> None:
    """Brings the whole stack up, runs `test_paths` against it, tears it down.

    Shared by `e2e` and `e2e_replay` so the two cannot drift on anything except
    the one difference that distinguishes them - which service, if any, is
    started pointed somewhere else. `service_env` maps a name in
    `_LOCAL_SERVICES` to the settings that service alone should see.

    Brings up docker-compose's `postgres` service plus the whole Target
    Environment - the Target Service, the feature-flag provider and that
    provider's database, `include`d from the sibling repo's own compose file -
    and the local `read_mcp`, `anthropic_double` and `argus_web` processes (none
    containerized - design.md's decision). Everything, which is why no service
    is named: this is the one caller that wants the lot. A suite needing only
    the database names it instead - see `docker-compose.yml`. Teardown runs even
    if the tests fail, so nothing is left running.

    Teardown passes `-v` so Postgres's anonymous volume goes with the
    container. Without it the database survives between runs, and since the
    schema is applied as `CREATE TABLE IF NOT EXISTS`, a table that already
    exists is never altered - a column added or renamed in `argus_core.schema`
    would silently never appear, and the suite would fail against a schema no
    file in the repo describes. An e2e run should start from nothing anyway.
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
    try:
        # `--build` because the Target Service image is built from a sibling
        # working copy, not pulled: without it Compose reuses whatever was
        # built last, and a scenario edited in that repo ships stale to the
        # one suite whose whole job is to exercise the real thing. That failure
        # is silent in the worst way - the run goes green against yesterday's
        # fixture, or 404s on an endpoint the source plainly has.
        session.run(
            "docker", "compose", "up", "-d", "--wait", "--build", external=True,
        )
        for name, module_args, ready_url in _LOCAL_SERVICES:
            started.append(_start_service(module_args, env=service_env.get(name)))
            # A service that listens on nothing is waited for by nothing: the
            # worker's readiness shows up in the queue it drains, not on a port.
            if ready_url is not None:
                _wait_for_http(name, ready_url)
        # Anything after `--` goes to pytest, so a single failing case can be
        # re-run against the stack (`-- -k fallback`) instead of the whole
        # suite. Bringing the stack up is the slow part of a green run and the
        # cheap part of a debugging one.
        session.run(
            *(command or ["uv", "run", "python", "-m", "pytest", *test_paths, "-v"]),
            *session.posargs, external=True,
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
        for process in reversed(started):
            _stop_service(process)
        session.run("docker", "compose", "down", "-v", external=True)


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
            external=True, success_codes=[0, 1],
        )


@nox.session
def e2e(session: nox.Session) -> None:
    """
    Registers `e2e` as a nox session, i.e., runnable via `uv run python -m nox -s e2e`.
    Runs the end-to-end suite (plus `tests/integration`) against the full local
    stack, with `argus_web` talking to the **real Anthropic API**.

    This is the paid, manual, pre-merge run: it needs `ANTHROPIC_API_KEY` and
    spends tokens on every incident it drives. It is the only suite in which a
    real model reads real retrieved evidence and reaches a conclusion end to
    end, which is what makes it worth the money before a merge that changes the
    investigation path.

    For the free counterpart that checks the same pipeline with every model
    answer replayed from a recording, see `e2e_replay` - that is the one CI
    runs on every push.
    """
    test_paths = ["tests/e2e"]
    if Path("tests/integration").exists():
        test_paths.append("tests/integration")

    _run_against_the_stack(session, test_paths)


@nox.session
def e2e_replay(session: nox.Session) -> None:
    """
    Registers `e2e_replay` as a nox session, i.e., runnable via
    `uv run python -m nox -s e2e_replay`.
    Runs the end-to-end suite against the full local stack with `argus_web`
    pointed at the Anthropic double, so **every model answer is replayed from a
    recording committed to this repo**. No API key, no tokens, no cost - which
    is exactly why this is the version CI runs on every push.

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
    _run_against_the_stack(
        session,
        ["tests/e2e"],
        service_env={"worker": {"ANTHROPIC_BASE_URL": _ANTHROPIC_DOUBLE_BASE_URL}},
    )


@nox.session
def record(session: nox.Session) -> None:
    """
    Registers `record` as a nox session, i.e., runnable via
    `uv run python -m nox -s record -- <name> [<name> ...]` - for example
    `-- flag-toggle-red-herring`, or `-- all` for every recording the offline
    suites rest on.
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
    """
    _run_against_the_stack(
        session,
        test_paths=[],
        service_env={"worker": {"ANTHROPIC_BASE_URL": _ANTHROPIC_DOUBLE_BASE_URL}},
        # `-m`, not the path: the script reuses the e2e suite's own world-reset
        # rather than keeping a second copy of it, and only the module form puts
        # the repo root on the path for `tests.` to resolve.
        command=["uv", "run", "python", "-m", "scripts.record_incident"],
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
    )
