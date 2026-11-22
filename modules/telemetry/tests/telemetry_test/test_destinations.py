"""Which backends a process sends its telemetry to, besides the files.

The general OTLP backend, which receives every signal, off until it is
configured; and whatever vendor's backend the process's root hands over beside
it (`telemetry.langfuse` says Langfuse's). Both may be on at once, and then a
trace reaches both - deliberately, so each backend holds the whole picture on
its own.

What is under test is the decision, not the sending: which signal goes where,
to which URL, carrying which headers. The URLs are the part worth pinning. The
general endpoint is a base that each signal's path is appended to, as OTel's own
`OTEL_EXPORTER_OTLP_ENDPOINT` is, and an exporter handed a URL uses it exactly
as written, so a missing path segment is a backend that answers every export
with a 404.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, the_answer_was
from core import TelemetrySettings
from telemetry import Destination, Signal, destinations_for

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
def test_a_vendors_backend_handed_over_is_sent_to_after_the_general_one() -> None:
    # The overlap is the point rather than an accident: each backend holds a
    # walk's whole trace, so neither is half a picture of an incident. The
    # general backend first, then the vendor's, which is the order a reader of
    # the configuration meets them in.
    some_endpoint = "http://collector.example:4318"
    some_vendors_traces = Destination(signal=Signal.TRACES,
                                      endpoint="https://some-vendor.example/traces",
                                      headers={})

    Scenario() \
        .given(
            settings_naming_a_general_backend := _settings(
                otel_exporter_otlp_endpoint=some_endpoint
            )
        ) \
        .when(
            lambda: [
                destination.endpoint
                for destination in destinations_for(settings_naming_a_general_backend,
                                                    also=[some_vendors_traces])
                if destination.signal is Signal.TRACES
            ]
        ) \
        .then(
            the_answer_was([
                f"{some_endpoint}/v1/traces",
                some_vendors_traces.endpoint
            ])
        )


def _settings(otel_exporter_otlp_endpoint: str = "",
              otel_exporter_otlp_headers: str = "") -> TelemetrySettings:
    return TelemetrySettings(
        telemetry_directory=DONT_CARE_DIRECTORY,
        otel_exporter_otlp_endpoint=otel_exporter_otlp_endpoint,
        otel_exporter_otlp_headers=otel_exporter_otlp_headers,
        log_level="INFO"
    )
