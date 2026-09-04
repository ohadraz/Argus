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
    """
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
    """
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
    """
    name, module_args, ready_url = _ANTHROPIC_DOUBLE
    double_process = _start_service(module_args)
    try:
        _wait_for_http(name, ready_url)
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
                "ANTHROPIC_BASE_URL": _ANTHROPIC_DOUBLE_BASE_URL,
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


def _start_service(
    module_args: list[str], env: dict[str, str] | None = None
) -> subprocess.Popen[bytes]:
    """Starts one local service as a child of this session, via the venv's Python.

    CREATE_NEW_PROCESS_GROUP is required on Windows for CTRL_BREAK_EVENT (the
    graceful-shutdown signal `_stop_service` sends) to be deliverable to the
    child at all.

    `env` overrides settings for *this* service only, which is how one process
    in the stack can be pointed somewhere the others are not - `e2e_replay`
    uses it to aim `argus_web` at the Anthropic double. It is merged into a
    copy of the session's own environment rather than replacing it: a child
    started with only the overrides would lose `PATH`, `SYSTEMROOT` and the
    database URL, and would fail in ways that look nothing like the cause.
    """
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(
        [_venv_python_binary(), *module_args],
        creationflags=creationflags,
        env={**os.environ, **env} if env else None,
    )


def _stop_service(process: subprocess.Popen[bytes], timeout: float = 10.0) -> None:
    """Graceful shutdown via the signal uvicorn's own asyncio server already
    handles - SIGTERM on POSIX, `CTRL_BREAK_EVENT` on Windows (Windows has no
    deliverable SIGTERM equivalent for an arbitrary child process). Falls
    back to a hard kill only if the process hasn't exited within `timeout`.
    """
    if sys.platform == "win32":
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.terminate()

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
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
        port = urllib.parse.urlparse(ready_url).port
        with socket.socket() as probe:
            probe.settimeout(1.0)
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                continue

        raise RuntimeError(
            f"port {port} is already in use, so [{name}] cannot start - a stack "
            f"from an earlier run is still up. Stop it first: "
            f"Get-NetTCPConnection -State Listen -LocalPort {port} | "
            f"ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force }}"
        )


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

# Settings every process in an e2e run shares - the services started here and
# the pytest process asserting on them. One place, because the two derive
# different things from the same number: `agent_mitigation` waits this long for
# the service to recover, and the suite's own timeouts are computed from it. If
# they disagreed, the suite would either give up before Argus did or wait long
# after it had.
#
# Two minutes rather than the configured three: recovery is judged on the first
# whole minute after an action, so the window has to outlast that minute's
# bucket and the scrape that publishes it - and no less. A walk of several
# attempts pays this wait once per attempt, so the third minute is pure
# wall-clock in the one suite that already costs the most to run.
_E2E_SETTINGS = {
    "MITIGATION_VERIFICATION_TIMEOUT_SECONDS": "120",
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
    "STRIPE_BASE_URL": "http://localhost:8080/stripe"
}

_ANTHROPIC_DOUBLE: tuple[str, list[str], str] = (
    "anthropic_double",
    ["-m", "anthropic_double.server"],
    f"{_ANTHROPIC_DOUBLE_BASE_URL}/health",
)

_LOCAL_SERVICES: list[tuple[str, list[str], str]] = [
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
            _wait_for_http(name, ready_url)
        # Anything after `--` goes to pytest, so a single failing case can be
        # re-run against the stack (`-- -k fallback`) instead of the whole
        # suite. Bringing the stack up is the slow part of a green run and the
        # cheap part of a debugging one.
        session.run(
            *(command or ["uv", "run", "python", "-m", "pytest", *test_paths, "-v"]),
            *session.posargs, external=True,
        )
    finally:
        for process in reversed(started):
            _stop_service(process)
        session.run("docker", "compose", "down", "-v", external=True)


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

    Selecting the double is one setting (`anthropic_base_url`), passed to
    `argus_web` alone. Nothing in the production path knows this session
    exists: a pipeline that behaves differently when observed is not the
    pipeline.
    """
    _run_against_the_stack(
        session,
        ["tests/e2e"],
        service_env={"argus_web": {"ANTHROPIC_BASE_URL": _ANTHROPIC_DOUBLE_BASE_URL}},
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

    `argus_web` is pointed at the double exactly as in `e2e_replay` - which is
    what puts the double in the path at all - and the double forwards the call
    upstream because it was told to record rather than seeded.
    """
    _run_against_the_stack(
        session,
        test_paths=[],
        service_env={"argus_web": {"ANTHROPIC_BASE_URL": _ANTHROPIC_DOUBLE_BASE_URL}},
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
