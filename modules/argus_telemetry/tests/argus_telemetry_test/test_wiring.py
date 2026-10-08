"""What one process's telemetry is written to, whether or not anything else hears it.

Every signal goes to disk, always, as OTLP JSON lines: one file per signal, in a
directory belonging to this run of this process alone. What lands there is
what any OTLP backend would ingest, so the files can be read by a person today
and loaded into a backend later.

Real files under a temporary directory, and OTel's real providers and file
exporters - the claim is about what is on disk once a process closes its
telemetry, and nothing short of writing it says that. No backend is configured
anywhere in this file, so nothing here reaches a network.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from argus_core import TelemetrySettings
from argus_telemetry import Telemetry, telemetry_for
from argus_testkit import Assertion, Scenario, all_of, the_answer_was

SOME_SERVICE = "argus-worker"
SOME_START = datetime(2026, 10, 8, 15, 14, 3, tzinfo=UTC)
SOME_PID = 4242

DONT_CARE_SERVICE = "argus-dont-care"
DONT_CARE_PID = 1


@pytest.mark.unit
def test_a_process_run_writes_into_a_directory_of_its_own(tmp_path: Path) -> None:
    # Named for the service and the run, so two processes never append to one
    # file - a span batch carrying a prompt is far larger than any append the
    # filesystem keeps whole - and so the run a person is looking for is one
    # directory rather than a grep.
    Scenario() \
        .given(
            some_settings := _settings_writing_under(tmp_path)
        ) \
        .when(
            lambda: telemetry_for(some_settings, SOME_SERVICE,
                                  started_at=SOME_START, pid=SOME_PID).run_directory
        ) \
        .then(
            the_answer_was(tmp_path / SOME_SERVICE / "20261008T151403Z-4242")
        )


@pytest.mark.unit
def test_a_span_is_written_as_otlp_json_with_its_trace_id_in_hex(tmp_path: Path) -> None:
    # Hex rather than the base64 protobuf's own JSON mapping would give: OTLP's
    # JSON encoding says hex, and a backend reading these files back matches a
    # span to its parent by exactly this string.
    Scenario() \
        .given(
            a_telemetry := _a_telemetry_writing_under(tmp_path)
        ) \
        .when(
            lambda: _a_span_ended_and_closed(a_telemetry, "some-span")
        ) \
        .then(
            all_of(
                _a_line_in(a_telemetry, "traces.jsonl", carries=_a_span_named("some-span")),
                _a_line_in(a_telemetry, "traces.jsonl", carries=_the_service(DONT_CARE_SERVICE))
            )
        )


@pytest.mark.unit
def test_a_metric_point_is_written_as_otlp_json(tmp_path: Path) -> None:
    Scenario() \
        .given(
            a_telemetry := _a_telemetry_writing_under(tmp_path)
        ) \
        .when(
            lambda: _a_counter_added_to_and_closed(a_telemetry, "some.counter")
        ) \
        .then(
            _a_line_in(a_telemetry, "metrics.jsonl", carries=_a_metric_named("some.counter"))
        )


@pytest.mark.unit
def test_a_log_record_written_inside_a_span_carries_that_spans_trace(tmp_path: Path) -> None:
    # The whole reason logs go through OTel rather than beside it: a line read
    # out of `logs.jsonl` leads to the walk it was written during, in this
    # process's files and in every other process the walk reached.
    Scenario() \
        .given(
            a_telemetry := _a_telemetry_writing_under(tmp_path)
        ) \
        .when(
            lambda: _a_warning_logged_inside_a_span_and_closed(
                a_telemetry, "argus_telemetry_test.some_logger", "some warning"
            )
        ) \
        .then(
            _a_line_in(a_telemetry, "logs.jsonl", carries=_a_record_in_the_trace_returned)
        )


@pytest.mark.unit
def test_the_sdks_own_records_are_not_exported(tmp_path: Path) -> None:
    # An exporter reports its own failures through `logging`. Exported in turn,
    # a failing log export would be a log record about a failed log export,
    # handed to the exporter that just failed - for as long as it keeps failing.
    Scenario() \
        .given(
            a_telemetry := _a_telemetry_writing_under(tmp_path)
        ) \
        .when(
            lambda: _a_warning_logged_inside_a_span_and_closed(
                a_telemetry, "opentelemetry.some_exporter", "some export failed"
            )
        ) \
        .then(
            _no_line_in(a_telemetry, "logs.jsonl", says="some export failed")
        )


@pytest.mark.unit
def test_a_directory_that_cannot_be_written_leaves_the_process_working(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Telemetry is evidence about the work, never a participant in it. A
    # process whose directory is unwritable starts, works, and says once that
    # it is writing nothing - rather than refusing to start over its own logs.
    a_file_where_the_directory_should_be = tmp_path / "telemetry"
    a_file_where_the_directory_should_be.write_text("not a directory")

    Scenario() \
        .given(
            unwritable_settings := _settings_writing_under(a_file_where_the_directory_should_be)
        ) \
        .when(
            lambda: _a_span_ended_and_closed(
                telemetry_for(unwritable_settings, DONT_CARE_SERVICE,
                              started_at=SOME_START, pid=DONT_CARE_PID),
                "dont-care-span"
            )
        ) \
        .then(
            _a_warning_was_logged(caplog, mentioning=str(a_file_where_the_directory_should_be))
        )


def _settings_writing_under(directory: Path) -> TelemetrySettings:
    return TelemetrySettings(
        telemetry_directory=str(directory),
        otel_exporter_otlp_endpoint="",
        otel_exporter_otlp_headers="",
        langfuse_base_url="",
        langfuse_public_key="",
        langfuse_secret_key=""
    )


def _a_telemetry_writing_under(directory: Path) -> Telemetry:
    return telemetry_for(_settings_writing_under(directory), DONT_CARE_SERVICE,
                         started_at=SOME_START, pid=DONT_CARE_PID)


def _a_span_ended_and_closed(telemetry: Telemetry, name: str) -> str:
    """One span, ended, and the telemetry closed so the batch reaches disk.

    Returns the span's trace id as OTLP's JSON spells it, which is what the
    file is then searched for.
    """
    with telemetry.tracer_provider.get_tracer(__name__).start_as_current_span(name) as span:
        trace_id = format(span.get_span_context().trace_id, "032x")

    telemetry.close()

    return trace_id


def _a_counter_added_to_and_closed(telemetry: Telemetry, name: str) -> None:
    telemetry.meter_provider.get_meter(__name__).create_counter(name).add(1)
    telemetry.close()


def _a_warning_logged_inside_a_span_and_closed(telemetry: Telemetry,
                                               logger_name: str,
                                               message: str) -> str:
    """A warning logged while a span is current, through the telemetry's handler.

    A logger of its own rather than the root, so that the handler is attached
    to nothing another test logs through. Returns the span's trace id.
    """
    logger = logging.getLogger(logger_name)
    logger.addHandler(telemetry.log_handler)

    try:
        tracer = telemetry.tracer_provider.get_tracer(__name__)

        with tracer.start_as_current_span("dont-care-span") as span:
            trace_id = format(span.get_span_context().trace_id, "032x")
            logger.warning(message)
    finally:
        logger.removeHandler(telemetry.log_handler)

    telemetry.close()

    return trace_id


def _lines_of(telemetry: Telemetry, file_name: str) -> list[dict[str, Any]]:
    """Every line of one of the run's files, parsed - none where it was never written."""
    assert telemetry.run_directory is not None
    path = telemetry.run_directory / file_name

    if not path.exists():
        return []

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# What one line has to show, given the line and whatever `when` returned - the
# trace id, where there is one. Its docstring says what it looks for, so that a
# failure can say it too.
LineCheck = Callable[[dict[str, Any], Any], bool]


