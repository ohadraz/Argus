"""Which backends a process sends its telemetry to, besides the files.

Two, each off until it is configured: a general OTLP backend, which receives
every signal, and Langfuse, which receives traces alone. Both may be on at once,
and then a trace reaches both - deliberately, so each backend holds the whole
picture on its own.

What is under test is the decision, not the sending: which signal goes where,
to which URL, carrying which headers. The URLs are the part worth pinning. The
general endpoint is a base that each signal's path is appended to, as OTel's own
`OTEL_EXPORTER_OTLP_ENDPOINT` is; Langfuse publishes one fixed path for traces;
and an exporter handed a URL uses it exactly as written, so a missing path
segment is a backend that answers every export with a 404.
"""

from __future__ import annotations

import base64

import pytest
from argus_core import TelemetrySettings
from argus_telemetry import Destination, Signal, destinations_for
from argus_testkit import Scenario, the_answer_was

DONT_CARE_DIRECTORY = "telemetry"


@pytest.mark.unit
def test_nothing_configured_sends_nothing_anywhere() -> None:
    # The default, and the one every fresh checkout runs with. The files are
    # written regardless; this is about everything else, and everything else
    # is nothing.
    Scenario() \
        .given(
            settings_naming_no_backend := _settings()
        ) \
        .when(
            lambda: destinations_for(settings_naming_no_backend)
        ) \
        .then(
            the_answer_was([])
        )


@pytest.mark.unit
def test_a_general_backend_receives_every_signal_at_its_own_path() -> None:
    # One base URL, three signals, each at the path OTLP/HTTP gives it. The
    # headers are OTel's own format - comma-separated pairs - and arrive with
    # every signal, since they are where the backend's credential goes.
    some_endpoint = "http://collector.example:4318"
    some_headers = {"x-api-key": "some-key", "x-team": "argus"}

    Scenario() \
        .given(
            settings_naming_a_general_backend := _settings(
                otel_exporter_otlp_endpoint=some_endpoint,
                otel_exporter_otlp_headers="x-api-key=some-key,x-team=argus"
            )
        ) \
        .when(
            lambda: destinations_for(settings_naming_a_general_backend)
        ) \
        .then(
            the_answer_was([
                Destination(signal=Signal.TRACES,
                            endpoint=f"{some_endpoint}/v1/traces",
                            headers=some_headers),
                Destination(signal=Signal.METRICS,
                            endpoint=f"{some_endpoint}/v1/metrics",
                            headers=some_headers),
                Destination(signal=Signal.LOGS,
                            endpoint=f"{some_endpoint}/v1/logs",
                            headers=some_headers)
            ])
        )


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
            settings_naming_langfuse := _settings(
                langfuse_base_url=some_base_url,
                langfuse_public_key=some_public_key,
                langfuse_secret_key=some_secret_key
            )
        ) \
        .when(
            lambda: destinations_for(settings_naming_langfuse)
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
            settings_naming_langfuse_without_its_secret := _settings(
                langfuse_base_url="https://cloud.langfuse.example",
                langfuse_public_key="pk-lf-some-public-key"
            )
        ) \
        .when(
            lambda: destinations_for(settings_naming_langfuse_without_its_secret)
        ) \
        .then(
            the_answer_was([])
        )


@pytest.mark.unit
def test_both_backends_configured_send_traces_to_each() -> None:
    # The overlap is the point rather than an accident: each backend holds a
    # walk's whole trace, so neither is half a picture of an incident.
    some_endpoint = "http://collector.example:4318"
    some_base_url = "https://cloud.langfuse.example"

    Scenario() \
        .given(
            settings_naming_both := _settings(
                otel_exporter_otlp_endpoint=some_endpoint,
                langfuse_base_url=some_base_url,
                langfuse_public_key="pk-lf-dont-care",
                langfuse_secret_key="sk-lf-dont-care"
            )
        ) \
        .when(
            lambda: [
                destination.endpoint
                for destination in destinations_for(settings_naming_both)
                if destination.signal is Signal.TRACES
            ]
        ) \
        .then(
            the_answer_was([
                f"{some_endpoint}/v1/traces",
                f"{some_base_url}/api/public/otel/v1/traces"
            ])
        )


def _settings(otel_exporter_otlp_endpoint: str = "",
              otel_exporter_otlp_headers: str = "",
              langfuse_base_url: str = "",
              langfuse_public_key: str = "",
              langfuse_secret_key: str = "") -> TelemetrySettings:
    return TelemetrySettings(
        telemetry_directory=DONT_CARE_DIRECTORY,
        otel_exporter_otlp_endpoint=otel_exporter_otlp_endpoint,
        otel_exporter_otlp_headers=otel_exporter_otlp_headers,
        langfuse_base_url=langfuse_base_url,
        langfuse_public_key=langfuse_public_key,
        langfuse_secret_key=langfuse_secret_key,
        log_level="INFO"
    )
