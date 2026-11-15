"""Collecting what the investigator reported instead of storing it."""

from __future__ import annotations

from argus_core.replay import ReplayEntry
from argus_testkit import Kept


def a_recorder_that_keeps_what_it_is_given() -> Kept[ReplayEntry]:
    """A recorder that collects entries instead of storing them.

    Handed over as `recorded.take` rather than as the object itself: a
    `Scenario` calls anything callable it is given, and a recorder that ran
    while the test was being arranged would record nothing and report it
    faithfully.
    """
    return Kept()
