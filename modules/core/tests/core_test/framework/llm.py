"""What a model said, for the suites of the clients that carry it."""

from __future__ import annotations

from core.models.turn import Turn


def a_turn_that_said(said: str) -> Turn:
    """A turn carrying words and nothing else - no tool calls, no real counts.

    The token counts are present but arbitrary: a `Turn` cannot be built
    without them, and no test using this builder is about what anything cost.
    A test that *is* about the counts states them itself.
    """
    dont_care_tokens = 1

    return Turn(
        text=said,
        tool_calls=[],
        input_tokens=dont_care_tokens,
        output_tokens=dont_care_tokens
    )
