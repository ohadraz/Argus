"""What a configuration must agree with itself about, and what one process may know.

Two questions, and they are not the same one asked twice. `Settings` is the
whole of Argus's own environment, and the relationships across it - the windows
that have to admit each other - are checked in one place because no individual
field can check them. A slice is what a single consumer is handed out of that
whole, beside a vendor's settings where it reads one of theirs, and the question
there is not what it holds but what it cannot name. What a vendor needs is its
adapter's settings, tested in that adapter's suite.
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
    the_answer_was,
    the_error_mentioned,
)
from core.config import (
    AdapterSettings,
    DatabaseSettings,
    ReadMcpEndpoint,
    Settings,
    SettingsSlice,
    TelemetrySettings,
)
from pydantic import ValidationError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# The environment variable the service's source paths are read from - spelled
# out rather than imported, because the name a deployment's `.env` holds is the
# claim.
THE_SOURCE_PATHS = "SERVICE_SOURCE_PATHS"

# What a slice built from two settings that both declare one of its fields is
# refused with - its own words, since a missing field is refused as a
# `ValueError` naming the same field.
THE_REFUSAL_OF_A_FIELD_DECLARED_TWICE = "is configured by each of"


@pytest.mark.unit
def test_a_max_log_window_narrower_than_the_derived_window_is_rejected() -> None:
    # The ceiling has to admit the window the server derives for itself, or
    # `get_log_lines` hands out a 40-minute derived window while refusing a
    # 40-minute explicit one.
    Scenario() \
        .given(
            some_lookback_minutes := 30,
            some_lookahead_minutes := 10,
            too_narrow_max_window := 30 + 10 - 1,
            dont_care_metrics_window_minutes := 360
        ) \
        .when(
            attempting(
                lambda: Settings(
                    log_initial_lookback_minutes=some_lookback_minutes,
                    log_initial_lookahead_minutes=some_lookahead_minutes,
                    log_max_window_minutes=too_narrow_max_window,
                    metrics_window_minutes=dont_care_metrics_window_minutes
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("log_max_window_minutes")
            )
        )


@pytest.mark.unit
def test_a_metrics_window_narrower_than_the_max_log_window_is_rejected() -> None:
    # Metrics exist to locate an onset the log budget may not reach. A metrics
    # window no wider than the logs' can only confirm what the logs showed.
    Scenario() \
        .given(
            some_max_log_window_minutes := 180,
            some_lookback_minutes := 30,
            some_lookahead_minutes := 10,
            too_narrow_metrics_window := 180 - 1
        ) \
        .when(
            attempting(
                lambda: Settings(
                    log_initial_lookback_minutes=some_lookback_minutes,
                    log_initial_lookahead_minutes=some_lookahead_minutes,
                    log_max_window_minutes=some_max_log_window_minutes,
                    metrics_window_minutes=too_narrow_metrics_window
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("metrics_window_minutes")
            )
        )


@pytest.mark.unit
def test_a_max_log_window_exactly_matching_the_derived_window_is_accepted() -> None:
    # The boundary the rejection above is drawn at. Equal is admitted: the
    # derived window fits, exactly, and nothing was withheld.
    Scenario() \
        .given(
            some_lookback_minutes := 30,
            some_lookahead_minutes := 10,
            max_window_exactly_the_derived_window := 30 + 10,
            dont_care_metrics_window_minutes := 360
        ) \
        .when(
            lambda: Settings(
                log_initial_lookback_minutes=some_lookback_minutes,
                log_initial_lookahead_minutes=some_lookahead_minutes,
                log_max_window_minutes=max_window_exactly_the_derived_window,
                metrics_window_minutes=dont_care_metrics_window_minutes
            )
        ) \
        .then(
            _it_kept("log_max_window_minutes",
                     max_window_exactly_the_derived_window)
        )


@pytest.mark.unit
def test_a_candidate_budget_below_one_is_rejected() -> None:
    # A verdict always names at least its best explanation, so a budget of
    # zero describes an investigation whose answer is thrown away - and a walk
    # with nothing to walk, which the graph's traversal budget is derived from.
    Scenario() \
        .given(
            a_budget_that_keeps_nothing := 0
        ) \
        .when(
            attempting(
                lambda: Settings(
                    investigation_max_candidates=a_budget_that_keeps_nothing
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("investigation_max_candidates")
            )
        )


@pytest.mark.unit
def test_a_reporting_currency_is_held_as_argus_spells_a_currency() -> None:
    # Configured "USD", it would be compared with the revenue source's and the
    # rate table's "usd" and match neither: on a day the rates could not be
    # read, the takings in it would be stated as nothing.
    some_currency = "usd"

    Scenario() \
        .given(
            some_currency_configured_upper_case := some_currency.upper()
        ) \
        .when(
            lambda: Settings(reporting_currency=some_currency_configured_upper_case
                             ).reporting_currency
        ) \
        .then(
            the_answer_was(some_currency)
        )


@pytest.mark.unit
def test_a_candidate_budget_of_exactly_one_is_accepted() -> None:
    # The single-candidate walk: Argus tries its best explanation and stops.
    # It is the behaviour that existed before the walk did, and configuring it
    # back is a legitimate thing to want.
    Scenario() \
        .given(
            the_best_explanation_only := 1
        ) \
        .when(
            lambda: Settings(
                investigation_max_candidates=the_best_explanation_only
            )
        ) \
        .then(
            _it_kept("investigation_max_candidates", the_best_explanation_only)
        )


@pytest.mark.unit
def test_a_non_positive_deviation_count_is_rejected() -> None:
    # Zero deviations from baseline makes every minute anomalous, including
    # the calm ones the loop needs in order to have a baseline at all.
    Scenario() \
        .given(
            a_deviation_count_that_flags_every_minute := 0.0
        ) \
        .when(
            attempting(
                lambda: Settings(
                    anomaly_deviations_from_baseline=(
                        a_deviation_count_that_flags_every_minute
                    )
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("anomaly_deviations_from_baseline")
            )
        )


@pytest.mark.unit
def test_a_non_positive_change_lookback_is_rejected() -> None:
    # A zero-length change window can contain no change, so the channel could
    # only ever report "nothing changed" - the answer it exists to stop Argus
    # giving for the wrong reason.
    Scenario() \
        .given(
            a_change_lookback_that_can_hold_nothing := 0
        ) \
        .when(
            attempting(
                lambda: Settings(
                    change_lookback_minutes=a_change_lookback_that_can_hold_nothing
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("change_lookback_minutes")
            )
        )


@pytest.mark.unit
def test_a_change_lookback_no_wider_than_the_log_ceiling_is_rejected() -> None:
    # Change events exist to surface a cause the logs cannot reach. A change
    # window no wider than the log ceiling can only ever repeat what the log
    # window already showed.
    Scenario() \
        .given(
            some_max_log_window_minutes := 180,
            some_lookback_minutes := 30,
            some_lookahead_minutes := 10,
            dont_care_metrics_window_minutes := 360,
            too_narrow_change_lookback := 180
        ) \
        .when(
            attempting(
                lambda: Settings(
                    log_initial_lookback_minutes=some_lookback_minutes,
                    log_initial_lookahead_minutes=some_lookahead_minutes,
                    log_max_window_minutes=some_max_log_window_minutes,
                    metrics_window_minutes=dont_care_metrics_window_minutes,
                    change_lookback_minutes=too_narrow_change_lookback
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("change_lookback_minutes")
            )
        )


@pytest.mark.unit
def test_a_slice_carries_only_the_fields_it_declares() -> None:
    # The whole point of slicing. A process that cannot change the platform does
    # not name the credential that could - not because the environment withheld
    # it, but because the type has no field to put it in. What it does carry is
    # where the read tier is and how long a caller waits for its answers.
    Scenario() \
        .given(
            settings_holding_a_credential := Settings(
                database_password="a-password-the-read-tier-must-not-name"
            )
        ) \
        .when(
            lambda: ReadMcpEndpoint.of(settings_holding_a_credential)
        ) \
        .then(
            _it_carries_exactly({
                "read_mcp_host",
                "read_mcp_port",
                "read_mcp_url",
                "read_mcp_answered_within_seconds"
            })
        )


@pytest.mark.unit
def test_a_slice_takes_a_derived_property_as_a_field() -> None:
    # `database_url` is composed from four settings and is the only one of the
    # five anything actually wants. A slice that could not take it would be a
    # slice of the recipe rather than of the answer.
    Scenario() \
        .given(
            some_settings := Settings(
                database_user="some-user",
                database_password="some-password",
                database_host="some-host",
                database_port=6543
            )
        ) \
        .when(
            lambda: DatabaseSettings.of(some_settings)
        ) \
        .then(
            _the_database_url_is(
                "postgresql://some-user:some-password@some-host:6543/argus"
            )
        )


@pytest.mark.unit
def test_a_slice_cannot_be_edited_after_it_is_built() -> None:
    # Configuration is read at the top of a process. A slice that could be
    # edited on the way down would be a second way to configure Argus, and one
    # that nothing declares.
    Scenario() \
        .given(
            a_slice := DatabaseSettings.of(Settings()),
            some_other_url := "postgresql://somewhere-else:5432/argus"
        ) \
        .when(
            attempting(
                lambda: setattr(a_slice, "database_url", some_other_url)
            )
        ) \
        .then(
            an_error_was_raised(ValidationError)
        )


@pytest.mark.unit
def test_a_slice_naming_a_setting_that_does_not_exist_is_refused() -> None:
    # A slice is taken by name, so a misspelling is a field `Settings` does not
    # have. It fails where the slice is built, which is a composition root at
    # the top of a process, rather than at the moment the value was wanted.
    class _NamingSomethingUnconfigurable(SettingsSlice):
        a_setting_nobody_declared: int

    Scenario() \
        .given(
            dont_care_settings := Settings()
        ) \
        .when(
            attempting(
                lambda: _NamingSomethingUnconfigurable.of(dont_care_settings)
            )
        ) \
        .then(
            an_error_was_raised(ValidationError)
        )


@pytest.mark.unit
def test_a_slice_takes_a_field_from_the_vendor_settings_that_declare_it() -> None:
    # An agent's model is named in the provider's catalogue, so it is the
    # provider's setting - and the agent's slice still carries it beside the
    # kernel's, taken by name from whichever settings declare it.
    some_model = "some-model"
    some_rounds = 2

    class _AnAgentsSlice(SettingsSlice):
        investigation_max_rounds: int
        some_agent_model: str

    class _SomeProvidersSettings(AdapterSettings):
        some_agent_model: str

    Scenario() \
        .given(
            some_settings := Settings(investigation_max_rounds=some_rounds),
            some_providers := _SomeProvidersSettings(some_agent_model=some_model)
        ) \
        .when(
            lambda: _AnAgentsSlice.of(some_settings, some_providers)
        ) \
        .then(
            the_answer_was(_AnAgentsSlice(investigation_max_rounds=some_rounds,
                                          some_agent_model=some_model))
        )


@pytest.mark.unit
def test_a_field_two_settings_both_declare_is_refused() -> None:
    # Which of the two the slice meant is not something a name can say, so it
    # is refused where the slice is built rather than taken from whichever came
    # first.
    class _AnAgentsSlice(SettingsSlice):
        investigation_max_rounds: int

    class _SettingsDeclaringItToo(AdapterSettings):
        investigation_max_rounds: int

    Scenario() \
        .given(
            dont_care_settings := Settings(),
            settings_declaring_it_too := _SettingsDeclaringItToo(investigation_max_rounds=1)
        ) \
        .when(
            attempting(lambda: _AnAgentsSlice.of(dont_care_settings, settings_declaring_it_too))
        ) \
        .then(
            all_of(
                an_error_was_raised(ValueError),
                the_error_mentioned("investigation_max_rounds"),
                the_error_mentioned(THE_REFUSAL_OF_A_FIELD_DECLARED_TWICE)
            )
        )


@pytest.mark.unit
def test_the_telemetry_slice_carries_where_signals_go_and_the_log_level() -> None:
    # What `telemetry` is handed at the top of every process: the
    # directory every signal is written under, the general OTLP backend and the
    # level below which nothing is logged - and nothing else, so that wiring the
    # exporters names no credential of any other tier.
    Scenario() \
        .given(
            settings_holding_a_credential := Settings(
                database_password="a-password-telemetry-must-not-name"
            )
        ) \
        .when(
            lambda: TelemetrySettings.of(settings_holding_a_credential)
        ) \
        .then(
            _it_carries_exactly({
                "telemetry_directory",
                "otel_exporter_otlp_endpoint",
                "otel_exporter_otlp_headers",
                "log_level"
            })
        )


@pytest.mark.unit
def test_telemetry_is_written_under_dot_telemetry_and_sent_nowhere_by_default() -> None:
    # The configuration a fresh checkout runs with: every signal on disk, in a
    # directory the repository ignores, and no backend - an empty endpoint is
    # what switches each one off. Read off the declared defaults rather than off
    # a `Settings()`, which would read the developer's own `.env` and fail the
    # day somebody points theirs at a backend.
    Scenario() \
        .given(
            the_declared_defaults := Settings.model_construct()
        ) \
        .when(
            lambda: TelemetrySettings.of(the_declared_defaults)
        ) \
        .then(
            _it_is(TelemetrySettings(
                telemetry_directory=".telemetry",
                otel_exporter_otlp_endpoint="",
                otel_exporter_otlp_headers="",
                log_level="INFO"
            ))
        )


@pytest.mark.unit
def test_a_non_positive_intent_reader_pause_is_rejected() -> None:
    # A pause of nothing is an intent reader asking the log for new messages as fast
    # as the database will answer, for as long as nobody writes anything.
    Scenario() \
        .given(
            a_pause_that_never_pauses := 0.0
        ) \
        .when(
            attempting(
                lambda: Settings(intent_poll_seconds=a_pause_that_never_pauses)
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("intent_poll_seconds")
            )
        )


def _it_kept(field: str, expected: object) -> Assertion[Settings]:
    """That a setting came back as it was given.

    What an acceptance test asserts. "It did not raise" is already what `when`
    returning at all says; what is worth pinning is that the value survived the
    validator rather than being quietly adjusted into range.
    """
    def kept(settings: Settings) -> bool:
        actual = getattr(settings, field)
        if actual != expected:
            raise AssertionError(
                f"Expected [{field}] to have been kept as [{expected}], "
                f"and it came back [{actual}]."
            )

        return True

    return kept


def _it_carries_exactly(field_names: set[str]) -> Assertion[SettingsSlice]:
    """That the slice declares these fields and no others.

    Asserted as a whole set rather than field by field, because the claim is
    about what a consumer cannot reach: a slice that grew an extra field would
    pass every check written about the ones it was supposed to have.
    """
    def carries_exactly(narrowed: SettingsSlice) -> bool:
        carried = set(type(narrowed).model_fields)
        if carried != field_names:
            raise AssertionError(
                f"Expected the slice to carry exactly {sorted(field_names)}, "
                f"and it carries {sorted(carried)}"
            )

        return True

    return carries_exactly


def _the_database_url_is(expected: str) -> Assertion[DatabaseSettings]:
    """That the composed URL arrived intact through the narrowing."""
    def the_database_url_is(narrowed: DatabaseSettings) -> bool:
        if narrowed.database_url != expected:
            raise AssertionError(
                f"Expected the database url [{expected}], "
                f"and it is [{narrowed.database_url}]."
            )

        return True

    return the_database_url_is


def _it_is(expected: TelemetrySettings) -> Assertion[TelemetrySettings]:
    """That the slice holds exactly these values.

    Compared whole rather than field by field, so that a default nobody meant
    to change is reported beside the one the test was written about.
    """
    def it_is(narrowed: TelemetrySettings) -> bool:
        if narrowed != expected:
            raise AssertionError(
                f"Expected the telemetry settings {expected!r}, "
                f"and they are {narrowed!r}."
            )

        return True

    return it_is


@pytest.mark.unit
def test_an_environment_naming_the_service_source_paths_is_read(tmp_path: Path) -> None:
    some_paths = "src/io_shop,deploy"
    an_env_file = tmp_path / ".env"
    an_env_file.write_text(f"{THE_SOURCE_PATHS}={some_paths}\n", encoding="utf-8")

    Scenario() \
        .given(an_env_file) \
        .when(lambda: _settings_read_from(an_env_file).service_source_paths) \
        .then(the_answer_was(some_paths))


def _settings_read_from(env_file: Path) -> Settings:
    """The whole configuration as read from `env_file` alone - every validator
    inherited, and nothing from the environment the suite runs in."""
    class ReadFromThatFile(Settings):
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
