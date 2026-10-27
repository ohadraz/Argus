"""The real write server, for a world in which one claim holds one run.

Run as `python -m write_mcp_client_test.a_write_server_holding_one_run`. The
server's own `main`, every tool and every adapter as it starts in production,
with one thing stood in for: whether a claim still holds its run. That is a row
in a database the client never sees, decided by a protocol the client knows
nothing of - so here `THE_RUN_HELD` holds its run, and every other claim is one
the run has moved past.

A change that lands through this server therefore proves the client said which
claim it acted for, and said it so the server could read it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial

from argus_core import DatabaseSettings, Fence
from write_mcp_server.fencing import HoldForAChange
from write_mcp_server.server import main

THE_RUN_HELD = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)


def holding_only(held: Fence) -> HoldForAChange:
    """A run that `held` holds and no other claim does."""
    @contextmanager
    def hold(fence: Fence) -> Iterator[bool]:
        yield fence == held

    return hold


@contextmanager
def holds_for(held: Fence, dont_care_settings: DatabaseSettings) -> Iterator[HoldForAChange]:
    """What the server's `main` is handed in place of the database's holds."""
    yield holding_only(held)


if __name__ == "__main__":
    main(holds=partial(holds_for, THE_RUN_HELD))
