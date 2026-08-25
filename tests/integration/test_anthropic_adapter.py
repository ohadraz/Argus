from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from functools import partial
from http import HTTPStatus as HttpStatus
from typing import Any

import anthropic
import httpx
import pytest
from anthropic_double import recordings
from anthropic_double.server import DEFAULT_BASE_URL
from argus_core.anthropic_llm import (
    AnthropicLLMClient,
    MalformedVerdict,
    ModelRefused,
    VerdictTruncated,
)
from argus_core.config import Settings
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.evidence import Evidence
from argus_testkit.assertions import an_error_was_raised
from argus_testkit.scenario import Scenario, attempting

from tests.framework.assertions import (
    no_cause_was_determined,
    some_confidence_was_given,
    the_cause_was_identified_as,
    the_hypothesis_belongs_to,
)

# The recordings these tests replay, by the names they are stored under in
# modules/anthropic_double/recordings/.
A_RECORDED_FLAG_TOGGLE = "feature-flag-toggle"
A_RECORDED_UNDETERMINED_CAUSE = "no-evidence"


@pytest.fixture
def double() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=DEFAULT_BASE_URL, timeout=30.0) as control:
        control.post("/double-control/reset").raise_for_status()
        yield control
        control.post("/double-control/reset").raise_for_status()


@pytest.fixture
def client() -> AnthropicLLMClient:
    # No API key on purpose: these run from a fresh clone, and the double is
    # the reason that is possible.
    return AnthropicLLMClient(
        Settings(anthropic_api_key="", anthropic_base_url=DEFAULT_BASE_URL)
    )


