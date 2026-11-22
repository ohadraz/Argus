"""What it takes to reach Anthropic, as the provider's own settings say it.

The one rule across them is the grounding judge's address. A replay answers each
stand-in's calls in the order they were recorded, so the judge is reached at a
stand-in of its own wherever every agent is - and refused one where every agent
has a stand-in and it has none, since neither default is safe there.
"""

from __future__ import annotations

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_error_mentioned,
)
from llm_anthropic import AnthropicSettings

SOME_KEY = "some-key"
SOME_STAND_IN = "http://every-agent.example"
SOME_STAND_IN_FOR_THE_JUDGE = "http://the-judge.example"
# No address: the SDK's own, which is the real API.
THE_REAL_API = ""


@pytest.mark.unit
def test_the_judge_is_reached_at_its_own_address_where_one_is_set() -> None:
    # Its own, so a replay can answer the writer from one stand-in and the
    # judge from another, each in the order its own calls were recorded.
    Scenario() \
        .given(
            some_settings := AnthropicSettings(
                anthropic_api_key=SOME_KEY,
                anthropic_base_url=SOME_STAND_IN,
                judge_anthropic_base_url=SOME_STAND_IN_FOR_THE_JUDGE)
        ) \
        .when(
            lambda: some_settings.for_the_judge()
        ) \
        .then(
            _reaches(SOME_KEY, SOME_STAND_IN_FOR_THE_JUDGE)
        )


@pytest.mark.unit
def test_the_judge_reaches_the_real_api_where_every_agent_does() -> None:
    Scenario() \
        .given(
            some_settings := AnthropicSettings(anthropic_api_key=SOME_KEY,
                                               anthropic_base_url=THE_REAL_API,
                                               judge_anthropic_base_url=THE_REAL_API)
        ) \
        .when(
            lambda: some_settings.for_the_judge()
        ) \
        .then(
            _reaches(SOME_KEY, THE_REAL_API)
        )


@pytest.mark.unit
def test_a_judge_with_no_address_where_every_agent_has_a_stand_in_is_refused() -> None:
    # Neither default is safe. The writer's stand-in would serve the judge the
    # writer's recordings out of turn, or record the judge's calls into the
    # writer's scenario; the real API would spend on every write-up judged.
    Scenario() \
        .given(
            some_settings := AnthropicSettings(anthropic_api_key=SOME_KEY,
                                               anthropic_base_url=SOME_STAND_IN,
                                               judge_anthropic_base_url=THE_REAL_API)
        ) \
        .when(
            attempting(lambda: some_settings.for_the_judge())
        ) \
        .then(
            all_of(
                an_error_was_raised(ValueError),
                the_error_mentioned("JUDGE_ANTHROPIC_BASE_URL")
            )
        )


def _reaches(key: str, address: str) -> Assertion[AnthropicSettings]:
    """That the settings reach the model at `address`, under `key`."""
    def assertion(reached: AnthropicSettings) -> bool:
        if (reached.anthropic_api_key, reached.anthropic_base_url) != (key, address):
            raise AssertionError(
                f"Expected the judge to reach [{address}] with the agents' key, got "
                f"[{reached.anthropic_base_url}]"
                f"{'' if reached.anthropic_api_key == key else ' with another key'}."
            )

        return True

    return assertion
