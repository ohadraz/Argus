"""Installing OpenTelemetry's SDK in one process, and what it writes to.

Every signal goes to disk, always, through OTel's own OTLP JSON file exporters:
one directory per run of a process, one file per signal. Each configured
backend receives what `destinations_for` says it should, over OTLP/HTTP, beside
the files rather than instead of them.

Two halves, for the reason most composition roots have two. `telemetry_for`
builds the providers and the log handlers and hands them back without touching
anything global, so a test can build one and inspect it - and closes it after,
since the console's writer thread runs until `close()`. `start_telemetry` is
the one call a process's `main` makes: it builds, then installs the result as
the process's own - the global providers the OTel API reports to, both handlers
on the root logger, and the levels.

The logs half of the SDK is still experimental in Python and lives in
underscore modules (`opentelemetry.sdk._logs`, `..._log_exporter`). They are the
vendor's published surface for the signal, not anybody's private names, and
this is the only module in the workspace that imports them.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from datetime import UTC, datetime
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from queue import SimpleQueue
from types import FrameType, TracebackType
from typing import Final, TextIO

from argus_core import TelemetrySettings
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.json.file import FileMetricExporter, FileSpanExporter
from opentelemetry.exporter.otlp.json.file._log_exporter import FileLogExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from argus_telemetry.destinations import Destination, Signal, destinations_for
from argus_telemetry.levels import apply_levels
from argus_telemetry.records import ConsoleFormatter, Redacted, StampedFromBaggage

_logger = logging.getLogger(__name__)

# What a run directory is named by: when the process started, in UTC, then its
# pid. Compact rather than ISO, because a colon is not a character every
# filesystem will put in a name.
_RUN_STARTED_FORMAT: Final = "%Y%m%dT%H%M%SZ"

# One file per signal, named for it.
TRACES_FILE: Final = "traces.jsonl"
METRICS_FILE: Final = "metrics.jsonl"
LOGS_FILE: Final = "logs.jsonl"

# The SDK's own loggers, whose records the log bridge does not export. An
# exporter reports its failures through `logging`, so a failing log export
# exported in turn would be handed straight back to the exporter that failed.
_THE_SDKS_OWN_LOGGERS: Final = "opentelemetry"

# A process's first and last lines, and the value they name it by.
_STARTED: Final = "service started"
_STOPPED: Final = "service stopped"
_DIED: Final = "service died"
_SERVICE_KEY: Final = "service"

# What leaves a `main` because somebody asked it to, rather than because it
# failed: a return is not an exception at all, and these two are the others.
_STOPPED_ON_PURPOSE: Final = (SystemExit, KeyboardInterrupt)

# What a process is stopped by: SIGTERM, and on Windows - which cannot deliver
# SIGTERM to another process - the CTRL_BREAK a group is sent instead. A
# statement rather than an expression, which is the form a type checker reads
# a platform from.
if sys.platform == "win32":
    _STOP_SIGNALS: Final = (signal.SIGTERM, signal.SIGBREAK)
else:
    _STOP_SIGNALS: Final = (signal.SIGTERM,)


class Telemetry:
    """One process's providers, its two log handlers, and how to put them down.

    `run_directory` is `None` when the directory could not be made, which is a
    process writing no files rather than a process that failed to start.

    Two handlers, each carrying the same two filters, so the console and
    `logs.jsonl` never disagree about what a record said:
    - `log_handler` hands each record to OTel's log pipeline, on the thread
      that logged. That thread is the only one that knows the record's span,
      and the handler already only hands the record to a batch, so it does
      not block.
    - `console_handler` formats each line on the thread that logged and
      queues it. A thread of its own writes it to `console`, so a walk never
      waits on a pipe nobody is reading.
    """

    def __init__(self,
                 service: str,
                 tracer_provider: TracerProvider,
                 meter_provider: MeterProvider,
                 logger_provider: LoggerProvider,
                 run_directory: Path | None,
                 console: TextIO) -> None:
        self.service = service
        self.tracer_provider = tracer_provider
        self.meter_provider = meter_provider
        self.logger_provider = logger_provider
        self.run_directory = run_directory

        self.log_handler = LoggingHandler(logger_provider=logger_provider)
        self.log_handler.addFilter(_not_the_sdks_own)

        lines: SimpleQueue[logging.LogRecord] = SimpleQueue()
        self.console_handler = QueueHandler(lines)
        self.console_handler.setFormatter(ConsoleFormatter())
        self._console_writer = QueueListener(lines, logging.StreamHandler(console))
        self._console_writer.start()

        for handler in (self.log_handler, self.console_handler):
            handler.addFilter(Redacted())
            handler.addFilter(StampedFromBaggage())

    def __enter__(self) -> Telemetry:
        """What a `main` runs inside: the process's first line is that it started."""
        _logger.info(_STARTED, extra={_SERVICE_KEY: self.service})

        return self

    def __exit__(self,
                 kind: type[BaseException] | None,
                 raised: BaseException | None,
                 traceback: TracebackType | None) -> None:
        """The process's last line, then everything written out.

        Stopped on purpose - returning, `sys.exit`, Ctrl+C - is stopping. Any
        other exception reaching here has reached the top of the process, so
        it is the CRITICAL every process has at most one of, with its stack
        trace; it is not suppressed, and the process still dies of it.
        """
        if raised is None or isinstance(raised, _STOPPED_ON_PURPOSE):
            _logger.info(_STOPPED, extra={_SERVICE_KEY: self.service})
        else:
            _logger.critical(_DIED, exc_info=raised, extra={_SERVICE_KEY: self.service})

        self.close()

    def close(self) -> None:
        """Writes out every queued line, flushes everything batched, then stops.

        Called on the way out of a process, so what it collected in its last
        seconds - which is exactly what a crash leaves a person wanting - is on
        disk and on the console rather than in a queue that died with it.
        """
        self._console_writer.stop()
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        self.logger_provider.shutdown()


