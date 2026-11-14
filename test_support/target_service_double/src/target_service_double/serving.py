"""The shop's own app, with a door for a case to name the world it replays into.

Everything the shop serves is served as the shop serves it. What is added is the
house's `/double-control/*` seam: a case stages its recording's anchor there and
reads back which anchor the last seed used. The only thing changed is what a
seed is - the shop's own `seed`, run through `Seeding`, so a staged anchor's
world is the one seeded.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from target_service_double.seeding import Seeding

# How a staged anchor is refused: the shape a case can act on, as FastAPI says
# any other request it cannot read.
_UNREADABLE = 422


def standing_in_for(shop: FastAPI, state: Any, seeding: Seeding) -> FastAPI:
    """`shop`, seeding through `seeding` and answering on `/double-control/*`.

    `state` is the shop's own state object, whose `seed` its seed route calls.
    Wrapped in place, so the shop's route - its validation, its errors, the
    status it answers with - is the shop's, unchanged.
    """
    seed_as_the_shop_does = state.seed

    def seed(*arguments: Any, **keywords: Any) -> Any:
        return seeding.seed(lambda: seed_as_the_shop_does(*arguments, **keywords))

    state.seed = seed

    @shop.post("/double-control/anchor")
    def stage_the_anchor(body: dict[str, Any]) -> JSONResponse:
        seeding.stage(_an_instant(body.get("anchor")))

        return _the_state_of(seeding)

    @shop.post("/double-control/reset")
    def reset() -> JSONResponse:
        seeding.reset()

        return _the_state_of(seeding)

    @shop.get("/double-control/state")
    def state_of() -> JSONResponse:
        return _the_state_of(seeding)

    return shop


def _an_instant(anchor: Any) -> datetime:
    """The anchor as one instant, or a refusal saying why it is not one."""
    if not isinstance(anchor, str):
        raise HTTPException(status_code=_UNREADABLE,
                            detail="an anchor is the set's .anchor file, as text")

    try:
        instant = datetime.fromisoformat(anchor.strip())
    except ValueError as error:
        raise HTTPException(status_code=_UNREADABLE,
                            detail=f"[{anchor}] names no instant") from error

    if instant.tzinfo is None:
        raise HTTPException(status_code=_UNREADABLE,
                            detail=f"[{anchor}] has no offset, so it is no one instant")

    return instant


def _the_state_of(seeding: Seeding) -> JSONResponse:
    state = seeding.state()

    return JSONResponse({
        "staged": _as_text(state.staged),
        "shift_seconds": state.shift / timedelta(seconds=1),
        "last_seeded_from": _as_text(state.last_seeded_from)
    })


def _as_text(instant: datetime | None) -> str | None:
    return instant.isoformat() if instant is not None else None
