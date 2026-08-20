import signal
import subprocess
import sys
import time
import urllib.error
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


def _discover_modules() -> list[str]:
    """
    Any subdirectory of `modules/` containing a `pyproject.toml` is a module.
    """
    current_dir = Path(__file__).parent

    if not (current_dir / "modules").exists():
        return []
    
    modules_dir = current_dir / "modules"

    return sorted(
        path.name for path in modules_dir.iterdir()
        if path.is_dir() and (path / "pyproject.toml").exists()
    )


MODULES: list[str] = _discover_modules()


@nox.session
def lint(session: nox.Session) -> None:
    """ 
    Registers `lint` as a nox session, i.e., runnable via `nox -s lint`.
    Runs ruff linter on the entire workspace.
    """
    session.run("uv", "run", "python", "-m", "ruff", "check", ".", external=True)

@nox.session
def typecheck(session: nox.Session) -> None:
    """
    Registers `typecheck` as a nox session, i.e., runnable via `nox -s typecheck`.
    Runs mypy --strict (via pyproject.toml's `[tool.mypy]`) on the entire modules/
    directory. Skips gracefully if no modules exist yet. Uses `--all-packages` so
    every workspace member's dependencies are installed regardless of what a prior
    plain `uv sync`/`uv run` happened to resolve (without it, mypy can spuriously
    report "Cannot find implementation or library stub" for a dependency that's
    declared but wasn't actually installed into the shared venv yet).
    """
    if not MODULES:
        session.skip("no modules/ yet - nothing to type-check")
    session.run("uv", "run", "--all-packages", "python", "-m", "mypy", "modules", external=True)

@nox.session
@nox.parametrize("module", MODULES)
def test_module(session: nox.Session, module: str) -> None:
    """
    Registers `test_module` as a nox session, parametrized once per discovered module,
    i.e., runnable via `nox -s test_module -- <module-name>`.
    Runs that module's `unit` and `integration` tests in isolation, using only its own
    declared dependencies (via `uv run --package`).
    """
    session.run(
        "uv", "run", "--package", f"argus-{module}",
        "python", "-m", "pytest", f"modules/{module}/tests", "-m", "unit or integration", "-v",
        external=True,
    )

@nox.session
def test_all(session: nox.Session) -> None:
    """
    Registers `test_all` as a nox session, i.e., runnable via `nox -s test_all`
    (fail-fast, default) or `nox -s test_all -- --ci` or `--aggregate` (continue past failures,
    aggregate and report at the end).
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
    `nox -s guard_e2e_boundary`.
    Fails if any test under modules/*/tests/ carries the `e2e` pytest marker -
    those need the docker-compose stack that only `nox -s e2e` brings up, and
    only for root tests/e2e/.
    """
    session.run("uv", "run", "python", "scripts/guard_e2e_boundary.py", external=True)

@nox.session
def contract(session: nox.Session) -> None:
    """
    Registers `contract` as a nox session, i.e., runnable via `nox -s contract`.
    Runs the top-level contract tests that verify agent-exposed tool schemas still
    match what the orchestrator expects to call (catches cross-module drift).
    """
    session.run("uv", "run", "python", "-m", "pytest", "tests/contract", "-v", external=True)

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


def _start_argus_web() -> subprocess.Popen[bytes]:
    # CREATE_NEW_PROCESS_GROUP is required on Windows for CTRL_BREAK_EVENT
    # (the graceful-shutdown signal below) to be deliverable to this process.
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(
        [_venv_python_binary(), "-m", "uvicorn", "argus_web.app:app", "--port", "8000"],
        creationflags=creationflags,
    )


def _stop_argus_web(process: subprocess.Popen[bytes], timeout: float = 10.0) -> None:
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


def _wait_for_argus_web(timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen("http://localhost:8000/openapi.json", timeout=1.0)
            return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.5)
    raise TimeoutError("argus_web did not become ready within the timeout")


def _start_read_mcp() -> subprocess.Popen[bytes]:
    # Same process-group/signal-delivery reasoning as `_start_argus_web`.
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(
        [_venv_python_binary(), "-m", "read_mcp_server.server"],
        creationflags=creationflags,
    )


def _stop_read_mcp(process: subprocess.Popen[bytes], timeout: float = 10.0) -> None:
    if sys.platform == "win32":
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.terminate()

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _wait_for_read_mcp(timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen("http://localhost:8090/mcp", timeout=1.0)
            return
        except urllib.error.HTTPError:
            return  # a real HTTP response (even an error one) means the server is up
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.5)
    raise TimeoutError("read_mcp did not become ready within the timeout")


@nox.session
def e2e(session: nox.Session) -> None:
    """
    Registers `e2e` as a nox session, i.e., runnable via `nox -s e2e`.
    Brings up docker-compose's `postgres` service (always-on, base
    definition) plus `target-service` (the `e2e` Compose profile - it's a
    demo/test fixture, not something Argus itself depends on, so it stays
    out of the default `docker compose up`) and local `argus_web` and
    `read_mcp` processes (neither containerized - design.md's decision),
    runs the end-to-end suite (plus `tests/integration` once that directory
    exists) against them, then tears everything back down - even if the
    tests fail, so nothing is left running.
    """
    test_paths = ["tests/e2e"]
    if Path("tests/integration").exists():
        test_paths.append("tests/integration")

    web_process: subprocess.Popen[bytes] | None = None
    read_mcp_process: subprocess.Popen[bytes] | None = None
    try:
        session.run(
            "docker", "compose", "--profile", "e2e", "up", "-d", "--wait", external=True
        )
        read_mcp_process = _start_read_mcp()
        _wait_for_read_mcp()
        web_process = _start_argus_web()
        _wait_for_argus_web()
        session.run("uv", "run", "python", "-m", "pytest", *test_paths, "-v", external=True)
    finally:
        if web_process is not None:
            _stop_argus_web(web_process)
        if read_mcp_process is not None:
            _stop_read_mcp(read_mcp_process)
        session.run("docker", "compose", "--profile", "e2e", "down", external=True)
