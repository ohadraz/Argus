"""The model provider a suite reaches, built the way a process's root builds it.

No agent has a default way to reach a model: whoever assembles it hands one
over. The suites that drive an agent against the Anthropic double, and the
evals that drive one against the real API, assemble it themselves, and this is
the one place they say which provider that is - the settings decide where it
is, as they do for the worker.
"""

from __future__ import annotations

from core import LLMSettings, get_settings
from core.llm import ModelProvider
from core.llm.adapters.anthropic_adapter import AnthropicProvider


def the_configured_models() -> ModelProvider:
    """The provider the process's settings point at: the double in a suite
    that started one, the real API in an eval."""
    return AnthropicProvider(LLMSettings.of(get_settings()))
