"""Refusing to bring infrastructure up in the e2e stack's compose project.

A suite that needs postgres or qdrant brings it up with `docker compose`, and
compose decides whose container that is by the project name in the environment.
Every nox session that runs such a suite names one of its own. A bare `pytest`,
or an IDE's runner, names none - and compose then names the project after the
directory, which in a checkout of this repo is the e2e stack's own.

There, a suite's setup resets what a running stack's worker is using - the
database's schema, or the vector store - and its teardown stops that stack. Every case after it
fails, and nothing in the run says why. So the refusal comes before the first
docker call, and says which session to run instead.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

import pytest

# The e2e stack's compose project. Mirrors the project in the noxfile's
# `_THE_STACKS_OWN_PLACES` by hand: a test cannot import the noxfile.
_THE_E2E_STACKS_PROJECT: Final = "argus"

_PROJECT_VARIABLE: Final = "COMPOSE_PROJECT_NAME"


def refuse_the_e2e_stacks_project(session: str,
                                  environ: Mapping[str, str] = os.environ) -> None:
    """Ends the run unless compose would use a project other than the e2e stack's.

    Unset and empty are refused with the stack's own name, because that is what
    compose falls back to here. `session` is the nox session that gives this
    suite a project of its own - `"integration"`, or
    `"test_module(module='core')"` - and is named in the message, so the reader
    is told what to run rather than only what not to.

    Ends the run rather than skipping or failing a test: nothing in the suite
    can pass without the infrastructure, and a usage error is what this is.
    """
    project = environ.get(_PROJECT_VARIABLE, "")

    if project and project != _THE_E2E_STACKS_PROJECT:
        return

    where = (
        f"[{_PROJECT_VARIABLE}] is [{project}]" if project
        else f"[{_PROJECT_VARIABLE}] is unset, so compose would use the directory's "
             f"name [{_THE_E2E_STACKS_PROJECT}]"
    )

    pytest.exit(
        f"Expected a compose project of this suite's own, and {where}, which is the "
        "e2e stack's: bringing it up there resets what a running stack's worker is "
        "using, and stopping it takes the stack down. "
        f'Run `uv run python -m nox -s "{session}"` instead.',
        returncode=pytest.ExitCode.USAGE_ERROR
    )
