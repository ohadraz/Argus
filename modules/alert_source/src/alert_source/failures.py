"""How a sender's adapter says a delivery could not be read."""

from __future__ import annotations


class AlertUnreadable(Exception):
    """A delivery the sender's shape does not fit.

    The sender's input rather than a fault in Argus, so refused rather than
    failed: a sender sends a failure again, and a delivery that could not be
    read once reads no better the next time. Says what was wrong with it, as
    the error that found it said.
    """
