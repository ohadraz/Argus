"""Where an Argus process's traces, metrics and logs go.

Instrumented code throughout the workspace speaks the OpenTelemetry API and
nothing else, and the API does nothing until a process installs an SDK. This is
that installation, done once at the top of each process: every signal written
to disk as OTLP JSON lines, and sent on to whichever backends are configured,
and every log record written to the console as well.
"""

from telemetry.destinations import Destination, Signal, destinations_for
from telemetry.levels import apply_levels
from telemetry.records import ConsoleFormatter, Redacted, StampedFromBaggage
from telemetry.wiring import Telemetry, start_telemetry, telemetry_for

__all__ = [
    "ConsoleFormatter",
    "Destination",
    "Redacted",
    "Signal",
    "StampedFromBaggage",
    "Telemetry",
    "apply_levels",
    "destinations_for",
    "start_telemetry",
    "telemetry_for"
]
