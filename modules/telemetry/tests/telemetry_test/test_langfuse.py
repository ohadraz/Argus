"""Langfuse, as a backend a process's root may hand its telemetry beside the
general one.

Traces alone, at the one fixed path Langfuse publishes for them, under its key
pair as Basic auth - and nothing at all unless all three of its values are
given. An exporter handed a URL uses it exactly as written, so the path is the
part worth pinning.
"""

from __future__ import annotations

import base64

import pytest
from argus_testkit import Scenario, the_answer_was
from telemetry import Destination, Signal
from telemetry.langfuse import LangfuseSettings, to_langfuse


@pytest.mark.unit
def test_langfuse_receives_traces_at_its_otel_path_with_its_key_pair_as_basic_auth() -> None:
    # Langfuse reads traces and nothing else, at the one path it publishes for
    # them, and authenticates a project by its key pair sent as Basic auth.
    some_base_url = "https://cloud.langfuse.example"
    some_public_key = "pk-lf-some-public-key"
    some_secret_key = "sk-lf-some-secret-key"
    the_key_pair_as_basic_auth = "Basic " + base64.b64encode(
        f"{some_public_key}:{some_secret_key}".encode()
    ).decode()

    Scenario() \
        .given(
            settings_naming_langfuse := LangfuseSettings(
                langfuse_base_url=some_base_url,
                langfuse_public_key=some_public_key,
                langfuse_secret_key=some_secret_key
            )
        ) \
        .when(
            lambda: to_langfuse(settings_naming_langfuse)
        ) \
        .then(
            the_answer_was([
                Destination(signal=Signal.TRACES,
                            endpoint=f"{some_base_url}/api/public/otel/v1/traces",
                            headers={"Authorization": the_key_pair_as_basic_auth})
            ])
        )


@pytest.mark.unit
def test_langfuse_with_any_of_its_three_values_missing_receives_nothing() -> None:
    # An address without a key pair is a project nobody can authenticate to.
    # Sending to it anyway would fail at every export for the life of the
    # process; sending nothing is the configuration's honest reading.
    Scenario() \
        .given(
            settings_naming_langfuse_without_its_secret := LangfuseSettings(
                langfuse_base_url="https://cloud.langfuse.example",
                langfuse_public_key="pk-lf-some-public-key",
                langfuse_secret_key=""
            )
        ) \
        .when(
            lambda: to_langfuse(settings_naming_langfuse_without_its_secret)
        ) \
        .then(
            the_answer_was([])
        )
