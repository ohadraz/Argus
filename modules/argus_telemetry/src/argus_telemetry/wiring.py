"""Installing OpenTelemetry's SDK in one process, and what it writes to.

Every signal goes to disk, always, through OTel's own OTLP JSON file exporters:
one directory per run of a process, one file per signal. Each configured
backend receives what `destinations_for` says it should, over OTLP/HTTP, beside
the files rather than instead of them.

Two halves, for the reason most composition roots have two. `telemetry_for`
builds the providers and hands them back without touching anything global, so
it can be built and inspected as often as a test likes. `start_telemetry` is the
one call a process's `main` makes: it builds, then installs the result as the
process's own - the global providers the OTel API reports to, and a handler on
the root logger.

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
from pathlib import Path
from types import FrameType
from typing import Final

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

# What a process is stopped by: SIGTERM, and on Windows - which cannot deliver
# SIGTERM to another process - the CTRL_BREAK a group is sent instead. A
# statement rather than an expression, which is the form a type checker reads
# a platform from.
if sys.platform == "win32":
    _STOP_SIGNALS: Final = (signal.SIGTERM, signal.SIGBREAK)
else:
    _STOP_SIGNALS: Final = (signal.SIGTERM,)


class Telemetry:
    """One process's providers, where they write, and how to put them down.

    `run_directory` is `None` when the directory could not be made, which is a
    process writing no files rather than a process that failed to start.
    """

    def __init__(self,
                 tracer_provider: TracerProvider,
                 meter_provider: MeterProvider,
                 logger_provider: LoggerProvider,
                 run_directory: Path | None) -> None:
        self.tracer_provider = tracer_provider
        self.meter_provider = meter_provider
        self.logger_provider = logger_provider
        self.run_directory = run_directory
        self.log_handler = LoggingHandler(logger_provider=logger_provider)
        self.log_handler.addFilter(_not_the_sdks_own)

    def close(self) -> None:
        """Flushes everything still batched, then stops every exporter.

        Called on the way out of a process, so what it collected in its last
        seconds - which is exactly what a crash leaves a person wanting - is on
        disk rather than in a queue that died with it.
        """
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        self.logger_provider.shutdown()


def telemetry_for(settings: TelemetrySettings,
                  service: str,
                  started_at: datetime | None = None,
                  pid: int | None = None) -> Telemetry:
    """Builds one process's providers, writing to disk and to every backend.

    Installs nothing - see `start_telemetry`. `started_at` and `pid` name the
    run directory and default to now and this process; they are parameters so
    that the name can be asserted. Now by the wall clock, not the stack's: the
    SDK stamps every span from the wall, and a directory named by a simulated
    clock would be named for a moment its own contents never mention.
    """
    run_directory = _a_run_directory(
        settings, service,
        started_at if started_at is not None else datetime.now(UTC),
        pid if pid is not None else os.getpid()
    )
    destinations = destinations_for(settings)
    resource = Resource.create({SERVICE_NAME: service})

    return Telemetry(
        tracer_provider=_a_tracer_provider(resource, run_directory, destinations),
        meter_provider=_a_meter_provider(resource, run_directory, destinations),
        logger_provider=_a_logger_provider(resource, run_directory, destinations),
        run_directory=run_directory
    )


def start_telemetry(settings: TelemetrySettings, service: str) -> Telemetry:
    """Builds this process's telemetry and makes it the process's own.

    The global providers are what every instrumented call in the workspace
    reports to through the OTel API, and the handler on the root logger is
    what carries each `logging` record into `logs.jsonl` with the trace it was
    written in. Console logging is left exactly as it was.

    Once per process, at the top of `main`, and closed as that `main` ends.
    OTel refuses to replace a global provider once set, so a second call would
    build providers nothing reports to.

    And closed when the process is stopped, which is not `main` ending: a stop
    signal's default ends a process where it stands, past every `finally`. See
    `_closed_when_stopped`.
    """
    telemetry = telemetry_for(settings, service)

    trace.set_tracer_provider(telemetry.tracer_provider)
    metrics.set_meter_provider(telemetry.meter_provider)
    set_logger_provider(telemetry.logger_provider)
    logging.getLogger().addHandler(telemetry.log_handler)
    _closed_when_stopped(telemetry)

    return telemetry


def _closed_when_stopped(telemetry: Telemetry) -> None:
    """Flushes on a stop signal, then lets the signal do what it would have.

    Only the flush is added. The process still ends where it stands, exactly
    as the signal's default would end it - nothing else in it learns it was
    stopped, so a walk interrupted mid-step is left for its lease to expire,
    as it always was, rather than unwound by an exception it never expected.

    A server whose framework handles the same signal replaces this while it
    serves, and puts it back when it stops; either way the batch is flushed.
    """
    def flush_then_stop(signal_number: int, _frame: FrameType | None) -> None:
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
    except OSError as unwritable:
        _logger.warning("telemetry is not being written to disk: %s could not be "
                        "made (%s)", run_directory, unwritable)

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
