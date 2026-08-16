from __future__ import annotations


def notify(incident_id: str, message: str) -> None:
    """Stub Communicator (spec §7.5) - exists as a real graph node so the
    FSM's shape is complete (design.md Non-Goals), but this change's happy
    path never routes to it. No Slack/email call."""
    raise NotImplementedError(
        "Communicator is not driven end-to-end in the walking-skeleton change"
    )
