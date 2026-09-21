from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel

# How hard the model is asked to think. Anthropic's five, restated once here
# rather than spelled at each of the places that hold one: configuration reads
# it out of the environment and the adapter renders it onto a request, and
# neither may import the other - `config` pulling in an SDK would put Anthropic
# into every module that reads a setting.
#
# A `Literal` rather than a free string so that a deployment naming an effort
# that does not exist fails when its configuration is read, which is at
# startup, rather than on the first call of the first incident.
type Effort = Literal["low", "medium", "high", "xhigh", "max"]

# What an agent gets when its deployment names nothing, and the one place
# either value is written down. Here rather than in the adapter that renders
# them or the configuration that reads them: the adapter imports a vendor's
# SDK, so anything naming it drags Anthropic along, and configuration is read
# by every module there is. A plain string and a `Literal` belong to neither
# and can be named by both.
DEFAULT_MODEL: Final = "claude-opus-5"

# The API's own default, stated rather than relied on. A default that moved
# under us would change what every agent costs and how long it takes with
# nothing here mentioning it.
DEFAULT_EFFORT: Final[Effort] = "high"

# How much room an answer gets. Sixteen thousand is what every agent had
# when they shared one client, and it is the right order for an answer
# that is a short thing to say plus the calls it asks for. It is the wrong
# order for an answer that is a file: the largest in the Target Service is
# 21,484 tokens, so a cap of this size makes some fixes impossible rather
# than merely tight, and no retry can help because the same request
# overflows the same ceiling every time.
DEFAULT_MAX_OUTPUT_TOKENS: Final = 16_000

# Above this the SDK refuses a non-streaming request outright, by a rule
# of its own: it expects 128,000 tokens to take an hour, will not let a
# single response run past ten minutes, and 128000 * 600/3600 is this.
# Hardcoded there, and unmoved by the client's own timeout - so this is
# not a threshold to tune but the line where streaming stops being a
# preference and becomes the only way to ask.
LARGEST_UNSTREAMED_ANSWER: Final = 21_333


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

    model: str = DEFAULT_MODEL
    effort: Effort = DEFAULT_EFFORT
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