def telemetry_for(settings: TelemetrySettings,
                  service: str,
                  started_at: datetime | None = None,
                  pid: int | None = None,
                  console: TextIO | None = None) -> Telemetry:
    """Builds one process's providers and log handlers, writing to disk and to every backend.

    Installs nothing global - see `start_telemetry` - but starts the console's
    writer thread, which `close()` stops. `started_at` and `pid` name the
    run directory and default to now and this process; they are parameters so
    that the name can be asserted. Now by the wall clock, not the stack's: the
    SDK stamps every span from the wall, and a directory named by a simulated
    clock would be named for a moment its own contents never mention.

    `console` is where log lines are written for a person watching, and
    defaults to standard error; a parameter so that what was written can be
    read back.
    """
    run_directory = _a_run_directory(
        settings, service,
        started_at if started_at is not None else datetime.now(UTC),
        pid if pid is not None else os.getpid()
    )
    destinations = destinations_for(settings)
    resource = Resource.create({SERVICE_NAME: service})

    return Telemetry(
        service=service,
        tracer_provider=_a_tracer_provider(resource, run_directory, destinations),
        meter_provider=_a_meter_provider(resource, run_directory, destinations),
        logger_provider=_a_logger_provider(resource, run_directory, destinations),
        run_directory=run_directory,
        console=console if console is not None else sys.stderr
    )


def start_telemetry(settings: TelemetrySettings, service: str) -> Telemetry:
    """Builds this process's telemetry and makes it the process's own.

    The global providers are what every instrumented call in the workspace
    reports to through the OTel API. The two handlers on the root logger carry
    each `logging` record to `logs.jsonl`, with the trace it was written in,
    and to the console. The root's level is the settings' own, and the chatty
    libraries are held at WARNING (`apply_levels`). Nothing else in a process
    configures logging.

    Once per process, at the top of `main`, as the `with` the rest of `main`
    runs inside - which is what says the process started, stopped or died, and
    closes it as `main` ends. OTel refuses to replace a global provider once
    set, so a second call would build providers nothing reports to.

    And closed when the process is stopped, which is not `main` ending: a stop
    signal's default ends a process where it stands, past every `finally`. See
    `_closed_when_stopped`.
    """
    telemetry = telemetry_for(settings, service)

    trace.set_tracer_provider(telemetry.tracer_provider)
    metrics.set_meter_provider(telemetry.meter_provider)
    set_logger_provider(telemetry.logger_provider)
    apply_levels(settings.log_level)
    logging.getLogger().addHandler(telemetry.log_handler)
    logging.getLogger().addHandler(telemetry.console_handler)
    _closed_when_stopped(telemetry)

    return telemetry


