"""Which model answers an agent, and how hard it is asked to think.

Three fields and one rule between them, but the rule is the whole reason this
is a type rather than three loose arguments: an effort that does not exist
must fail when the configuration is read, at startup, and not on the first
call of the first incident - by which point an agent has been assembled, a
walk has been claimed, and the thing that fails is an investigation somebody
was waiting on.

The defaults matter as much as the validation. A deployment naming none of
these gets what every agent got when there was one answer for all of them, so
adding the choice cannot quietly change what an unconfigured deployment does.
"""

from __future__ import annotations

import pytest
from argus_core.models.model_policy import (
    DEFAULT_EFFORT,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    LARGEST_UNSTREAMED_ANSWER,
    ModelPolicy,
)
from pydantic import ValidationError


@pytest.mark.unit
def test_an_effort_the_model_does_not_offer_is_refused() -> None:
    # The reason this is a `Literal` and not a string. An effort nobody
    # implements is a request the API rejects, and the useful moment to find
    # that out is when the configuration is read rather than partway through
    # the first incident of the day.
    with pytest.raises(ValidationError, match="effort"):
        ModelPolicy(effort="exhaustive")  # type: ignore[arg-type]


@pytest.mark.unit
def test_a_policy_nobody_configured_asks_what_every_agent_used_to_ask() -> None:
    # Per-agent policy arrived after a single shared answer, and it must not
    # have moved the answer on its way in: a deployment that names nothing is
    # a deployment nothing changed for.
    asked_of = ModelPolicy()

    assert asked_of.model == DEFAULT_MODEL
    assert asked_of.effort == DEFAULT_EFFORT
    assert asked_of.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS


@pytest.mark.unit
def test_the_default_answer_fits_in_one_response() -> None:
    # The default has to sit under the line where the SDK refuses to send a
    # non-streaming request, because most agents answer with a short verdict
    # and streaming every one of them would take on the harder-to-read
    # failure mode for nothing. Code-Fix is the exception and says so by
    # configuring its own.
    assert DEFAULT_MAX_OUTPUT_TOKENS <= LARGEST_UNSTREAMED_ANSWER


@pytest.mark.unit
def test_every_effort_the_model_offers_is_accepted() -> None:
    # The other side of the rejection above, and the one that would fail
    # silently: a `Literal` missing a level the API supports is a level no
    # deployment can select, and nothing would say so except a configuration
    # that refused to load.
    for effort in ("low", "medium", "high", "xhigh", "max"):
        assert ModelPolicy(effort=effort).effort == effort  # type: ignore[arg-type]
