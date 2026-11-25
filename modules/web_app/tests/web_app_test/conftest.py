"""The database, for whichever of this suite's cases asks for it.

Asked for by every component case, through `component/`'s own conftest, and by
the cases outside it that read a connection - never brought up for a case that
does not.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from typing import Final

import pytest
from argus_testkit import refuse_the_e2e_stacks_project
from postgres import connect_from_env, reset_schema

# The compose service this suite brings up, and what it stops.
_POSTGRES: Final = "postgres"
# What postgres depends on in docker-compose.yml, so `up` starts it with
# postgres and the stop names it too - or it outlives the suite.
_ITS_CLOCK: Final = "sim-clock"


@pytest.fixture(scope="session")
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
        subprocess.run(["docker", "compose", "stop", _POSTGRES, _ITS_CLOCK], check=True)
