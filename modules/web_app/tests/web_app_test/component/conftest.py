"""Postgres, and nothing else.

A component test runs `web_app` entire - its routes, its reads, its
serialization - and stubs only what it genuinely cannot be: the database. There
is no in-memory Postgres for this workspace's Python, and a SQLite stand-in
would need a second dialect of the schema, which is precisely the thing a
component test is supposed to be checking against. So the real server comes up,
from the same `docker-compose.yml` the stack runs on, with the same DDL.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from typing import Final

import pytest
from argus_testkit import refuse_the_e2e_stacks_project
from core import connect_from_env
from core.schema import reset_schema

# The compose service this suite brings up, and the only one it stops.
_POSTGRES: Final = "postgres"


@pytest.fixture(scope="session", autouse=True)
def postgres() -> Iterator[None]:
    """The database, up for the whole suite and stopped after it.

    Started from an empty schema rather than an adopted one: the container may
    be a previous run's, and a run that was killed left its rows behind.

    Refused in the e2e stack's compose project, where the reset would empty the
    database a running stack's worker is attached to. Stops only the database
    on the way out, so a project shared by mistake still keeps its other
    services.
    """
    refuse_the_e2e_stacks_project("test_module(module='web_app')")
    subprocess.run(["docker", "compose", "up", "-d", "--wait", _POSTGRES], check=True)
    try:
        with connect_from_env() as conn:
            reset_schema(conn)
        yield
    finally:
        subprocess.run(["docker", "compose", "stop", _POSTGRES], check=True)
