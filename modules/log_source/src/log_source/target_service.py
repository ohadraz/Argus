"""The service's logs, as the demo Target Service serves them: one route, a
JSON list of lines - and the only module that knows the route or the address.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

import httpx2
from core import AdapterSettings

from log_source.port import LogSource

# The route the service serves its log lines at, as the service spells it.
LOGS_PATH: Final = "/logs"

# How long one read of the service's logs may take, as every other read the read
# tier makes of somebody else's API is bounded.
LOGS_REQUEST_TIMEOUT_SECONDS: Final = 10.0


class TargetServiceLogSettings(AdapterSettings):
    """Where the service Argus is watching answers from.

    One field: an address is decided once, where the process starts, and what
    is read from it - how much, over which window - is the read tier's to say
    per call.
    """

    target_service_url: str = "http://localhost:8080"


HttpGet = Callable[..., httpx2.Response]


def target_service_logs(settings: TargetServiceLogSettings,
                        get: HttpGet = httpx2.get) -> LogSource:
    """The real log fetcher, aimed at the service this deployment watches.

    A factory rather than a function taking the address, so that what the
    tools are handed stays the no-argument `LogSource` a test can stand in for
    with a lambda. The address is bound once, where the server is built; `get`
    is where a test puts the service.

    A body that is not a list of lines raises `ValueError` rather than being
    handed on: everything past the port takes what it is handed for the lines
    the service wrote.
    """
    def fetch() -> list[str]:
        url = f"{settings.target_service_url}{LOGS_PATH}"
        response = get(url, timeout=LOGS_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()

        return _the_lines_in(response.json(), url)

    return fetch


def _the_lines_in(body: Any, url: str) -> list[str]:
    """`body` as the lines it is, or the refusal that it is not lines."""
    if not isinstance(body, list) or not all(isinstance(line, str) for line in body):
        raise ValueError(f"the logs at [{url}] are not a list of lines: {body!r:.200}")

    lines: list[str] = body

    return lines
