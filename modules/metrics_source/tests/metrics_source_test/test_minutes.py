"""What a metrics source is told about where it answers.

One claim: the slice is taken out of the deployment's whole configuration, and
the address arrives intact. A composition root builds it at the top of a
process, so a setting the whole does not declare is a process that fails to
start rather than one that reads metrics from nowhere.
"""

from __future__ import annotations

import pytest
from argus_core import Settings
from argus_testkit import Scenario, the_answer_was
from metrics_source.minutes import MetricsSettings


@pytest.mark.unit
def test_the_address_a_deployment_configures_is_the_one_the_source_is_given() -> None:
    some_base_url = "http://some-prometheus:9090"

    Scenario() \
        .given(
            some_settings := Settings(prometheus_base_url=some_base_url)
        ) \
        .when(
            lambda: MetricsSettings.of(some_settings).prometheus_base_url
        ) \
        .then(
            the_answer_was(some_base_url)
        )
