"""The stand-in from the outside: the shop's own app, with a door for a case to
say which recording's world the next seed is.

The shop is a fake here, shaped as the real one is where the stand-in touches
it: an app whose seed route asks a state object to seed, and routes the
stand-in has no business with. Whether the real shop's world comes out as the
recorded one is the contract suite's question, asked of the real shop.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx
import pytest
from argus_testkit import Assertion, Scenario, all_of, calling
from fastapi import FastAPI
from fastapi.testclient import TestClient
from target_service_double.draws import ShiftedDraws
from target_service_double.seeding import Seeding
from target_service_double.serving import standing_in_for

THE_SHOPS_MINUTE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# A set's anchor exactly as its `.anchor` file holds it.
SOME_ANCHOR_AS_FILED = "2026-09-28T22:11:43.502554Z"
SOME_ANCHOR = datetime(2026, 9, 28, 22, 11, 43, 502554, tzinfo=UTC)
SOME_REPLAY_START = datetime(2026, 10, 14, 3, 50, 10, tzinfo=UTC)
THE_SEED_INSTANT = datetime(2026, 10, 14, 3, 50, 43, 502554, tzinfo=UTC)

SOME_SCENARIO = "upstream-dependency-failure"
SOME_LOG_LINES = ["2026-10-14T03:49:00Z INFO io-shop: account pages rendered normally"]


class _FakeShop:
    """The shop's state where the stand-in meets it: one `seed`, and a clock
    the stand-in may pin while it runs."""

    def __init__(self) -> None:
        self.clock_reading: datetime = SOME_REPLAY_START
        self.pinned_at: datetime | None = None
        self.seeded: list[str] = []
        self.seeded_at: datetime | None = None

    def seed(self, scenario_id: str) -> None:
        self.seeded.append(scenario_id)
        self.seeded_at = self.pinned_at or self.clock_reading

    def now(self) -> datetime:
        return self.clock_reading

    def sleep(self, dont_care_seconds: float) -> None:
        self.clock_reading += timedelta(seconds=1)

    @contextmanager
    def pinned(self, instant: datetime) -> Iterator[None]:
        self.pinned_at = instant
        try:
            yield
        finally:
            self.pinned_at = None


def _the_shops_app(shop: _FakeShop) -> FastAPI:
    app = FastAPI()

    @app.post("/scenario/seed")
    def seed_scenario(body: dict[str, Any]) -> dict[str, Any]:
        shop.seed(body["scenario_id"])
        return {"seeded_at": shop.seeded_at.isoformat() if shop.seeded_at else None}

    @app.get("/logs")
    def logs() -> list[str]:
        return SOME_LOG_LINES

    return app


@contextmanager
def _the_stand_in(shop: _FakeShop) -> Iterator[TestClient]:
    seeding = Seeding(ShiftedDraws(random, THE_SHOPS_MINUTE_FORMAT),
                      now=shop.now,
                      sleep=shop.sleep,
                      pin_the_shops_clock=shop.pinned)

    with TestClient(standing_in_for(_the_shops_app(shop), shop, seeding)) as client:
        yield client


@pytest.mark.component
def test_a_seed_after_an_anchor_is_staged_is_the_recorded_world() -> None:
    shop = _FakeShop()

    with _the_stand_in(shop) as stand_in:
        Scenario() \
            .given(calling(lambda: stand_in.post("/double-control/anchor",
                                                 json={"anchor": SOME_ANCHOR_AS_FILED}))) \
            .when(lambda: stand_in.post("/scenario/seed", json={"scenario_id": SOME_SCENARIO})) \
            .then(all_of(
                _answered(HttpStatus.OK),
                _the_shop_was_seeded_at(shop, THE_SEED_INSTANT),
                _the_stand_in_says(stand_in,
                                   last_seeded_from=SOME_ANCHOR_AS_FILED,
                                   shift_seconds=(THE_SEED_INSTANT - SOME_ANCHOR).total_seconds())
            ))


@pytest.mark.component
def test_a_seed_with_nothing_staged_is_the_shops_own() -> None:
    shop = _FakeShop()

    with _the_stand_in(shop) as stand_in:
        Scenario() \
            .when(lambda: stand_in.post("/scenario/seed", json={"scenario_id": SOME_SCENARIO})) \
            .then(all_of(
                _answered(HttpStatus.OK),
                _the_shop_was_seeded_at(shop, SOME_REPLAY_START),
                _the_stand_in_says(stand_in, last_seeded_from=None, shift_seconds=0.0)
            ))


@pytest.mark.component
def test_every_other_route_is_the_shops_own() -> None:
    shop = _FakeShop()

    with _the_stand_in(shop) as stand_in:
        Scenario() \
            .when(lambda: stand_in.get("/logs")) \
            .then(all_of(
                _answered(HttpStatus.OK),
                _answered_with(SOME_LOG_LINES)
            ))


@pytest.mark.component
def test_a_reset_forgets_what_was_staged() -> None:
    shop = _FakeShop()

    with _the_stand_in(shop) as stand_in:
        Scenario() \
            .given(calling(lambda: stand_in.post("/double-control/anchor",
                                                 json={"anchor": SOME_ANCHOR_AS_FILED}))) \
            .when(lambda: stand_in.post("/double-control/reset")) \
            .then(all_of(
                _answered(HttpStatus.OK),
                _the_stand_in_says(stand_in, staged=None, shift_seconds=0.0)
            ))


@pytest.mark.component
def test_an_anchor_that_names_no_instant_is_refused() -> None:
    shop = _FakeShop()

    with _the_stand_in(shop) as stand_in:
        Scenario() \
            .when(lambda: stand_in.post("/double-control/anchor", json={"anchor": "yesterday"})) \
            .then(_answered(HttpStatus.UNPROCESSABLE_ENTITY))


@pytest.mark.component
def test_an_anchor_with_no_offset_is_refused() -> None:
    # An instant with no offset is a different instant on every machine that
    # reads it, and the whole point of an anchor is that it is one instant.
    shop = _FakeShop()

    with _the_stand_in(shop) as stand_in:
        Scenario() \
            .when(lambda: stand_in.post("/double-control/anchor",
                                        json={"anchor": "2026-09-28T22:11:43.502554"})) \
            .then(_answered(HttpStatus.UNPROCESSABLE_ENTITY))


def _answered(expected: HttpStatus) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        if response.status_code != expected:
            raise AssertionError(
                f"Expected the stand-in to answer [{expected}], got "
                f"[{response.status_code}]: {response.text}"
            )

        return True

    return assertion


def _answered_with(expected: Any) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        if response.json() != expected:
            raise AssertionError(f"Expected the answer {expected}, got {response.json()}.")

        return True

    return assertion


def _the_shop_was_seeded_at(shop: _FakeShop, expected: datetime) -> Assertion[httpx.Response]:
    def assertion(_: httpx.Response) -> bool:
        if shop.seeded_at != expected:
            raise AssertionError(
                f"Expected the shop seeded at [{expected.isoformat()}], and it was "
                f"seeded at [{shop.seeded_at}]."
            )

        return True

    return assertion


def _the_stand_in_says(stand_in: TestClient, **expected: Any) -> Assertion[httpx.Response]:
    def assertion(_: httpx.Response) -> bool:
        said = stand_in.get("/double-control/state").json()
        differing = {key: (value, said.get(key)) for key, value in expected.items()
                     if _as_said(value) != _as_said(said.get(key))}

        if differing:
            raise AssertionError(
                f"Expected the stand-in's state to say {expected}, and it said "
                f"{said} - (expected, said) where they differ: {differing}."
            )

        return True

    return assertion


def _as_said(value: Any) -> Any:
    """An instant as an instant, however it was spelled; anything else as is."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value

    return value
