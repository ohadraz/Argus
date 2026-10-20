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

It is also what `-- --hold` runs once each case is done, before its world is
put back, so what the case left - the database, the page - can be read before
the suite empties it. A suite
held in the background has nobody at its keyboard, and killing it would skip
the teardown and leave its services holding their ports; so it lets go too
when `RELEASE` appears, and takes the file away again.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

SHOP_CONSOLE = "http://localhost:8080"
ARGUS_PAGE = "http://localhost:8000"

# The file whose appearing lets a held stack go. Under the repository's own
# ignored local directory, so creating it changes nothing anybody commits.
RELEASE = Path(__file__).resolve().parent.parent / ".claude" / "local" / "release-the-stack"

# How often the release file is looked for. Often enough that nobody waits on
# it, rarely enough that looking costs nothing.
_LOOK_EVERY_SECONDS = 1.0


def main() -> None:
    print()
    print(f"  The shop's console   {SHOP_CONSOLE}")
    print(f"  Argus's own page     {ARGUS_PAGE}")
    print()
    print("  Stage a scenario on the shop's console; it fires the alert itself.")
    print("  Press Enter, or interrupt this session, to bring the stack down -")
    print(f"  or, from anywhere, create {RELEASE}")
    print()

    try:
        wait_until_told_to_stop()
    except KeyboardInterrupt:
        print()


def wait_until_told_to_stop() -> None:
    """Blocks until a person ends it, however this script was started.

    Enter is the obvious way and works whenever there is somebody at a
    keyboard. Started from a launcher there is not, and `input()` reads EOF and
    returns immediately - which would bring the stack up and take it down again
    inside a second, a failure indistinguishable from one that never started.
    So EOF leaves the wait to the other two: an interrupt, or `RELEASE`
    appearing, which is the one a run held in the background is let go by.

    The EOF is caught rather than predicted: `sys.stdin.isatty()` answers `True`
    for some non-interactive parents, so a branch on it is a guess, and the
    thing being guessed at is already reported plainly by the read itself. Read
    on a thread of its own, so the release file is looked for while it waits.
    """
    told = threading.Event()
    threading.Thread(target=_wait_for_enter, args=(told,), daemon=True).start()

    while not told.wait(_LOOK_EVERY_SECONDS):
        if RELEASE.exists():
            RELEASE.unlink()
            return


def _wait_for_enter(told: threading.Event) -> None:
    """Sets `told` when Enter is pressed - and never, where there is no
    keyboard to press it on."""
    try:
        if sys.stdin is not None:
            input()
            told.set()
    except EOFError:
        pass


if __name__ == "__main__":
    main()
