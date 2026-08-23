from __future__ import annotations

from collections.abc import Callable

Emit = Callable[[str], None]


def _to_stdout(line: str) -> None:
    print(line)


def notify(incident_id: str, message: str, emit: Emit = _to_stdout) -> None:
    """Stub Communicator (spec §7.5) - no Slack post, no email yet.

    It used to raise `NotImplementedError`, on the grounds that nothing routed
    here. That stopped being true the moment "Argus could not determine the
    cause" became a real outcome: escalation routes through the Communicator
    (§10), so a stub on that path has to *work*, even if all it does is say
    what it would have sent. A stub that raises on a reachable path turns an
    honest "I don't know" into a crash.

    `emit` is the seam a real Slack/email adapter replaces.
    """
    emit(f"argus[{incident_id}]: {message}")
