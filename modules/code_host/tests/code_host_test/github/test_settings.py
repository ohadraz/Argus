"""What GitHub's settings refuse to start on: the name the service's source
paths went by before they said whose paths they are.

Spelled in GitHub's namespace, so GitHub's settings refuse it - and every
process that reads the paths under their new name reads a repository through
this adapter. Read from a `.env` written for the case, because a name in a
deployment's file is the claim.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_error_mentioned,
)
from code_host.github import GitHubReadSettings, GitHubSettings
from code_host.github.settings import GitHubRepositorySettings
from pydantic import ValidationError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# The environment variable the service's source paths were read from, and the
# one they are read from now - spelled out rather than imported, because the
# names a deployment's `.env` holds are the claim.
THE_RETIRED_NAME = "GITHUB_SOURCE_PATHS"
THE_NAME_IT_BECAME = "SERVICE_SOURCE_PATHS"


@pytest.mark.unit
@pytest.mark.parametrize("held", [pytest.param("src", id="some-paths"),
                                  pytest.param("", id="empty")])
@pytest.mark.parametrize("reading", [pytest.param(GitHubReadSettings, id="read"),
                                     pytest.param(GitHubSettings, id="write")])
def test_an_environment_still_naming_the_retired_source_paths_is_refused(
    tmp_path: Path, held: str, reading: type[GitHubRepositorySettings]
) -> None:
    # A name nothing declares is ignored, so a `.env` kept from before the
    # rename would start on the whole repository and change what Code-Fix reads
    # without a word. Refused at the start instead, naming what to rename it to;
    # empty too, since it still says the deployment meant to set this.
    an_env_file = tmp_path / ".env"
    an_env_file.write_text(f"{THE_RETIRED_NAME}={held}\n", encoding="utf-8")

    Scenario() \
        .given(an_env_file) \
        .when(attempting(lambda: _settings_read_from(reading, an_env_file))) \
        .then(all_of(
            an_error_was_raised(ValidationError),
            the_error_mentioned(THE_NAME_IT_BECAME)
        ))


@pytest.mark.unit
def test_an_environment_not_naming_it_starts(tmp_path: Path) -> None:
    some_repository = "some-owner/some-repository"
    an_env_file = tmp_path / ".env"
    an_env_file.write_text(f"GITHUB_REPOSITORY={some_repository}\n", encoding="utf-8")

    Scenario() \
        .given(an_env_file) \
        .when(lambda: _settings_read_from(GitHubReadSettings, an_env_file)) \
        .then(_it_reads(some_repository))


def _settings_read_from(reading: type[GitHubRepositorySettings],
                        env_file: Path) -> GitHubRepositorySettings:
    """One tier's settings as read from `env_file` alone - every validator the
    tier has, and nothing from the environment the suite runs in."""
    from_that_file = type("ReadFromThatFile", (reading,), {
        "model_config": SettingsConfigDict(env_file=env_file),
        "settings_customise_sources": classmethod(_the_file_alone)
    })
    read: GitHubRepositorySettings = from_that_file()

    return read


def _the_file_alone(cls: type[BaseSettings],
                    settings_cls: type[BaseSettings],
                    init_settings: PydanticBaseSettingsSource,
                    env_settings: PydanticBaseSettingsSource,
                    dotenv_settings: PydanticBaseSettingsSource,
                    file_secret_settings: PydanticBaseSettingsSource
                    ) -> tuple[PydanticBaseSettingsSource, ...]:
    """What is handed over and what the file says, and never the process's own
    environment - which on a CI runner already names a repository, an API and
    more of its own, and would outrank the file."""
    return init_settings, dotenv_settings


def _it_reads(repository: str) -> Assertion[GitHubRepositorySettings]:
    """That the settings read the repository the file names."""
    def assertion(read: GitHubRepositorySettings) -> bool:
        if read.github_repository != repository:
            raise AssertionError(
                f"Expected the repository [{repository}], got [{read.github_repository}].")

        return True

    return assertion
