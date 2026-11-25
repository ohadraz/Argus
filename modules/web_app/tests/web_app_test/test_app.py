"""What the application decides as it is built, and what it hands its routes.

What each route does with what arrives is `component/`'s. This is the one
thing `an_app` refuses outright: a sender heard at `/webhooks/alerts` that it
is not handed - which would otherwise start, and answer every alert posted
there with a failure. And what a page is handed to read on (`a_moment_of`): a
connection holding one read-only snapshot.
"""

from __future__ import annotations

from typing import NamedTuple
from unittest.mock import create_autospec

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_error_mentioned,
)
from core import DatabaseSettings
from core.models import CodeSearch
from postgres import Connections, connect_from_env
from push_source import PushSource
from web_app.app import a_moment_of, an_app
from web_app.pushes import PushSettings

from web_app_test.framework.senders import AlertsAsArgusWritesThem

SOME_SENDER = "some-sender"
SOME_OTHER_SENDER = "some-other-sender"

# What `SHOW transaction_isolation` and `SHOW transaction_read_only` answer
# inside a moment, as Postgres spells them.
REPEATABLE_READ = "repeatable read"
READ_ONLY = "on"


class _Moment(NamedTuple):
    isolation: str
    read_only: str


@pytest.mark.unit
def test_an_app_told_to_hear_unnamed_a_sender_it_was_not_handed_is_refused() -> None:
    Scenario() \
        .given(senders_heard := {SOME_SENDER: AlertsAsArgusWritesThem()}) \
        .when(attempting(lambda: an_app(
            database=DatabaseSettings(database_url="postgresql://dont-care/argus"),
            push_settings=PushSettings(repository="dont-care/repository",
                                       deployed_branch="dont-care-branch",
                                       code_search=CodeSearch.BOTH),
            alert_sources=senders_heard,
            the_unnamed_senders_name=SOME_OTHER_SENDER,
            push_source=create_autospec(PushSource, instance=True),
            oncall_platform=None,
            chat_platform=None
        ))) \
        .then(all_of(
            an_error_was_raised(ValueError),
            the_error_mentioned(SOME_OTHER_SENDER)
        ))


@pytest.mark.integration
def test_a_moment_handed_to_a_page_reads_one_snapshot_and_writes_nothing(
    postgres: None
) -> None:
    Scenario() \
        .when(
            lambda: _the_moment_of(a_moment_of(connect_from_env))
        ) \
        .then(
            _the_moment_is(_Moment(isolation=REPEATABLE_READ, read_only=READ_ONLY))
        )


def _the_moment_of(connections: Connections) -> _Moment:
    with connections() as conn, conn.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        isolation = cursor.fetchone()
        cursor.execute("SHOW transaction_read_only")
        read_only = cursor.fetchone()

    return _Moment(isolation=isolation[0] if isolation else "",
                   read_only=read_only[0] if read_only else "")


def _the_moment_is(expected: _Moment) -> Assertion[_Moment]:
    def assertion(found: _Moment) -> bool:
        if found != expected:
            raise AssertionError(
                f"Expected a page's connection to read as {expected}, got {found}."
            )

        return True

    return assertion
