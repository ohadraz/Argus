from __future__ import annotations

from collections.abc import Callable

Emit = Callable[[str], None]


def _to_stdout(line: str) -> None:
    print(line)


def post_update(incident_id: str, message: str, emit: Emit = _to_stdout) -> None:
    """Writes an update into the incident's war room (spec §7.5) - no Slack
    post, no email yet.

    Sent while Argus still has moves: an explanation was tried, it did not hold,
    and another one is about to be. It wakes nobody. Its job is that a human
    watching a walk can see it happening and step in, because a longer walk is
    a longer silence, and an incident being worked looks from outside exactly
    like an incident nobody is on.

    `emit` is the seam a real Slack/email adapter replaces.
    """
    emit(f"argus[{incident_id}] update: {message}")


def raise_page(incident_id: str, message: str, emit: Emit = _to_stdout) -> None:
    """Raises the page that ends an incident's autonomous phase (spec §7.5) -
    no Slack post, no email yet.

    Sent once, when the walk is out of moves and a person is required. It is a
    separate function rather than a severity argument because the difference is
    not one of wording: a page interrupts someone, and one raised per refuted
    candidate would teach its readers to ignore pages, which costs more than
    the pages are worth.

    It used to be `notify`, which raised `NotImplementedError` on the grounds
    that nothing routed here. That stopped being true the moment "Argus could
    not determine the cause" became a real outcome: escalation routes through
    the Communicator (§10), so a stub on that path has to *work*, even if all
    it does is say what it would have sent.
    """
    emit(f"argus[{incident_id}] PAGE: {message}")
