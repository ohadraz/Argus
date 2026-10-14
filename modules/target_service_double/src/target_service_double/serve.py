"""Serving the shop as a replay sees it: `python -m target_service_double.serve`,
run inside the shop's own image in place of `python -m target_app.serve`.

The shop is loaded by name rather than imported, because this package is part
of Argus's workspace and the shop is not: Argus's checks see a package that
depends on nothing of the shop's, and the image this runs in is the only place
the shop's code and its locked dependencies are both installed.

One process, one listener, for the reason the shop gives for its own: the
seeded world lives in this process's memory.
"""

from __future__ import annotations

import importlib
import os
import random
import time
from datetime import UTC, datetime
from typing import Any

import uvicorn

from target_service_double.draws import ShiftedDraws
from target_service_double.seeding import Seeding
from target_service_double.serving import standing_in_for
from target_service_double.shop import (
    asking_the_checks_as_recorded,
    pinning_the_clock_of,
    what_the_shop_lacks,
)

# Where the stand-in answers: where the shop would.
PORT = int(os.environ.get("PORT", "8000"))

# Every interface, for the shop's own reason: its alerts are posted from inside
# this container.
HOST = "0.0.0.0"


def main() -> None:
    """Loads the shop, checks it can still be reached where the stand-in reaches
    it, and serves it - refusing to start rather than serving a world it cannot
    move."""
    the_app: Any = importlib.import_module("target_app.app")
    generator: Any = importlib.import_module("target_app.generator")
    state: Any = importlib.import_module("target_app.state")
    scenarios: Any = importlib.import_module("target_app.scenarios")
    integrity: Any = importlib.import_module("target_app.integrity")

    lacking = what_the_shop_lacks(generator, state, scenarios, integrity)
    if lacking:
        raise SystemExit("the stand-in cannot serve this shop: " + "; ".join(lacking))

    draws = ShiftedDraws(random, scenarios.TIMESTAMP_FORMAT)
    generator.random = draws
    # The checks move by the shift the draws were moved by, so the purchases
    # they find are the recorded ones in the minutes the draws are.
    asking_the_checks_as_recorded(state, lambda: draws.shift)

    seeding = Seeding(draws,
                      # The stack's clock: the image preloads the stack's fake
                      # time, so the wall clock here is the stack's.
                      now=lambda: datetime.now(UTC),
                      sleep=time.sleep,
                      pin_the_shops_clock=pinning_the_clock_of(state))

    uvicorn.run(standing_in_for(the_app.app, the_app.state, seeding), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
