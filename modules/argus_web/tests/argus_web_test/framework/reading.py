"""Driving the app, and reading what came back out of it.

Not assertions: these answer questions about a response or a document, and
leave the judging to `assertions`. Two suites ask the same questions of the
same pages, so asking them the same way is what stops one of them quietly
testing a different thing.
"""

from __future__ import annotations

import re

from argus_web.app import app
from fastapi.testclient import TestClient


def page_at(path: str) -> str:
    """The document at `path`, insisting the server actually served one.

    The status is checked here rather than asserted by the caller because a
    404 renders as a perfectly good string: a test that went on to look for
    text in an error page would report "the page does not say X" when what
    happened is that there was no page.

    The client is entered and left around the one request so the app's
    lifespan runs - the startup that checks the schema is there is part of
    what a component test is exercising.
    """
    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200, (
        f"Expected 200 from {path}, got {response.status_code}."
    )

    return response.text


def attribute(name: str, html: str) -> list[str]:
    """Every value of one `data-` attribute, in the order the document carries
    them - which is the order a reader sees."""
    return re.findall(rf'data-{name}="([^"]*)"', html)
