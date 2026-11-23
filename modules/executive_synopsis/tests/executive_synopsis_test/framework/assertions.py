"""How the grounding judge was built for the overview.

The overview's conversation hands the judge what to judge by, as the
postmortem's does, and a reader of a failure is told what it was built with
and what was expected.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from argus_testkit import Assertion
from core.llm import LLMClient

from executive_synopsis_test.framework.builders import AGrounding


def built_with(grounding: AGrounding, *, judge: LLMClient, rows_holding: Iterable[str],
               scope: Sequence[str], incident_id: str, logger: str,
               logged_as: str) -> Assertion[object]:
    """That the grounding was built once: with the judge given, by identity,
    rows holding each of `rows_holding`, and the rest exactly as given."""
    def assertion(_: object) -> bool:
        built = grounding.built.only()
        missing = sorted(set(rows_holding) - built.rows)
        wanted = (tuple(scope), incident_id, logger, logged_as)
        got = (tuple(built.scope), built.incident_id, built.logger, built.logged_as)
        if built.judge is not judge or missing or got != wanted:
            raise AssertionError(
                f"Expected the grounding built with {judge}, its rows holding "
                f"{sorted(rows_holding)}, and {wanted}; got {built.judge}, rows "
                f"{sorted(built.rows)}, and {got}.")

        return True

    return assertion