def _a_line_in(telemetry: Telemetry, file_name: str, carries: LineCheck) -> Assertion[Any]:
    """That some line of the file satisfies `carries`, given what `when` returned."""
    def assertion(returned: Any) -> bool:
        lines = _lines_of(telemetry, file_name)

        if not any(carries(line, returned) for line in lines):
            raise AssertionError(
                f"Expected a line of [{file_name}] to carry {carries.__doc__}, "
                f"and its {len(lines)} lines were {lines}."
            )

        return True

    return assertion


def _no_line_in(telemetry: Telemetry, file_name: str, says: str) -> Assertion[Any]:
    def assertion(_returned: Any) -> bool:
        lines = _lines_of(telemetry, file_name)
        saying_it = [line for line in lines if says in json.dumps(line)]

        if saying_it:
            raise AssertionError(
                f"Expected no line of [{file_name}] to say [{says}], and these did: {saying_it}."
            )

        return True

    return assertion


def _a_span_named(name: str) -> LineCheck:
    def check(line: dict[str, Any], trace_id: str) -> bool:
        """a span with the name and trace id of the one that was ended"""
        return any(
            span["name"] == name and span["traceId"] == trace_id
            for resource in line.get("resourceSpans", [])
            for scope in resource["scopeSpans"]
            for span in scope["spans"]
        )

    return check


def _the_service(service: str) -> LineCheck:
    def check(line: dict[str, Any], _returned: Any) -> bool:
        """the service's name on its resource"""
        return any(
            attribute == {"key": "service.name", "value": {"stringValue": service}}
            for resource in line.get("resourceSpans", [])
            for attribute in resource["resource"]["attributes"]
        )

    return check


def _a_metric_named(name: str) -> LineCheck:
    def check(line: dict[str, Any], _returned: Any) -> bool:
        """a metric with the counter's name"""
        return any(
            metric["name"] == name
            for resource in line.get("resourceMetrics", [])
            for scope in resource["scopeMetrics"]
            for metric in scope["metrics"]
        )

    return check


def _a_record_in_the_trace_returned(line: dict[str, Any], trace_id: str) -> bool:
    """a log record carrying the trace id of the span it was written in"""
    return any(
        record.get("traceId") == trace_id
        for resource in line.get("resourceLogs", [])
        for scope in resource["scopeLogs"]
        for record in scope["logRecords"]
    )


def _a_warning_was_logged(caplog: pytest.LogCaptureFixture, mentioning: str) -> Assertion[Any]:
    def assertion(_returned: Any) -> bool:
        warnings = [record.getMessage() for record in caplog.records
                    if record.levelno == logging.WARNING]

        if not any(mentioning in warning for warning in warnings):
            raise AssertionError(
                f"Expected a warning mentioning [{mentioning}], and the warnings were {warnings}."
            )

        return True

    return assertion
