"""What a log record carries by the time any handler writes it.

Three things happen to every record before any handler writes it:
- the incident, run and agent the work belonged to are copied off the baggage;
- any value whose name says it is a secret is blanked;
- on the console, every value the record was logged with is written after its
  message, as `key=value`.

The records are real ones, as `logging` makes them. The baggage is handed in
as a mapping, so no OTel context is attached here: whether the real baggage
reaches the filter is `test_wiring`'s question, asked through a real handler.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import pytest
from argus_core.telemetry import ARGUS_AGENT, ARGUS_INCIDENT_ID, ARGUS_RUN_ID
from argus_telemetry import ConsoleFormatter, Redacted, StampedFromBaggage
from argus_testkit import Assertion, Scenario, all_of

SOME_INCIDENT = "4f0c2a1e-5b6d-4c3e-9a8b-7d6e5f4c3b2a"
SOME_RUN = "9b7d3c2e-1a0f-4e9d-8c7b-6a5f4e3d2c1b"
SOME_AGENT = "investigator"

SOME_LOGGER = "argus_telemetry_test.some_logger"
SOME_MESSAGE = "service scaled out"

DONT_CARE_MESSAGE = "dont care"


@pytest.mark.unit
def test_a_record_written_inside_an_incident_carries_its_incident_run_and_agent() -> None:
    # Stamped from the baggage rather than passed by each call site, so a line
    # written deep inside an agent, or inside a tool call on the far side of an
    # MCP server, says whose work it was without anybody remembering to.
    Scenario() \
        .given(
            a_record := _a_record()
        ) \
        .when(
            lambda: StampedFromBaggage(baggage_now=lambda: {
                ARGUS_INCIDENT_ID: SOME_INCIDENT,
                ARGUS_RUN_ID: SOME_RUN,
                ARGUS_AGENT: SOME_AGENT
            }).filter(a_record)
        ) \
        .then(
            all_of(
                _it_carries(ARGUS_INCIDENT_ID, SOME_INCIDENT),
                _it_carries(ARGUS_RUN_ID, SOME_RUN),
                _it_carries(ARGUS_AGENT, SOME_AGENT)
            )
        )


@pytest.mark.unit
def test_a_record_written_outside_any_incident_carries_none_of_them() -> None:
    # The index's catch-up loop and the relay work for no incident. A record
    # of theirs carrying an empty incident id would be one a backend's filter
    # on that id finds and should not.
    Scenario() \
        .given(
            a_record := _a_record()
        ) \
        .when(
            lambda: StampedFromBaggage(baggage_now=lambda: {}).filter(a_record)
        ) \
        .then(
            _it_carries_none_of([ARGUS_INCIDENT_ID, ARGUS_RUN_ID, ARGUS_AGENT])
        )


@pytest.mark.unit
def test_baggage_that_is_not_argus_own_is_not_copied() -> None:
    # The baggage is anybody's to fill - a caller upstream, a library. What a
    # record carries is the three things Argus put there to be carried, and
    # nothing a stranger can make every log line repeat.
    Scenario() \
        .given(
            a_record := _a_record()
        ) \
        .when(
            lambda: StampedFromBaggage(baggage_now=lambda: {
                "some.vendor.key": "some-value"
            }).filter(a_record)
        ) \
        .then(
            _it_carries_none_of(["some.vendor.key"])
        )


@pytest.mark.unit
@pytest.mark.parametrize("secret_name", [
    "slack_token",
    "LANGFUSE_SECRET_KEY",
    "database_password",
    "anthropic_api_key",
    "Authorization"
])
def test_a_value_named_as_a_secret_is_blanked(secret_name: str) -> None:
    # By name, because a name is the one thing about a secret that can be read
    # without already knowing the secret. Any case, because settings arrive
    # spelled as an environment spells them as often as Python does.
    Scenario() \
        .given(
            a_record := _a_record(extra={secret_name: "some-secret-value"})
        ) \
        .when(
            lambda: Redacted().filter(a_record)
        ) \
        .then(
            _it_carries(secret_name, "[redacted]")
        )


@pytest.mark.unit
def test_a_value_not_named_as_a_secret_is_left_as_it_was() -> None:
    Scenario() \
        .given(
            a_record := _a_record(extra={"from_replicas": 3})
        ) \
        .when(
            lambda: Redacted().filter(a_record)
        ) \
        .then(
            _it_carries("from_replicas", 3)
        )


@pytest.mark.unit
def test_the_console_line_ends_with_every_value_logged_the_stamped_ones_first() -> None:
    # The message is the same phrase every time, so the values are what tell
    # one line from the next. Whose work it was leads, because it is what a
    # person scanning a console reads first.
    Scenario() \
        .given(
            a_record := _a_record(SOME_MESSAGE, extra={
                "from_replicas": 3,
                "to_replicas": 6,
                ARGUS_AGENT: SOME_AGENT,
                ARGUS_INCIDENT_ID: SOME_INCIDENT
            })
        ) \
        .when(
            lambda: ConsoleFormatter().format(a_record)
        ) \
        .then(
            _the_line_ends_with(
                f"INFO {SOME_LOGGER}: {SOME_MESSAGE} "
                f"{ARGUS_INCIDENT_ID}={SOME_INCIDENT} {ARGUS_AGENT}={SOME_AGENT} "
                f"from_replicas=3 to_replicas=6"
            )
        )


@pytest.mark.unit
def test_a_console_line_with_no_values_is_the_message_alone() -> None:
    Scenario() \
        .given(
            a_record := _a_record(SOME_MESSAGE)
        ) \
        .when(
            lambda: ConsoleFormatter().format(a_record)
        ) \
        .then(
            _the_line_ends_with(f"INFO {SOME_LOGGER}: {SOME_MESSAGE}")
        )


@pytest.mark.unit
def test_a_failure_is_written_below_the_line_its_values_are_on() -> None:
    # The values stay on the line with the message, where a search for the
    # message finds them, and the stack trace follows.
    Scenario() \
        .given(
            a_record := _a_record_of_a_failure(SOME_MESSAGE, extra={"from_replicas": 3})
        ) \
        .when(
            lambda: ConsoleFormatter().format(a_record)
        ) \
        .then(
            all_of(
                _the_first_line_ends_with(f"{SOME_MESSAGE} from_replicas=3"),
                _the_line_holds("ValueError: some failure")
            )
        )


def _a_record(message: str = DONT_CARE_MESSAGE,
              extra: dict[str, Any] | None = None) -> logging.LogRecord:
    """A record as a logger makes one for `logger.info(message, extra=extra)`."""
    return logging.getLogger(SOME_LOGGER).makeRecord(
        SOME_LOGGER, logging.INFO, __file__, 0, message, (), None, extra=extra
    )


def _a_record_of_a_failure(message: str, extra: dict[str, Any]) -> logging.LogRecord:
    """A record as `logger.exception` makes one, with a real exception in hand."""
    try:
        raise ValueError("some failure")
    except ValueError:
        return logging.getLogger(SOME_LOGGER).makeRecord(
            SOME_LOGGER, logging.ERROR, __file__, 0, message, (), sys.exc_info(),
            extra=extra
        )


def _it_carries(name: str, expected: Any) -> Assertion[logging.LogRecord | bool]:
    def assertion(returned: logging.LogRecord | bool) -> bool:
        actual = getattr(_handed_back(returned), name, None)

        if actual != expected:
            raise AssertionError(
                f"Expected the record to carry [{name}] as [{expected}], "
                f"and it carried [{actual}]."
            )

        return True

    return assertion


def _it_carries_none_of(names: list[str]) -> Assertion[logging.LogRecord | bool]:
    def assertion(returned: logging.LogRecord | bool) -> bool:
        record = _handed_back(returned)
        carried = {name: getattr(record, name) for name in names if hasattr(record, name)}

        if carried:
            raise AssertionError(
                f"Expected the record to carry none of {names}, and it carried {carried}."
            )

        return True

    return assertion


def _handed_back(returned: logging.LogRecord | bool) -> logging.LogRecord:
    """The record a filter returned, which is how a filter says it changed one."""
    if not isinstance(returned, logging.LogRecord):
        raise AssertionError(
            f"Expected the filter to hand the record back, and it returned [{returned}]."
        )

    return returned


def _the_line_ends_with(expected: str) -> Assertion[str]:
    def assertion(line: str) -> bool:
        if not line.endswith(expected):
            raise AssertionError(
                f"Expected the console line to end with [{expected}], and it was [{line}]."
            )

        return True

    return assertion


def _the_first_line_ends_with(expected: str) -> Assertion[str]:
    def assertion(text: str) -> bool:
        first = text.splitlines()[0]

        if not first.endswith(expected):
            raise AssertionError(
                f"Expected the first console line to end with [{expected}], "
                f"and it was [{first}]."
            )

        return True

    return assertion


def _the_line_holds(fragment: str) -> Assertion[str]:
    def assertion(text: str) -> bool:
        if fragment not in text:
            raise AssertionError(
                f"Expected the console output to hold [{fragment}], and it was [{text}]."
            )

        return True

    return assertion
