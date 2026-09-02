"""The dispatcher under test, and the calls the model makes to it.

Shared because every tool test needs both, and each names only the channel it
is about. The incident these are built around is one incident: the same onset
and the same alert everywhere, so that a window in one test file means what it
means in the next.
"""

from __future__ import annotations

from unittest.mock import Mock, create_autospec

from agent_investigator.retrieval import fetch_change_events, fetch_logs, fetch_metrics
from agent_investigator.tools import Dispatcher
from argus_core.models.turn import ToolCall

# The incident every tool test is about. The onset sits five minutes before
# the alert, which is the ordinary shape: something started, and a rule
# noticed it afterwards.
AN_ONSET = "2026-08-29T22:15:00Z"
AN_ALERT_TIME = "2026-08-29T22:20:00Z"
A_SERVICE = "io-shop"


def a_dispatcher(reads_metrics: Mock | None = None,
                 reads_logs: Mock | None = None,
                 reads_changes: Mock | None = None,
                 alert_time: str | None = AN_ALERT_TIME) -> Dispatcher:
    """A dispatcher whose unnamed channels answer with nothing.

    Each test names the one channel it is about; the others must not be the
    reason it passes, and a real reader would reach for a server that is not
    running.

    The parameters are named for what the channel does rather than for the
    function they replace, so they cannot shadow the imports they are specced
    against.

    `alert_time` is a parameter rather than a constant because its absence is a
    real case - an alert that never said when it started - and it changes where
    a default log window ends.
    """
    return Dispatcher(
        service=A_SERVICE,
        onset=AN_ONSET,
        alert_time=alert_time,
        fetch_metrics=reads_metrics or create_autospec(fetch_metrics, return_value=[]),
        fetch_logs=reads_logs or create_autospec(fetch_logs, return_value=[]),
        fetch_change_events=reads_changes or create_autospec(fetch_change_events,
                                                             return_value=[])
    )


def a_call_to(name: str, call_id: str = "toolu_dont_care", **arguments: str) -> ToolCall:
    """One call the model made, with whatever arguments the test is about.

    The id defaults because most tests do not care what it is - only that
    whatever it was comes back on the result.
    """
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))
