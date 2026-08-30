from __future__ import annotations

import subprocess
from collections.abc import Iterator

import pytest
from argus_core.db import connect
from argus_core.schema import create_schema

"""Postgres, and nothing else.

A component test runs `argus_web` entire - its routes, its reads, its
serialization - and stubs only what it genuinely cannot be: the database. There
is no in-memory Postgres for this workspace's Python, and a SQLite stand-in
would need a second dialect of the schema, which is precisely the thing a
component test is supposed to be checking against. So the real server comes up,
from the same `docker-compose.yml` the stack runs on, with the same DDL.
"""


@pytest.fixture(scope="session", autouse=True)
def postgres() -> Iterator[None]:
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "postgres"], check=True)
    try:
        with connect() as conn:
            create_schema(conn)
        yield
    finally:
        subprocess.run(["docker", "compose", "stop", "postgres"], check=True)
