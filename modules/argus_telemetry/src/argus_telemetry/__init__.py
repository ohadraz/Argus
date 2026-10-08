"""Where an Argus process's traces, metrics and logs go.

Instrumented code throughout the workspace speaks the OpenTelemetry API and
nothing else, and the API does nothing until a process installs an SDK. This is
that installation, done once at the top of each process: every signal written
to disk as OTLP JSON lines, and sent on to whichever backends are configured.
"""

from argus_telemetry.destinations import Destination, Signal, destinations_for
from argus_telemetry.wiring import Telemetry, start_telemetry, telemetry_for

__all__ = [
    "Destination",
    "Signal",
    "Telemetry",
    "destinations_for",
    "start_telemetry",
    "telemetry_for"
]
