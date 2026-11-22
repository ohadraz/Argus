"""What the Prometheus adapter is told about where it answers.

One claim: the address a deployment configures, under the variable it always
had, arrives intact. A composition root reads these settings at the top of a
process, so a variable they do not declare is a process that reads metrics
from the default rather than from where it was told.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from argus_testkit import Scenario, the_answer_was
from metrics_source.prometheus_settings import PrometheusSettings
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


@pytest.mark.unit
def test_the_address_a_deployment_configures_is_the_one_the_source_is_given(
        tmp_path: Path) -> None:
    some_base_url = "http://some-prometheus:9090"
    an_env_file = tmp_path / ".env"
    an_env_file.write_text(f"PROMETHEUS_BASE_URL={some_base_url}\n", encoding="utf-8")

    Scenario() \
        .given(
            an_env_file
        ) \
        .when(
            lambda: _settings_read_from(an_env_file).prometheus_base_url
        ) \
        .then(
            the_answer_was(some_base_url)
        )


def _settings_read_from(env_file: Path) -> PrometheusSettings:
    """The adapter's settings as read from `env_file` alone - everything else
    inherited, and nothing from the environment the suite runs in."""
    class ReadFromThatFile(PrometheusSettings):
        model_config = SettingsConfigDict(env_file=env_file)

        @classmethod
        def settings_customise_sources(cls,
                                       settings_cls: type[BaseSettings],
                                       init_settings: PydanticBaseSettingsSource,
                                       env_settings: PydanticBaseSettingsSource,
                                       dotenv_settings: PydanticBaseSettingsSource,
                                       file_secret_settings: PydanticBaseSettingsSource
                                       ) -> tuple[PydanticBaseSettingsSource, ...]:
            """What is handed over and what the file says, and never the
            process's own environment - which on a CI runner already names a
            repository, an API and more of its own, and would outrank the file."""
            return init_settings, dotenv_settings

    return ReadFromThatFile()
