"""Runs several nox sessions at once and fails if any of them fails.

The commit hook's checks - the type check and the guards - each read the whole
repository and write nothing, so none waits on another. Run one after another
they cost the sum of their times; side by side they cost the slowest one's.

Each session's output is held until it ends and printed whole under a line
naming it, so two sessions' lines never interleave.

Usage: python scripts/run_sessions_together.py <session> [<session> ...]
"""

from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple


class Finished(NamedTuple):
    """One session, as it ended."""

    session: str
    passed: bool
    seconds: float
    output: str


def _run(session: str) -> Finished:
    """One nox session, through the interpreter rather than the `nox` shim."""
    started = time.monotonic()
    ran = subprocess.run(
        [sys.executable, "-m", "nox", "-s", session],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        # Said rather than left to the console, whose code page on Windows
        # cannot decode what nox and mypy print.
        encoding="utf-8", errors="replace"
    )
    return Finished(session, ran.returncode == 0, time.monotonic() - started, ran.stdout)


def main(sessions: list[str]) -> int:
    """Every session at once; the exit status says whether all of them passed."""
    with ThreadPoolExecutor(max_workers=len(sessions)) as pool:
        finished = list(pool.map(_run, sessions))

    for each in finished:
        verdict = "passed" if each.passed else "FAILED"
        print(f"=== {each.session}: {verdict} in {each.seconds:.0f}s ===")
        if not each.passed:
            print(each.output)

    failed = [each.session for each in finished if not each.passed]
    if failed:
        print(f"Failed: {', '.join(failed)}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
