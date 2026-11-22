"""Langfuse, as a backend a process may send its traces to.

The one place in Argus that knows Langfuse: its settings, the path it reads
OTLP traces at, and how its key pair is sent. A process's root reads the
settings and hands what this says to `start_telemetry` beside the general
backend; nothing else names the vendor.

A decision and nothing else, as `destinations` is: values in, values out.
"""

from __future__ import annotations

import base64
from typing import Final

from core import AdapterSettings
from pydantic import Field

from telemetry.destinations import Destination, Signal

# Where Langfuse reads OTLP traces, below whatever base URL its region or a
# self-hosted instance answers on. Langfuse's own path, and the only signal it
# publishes one for.
LANGFUSE_TRACES_PATH: Final = "/api/public/otel/v1/traces"

# How a key pair is sent to Langfuse: HTTP Basic auth, the public key as the
# user and the secret key as the password. The header and scheme are HTTP's.
AUTHORIZATION_HEADER: Final = "Authorization"
BASIC_SCHEME: Final = "Basic"


class LangfuseSettings(AdapterSettings):
    """Where Langfuse is, and the key pair it is sent traces under.

    Three values because that is what Langfuse issues: an address and a key
    pair, sent as Basic auth. All three or nothing; two of them name a project
    nobody can authenticate to, so a partial configuration sends nothing rather
    than failing at every export. Empty by default, which is a deployment
    keeping its traces to itself.
    """

    langfuse_base_url: str = Field(default="")
    langfuse_public_key: str = Field(default="")
    langfuse_secret_key: str = Field(default="")


def to_langfuse(settings: LangfuseSettings) -> list[Destination]:
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
