"""Where a route's work ran: on the event loop, or off it."""

from __future__ import annotations

import asyncio
from typing import Any

from argus_testkit import Assertion


def on_an_event_loop() -> bool:
    """Whether the caller is running on an event loop.

    A synchronous route's body runs in the threadpool, where no loop runs; an
    asynchronous one's runs on the loop every other request is served on, and
    blocking work there holds all of them.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False

    return True


def handed_off_the_event_loop(asked: list[tuple[bytes, bool]],
                              body: bytes) -> Assertion[Any]:
    """That whatever reads a delivery was asked once, with the bytes that
    arrived, and not on the event loop - `asked` being what it noted, each
    time, with `on_an_event_loop`."""
    def assertion(_response: Any) -> bool:
        if asked != [(body, False)]:
            raise AssertionError(
                f"Expected one ask, with [{body!r}] and off the event loop, got "
                f"{asked} (bytes, on the event loop)."
            )

        return True

    return assertion
