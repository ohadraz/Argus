"""Which backends a process sends its telemetry to, besides its own files.

A decision and nothing else: values in, values out. What a destination is sent
over is the wiring's business, and keeping the two apart is what lets the
decision - which signal, which URL, which headers - be pinned down without a
network to send to.
"""

from __future__ import annotations

import base64
from enum import StrEnum
from typing import Final
from urllib.parse import unquote

from argus_core import TelemetrySettings
from pydantic import BaseModel, ConfigDict

# Where Langfuse reads OTLP traces, below whatever base URL its region or a
# self-hosted instance answers on. Langfuse's own path, and the only signal it
# publishes one for.
LANGFUSE_TRACES_PATH: Final = "/api/public/otel/v1/traces"

# How a key pair is sent to Langfuse: HTTP Basic auth, the public key as the
# user and the secret key as the password. The header and scheme are HTTP's.
AUTHORIZATION_HEADER: Final = "Authorization"
BASIC_SCHEME: Final = "Basic"

# OTel's format for `OTEL_EXPORTER_OTLP_HEADERS`: pairs separated by commas, a
# key separated from its value by an equals sign, values URL-encoded.
_PAIR_SEPARATOR: Final = ","
_KEY_VALUE_SEPARATOR: Final = "="


class Signal(StrEnum):
    """The three kinds of telemetry, spelled as OTLP/HTTP's paths spell them.

    The spelling is load-bearing: a general backend receives each signal at
    `<endpoint>/v1/<signal>`, so the value here is a path segment as well as a
    name.
    """

    TRACES = "traces"
    METRICS = "metrics"
    LOGS = "logs"


class Destination(BaseModel):
    """One signal, sent to one URL with these headers.

    The URL is complete. An OTLP exporter handed an endpoint uses it exactly as
    written, so a destination naming a base and leaving the path to someone
    else is a backend that answers every export with a 404.
    """

    model_config = ConfigDict(frozen=True)

    signal: Signal
    endpoint: str
    headers: dict[str, str]


def destinations_for(settings: TelemetrySettings) -> list[Destination]:
    """Every backend this configuration names, one destination per signal sent.

    The general backend first and Langfuse after it, which is the order a
    reader of the settings meets them in. Both may be configured, and then a
    trace goes to each - deliberately, so that each holds a walk's whole trace
    rather than half of one.
    """
    return _the_general_backend(settings) + _langfuse(settings)


def _the_general_backend(settings: TelemetrySettings) -> list[Destination]:
    """All three signals, each at the path OTLP/HTTP gives it below the base."""
    if not settings.otel_exporter_otlp_endpoint:
        return []

    base = settings.otel_exporter_otlp_endpoint
    headers = _headers_from(settings.otel_exporter_otlp_headers)

    return [
        Destination(signal=signal, endpoint=f"{base}/v1/{signal}", headers=headers)
        for signal in Signal
    ]


def _langfuse(settings: TelemetrySettings) -> list[Destination]:
    """Traces alone, and only when all three of Langfuse's values are given.

    Anything less names a project nobody can authenticate to, and sending to it
    anyway would fail at every export for the life of the process.
    """
    named = (
        settings.langfuse_base_url,
        settings.langfuse_public_key,
        settings.langfuse_secret_key
    )

    if not all(named):
        return []

    key_pair = f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}"
    encoded = base64.b64encode(key_pair.encode()).decode()

    return [
        Destination(
            signal=Signal.TRACES,
            endpoint=f"{settings.langfuse_base_url}{LANGFUSE_TRACES_PATH}",
            headers={AUTHORIZATION_HEADER: f"{BASIC_SCHEME} {encoded}"}
        )
    ]


def _headers_from(configured: str) -> dict[str, str]:
    """`key=value,key=value`, as OTel spells headers in its environment variable.

    A pair with no equals sign is skipped rather than refused: the setting is
    read once at startup, and a process that would not start over a header
    typed wrong is telemetry participating in the work.
    """
    headers: dict[str, str] = {}

    for pair in configured.split(_PAIR_SEPARATOR):
        key, separator, value = pair.partition(_KEY_VALUE_SEPARATOR)

        if separator and key.strip():
            headers[key.strip()] = unquote(value.strip())

    return headers