@pytest.mark.integration
def test_a_recorded_verdict_becomes_a_hypothesis(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    _the_llm_verdic_is_feature_flag_cause = partial(_the_llm_verdics_is_in_recording, 
                                                    double, A_RECORDED_FLAG_TOGGLE)

    Scenario() \
        .given(
            _the_llm_verdic_is_feature_flag_cause()
        ) \
        .when(
            lambda: client.propose_hypothesis(_an_evidence_payload())
        ) \
        .then(
            the_cause_was_identified_as(CauseType.FEATURE_FLAG_TOGGLE),
            some_confidence_was_given()
        )


@pytest.mark.integration
def test_a_recorded_undetermined_verdict_carries_no_confidence(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    _the_llm_couldnt_determine_a_verdic = partial(_the_llm_verdics_is_in_recording, 
                                                  double, A_RECORDED_UNDETERMINED_CAUSE)

    Scenario() \
        .given(
            _the_llm_couldnt_determine_a_verdic()
        ) \
        .when(
            lambda: client.propose_hypothesis(_an_evidence_payload())
        ) \
        .then(
            no_cause_was_determined()
        )


@pytest.mark.integration
def test_the_hypothesis_belongs_to_the_incident_the_evidence_came_from(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    some_evidence = _an_evidence_payload()
    _the_llm_came_to_some_verdic = partial(_the_llm_verdics_is_in_recording, 
                                           double, A_RECORDED_UNDETERMINED_CAUSE)

    Scenario() \
        .given(
            _the_llm_came_to_some_verdic()
        ) \
        .when(
            lambda: client.propose_hypothesis(some_evidence)
        ) \
        .then(
            the_hypothesis_belongs_to(some_evidence.incident_id)
        )


@pytest.mark.integration
def test_a_refusal_is_not_reported_as_a_malformed_answer(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    # A refusal is a complete, well-formed response that declines.
    some_evidence = _an_evidence_payload()
    _the_llm_stopped_due_to_refusale = partial(_the_llm_stopped_due_to, 
                                               double, "refusal")


    Scenario() \
        .given(
            _the_llm_stopped_due_to_refusale()
        ) \
        .when(
            attempting(lambda: client.propose_hypothesis(some_evidence))
        ) \
        .then(
            an_error_was_raised(ModelRefused)
        )


@pytest.mark.integration
def test_a_truncated_response_is_not_reported_as_a_malformed_answer(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    some_evidence = _an_evidence_payload()
    _the_llm_stopped_due_to_max_token = partial(_the_llm_stopped_due_to, 
                                                double, "max_tokens")


    Scenario() \
        .given(
            _the_llm_stopped_due_to_max_token()
        ) \
        .when(
            attempting(lambda: client.propose_hypothesis(some_evidence))
        ) \
        .then(
            an_error_was_raised(VerdictTruncated)
        )


@pytest.mark.integration
def test_a_verdict_missing_a_required_field_is_malformed(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    # applies to the adapter. the "real" anthropic server is not expected to miss required fields.

    some_evidence = _an_evidence_payload()
    _the_llm_miss_summary_field = partial(_the_llm_miss_field, double, "summary")

    Scenario() \
        .given(
            _the_llm_miss_summary_field()
        ) \
        .when(
            attempting(lambda: client.propose_hypothesis(some_evidence))
        ) \
        .then(
            an_error_was_raised(MalformedVerdict)
        )


@pytest.mark.integration
def test_a_cause_named_at_null_confidence_is_malformed(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    some_evidence = _an_evidence_payload()
    _the_llm_miss_named_a_cause_with_null_confidence = partial(_the_llm_miss_named_a_cause_with, 
                                                               double, "confidence", None)

    Scenario() \
        .given(
            _the_llm_miss_named_a_cause_with_null_confidence()
        ) \
        .when(
            attempting(lambda: client.propose_hypothesis(some_evidence))
        ) \
        .then(
            an_error_was_raised(MalformedVerdict)
        )


@pytest.mark.integration
def test_a_rate_limit_reaches_the_caller_as_the_sdks_own_error(
    double: httpx.Client, client: AnthropicLLMClient
) -> None:
    # Not wrapped: a rate limit is a transport fact, and the SDK already has
    # the right word for it. Wrapping would only hide the retry-after header.
    some_evidence = _an_evidence_payload()
    _the_llm_hit_rate_limit = partial(_llm_returned_status, double, HttpStatus.TOO_MANY_REQUESTS)

    Scenario() \
        .given(
            _the_llm_hit_rate_limit()
        ) \
        .when(
            attempting(lambda: client.propose_hypothesis(some_evidence))
        ) \
        .then(
            an_error_was_raised(anthropic.RateLimitError)
        )


def _an_evidence_payload() -> Evidence:
    # The double answers from what the test seeded, never from what it was
    # asked, so this only has to be constructible.
    return Evidence(
        incident_id=new_id(),
        alert=Alert(service="some-service", alert_name="SomeAlert"),
        metric_buckets=[],
        log_lines=[],
    )


def _a_response_that_stopped_for(stop_reason: str) -> dict[str, Any]:
    """A real recorded response that ended before it wrote a verdict."""
    body = copy.deepcopy(recordings.load(A_RECORDED_FLAG_TOGGLE))
    body["content"] = [block for block in body["content"] if block["type"] != "text"]
    body["stop_reason"] = stop_reason
    return body


def _a_recorded_verdict_without(field: str) -> dict[str, Any]:
    """A real recorded response with one field dropped from its verdict.

    Derived from a recording rather than hand-written, so the envelope around
    the damaged verdict stays a shape Anthropic actually produced.
    """
    body = copy.deepcopy(recordings.load(A_RECORDED_FLAG_TOGGLE))
    for block in body["content"]:
        if block["type"] == "text":
            verdict = json.loads(block["text"])
            del verdict[field]
            block["text"] = json.dumps(verdict)
    return body


def _a_recorded_verdict_with(field: str, value: Any) -> dict[str, Any]:
    body = copy.deepcopy(recordings.load(A_RECORDED_FLAG_TOGGLE))
    for block in body["content"]:
        if block["type"] == "text":
            verdict = json.loads(block["text"])
            verdict[field] = value
            block["text"] = json.dumps(verdict)
    return body


def _the_llm_verdics_is_in_recording(double: httpx.Client, recording: str) -> None:
    double.post("/double-control/seed", json={"recording": recording})

def _the_llm_stopped_due_to(double: httpx.Client, reason: str) -> None:
    double.post("/double-control/seed", json={"body": _a_response_that_stopped_for(reason)})

def _the_llm_miss_field(double: httpx.Client, field: str) -> None:
    double.post("/double-control/seed", json={"body": _a_recorded_verdict_without(field)})

def _the_llm_miss_named_a_cause_with(double: httpx.Client, field: str, value: Any) -> None:
    double.post("/double-control/seed", json={"body": _a_recorded_verdict_with(field, value)})

def _llm_returned_status(double: httpx.Client, status: HttpStatus) -> None:
    double.post("/double-control/seed", json={"status": status, "repeat": None})
