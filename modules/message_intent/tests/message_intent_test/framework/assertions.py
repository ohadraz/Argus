"""The claims both of the intent reader's suites make about what the asking was
handed."""

from __future__ import annotations

from argus_testkit import Assertion, Kept
from core.llm import LLMClient
from core.models import Ask, Turn

from message_intent_test.framework.builders import Asked


def asked_through[T](asked: Kept[Asked[T]], model: LLMClient, *,
                     attempts: int) -> Assertion[object]:
    """That the asking was handed the model given, by identity, and `attempts`."""
    def assertion(_: object) -> bool:
        handed = asked.only()
        if handed.llm is not model or handed.attempts != attempts:
            raise AssertionError(
                f"Expected the asking handed the model given and {attempts} attempts; it was "
                f"handed {handed.llm} and {handed.attempts}.")

        return True

    return assertion


def the_model_was_shown[T](asked: Kept[Asked[T]], words: str) -> Assertion[object]:
    """That the question handed to the asking says `words`, exactly."""
    def assertion(_: object) -> bool:
        shown = "\n".join(entry.text for entry in asked.only().transcript
                          if isinstance(entry, Ask))

        if words not in shown:
            raise AssertionError(
                f"Expected the model to be shown [{words}] exactly, and it was shown "
                f"[{shown}]."
            )

        return True

    return assertion


def the_tools_offered_were[T](asked: Kept[Asked[T]], expected: list[str]) -> Assertion[object]:
    """That the asking was handed these tools, by name, and no others."""
    def assertion(_: object) -> bool:
        names = [tool.name for tool in asked.only().tools]

        if names != expected:
            raise AssertionError(f"Expected the model offered {expected}, got {names}.")

        return True

    return assertion


def reads[T](asked: Kept[Asked[T]], turn: Turn, expected: T | None) -> Assertion[object]:
    """That the reader handed to the asking reads `turn` as `expected`."""
    def assertion(_: object) -> bool:
        read = asked.only().read(turn)

        if read != expected:
            raise AssertionError(f"Expected [{turn}] read as [{expected}], got [{read}].")

        return True

    return assertion
