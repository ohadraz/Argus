"""What a configuration must agree with itself about, and what one process may know.

Two questions, and they are not the same one asked twice. `Settings` is the
whole environment, and the relationships across it - the windows that have to
admit each other - are checked in one place because no individual field can
check them. A slice is what a single consumer is handed out of that whole, and
the question there is not what it holds but what it cannot name.
"""
from __future__ import annotations

import pytest
from argus_core.config import (
    DatabaseSettings,
    ReadMcpEndpoint,
    Settings,
    SettingsSlice,
)
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
)
from pydantic import ValidationError


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
                _it_complained_about("log_max_window_minutes")
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
                _it_complained_about("metrics_window_minutes")
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
                _it_complained_about("investigation_max_candidates")
            )
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
                _it_complained_about("anomaly_deviations_from_baseline")
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
                _it_complained_about("change_lookback_minutes")
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
                _it_complained_about("change_lookback_minutes")
            )
        )


@pytest.mark.unit
def test_a_slice_carries_only_the_fields_it_declares() -> None:
    # The whole point of slicing. A process that cannot change a flag does not
    # name the credential that could - not because the environment withheld it,
    # but because the type has no field to put it in.
    Scenario() \
        .given(
            settings_holding_every_credential := Settings(
                unleash_admin_token="an-admin-token-the-read-tier-must-not-name",
                anthropic_api_key="dont-care-key"
            )
        ) \
        .when(
            lambda: ReadMcpEndpoint.of(settings_holding_every_credential)
        ) \
        .then(
            _it_carries_exactly({"read_mcp_host", "read_mcp_port", "read_mcp_url"})
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


def _it_complained_about(field: str) -> Assertion[Exception | None]:
    """That the refusal named the field the test is about.

    A `Settings` has several relationships to satisfy at once, so it can be
    refused for a reason the test did not intend - a default that moved, a
    neighbouring field left at something incompatible - and a bare
    `ValidationError` would pass either way.
    """
    def complained_about(error: Exception | None) -> bool:
        if error is None or field not in str(error):
            raise AssertionError(
                f"Expected the refusal to name [{field}], "
                f"and it said [{error}]."
            )

        return True

    return complained_about


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
