"""Holds a running stack open until somebody says to stop.

`e2e` and `e2e_replay` bring the whole stack up, do their work and tear it
down, which is right for a suite and useless for a demo: the two screens worth
looking at - the shop's console and Argus's own page - exist only for as long
as the tests are running. This script is the "work" the `stack` session does
instead, so the same setup and the same teardown serve a person watching.

It prints where to look and then waits. Nothing here drives an incident: the
shop's console stages a scenario and fires its own alert, which is the truer
demo anyway - a real shop's monitoring notices without anybody pressing a
button on the watcher's side.
"""

from __future__ import annotations

import sys
import threading

SHOP_CONSOLE = "http://localhost:8080"
ARGUS_PAGE = "http://localhost:8000"


def main() -> None:
    print()
    print(f"  The shop's console   {SHOP_CONSOLE}")
    print(f"  Argus's own page     {ARGUS_PAGE}")
    print()
    print("  Stage a scenario on the shop's console; it fires the alert itself.")
    print("  Press Enter, or interrupt this session, to bring the stack down.")
    print()

    try:
        _wait()
    except KeyboardInterrupt:
        print()


def _wait() -> None:
    """Blocks until a person ends it, however this script was started.

    Enter is the obvious way and works whenever there is somebody at a
    keyboard. Started from a launcher there is not, and `input()` reads EOF and
    returns immediately - which would bring the stack up and take it down again
    inside a second, a failure indistinguishable from one that never started.
    So EOF falls through to a wait that only an interrupt ends.

    The EOF is caught rather than predicted: `sys.stdin.isatty()` answers `True`
    for some non-interactive parents, so a branch on it is a guess, and the
    thing being guessed at is already reported plainly by the read itself.
    """
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input()
            return
    except EOFError:
        pass

    threading.Event().wait()


if __name__ == "__main__":
    main()
