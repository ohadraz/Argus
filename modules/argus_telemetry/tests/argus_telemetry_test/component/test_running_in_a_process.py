"""A process's telemetry, as the process itself lives and ends.

What only a real process can show. A process is stopped by a signal, not by
returning from `main`, and a signal's default is to end the process where it
stands - past every `finally` that would have flushed what was still batched.
And the clock a run directory is named by is read once per process, from the
environment the process was started in.

Each case starts a child Python that installs telemetry exactly as a `main`
does, says where it is writing, and then waits to be stopped. No backend is
configured, so nothing here reaches a network.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario

THE_LAST_SPAN = "the-last-span"

# The child: telemetry started as a `main` starts it, one span ended, the run
# directory said on stdout, and then idle until something stops it. Idle in
# short sleeps rather than one long block, because a signal's Python handler
# runs only when the interpreter next gets control.
_A_PROCESS = f"""
import sys, time
from argus_core import TelemetrySettings
from argus_telemetry import start_telemetry
from opentelemetry import trace

telemetry = start_telemetry(TelemetrySettings(
    telemetry_directory=sys.argv[1],
    otel_exporter_otlp_endpoint="",
    otel_exporter_otlp_headers="",
    langfuse_base_url="",
    langfuse_public_key="",
    langfuse_secret_key=""
), "argus-dont-care")

with trace.get_tracer(__name__).start_as_current_span("{THE_LAST_SPAN}"):
    pass

print(telemetry.run_directory, flush=True)

while True:
    time.sleep(0.05)
"""

# A stack clock nowhere near the wall's: twice real time, counted from 1970,
# which puts it some fifty years ahead. Spelled as a stack spells it, since the
# environment is the whole of how a process learns it.
A_STACK_CLOCK_ELSEWHERE = {"SIM_CLOCK_EPOCH": "0", "SIM_CLOCK_SPEED": "2"}


@pytest.mark.component
def test_a_process_stopped_by_its_signal_has_written_what_it_had_batched(
    tmp_path: Path
) -> None:
    # How every stack stops a process: SIGTERM, or Windows' CTRL_BREAK. A span
    # ended a moment before is still in the batch, and a process that died
    # where it stood would take it along - the last seconds of a walk, which
    # are what a person reading a stopped stack's traces came for.
    Scenario() \
        .given(
            a_process := _a_process_writing_under(tmp_path)
        ) \
        .when(
            lambda: _stopped_by_its_signal(a_process)
        ) \
        .then(
            _its_traces_hold(THE_LAST_SPAN)
        )


@pytest.mark.component
def test_a_run_directory_is_named_for_the_wall_clock_whatever_the_stacks_clock_says(
    tmp_path: Path
) -> None:
    # Every time inside the files is the wall's - the SDK stamps spans from it
    # - so a directory named by a simulated clock would be named for a moment
    # its own contents never mention.
    started_after = datetime.now(UTC).replace(microsecond=0)

    Scenario() \
        .given(
            a_process := _a_process_writing_under(tmp_path, clock=A_STACK_CLOCK_ELSEWHERE)
        ) \
        .when(
            lambda: _stopped_by_its_signal(a_process)
        ) \
        .then(
            _named_for_a_start_between(started_after, datetime.now(UTC))
        )


class _Process:
    """A child that has started its telemetry, and the directory it said it writes to."""

    def __init__(self, running: subprocess.Popen[str], run_directory: Path) -> None:
        self.running = running
        self.run_directory = run_directory


def _a_process_writing_under(directory: Path, clock: dict[str, str] | None = None) -> _Process:
    environment = {**os.environ, **(clock or {})}
    running = subprocess.Popen(
        [sys.executable, "-c", _A_PROCESS, str(directory)],
        stdout=subprocess.PIPE,
        text=True,
        env=environment,
        creationflags=_a_group_of_its_own()
    )
    assert running.stdout is not None

    return _Process(running, Path(running.stdout.readline().strip()))


def _a_group_of_its_own() -> int:
    """On Windows, what lets CTRL_BREAK reach the child and nothing else."""
    if sys.platform == "win32":
        return subprocess.CREATE_NEW_PROCESS_GROUP

    return 0


def _stopped_by_its_signal(process: _Process) -> Path:
    """Stopped the way a stack stops it, and waited out. Returns the run directory."""
    if sys.platform == "win32":
        process.running.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.running.send_signal(signal.SIGTERM)

    process.running.wait(timeout=10)

    return process.run_directory


def _its_traces_hold(span_name: str) -> Assertion[Path]:
    def assertion(run_directory: Path) -> bool:
        traces = run_directory / "traces.jsonl"
        lines = traces.read_text(encoding="utf-8").splitlines() if traces.exists() else []
        names = [
            span["name"]
            for line in lines
            for resource in json.loads(line).get("resourceSpans", [])
            for scope in resource["scopeSpans"]
            for span in scope["spans"]
        ]

        if span_name not in names:
            raise AssertionError(
                f"Expected [{traces}] to hold the span [{span_name}] once the process "
                f"was stopped, and the spans it held were {names}."
            )

        return True

    return assertion


def _named_for_a_start_between(earliest: datetime, latest: datetime) -> Assertion[Any]:
    def assertion(run_directory: Path) -> bool:
        started = datetime.strptime(run_directory.name.split("-")[0], "%Y%m%dT%H%M%SZ") \
            .replace(tzinfo=UTC)

        if not earliest <= started <= latest:
            raise AssertionError(
                f"Expected the run directory to be named for a start between "
                f"{earliest.isoformat()} and {latest.isoformat()}, and it was "
                f"[{run_directory.name}]."
            )

        return True

    return assertion
