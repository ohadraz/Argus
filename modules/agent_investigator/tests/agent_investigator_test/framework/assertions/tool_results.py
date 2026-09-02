"""What is true of a tool result whatever channel produced it.

Only the two that every channel owes the model: that the result answers the
call it was made for, and that a result standing in for a failure says so.
Anything true of one channel alone stays private to the file that tests it.
"""

from __future__ import annotations

from argus_core.models.transcript import ToolResult
from argus_testkit import Assertion


def the_result_answers(call_id: str) -> Assertion[ToolResult]:
    """Without the id the result answers nothing and the model waits for a
    reply it will never recognise."""
    def assertion(result: ToolResult) -> bool:
        if result.call_id != call_id:
            raise AssertionError(
                f"Expected the result to answer [{call_id}], got [{result.call_id}]."
            )

        return True

    return assertion


def the_result_failed() -> Assertion[ToolResult]:
    """Marked as something to recover from rather than as evidence."""
    def assertion(result: ToolResult) -> bool:
        if not result.failed:
            raise AssertionError(
                f"Expected the result to be a failure, and it was not: [{result.content}]."
            )

        return True

    return assertion
