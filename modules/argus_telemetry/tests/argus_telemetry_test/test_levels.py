"""How much a process logs, and which libraries it keeps quiet.

The root logs at the configured level. A handful of libraries log at INFO about
things a span already says, or about things nobody reads: a line per HTTP
request, a line per MCP call, a line per dashboard poll. They are held at
WARNING whatever the root is set to, so lowering the level to chase an incident
shows Argus's own detail and not theirs.

The loggers are made fresh for each case rather than taken from `logging`'s own
registry, so no case sets a level that another test then logs under.
"""

from __future__ import annotations

import logging

import pytest
from argus_telemetry import apply_levels
from argus_testkit import Assertion, Scenario

THE_ROOT = ""

SOME_LEVEL = "DEBUG"


@pytest.mark.unit
def test_the_root_logs_at_the_configured_level() -> None:
    Scenario() \
        .given(
            loggers := _FreshLoggers()
        ) \
        .when(
            lambda: apply_levels(SOME_LEVEL, logger_named=loggers)
        ) \
        .then(
            _the_level_of(loggers, THE_ROOT, is_=logging.DEBUG)
        )


@pytest.mark.unit
@pytest.mark.parametrize("library", [
    "httpx",
    "httpx2",
    "httpcore",
    "httpcore2",
    "mcp",
    "uvicorn.access"
])
def test_a_chatty_library_is_held_at_warning_whatever_the_configured_level(
    library: str
) -> None:
    Scenario() \
        .given(
            loggers := _FreshLoggers()
        ) \
        .when(
            lambda: apply_levels(SOME_LEVEL, logger_named=loggers)
        ) \
        .then(
            _the_level_of(loggers, library, is_=logging.WARNING)
        )


class _FreshLoggers:
    """Loggers by name, as `logging.getLogger` hands them out, belonging to this case alone."""

    def __init__(self) -> None:
        self.made: dict[str, logging.Logger] = {}

    def __call__(self, name: str) -> logging.Logger:
        return self.made.setdefault(name, logging.Logger(name or "root"))


def _the_level_of(loggers: _FreshLoggers, name: str, is_: int) -> Assertion[None]:
    def assertion(_returned: None) -> bool:
        logger = loggers.made.get(name)
        actual = logging.getLevelName(logger.level) if logger is not None else "never asked for"

        if logger is None or logger.level != is_:
            raise AssertionError(
                f"Expected the logger [{name or 'root'}] to be set to "
                f"[{logging.getLevelName(is_)}], and it was [{actual}]."
            )

        return True

    return assertion
