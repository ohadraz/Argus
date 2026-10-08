"""A process's telemetry, as the process itself lives and ends.

What only a real process can show. A process is stopped by a signal, not by
returning from `main`, and a signal's default is to end the process where it
stands - past every `finally` that would have flushed what was still batched.
The clock a run directory is named by is read once per process, from the
environment the process was started in. And the level a process logs at is
the whole process's, set on the root by the one call a `main` makes.

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
from argus_testkit import Assertion, Scenario, all_of

THE_LAST_SPAN = "the-last-span"
SOME_INFO = "some milestone"
SOME_DEBUG = "some diagnostic detail"

# The child: telemetry started as a `main` starts it, one span ended, one
# record logged at INFO and one at DEBUG, the run directory said on stdout, and
# then idle until something stops it. Idle in short sleeps rather than one long
# block, because a signal's Python handler runs only when the interpreter next
# gets control.
_A_PROCESS = f"""
import logging, sys, time
from argus_core import TelemetrySettings
from argus_telemetry import start_telemetry
from opentelemetry import trace

with start_telemetry(TelemetrySettings(
    telemetry_directory=sys.argv[1],
    otel_exporter_otlp_endpoint="",
    otel_exporter_otlp_headers="",
    langfuse_base_url="",
    langfuse_public_key="",
    langfuse_secret_key="",
    log_level="INFO"
), "argus-dont-care") as telemetry:
    with trace.get_tracer(__name__).start_as_current_span("{THE_LAST_SPAN}"):
        pass

    logger = logging.getLogger("argus_dont_care.some_module")
    logger.info("{SOME_INFO}")
    logger.debug("{SOME_DEBUG}")

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
def test_a_process_stopped_by_its_signal_says_it_stopped(tmp_path: Path) -> None:
    # A signal ends a process past every `with`, so the line its telemetry
    # would have written on the way out of `main` is written on the way out of
    # the signal instead - or a stopped stack's logs would read as though every
    # process had been cut off mid-sentence.
    Scenario() \
        .given(
            a_process := _a_process_writing_under(tmp_path)
        ) \
        .when(
            lambda: _stopped_by_its_signal(a_process)
        ) \
        .then(
            _its_logs_say("service stopped")
        )


@pytest.mark.component
def test_a_process_logs_at_info_and_not_below_by_default(tmp_path: Path) -> None:
    # INFO is the audit trail a running stack keeps; DEBUG is for the incident
    # somebody is chasing, and costs a restart with the level lowered.
    Scenario() \
        .given(
            a_process := _a_process_writing_under(tmp_path)
        ) \
        .when(
            lambda: _stopped_by_its_signal(a_process)
        ) \
        .then(
            all_of(
                _its_logs_say(SOME_INFO),
                _its_logs_never_say(SOME_DEBUG)
            )
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


def _messages_in(run_directory: Path) -> list[str]:
    """Every log record's message in the run's `logs.jsonl`, none where it was never written."""
    logs = run_directory / "logs.jsonl"
    lines = logs.read_text(encoding="utf-8").splitlines() if logs.exists() else []

    return [
        record["body"]["stringValue"]
        for line in lines
        for resource in json.loads(line).get("resourceLogs", [])
        for scope in resource["scopeLogs"]
        for record in scope["logRecords"]
    ]


def _its_logs_say(message: str) -> Assertion[Path]:
    def assertion(run_directory: Path) -> bool:
        messages = _messages_in(run_directory)

        if message not in messages:
            raise AssertionError(
                f"Expected the process's logs to say [{message}] once it was stopped, "
                f"and they said {messages}."
            )

        return True

    return assertion


def _its_logs_never_say(message: str) -> Assertion[Path]:
    def assertion(run_directory: Path) -> bool:
        messages = _messages_in(run_directory)

        if message in messages:
            raise AssertionError(
                f"Expected the process's logs never to say [{message}], and they said {messages}."
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
