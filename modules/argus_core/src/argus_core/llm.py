from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class StubLLMClient:
    """Placeholder shape other modules import against - no real completions
    in the walking-skeleton change (design.md Non-Goals)."""

    def complete(self, prompt: str) -> str:
        raise NotImplementedError("no real LLM calls in the walking-skeleton change")


def get_llm_client() -> LLMClient:
    return StubLLMClient()
