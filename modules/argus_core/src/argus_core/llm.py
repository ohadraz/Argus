from __future__ import annotations

from typing import Protocol

from argus_core.models.evidence import Evidence
from argus_core.models.hypothesis import Hypothesis


class LLMClient(Protocol):
    """What Argus needs from a reasoning model, stated in Argus's own terms.

    `propose_hypotheses(evidence) -> list[Hypothesis]`, not
    `complete(prompt) -> str`. A string-in/string-out seam would push prompt
    wording and response parsing into every caller, and would let a test double
    satisfy the type while saying nothing about whether the real adapter works.
    This shape can only be implemented by something that actually produces a
    verdict.

    A list because the same evidence can support more than one explanation, and
    which of them is right is settled by trying them rather than by the model
    picking one. Best first; never empty - a model that identified no cause
    says so in the one explanation it returns.
    """

    def propose_hypotheses(self, evidence: Evidence) -> list[Hypothesis]: ...


def get_llm_client() -> LLMClient:
    """The client agents get by default.

    Imported lazily so that holding an `LLMClient` type does not drag the
    Anthropic SDK - and the settings it reads at construction - into a module
    that only ever injects a double.
    """
    from argus_core.anthropic_llm import AnthropicLLMClient

    return AnthropicLLMClient()