def _closed_when_stopped(telemetry: Telemetry) -> None:
    """Flushes on a stop signal, then lets the signal do what it would have.

    Only the "service stopped" line and the flush are added. The process still
    ends where it stands, exactly as the signal's default would end it -
    nothing else in it learns it was stopped, so a walk interrupted mid-step is
    left for its lease to expire, rather than unwound by an exception it never
    expected.

    A server whose framework handles the same signal replaces this while it
    serves, and puts it back when it stops; either way the batch is flushed.
    """
    def flush_then_stop(signal_number: int, _frame: FrameType | None) -> None:
        _logger.info(_STOPPED, extra={_SERVICE_KEY: telemetry.service})
        telemetry.close()
        signal.signal(signal_number, signal.SIG_DFL)
        signal.raise_signal(signal_number)

    for stop in _STOP_SIGNALS:
        signal.signal(stop, flush_then_stop)


def _a_run_directory(settings: TelemetrySettings,
                     service: str,
                     started_at: datetime,
                     pid: int) -> Path | None:
    """This run's directory, made - or `None`, said once, where it cannot be.

    Telemetry is evidence about the work and never a participant in it, so an
    unwritable directory costs the files and nothing else: the backends still
    receive what they would have, and the process starts.
    """
    run_name = f"{started_at.astimezone(UTC).strftime(_RUN_STARTED_FORMAT)}-{pid}"
    run_directory = Path(settings.telemetry_directory) / service / run_name

    try:
        run_directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        _logger.warning("telemetry not written to disk", exc_info=True,
                        extra={"directory": str(run_directory)})

        return None

    return run_directory


def _a_tracer_provider(resource: Resource,
                       run_directory: Path | None,
                       destinations: list[Destination]) -> TracerProvider:
    provider = TracerProvider(resource=resource)

    if run_directory is not None:
        provider.add_span_processor(
            BatchSpanProcessor(FileSpanExporter(run_directory / TRACES_FILE))
        )

    for destination in _sent(Signal.TRACES, destinations):
        provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=destination.endpoint, headers=destination.headers)
        ))

    return provider


def _a_meter_provider(resource: Resource,
                      run_directory: Path | None,
                      destinations: list[Destination]) -> MeterProvider:
    readers: list[MetricReader] = []

    if run_directory is not None:
        readers.append(
            PeriodicExportingMetricReader(FileMetricExporter(run_directory / METRICS_FILE))
        )

    readers.extend(
        PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=destination.endpoint, headers=destination.headers)
        )
        for destination in _sent(Signal.METRICS, destinations)
    )

    return MeterProvider(resource=resource, metric_readers=readers)


def _a_logger_provider(resource: Resource,
                       run_directory: Path | None,
                       destinations: list[Destination]) -> LoggerProvider:
    provider = LoggerProvider(resource=resource)

    if run_directory is not None:
        provider.add_log_record_processor(
            BatchLogRecordProcessor(FileLogExporter(run_directory / LOGS_FILE))
        )

    for destination in _sent(Signal.LOGS, destinations):
        provider.add_log_record_processor(BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=destination.endpoint, headers=destination.headers)
        ))

    return provider


def _sent(signal: Signal, destinations: list[Destination]) -> list[Destination]:
    return [destination for destination in destinations if destination.signal is signal]


def _not_the_sdks_own(record: logging.LogRecord) -> bool:
    """Whether a record may be exported - every record but the SDK's own."""
    return not (
        record.name == _THE_SDKS_OWN_LOGGERS
        or record.name.startswith(f"{_THE_SDKS_OWN_LOGGERS}.")
    )
