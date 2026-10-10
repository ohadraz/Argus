"""Captures one real classification of a person's message, as a recording the
intent agent's double replays.

    uv run python -m scripts.record_classification <name> "<message>"

For example `intent-resolve "rolled the flag back by hand, we're fine"`.

A walk's recordings are captured by driving a whole incident through a stack
(`scripts/record_incident.py`). A classification needs none of that: the
intent agent asks the model one question about one message and nothing about the
world, so this starts the Anthropic double on a port of its own, tells it to
record, and asks the question through it with the intent agent's own classifier -
the prompt, the tool and the adapter the intent agent sends, which is what makes
the stored answer one a replay can stand on.

Stored under the name as given, with no mode in front of it. A mode is the set
of tools a walk is offered to find code with, and a classification is offered one tool
whatever the mode - which is also how `guard_recordings` tells the two apart.

One small paid call, and it needs `ANTHROPIC_API_KEY`. Refused, and nothing
kept, where the first answer could not be used: the classifier asks a second time,
and a recording of two answers is one a case seeding a single answer replays
half of.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from typing import Any, Final

import httpx2
import uvicorn
from agent_intent.classifying import classify
from anthropic_double.recordings import RECORDINGS_DIR
from anthropic_double.server import app as the_double
from argus_core import get_settings
from argus_core.llm import build_llm_client
from argus_core.models import ModelPolicy

# A port of its own, so this can run while a stack is up: the walk's double and
# the intent agent's are that stack's while it runs.
_PORT: Final = 8099
_BASE_URL: Final = f"http://localhost:{_PORT}"

_A_MOMENT: Final = 0.05
_LONG_ENOUGH_TO_COME_UP: Final = 10.0


def main() -> None:
    """Classifies the message once, through the double in record mode, and says
    what was stored."""
    asked = _the_arguments()

    # Before anything reads a setting: the adapter is built from them, and this
    # is the one that points it at the double rather than at the API itself.
    os.environ["ANTHROPIC_BASE_URL"] = _BASE_URL
    settings = get_settings()

    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is not set, so there is no model to record.")

    server = uvicorn.Server(uvicorn.Config(the_double, host="localhost", port=_PORT,
                                           log_level="warning"))
    serving = threading.Thread(target=server.run, daemon=True)
    serving.start()

    try:
        _once_it_answers()
        httpx2.post(f"{_BASE_URL}/double-control/reset").raise_for_status()
        httpx2.post(f"{_BASE_URL}/double-control/record",
                    json={"name": asked.name}).raise_for_status()

        meaning = classify(asked.message,
                           llm=build_llm_client(policy=ModelPolicy(
                               model=settings.intent_model,
                               effort=settings.intent_effort)))
        answers = int(_the_double_holds()["recorded"])
    finally:
        server.should_exit = True
        serving.join(timeout=_LONG_ENOUGH_TO_COME_UP)

    if answers != 1:
        _throw_away(asked.name, answers)
        sys.exit(f"The model was asked {answers} times, so nothing was kept: a "
                 f"classification is one answer. Run it again.")

    print(f"Stored [{asked.name}]: the message classified as [{meaning}].")


def _the_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="what the recording is stored as, e.g. intent-resolve")
    parser.add_argument("message", help="what the person wrote, exactly")

    return parser.parse_args()


def _the_double_holds() -> dict[str, Any]:
    held: dict[str, Any] = httpx2.get(f"{_BASE_URL}/double-control/state").json()

    return held


def _throw_away(name: str, answers: int) -> None:
    """Removes every answer the run stored, so a refused run leaves nothing that
    reads as a recording."""
    for count in range(1, answers + 1):
        stored = RECORDINGS_DIR / (f"{name}.json" if count == 1 else f"{name}-{count}.json")
        stored.unlink(missing_ok=True)


def _once_it_answers() -> None:
    """Waits for the port, rather than guessing at how long a thread takes."""
    giving_up_at = time.monotonic() + _LONG_ENOUGH_TO_COME_UP
    while time.monotonic() < giving_up_at:
        try:
            httpx2.get(f"{_BASE_URL}/health", timeout=_A_MOMENT).raise_for_status()
            return
        except (httpx2.HTTPError, OSError):
            time.sleep(_A_MOMENT)

    raise RuntimeError(f"the anthropic double did not answer on {_BASE_URL} within "
                       f"{_LONG_ENOUGH_TO_COME_UP:.0f}s")


if __name__ == "__main__":
    main()
