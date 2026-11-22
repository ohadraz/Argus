"""What the application decides as it is built, before anything is served.

What each route does with what arrives is `component/`'s. This is the one
thing `an_app` refuses outright: a sender heard at `/webhooks/alerts` that it
is not handed - which would otherwise start, and answer every alert posted
there with a failure.
"""

from __future__ import annotations

from unittest.mock import create_autospec

import pytest
from argus_testkit import Scenario, all_of, an_error_was_raised, attempting, the_error_mentioned
from push_source import PushSource
from web_app.app import an_app

from web_app_test.framework.senders import AlertsAsArgusWritesThem

SOME_SENDER = "some-sender"
SOME_OTHER_SENDER = "some-other-sender"


@pytest.mark.unit
def test_an_app_told_to_hear_unnamed_a_sender_it_was_not_handed_is_refused() -> None:
    Scenario() \
        .given(senders_heard := {SOME_SENDER: AlertsAsArgusWritesThem()}) \
        .when(attempting(lambda: an_app(
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
