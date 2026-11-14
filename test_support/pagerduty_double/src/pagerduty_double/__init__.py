"""PagerDuty as Argus reads it, with no account involved.

The fourth external party Argus stands in for, on the terms the others are: a
real HTTP server the SDK is pointed at by base URL, dev-only, excluded from test
discovery. Nothing in `oncall_source` branches on whether PagerDuty is real.

What it holds is staged whole by the case that needs it - an incident, its
alerts' keys, who acknowledged it and what was written on it - and nothing
else: a double that invented an incident would be a scenario, and a scenario
is the test's.
"""

from pagerduty_double.server import (
    DEFAULT_BASE_URL,
    DEFAULT_PORT,
    Acknowledged,
    Staged,
    app,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_PORT",
    "Acknowledged",
    "Staged",
    "app"
]
