from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from argus_core.llm import LLMClient, get_llm_client
from argus_core.models.evidence import Evidence
from argus_core.models.hypothesis import Hypothesis

HypothesisProposer = Callable[[Evidence], list[Hypothesis]]


@lru_cache(maxsize=1)
def _llm_client() -> LLMClient:
    """The one client the whole process shares.

    Built on first use rather than at import: constructing it reads settings
    and opens a connection pool, and a module that only ever injects a double
    - every unit test of the loop - must not pay for either.
    """
    return get_llm_client()


def propose_hypotheses(evidence: Evidence) -> list[Hypothesis]:
    """Asks the model what caused the incident this evidence was gathered for.

    A module-level function rather than the client object itself, so the
    loop's seam is one call with one argument, and so a test can
    `create_autospec` it against a real public name instead of a Protocol.

    Answers with every explanation the evidence supports, best first, because
    which one is right is settled by trying them rather than by the model
    choosing. Never empty: a model that found no cause says so, in one.
    """
    return _llm_client().propose_hypotheses(evidence)
