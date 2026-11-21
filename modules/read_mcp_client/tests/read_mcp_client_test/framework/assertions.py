"""What this suite asserts of an offer, in more than one of its files."""

from __future__ import annotations

from argus_testkit import Assertion
from core.models import ToolDefinition


def the_tools_offered_are(expected: list[str]) -> Assertion[list[ToolDefinition]]:
    """The tools offered, by name and in order - the order being the agent's
    prompt."""
    def assertion(tools: list[ToolDefinition]) -> bool:
        names = [tool.name for tool in tools]

        if names != expected:
            raise AssertionError(f"Expected {expected} offered, and {names} were.")

        return True

    return assertion
