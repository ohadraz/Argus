"""How much a process logs, and which libraries it keeps quiet.

The root logs at the configured level. A few libraries log at INFO about things
a span already says, or that nobody reads: a line per HTTP request, a line per
MCP call, a line per dashboard poll. They are held at WARNING whatever the root
says, so lowering the level to chase an incident shows Argus's own detail and
not theirs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final

# Held at WARNING, by logger name. httpx and httpcore under both their names,
# since the workspace installs both generations; `mcp` for its line per tool
# call; `uvicorn.access` for its line per request, which on the dashboard is
# one every two seconds per open page.
HELD_AT_WARNING: Final = (
    "httpx",
    "httpx2",
    "httpcore",
    "httpcore2",
    "mcp",
    "uvicorn.access"
)

# What `logging.getLogger` calls the root when asked by name.
_THE_ROOT: Final = ""


def apply_levels(level: str,
                 logger_named: Callable[[str], logging.Logger] = logging.getLogger) -> None:
    """Sets the root to `level`, by the stdlib's name for it, and the chatty libraries to WARNING.

    `logger_named` defaults to `logging`'s own registry, which is the whole
    process's; it is a parameter so that a case can hand in loggers of its own
    and set no level any other test logs under.
    """
    logger_named(_THE_ROOT).setLevel(level)

    for library in HELD_AT_WARNING:
        logger_named(library).setLevel(logging.WARNING)
