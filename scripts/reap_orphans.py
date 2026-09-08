"""Kills the services a nox run started, when that run stops being able to.

POSIX's answer to the Windows job object, and the same idea by a different
mechanism. A job kills what it holds when the last handle to it closes; this
holds the read end of a pipe whose only writer is the run that started it, so
reading it returns EOF exactly when that run ends - cleanly, on a signal it
never handled, killed outright, or with the terminal simply closed. Nothing has
to run in the dying process for this to happen, which is the whole point:
teardown that has to survive a kill cannot live in the process being killed.

A pipe rather than a poll of the parent's pid, because the pipe is
edge-triggered and needs no interval to be chosen, and rather than
`PR_SET_PDEATHSIG`, which does the same thing natively and only on Linux. macOS
has no equivalent, and a repo with contributors on both should not have a
guarantee that quietly holds on one of them.

The run says `+<pid>` when it starts a service and `-<pid>` when it stops one,
so what is left at EOF is exactly what it did not get to stop. Without the
second half this would hold the pid of every service a long run ever started,
and kill whatever had been given that number in the meantime.
"""

from __future__ import annotations

import contextlib
import os
import signal
import sys
import time

# How long a service is given to end on its own before it is made to. It is
# already parentless by the time this runs, so there is nothing left for it to
# report to - but uvicorn closes its sockets on the way out, and a port
# released now is one the next run does not refuse to start over.
_SECONDS_TO_GO_QUIETLY = 5.0
_SECONDS_BETWEEN_LOOKS = 0.1


def _the_services_still_in_this_run() -> set[int]:
    """Reads until the run that started this one ends, and says what it left.

    The loop ends at EOF and at nothing else. A malformed line is ignored
    rather than fatal: this process's whole value is that it is still alive
    later, and there is no one to report a parsing complaint to anyway.
    """
    live: set[int] = set()

    for line in sys.stdin:
        entry = line.strip()

        if not entry[1:].isdigit():
            continue

        if entry.startswith("+"):
            live.add(int(entry[1:]))
        elif entry.startswith("-"):
            live.discard(int(entry[1:]))

    return live


def _stopped(pid: int) -> None:
    """Ends one service, politely and then not.

    Signals the process group rather than the process: every service is started
    in a session of its own, so the group is the service and whatever it went
    on to spawn - and a grandchild left holding the port would make this whole
    file pointless.
    """
    try:
        group = os.getpgid(pid)
        os.killpg(group, signal.SIGTERM)
    except OSError:
        return

    deadline = time.monotonic() + _SECONDS_TO_GO_QUIETLY

    while time.monotonic() < deadline:
        try:
            os.killpg(group, 0)
        except OSError:
            return

        time.sleep(_SECONDS_BETWEEN_LOOKS)

    with contextlib.suppress(OSError):
        os.killpg(group, signal.SIGKILL)


def main() -> None:
    for pid in _the_services_still_in_this_run():
        _stopped(pid)


if __name__ == "__main__":
    main()
