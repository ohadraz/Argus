"""What a log record carries by the time a handler writes it.

Two filters and a formatter, each installed on every handler a process has,
so that the console and `logs.jsonl` never disagree about what a record said.

- `Redacted` blanks any value whose name says it is a secret.
- `StampedFromBaggage` copies the incident, run and agent off the OTel baggage.
  A call site never passes them; the walk, and a tool call carrying the walk's
  context into a server, already put them there.
- `ConsoleFormatter` writes every value a record was logged with after its
  message, as `key=value`, the stamped ones first. `logs.jsonl` needs no
  formatter: the OTel handler exports each value as an attribute of its own.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Final

from argus_core.telemetry import ARGUS_AGENT, ARGUS_INCIDENT_ID, ARGUS_RUN_ID
from opentelemetry import baggage

# What a secret's value is written as, wherever it would have been written.
REDACTED: Final = "[redacted]"

# What a value's name has to contain, in any case, to be taken for a secret.
_SECRET_NAMES: Final = ("token", "secret", "password", "api_key", "authorization")

# The baggage entries a record is stamped with, in the order the console
# writes them: whose incident, which run of it, which agent.
_STAMPED: Final = (ARGUS_INCIDENT_ID, ARGUS_RUN_ID, ARGUS_AGENT)

# Every attribute a record has before anybody passes `extra`, plus the two a
# formatter adds - which is to say, every attribute that is not a value the
# record was logged with.
_A_RECORDS_OWN: Final = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None))
) | {"message", "asctime"}

_CONSOLE_FORMAT: Final = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class StampedFromBaggage(logging.Filter):
    """Copies the incident, run and agent off the baggage onto each record.

    `baggage_now` reads the current baggage, and defaults to OTel's own; it is
    a parameter so that a case can say what the baggage holds without
    attaching a context to say it.
    """

    def __init__(self,
                 baggage_now: Callable[[], Mapping[str, object]] = baggage.get_all) -> None:
        super().__init__()
        self._baggage_now = baggage_now

    def filter(self, record: logging.LogRecord) -> logging.LogRecord:
        carried = self._baggage_now()

        for key in _STAMPED:
            if key in carried:
                setattr(record, key, carried[key])

        return record


class Redacted(logging.Filter):
    """Blanks every value logged under a name that says it is a secret.

    By name alone. A value is the one thing about a secret that cannot be
    recognised without already knowing it, and message text is never scanned
    because a message here is a fixed phrase with no values in it.
    """

    def filter(self, record: logging.LogRecord) -> logging.LogRecord:
        for name in _values_of(record):
            if any(secret in name.lower() for secret in _SECRET_NAMES):
                setattr(record, name, REDACTED)

        return record


class ConsoleFormatter(logging.Formatter):
    """A record's line, then every value it was logged with as `key=value`.

    The values sit on the message's own line, where a search for the message
    finds them, and a stack trace follows below them.
    """

    def __init__(self) -> None:
        super().__init__(_CONSOLE_FORMAT)

    def formatMessage(self, record: logging.LogRecord) -> str:
        line = super().formatMessage(record)
        values = _values_of(record)
        ordered = [key for key in _STAMPED if key in values] \
            + [key for key in values if key not in _STAMPED]

        return " ".join([line, *(f"{key}={values[key]}" for key in ordered)])


def _values_of(record: logging.LogRecord) -> dict[str, object]:
    """The values a record was logged with: everything `extra` and the stamp added."""
    return {key: value for key, value in vars(record).items() if key not in _A_RECORDS_OWN}
