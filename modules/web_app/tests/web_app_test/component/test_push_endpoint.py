"""The door the code host knocks on when a branch moves, from the outside.

Which pushes are news is decided in `pushes`' own suite, and whether a delivery
is GitHub's in the push source's. What is left here is the door: what the
source is handed, and where the work after it runs.

The source is stood in through the app's own dependency seam: it is somebody
else's signature scheme, decided in the adapter's suite.
"""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus as HttpStatus
from unittest.mock import create_autospec

import pytest
from argus_testkit import Scenario, all_of
from fastapi.testclient import TestClient
from push_source import Pushed, PushSource
from web_app.app import app, push_source_of

from web_app_test.framework.assertions import the_response_was
from web_app_test.framework.event_loop import handed_off_the_event_loop, on_an_event_loop

PUSH_WEBHOOK = "/webhooks/github/push"


@pytest.mark.component
def test_the_source_is_handed_the_bytes_that_arrived_off_the_event_loop() -> None:
    # The signature is over those bytes. And the watermark's write after them
    # blocks, so it runs in the threadpool: on the loop it would hold every
    # other request being served.
    some_body = b'{"zen": "Keep it logically awesome."}'
    asked: list[tuple[bytes, bool]] = []

    def parse_delivery(body: bytes, headers: Mapping[str, str], /) -> Pushed | None:
        asked.append((body, on_an_event_loop()))

        return None

    source = create_autospec(PushSource, instance=True)
    source.parse_delivery.side_effect = parse_delivery
    app.dependency_overrides[push_source_of] = lambda: source

    try:
        with TestClient(app) as client:
            Scenario() \
                .when(lambda: client.post(PUSH_WEBHOOK, content=some_body)) \
                .then(all_of(
                    the_response_was(HttpStatus.ACCEPTED),
                    handed_off_the_event_loop(asked, some_body)
                ))
    finally:
        app.dependency_overrides.pop(push_source_of, None)
