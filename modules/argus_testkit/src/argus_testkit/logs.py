"""What a test can say about the log records the code under test wrote.

A log line is a fixed phrase and the values it was logged with (the `extra`),
so a line is asserted as both: exactly one record from that logger, at that
level, saying that phrase, carrying those values - and, where the code logged a
failure, carrying the exception it failed with.

Read off anything with a `records` list, which pytest's `caplog` fixture is.
A protocol rather than pytest's own type, so this module installs nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Protocol

from argus_testkit.assertions import Assertion


class Captured(Protocol):
    """Whatever kept the records - pytest's `caplog`, in practice."""

    @property
    def records(self) -> list[logging.LogRecord]: ...


# What an absent value reads as, so a record missing a value is told apart from
# one that carried `None`.
_ABSENT = "<absent>"


def one_record_was_logged(captured: Captured,
                          logger: str,
                          level: int,
                          message: str,
                          values: Mapping[str, object] | None = None,
                          failure: type[BaseException] | None = None) -> Assertion[Any]:
    """That exactly one record from `logger`, at `level`, said `message`.

    And that it carried each of `values` as an attribute, and - where `failure`
    is given - the exception it was logged with was one. Values it carried
    beyond those are not this assertion's business.
    """
    expected_values = dict(values or {})

    def assertion(_returned: Any) -> bool:
        said = [
            record for record in captured.records
            if record.name == logger and record.levelno == level
            and record.getMessage() == message
        ]

        if len(said) != 1:
            raise AssertionError(
                f"Expected one [{logging.getLevelName(level)}] record from [{logger}] "
                f"saying [{message}], and there were {len(said)} among "
                f"{_spelled(captured.records)}."
            )

        record = said[0]
        carried = {name: getattr(record, name, _ABSENT) for name in expected_values}

        if carried != expected_values:
            raise AssertionError(
                f"Expected the record saying [{message}] to carry {expected_values}, "
                f"and it carried {carried}."
            )

        raised = record.exc_info[1] if record.exc_info else None

        if failure is not None and not isinstance(raised, failure):
            raise AssertionError(
                f"Expected the record saying [{message}] to carry a "
                f"[{failure.__name__}], and it carried [{raised!r}]."
            )

        return True

    return assertion


def _spelled(records: list[logging.LogRecord]) -> list[str]:
    return [
        f"{record.levelname} {record.name}: {record.getMessage()}" for record in records
    ]
