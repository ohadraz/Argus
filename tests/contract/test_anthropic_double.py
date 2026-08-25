from __future__ import annotations

from collections.abc import Iterator

import anthropic
import httpx
import pytest
from anthropic_double import recordings
from anthropic_double.server import DEFAULT_BASE_URL
from argus_core.anthropic_llm import MODEL, AnthropicLLMClient
from argus_core.config import Settings, get_settings
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.evidence import Evidence
from argus_core.models.hypothesis import Hypothesis

# These spend real tokens on every run. That is the point - a contract test
# that never talks to the third party is not a contract test - but it is why
# they live behind their own marker and not in `test_all`.
needs_the_real_api = pytest.mark.skipif(
    not get_settings().anthropic_api_key,
    reason="no ANTHROPIC_API_KEY: the real half of the contract cannot be checked",
)

A_MODEL_THAT_DOES_NOT_EXIST = "claude-not-a-real-model"


@pytest.fixture
def double() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=DEFAULT_BASE_URL, timeout=30.0) as control:
        control.post("/double-control/reset").raise_for_status()
        yield control
        control.post("/double-control/reset").raise_for_status()


@pytest.mark.contract
@needs_the_real_api
def test_the_real_api_still_answers_with_a_parseable_verdict() -> None:
    # Structure only. The model writes different prose every call, and a
    # contract test that asserted on wording would fail for the one reason
    # that is not a contract break.
    real = AnthropicLLMClient(get_settings())

    hypothesis = real.propose_hypothesis(an_evidence_payload())

    assert isinstance(hypothesis, Hypothesis)


@pytest.mark.contract
@pytest.mark.parametrize("recording", recordings.available())
def test_a_stored_recording_still_parses_as_a_verdict(
    double: httpx.Client, recording: str
) -> None:
    # The other half: a recording goes stale when the SDK or the schema moves
    # under it, and nothing else in the suite would notice - every integration
    # test would keep passing against a body no real server would send today.
    double.post("/double-control/seed", json={"recording": recording})
    replaying = AnthropicLLMClient(
        Settings(anthropic_api_key="", anthropic_base_url=DEFAULT_BASE_URL)
    )

    hypothesis = replaying.propose_hypothesis(an_evidence_payload())

    assert isinstance(hypothesis, Hypothesis)


@pytest.mark.contract
@needs_the_real_api
def test_a_rejected_request_raises_the_same_error_class_from_both(
    double: httpx.Client,
) -> None:
    # Not the same *request* - the double never inspects one, so it cannot
    # reject a bad model on its own. What is compared is the rejection: given
    # an equivalent refusal, does the SDK raise the same class? That is what
    # a test seeding a status on the double is entitled to assume.
    double.post("/double-control/seed", json={"status": 404})

    error_from_the_real_api = _the_error_from(
        anthropic.Anthropic(api_key=get_settings().anthropic_api_key, max_retries=0),
        model=A_MODEL_THAT_DOES_NOT_EXIST,
    )
    error_from_the_double = _the_error_from(
        anthropic.Anthropic(api_key="not-used", base_url=DEFAULT_BASE_URL, max_retries=0),
        model=MODEL,
    )

    assert type(error_from_the_double) is type(error_from_the_real_api)


def _the_error_from(client: anthropic.Anthropic, model: str) -> Exception:
    try:
        client.messages.create(
            model=model, max_tokens=8, messages=[{"role": "user", "content": "hi"}]
        )
    except Exception as error:
        return error

    raise AssertionError(f"expected {model} to be rejected, but the call succeeded")


def an_evidence_payload() -> Evidence:
    # Minimal on purpose: the contract is about shape, and a bigger prompt
    # would only cost more tokens to prove the same thing.
    return Evidence(
        incident_id=new_id(),
        alert=Alert(service="some-service", alert_name="SomeAlert"),
        metric_buckets=[],
        log_lines=[],
    )
