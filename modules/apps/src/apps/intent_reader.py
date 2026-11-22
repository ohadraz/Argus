"""The Intent Reader's root: what understands people's words in an incident's
thread (spec §7.5a).

`python -m apps.intent_reader`. What a message means and what it calls for is
`message_intent`'s; this decides who answers its model calls and which chat
platform it asks about people, and starts the loop.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Final

from chat_platform.slack import SlackSettings, slack_from
from core import (
    Connections,
    DatabaseSettings,
    Settings,
    TelemetrySettings,
    get_settings,
    open_pool,
)
from core.llm import build_llm_client
from core.llm.adapters.anthropic_adapter import AnthropicProvider, AnthropicSettings
from core.models import ModelPolicy
from message_intent.watching import ModelFor, watch
from telemetry import start_telemetry
from telemetry.langfuse import LangfuseSettings, to_langfuse

logger = logging.getLogger(__name__)

# What this process is called in its telemetry.
_SERVICE: Final = "argus-intent"


def the_model_for(settings: Settings, model_settings: AnthropicSettings) -> ModelFor:
    """How this process gets a client for one incident: over the provider its
    settings point at, under the Intent Reader's own model - the provider's
    to name - and its effort, which is Argus's.

    The one place this process names a model vendor. The provider is built here
    and handed down as the port. Its adapter is imported at the top, as every
    adapter a root builds is: nothing imports a root, so the SDK it loads is
    loaded for this process alone.
    """
    return partial(build_llm_client,
                   AnthropicProvider(model_settings),
                   policy=ModelPolicy(model=model_settings.intent_model,
                                      effort=settings.intent_effort))


def main() -> None:
    """The process itself: a pool, a model, a chat platform, then watch
    until killed.

    An intent reader with no chat platform is not started at all: nothing would
    ever be written for it to understand, and a process idling on a record it
    can never act on is a process somebody has to wonder about.
    """
    settings = get_settings()

    with start_telemetry(TelemetrySettings.of(settings), _SERVICE,
                         also=to_langfuse(LangfuseSettings())):
        platform = slack_from(SlackSettings())

        if platform is None:
            logger.warning("no chat platform configured")
            return

        with open_pool(DatabaseSettings.of(settings)) as pool:
            connections: Connections = pool.connection

            logger.info("intent reader started")

            watch(connections, the_model_for(settings, AnthropicSettings()), platform.person_named,
                  pause=settings.intent_poll_seconds)


if __name__ == "__main__":
    main()
