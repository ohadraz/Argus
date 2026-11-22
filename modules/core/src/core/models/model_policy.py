from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel


class Reasoning(StrEnum):
    """How hard the model is asked to think, on Argus's own scale.

    Argus's words rather than a vendor's: each provider's adapter says how its
    own levels sit on this scale, so a deployment answered by another provider
    configures the same five and is never refused a level only one vendor
    spells. Five because five are offered today and two of them have been
    measured against each other; a scale that dropped one would leave an
    experiment nobody could repeat.

    Ordered, lowest first. `low`, `medium` and `high` read as they always did,
    so a deployment naming one of those loads unchanged, and a pooled eval
    sample stays in the pool it was taken for.

    An enum rather than a free string so that a deployment naming a level
    that does not exist fails when its configuration is read, which is at
    startup, rather than on the first call of the first incident.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    HIGHER = "higher"
    HIGHEST = "highest"


# How hard an agent is asked to think when its deployment names nothing, and
# the one place it is written down. Stated rather than left to a provider's own
# default. A default that moved under us would change what every agent costs
# and how long it takes with nothing here mentioning it.
#
# There is no default model beside it. A model is named in one provider's
# catalogue, so its defaults are that provider's settings', and every agent's
# policy names its own.
DEFAULT_EFFORT: Final = Reasoning.HIGH

# How much room an answer gets. Sixteen thousand is what every agent had
# when they shared one client, and it is the right order for an answer
# that is a short thing to say plus the calls it asks for. It is the wrong
# order for an answer that is a file: the largest in the Target Service,
# `monthly_statement.py`, is 21,593 tokens, so a cap of this size makes some
# fixes impossible rather than merely tight, and no retry can help because
# the same request overflows the same ceiling every time.
DEFAULT_MAX_OUTPUT_TOKENS: Final = 16_000


class ModelPolicy(BaseModel):
    """Which model answers one agent, and how hard it is asked to think.

    Per agent, because the agents differ by more than their prompts. The
    postmortem is a single-shot piece of prose with every figure already
    measured and no tools to explore; Code-Fix is agentic coding whose answers
    are whole files. One effort level across both is a setting that is wrong
    for at least one of them, and which one it is wrong for is not knowable
    from here.

    Carried as a value rather than read from configuration where it is used.
    What an agent's policy is belongs to whoever assembles that agent, and a
    client that re-read the environment could answer two turns of one
    conversation as two different models.

    Bound when the client is built, not passed per call. A loop has no
    business choosing how hard to think, any more than it has business holding
    a client - the seam it talks through stays `(transcript, tools) -> Turn`,
    and the choice sits with the composition root that already knows which
    agent it is assembling.
    """

    # Required: a model is a name in the answering provider's catalogue, and a
    # default here would be a vendor's name in a kernel that names none.
    model: str
    effort: Reasoning = DEFAULT_EFFORT
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    # What this agent is told about itself, once, ahead of every incident it
    # ever handles: what it is, what its tools are for, what ends the
    # conversation. It sits beside the model and the effort because it is the
    # same kind of fact - a property of the agent rather than of the incident -
    # and it is bound in the same place, by whoever assembles that agent.
    #
    # It is sent as the request's `system` rather than inside the first
    # message, which buys two things. Caching is a prefix match rendered
    # `tools` then `system` then `messages`, so standing text held in
    # `messages[0]` puts the first varying byte a few hundred tokens in and
    # every incident pays full price for words nobody has edited since they
    # were written; held here, the prefix up to it is byte-identical for every
    # incident this agent will ever see. And an operator's instructions stop
    # sharing a channel with the evidence they are used to judge.
    #
    # Empty means an agent with nothing standing to say, and that is a real
    # answer rather than an unset one: a brief written for the sake of having
    # one would buy a write premium against a prefix nothing needed.
    brief: str = ""
    # Whether a turn may carry more than one tool call. An agent whose one tool
    # ends the conversation has no use for a second call beside the first, and
    # one that arrived anyway was a placeholder submission refused at the price
    # of a whole turn. Off by default, because the agents that read evidence
    # ask for several things at once on purpose.
    one_tool_call_per_turn: bool = False
