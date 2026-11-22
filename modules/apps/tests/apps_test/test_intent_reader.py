"""Who answers the Intent Reader's model calls, as its root chooses.

The one place that process names a model vendor. What a message means is
`message_intent`'s, and tested there.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.intent_reader import the_model_for
from argus_testkit import Assertion, Scenario
from core import Settings, get_settings
from core.models import ModelPolicy, Reasoning
from llm_anthropic import AnthropicProvider, AnthropicSettings

# Where this process's model is reached, and which model and effort the Intent
# Reader asks - none of them the defaults, so a binding that ignored the
# settings could not pass by agreeing with them.
SOME_ADDRESS = "http://intent-reader.invalid"
SOME_MODEL = "claude-haiku-4-5"
SOME_EFFORT = Reasoning.LOW


@pytest.mark.unit
def test_the_model_is_reached_where_the_settings_say_under_the_intent_readers_policy() -> None:
    # The one place this process chooses who answers. Read off the binding,
    # because that is the only place it can be seen: a client built from the
    # wrong address or under the wrong model answers in the same shape.
    some_model_settings = AnthropicSettings(anthropic_api_key="",
                                            anthropic_base_url=SOME_ADDRESS,
                                            intent_model=SOME_MODEL)

    Scenario() \
        .given(
            the_process_settings := _settings_asking_with(SOME_EFFORT)
        ) \
        .when(lambda: the_model_for(the_process_settings, some_model_settings)) \
        .then(_built_over(AnthropicProvider(some_model_settings),
                          ModelPolicy(model=SOME_MODEL, effort=SOME_EFFORT)))


def _settings_asking_with(effort: Reasoning) -> Settings:
    """The process's settings, asking the Intent Reader's model with `effort`."""
    return get_settings().model_copy(update={"intent_effort": effort})


def _built_over(provider: AnthropicProvider, policy: ModelPolicy) -> Assertion[Any]:
    """That the binding builds each client over `provider`, under `policy`."""
    def assertion(binding: Any) -> bool:
        reached = next(iter(getattr(binding, "args", ())), None)
        asked_under = getattr(binding, "keywords", {}).get("policy")

        if reached != provider or asked_under != policy:
            # By address alone: the settings carry the key.
            raise AssertionError(
                f"Expected clients built over the provider at "
                f"[{provider.settings.anthropic_base_url}] under [{policy}], got one at "
                f"[{getattr(getattr(reached, 'settings', None), 'anthropic_base_url', None)}] "
                f"under [{asked_under}]."
            )

        return True

    return assertion
