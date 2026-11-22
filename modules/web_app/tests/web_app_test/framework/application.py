"""The application this suite drives.

Built as the process's root (`apps.web`) builds it, but hearing from stand-ins:
one sender of alerts, heard at its own route and with no name, and a push
source a case that posts a push stands its own in for. No on-call or chat
platform - a case about either stands its own in through the app's dependency
seam. Which vendor answers each port is the root's to choose and each
adapter's suite's to test; the suite cannot import the root, which installs
this module.
"""

from __future__ import annotations

from typing import Final
from unittest.mock import create_autospec

from push_source import PushSource
from web_app.app import an_app

from web_app_test.framework.senders import AlertsAsArgusWritesThem

# The route the suite's sender of alerts is heard at.
SOME_SENDER: Final = "some-sender"

app = an_app(
    alert_sources={SOME_SENDER: AlertsAsArgusWritesThem()},
    the_unnamed_senders_name=SOME_SENDER,
    push_source=create_autospec(PushSource, instance=True),
    oncall_platform=None,
    chat_platform=None
)
