"""What one process's telemetry is written to, whether or not anything else hears it.

Every signal goes to disk, always, as OTLP JSON lines: one file per signal, in a
directory belonging to this run of this process alone. What lands there is
what any OTLP backend would ingest, so the files can be read by a person today
and loaded into a backend later. A log record goes to the console as well,
written from a queue so that the thread that logged never waits on a pipe.

Real files under a temporary directory, and OTel's real providers and file
exporters - the claim is about what is on disk once a process closes its
telemetry, and nothing short of writing it says that. No backend is configured
anywhere in this file, so nothing here reaches a network.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from logging.handlers import QueueHandler
from pathlib import Path
from typing import Any

import pytest
from argus_core import TelemetrySettings
from argus_core.telemetry import ARGUS_INCIDENT_ID
from argus_telemetry import Telemetry, telemetry_for
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    calling,
    one_record_was_logged,
    the_answer_was,
)
from opentelemetry import baggage, context

SOME_SERVICE = "argus-worker"
SOME_START = datetime(2026, 10, 8, 15, 14, 3, tzinfo=UTC)
SOME_PID = 4242
SOME_INCIDENT = "4f0c2a1e-5b6d-4c3e-9a8b-7d6e5f4c3b2a"
SOME_TOKEN = "some-token-nobody-may-read"

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
def test_a_log_record_written_inside_an_incident_carries_it_into_logs_jsonl(
    tmp_path: Path
) -> None:
    # Read off the real baggage, as a walk leaves it and as a tool call carries
    # it into a server, and written under the very key the walk's spans use -
    # so a backend's filter on the incident finds its log lines and its spans
    # alike.
    Scenario() \
        .given(
            a_telemetry := _a_telemetry_writing_under(tmp_path)
        ) \
        .when(
            lambda: _a_warning_logged_inside_the_baggage_and_closed(
                a_telemetry, {ARGUS_INCIDENT_ID: SOME_INCIDENT}
            )
        ) \
        .then(
            _a_line_in(a_telemetry, "logs.jsonl",
                       carries=_a_record_carrying(ARGUS_INCIDENT_ID, SOME_INCIDENT))
        )


@pytest.mark.unit
def test_a_value_named_as_a_secret_is_blanked_before_either_handler_writes_it(
    tmp_path: Path
) -> None:
    # Both destinations, because a secret on the console is a secret in every
    # container log a stack keeps, and a secret in `logs.jsonl` is a secret in
    # every backend it is sent on to.
    Scenario() \
        .given(
            a_console := io.StringIO(),
            a_telemetry := _a_telemetry_writing_under(tmp_path, console=a_console)
        ) \
        .when(
            lambda: _a_warning_logged_through_both_and_closed(
                a_telemetry, extra={"slack_token": SOME_TOKEN}
            )
        ) \
        .then(
            all_of(
                _no_line_in(a_telemetry, "logs.jsonl", says=SOME_TOKEN),
                _a_line_in(a_telemetry, "logs.jsonl",
                           carries=_a_record_carrying("slack_token", "[redacted]")),
                _the_console(a_console, says="slack_token=[redacted]"),
                _the_console_never(a_console, says=SOME_TOKEN)
            )
        )


@pytest.mark.unit
def test_the_console_is_written_from_a_queue_and_drained_on_close(tmp_path: Path) -> None:
    # A write to a console is a write to a pipe, and a pipe nobody is reading
    # blocks whoever writes to it - a walk, if the walk is what logged. Queued,
    # the line is written by a thread of its own; drained by `close()`, so a
    # process that ends leaves its last lines on the console as well as on disk.
    Scenario() \
        .given(
            a_console := io.StringIO(),
            a_telemetry := _a_telemetry_writing_under(tmp_path, console=a_console)
        ) \
        .when(
            lambda: _a_warning_logged_through_both_and_closed(
                a_telemetry, message="some last words"
            )
        ) \
        .then(
            all_of(
                _the_console_is_queued(a_telemetry),
                _the_console(a_console, says="some last words")
            )
        )


@pytest.mark.unit
def test_a_process_says_it_started_and_that_it_stopped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # The first and last lines of every process's log, so a person reading
    # one knows where a run begins and whether it ended or was cut off - and
    # named for the service, since a console holds several processes' lines.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            a_telemetry := _a_telemetry_writing_under(tmp_path)
        ) \
        .when(
            lambda: _entered_and_left(a_telemetry)
        ) \
        .then(
            _its_life_was(caplog, [
                (logging.INFO, "service started"),
                (logging.INFO, "service stopped")
            ])
        )


@pytest.mark.unit
@pytest.mark.parametrize("stop", [SystemExit(0), KeyboardInterrupt()])
def test_a_process_stopped_on_purpose_says_it_stopped(
    stop: BaseException, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Asked to stop is stopping, not dying: a CRITICAL here would page somebody
    # every time a stack was brought down.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            a_telemetry := _a_telemetry_writing_under(tmp_path)
        ) \
        .when(
            lambda: _entered_and_left(a_telemetry, raising=stop)
        ) \
        .then(
            all_of(
                _its_life_was(caplog, [
                    (logging.INFO, "service started"),
                    (logging.INFO, "service stopped")
                ]),
                the_answer_was(stop)
            )
        )


@pytest.mark.unit
def test_a_process_that_dies_says_so_with_what_killed_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # The one place every CRITICAL comes from: an exception that reached the
    # top of a process. Logged with its stack trace, because it is the last
    # thing the process will ever say - and let through, because the process
    # must still die of it.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            a_telemetry := _a_telemetry_writing_under(tmp_path)
        ) \
        .when(
            lambda: _entered_and_left(a_telemetry, raising=ValueError("some failure"))
        ) \
        .then(
            all_of(
                _its_life_was(caplog, [
                    (logging.INFO, "service started"),
                    (logging.CRITICAL, "service died")
                ]),
                _the_death_carried_what_was_raised(caplog)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("raising", [None, ValueError("some failure")])
def test_leaving_a_process_telemetry_writes_out_what_it_held(
    raising: BaseException | None, tmp_path: Path
) -> None:
    # However the process leaves - and above all when it dies, since its last
    # seconds are what a person reading the files came for.
    Scenario() \
        .given(
            a_telemetry := _a_telemetry_writing_under(tmp_path)
        ) \
        .when(
            lambda: _entered_and_left(a_telemetry, raising=raising, ending_a_span="some-span")
        ) \
        .then(
            _a_line_in(a_telemetry, "traces.jsonl", carries=_a_span_named_anything("some-span"))
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
    # it is writing nothing - and where it tried, which is the whole diagnosis -
    # rather than refusing to start over its own logs.
    a_file_where_the_directory_should_be = tmp_path / "telemetry"
    a_file_where_the_directory_should_be.write_text("not a directory")

    Scenario() \
        .given(
            unwritable_settings := _settings_writing_under(a_file_where_the_directory_should_be)
        ) \
        .when(
            lambda: _a_span_ended_and_closed(
                telemetry_for(unwritable_settings, SOME_SERVICE,
                              started_at=SOME_START, pid=SOME_PID),
                "dont-care-span"
            )
        ) \
        .then(
            one_record_was_logged(
                caplog, "argus_telemetry.wiring", logging.WARNING,
                "telemetry not written to disk",
                values={"directory": str(
                    a_file_where_the_directory_should_be / SOME_SERVICE / "20261008T151403Z-4242"
                )},
                failure=OSError
            )
        )


def _settings_writing_under(directory: Path) -> TelemetrySettings:
    return TelemetrySettings(
        telemetry_directory=str(directory),
        otel_exporter_otlp_endpoint="",
        otel_exporter_otlp_headers="",
        langfuse_base_url="",
        langfuse_public_key="",
        langfuse_secret_key="",
        log_level="INFO"
    )


def _a_telemetry_writing_under(directory: Path,
                               console: io.StringIO | None = None) -> Telemetry:
    return telemetry_for(_settings_writing_under(directory), DONT_CARE_SERVICE,
                         started_at=SOME_START, pid=DONT_CARE_PID,
                         console=console if console is not None else io.StringIO())


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


def _a_warning_logged_inside_the_baggage_and_closed(telemetry: Telemetry,
                                                    entries: dict[str, str]) -> None:
    """A warning logged while the baggage holds `entries`, through the telemetry's handler.

    Attached and detached here, so no case leaves the baggage holding anything
    for the next.
    """
    carried = context.get_current()
    for key, value in entries.items():
        carried = baggage.set_baggage(key, value, context=carried)

    token = context.attach(carried)

    try:
        _a_warning_logged_through_both_and_closed(telemetry)
    finally:
        context.detach(token)


def _a_warning_logged_through_both_and_closed(telemetry: Telemetry,
                                              message: str = "dont care",
                                              extra: dict[str, Any] | None = None) -> None:
    """A warning logged through the console and the OTel handler both, then closed.

    A logger of its own rather than the root, for the reason given above.
    """
    logger = logging.getLogger("argus_telemetry_test.some_logger")
    logger.addHandler(telemetry.log_handler)
    logger.addHandler(telemetry.console_handler)

    try:
        logger.warning(message, extra=extra)
    finally:
        logger.removeHandler(telemetry.console_handler)
        logger.removeHandler(telemetry.log_handler)

    telemetry.close()


def _entered_and_left(telemetry: Telemetry,
                      raising: BaseException | None = None,
                      ending_a_span: str | None = None) -> BaseException | None:
    """The telemetry used as a `main` uses it, left normally or by `raising`.

    Returns what came out of the `with` - `None` where nothing did - so a case
    can say the exception went on past the telemetry rather than being eaten.
    """
    try:
        with telemetry:
            if ending_a_span is not None:
                telemetry.tracer_provider.get_tracer(__name__) \
                    .start_span(ending_a_span).end()
            if raising is not None:
                raise raising
    except BaseException as came_out:
        return came_out

    return None


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


def _a_span_named_anything(name: str) -> LineCheck:
    def check(line: dict[str, Any], _returned: Any) -> bool:
        """a span with the name of the one that was ended"""
        return any(
            span["name"] == name
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


def _a_record_carrying(key: str, value: str) -> LineCheck:
    def check(line: dict[str, Any], _returned: Any) -> bool:
        """a log record with the attribute the case logged it with"""
        return any(
            attribute == {"key": key, "value": {"stringValue": value}}
            for resource in line.get("resourceLogs", [])
            for scope in resource["scopeLogs"]
            for record in scope["logRecords"]
            for attribute in record.get("attributes", [])
        )

    return check


def _the_console(console: io.StringIO, says: str) -> Assertion[Any]:
    def assertion(_returned: Any) -> bool:
        written = console.getvalue()

        if says not in written:
            raise AssertionError(
                f"Expected the console to say [{says}], and it said [{written}]."
            )

        return True

    return assertion


def _the_console_never(console: io.StringIO, says: str) -> Assertion[Any]:
    def assertion(_returned: Any) -> bool:
        written = console.getvalue()

        if says in written:
            raise AssertionError(
                f"Expected the console never to say [{says}], and it said [{written}]."
            )

        return True

    return assertion


def _the_console_is_queued(telemetry: Telemetry) -> Assertion[Any]:
    def assertion(_returned: Any) -> bool:
        if not isinstance(telemetry.console_handler, QueueHandler):
            raise AssertionError(
                f"Expected the console to be written through a queue, "
                f"and its handler is a [{type(telemetry.console_handler).__name__}]."
            )

        return True

    return assertion


def _its_life_was(caplog: pytest.LogCaptureFixture,
                  expected: list[tuple[int, str]]) -> Assertion[Any]:
    """That the process's own records said exactly these, in order, each naming the service."""
    def assertion(_returned: Any) -> bool:
        own = [record for record in caplog.records if record.name == "argus_telemetry.wiring"]
        said = [(record.levelno, record.getMessage()) for record in own]
        services = {getattr(record, "service", None) for record in own}

        if said != expected or services != {DONT_CARE_SERVICE}:
            raise AssertionError(
                f"Expected the process to say {_spelled(expected)}, each naming "
                f"[{DONT_CARE_SERVICE}], and it said {_spelled(said)}, naming {services}."
            )

        return True

    return assertion


def _the_death_carried_what_was_raised(caplog: pytest.LogCaptureFixture) -> Assertion[Any]:
    def assertion(came_out: BaseException | None) -> bool:
        deaths = [record for record in caplog.records if record.levelno == logging.CRITICAL]
        carried = [record.exc_info[1] if record.exc_info else None for record in deaths]

        if came_out is None or carried != [came_out]:
            raise AssertionError(
                f"Expected the exception to go on past the telemetry and to be what "
                f"its death record carried, and [{came_out!r}] came out while the "
                f"death records carried {carried}."
            )

        return True

    return assertion


def _spelled(said: list[tuple[int, str]]) -> list[str]:
    return [f"{logging.getLevelName(level)} {message}" for level, message in said]
