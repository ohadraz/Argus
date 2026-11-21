"""The spaces Argus's two-key advisory locks are taken in.

Postgres names an advisory lock by two 32-bit keys, and the first says what
kind of thing is held: two locks for different purposes that happened to share
a key would hold each other up for reasons neither could see. Every such space
is a member here, side by side, so a new one is chosen next to the ones it must
not collide with - and `unique` refuses one that does.

One lock of Argus's is not here: the memory deliverer's, which takes the
one-key form, a single 64-bit key (`incident_memory.delivering`). That package
may not import this one, so it could not name its space here - and needs no
name here, since Postgres tags a one-key lock and a two-key lock apart, and the
two forms never meet whatever their numbers.
"""

from __future__ import annotations

from enum import IntEnum, unique


@unique
class AdvisoryLock(IntEnum):
    """What a two-key advisory lock holds, by its first key."""

    # A run the write tier is changing the world for (`runs.hold_for_a_change`).
    RUN_HELD_FOR_A_CHANGE = 1
    # A service whose alerts are being taken in (`incidents.take_in_alone`).
    INTAKE_FOR_A_SERVICE = 2
