"""What the schema job does to a database, as it is asked and as it is allowed.

Applying drops nothing; destroying drops the schema first, and is done only
where the environment says the schema may be destroyed. The flag says what is
intended and the setting says the database is one nobody minds losing - so a
deployment that keeps its data is never one flag away from being wiped.

What applying and destroying are is `postgres`'s, and tested there. Here they
stand in as the two ways in, so which one the job takes is asserted with no
database behind it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, create_autospec

import psycopg
import pytest
from apps.schema import DestructionRefused, the_schema_applied
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_error_mentioned,
)
from core import Settings, get_settings
from postgres import apply_schema, reset_schema

# What the job is told on its command line.
APPLYING = False
DESTROYING = True

# What the environment says about the schema it is applied to.
NOBODY_MINDS_LOSING_IT = True
SOMEBODY_MAY_MIND_LOSING_IT = False

# The setting the refusal has to name, as a person sets it.
THE_SETTING = "SCHEMA_MAY_BE_DESTROYED"

# What each way in is called in a failure.
APPLYING_IT = "applying the schema"
DESTROYING_IT = "dropping and applying the schema"


@pytest.mark.unit
@pytest.mark.parametrize("may_be_destroyed", [SOMEBODY_MAY_MIND_LOSING_IT, NOBODY_MINDS_LOSING_IT],
                         ids=["kept-data", "development"])
def test_the_schema_is_applied_without_a_drop_unless_destroying_is_asked_for(
        may_be_destroyed: bool) -> None:
    # Whatever the environment allows: what a deployment that keeps its data
    # runs is the job with no flag, and a development stack allowed to destroy
    # still destroys nothing it was not asked to.
    applying, resetting = _applying(), _resetting()

    Scenario() \
        .given(
            the_connection := _a_connection(),
            settings := _settings_where(may_be_destroyed=may_be_destroyed)
        ) \
        .when(lambda: the_schema_applied(the_connection, destroy=APPLYING, settings=settings,
                                         apply=applying, reset=resetting)) \
        .then(all_of(
            _it_was_done_once_to(applying, the_connection, named=APPLYING_IT),
            _it_was_never_done(resetting, named=DESTROYING_IT)
        ))


@pytest.mark.unit
def test_destroying_a_schema_the_environment_keeps_is_refused_and_touches_nothing() -> None:
    # Refused before anything is asked of the database, so a reader of the
    # refusal knows nothing happened - and named for the setting, because the
    # person reading it is deciding whether this database is theirs to lose.
    applying, resetting = _applying(), _resetting()

    Scenario() \
        .given(
            dont_care_connection := _a_connection(),
            settings := _settings_where(may_be_destroyed=SOMEBODY_MAY_MIND_LOSING_IT)
        ) \
        .when(attempting(lambda: the_schema_applied(
            dont_care_connection, destroy=DESTROYING, settings=settings,
            apply=applying, reset=resetting
        ))) \
        .then(all_of(
            an_error_was_raised(DestructionRefused),
            the_error_mentioned(THE_SETTING),
            _it_was_never_done(applying, named=APPLYING_IT),
            _it_was_never_done(resetting, named=DESTROYING_IT)
        ))


@pytest.mark.unit
def test_destroying_a_schema_the_environment_may_lose_drops_it_first() -> None:
    applying, resetting = _applying(), _resetting()

    Scenario() \
        .given(
            the_connection := _a_connection(),
            settings := _settings_where(may_be_destroyed=NOBODY_MINDS_LOSING_IT)
        ) \
        .when(lambda: the_schema_applied(the_connection, destroy=DESTROYING, settings=settings,
                                         apply=applying, reset=resetting)) \
        .then(all_of(
            _it_was_done_once_to(resetting, the_connection, named=DESTROYING_IT),
            _it_was_never_done(applying, named=APPLYING_IT)
        ))


def _a_connection() -> psycopg.Connection:
    """A connection the job hands on and never uses itself."""
    connection: psycopg.Connection = create_autospec(psycopg.Connection, instance=True)

    return connection


def _applying() -> MagicMock:
    """Applying the schema, standing in for `postgres.apply_schema`."""
    applying: MagicMock = create_autospec(apply_schema)

    return applying


def _resetting() -> MagicMock:
    """Destroying and applying it, standing in for `postgres.reset_schema`."""
    resetting: MagicMock = create_autospec(reset_schema)

    return resetting


def _settings_where(*, may_be_destroyed: bool) -> Settings:
    return get_settings().model_copy(update={"schema_may_be_destroyed": may_be_destroyed})


def _it_was_done_once_to(done: MagicMock,
                         connection: psycopg.Connection,
                         *,
                         named: str) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        if done.call_args_list != [call(connection)]:
            raise AssertionError(
                f"Expected {named} to be done once, to the job's connection, and it "
                f"was done {done.call_args_list}."
            )

        return True

    return assertion


def _it_was_never_done(done: MagicMock, *, named: str) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        if done.call_count:
            raise AssertionError(
                f"Expected {named} never to be done, and it was done "
                f"{done.call_args_list}."
            )

        return True

    return assertion
