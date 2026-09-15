from __future__ import annotations

from dataclasses import dataclass

from argus_core.models.hypothesis import Hypothesis
from argus_core.models.reading import Reading


@dataclass(frozen=True)
class Findings:
    """What one investigation concluded, and what it read to conclude it.

    Named for the product rather than the process: an investigation is the
    thing that runs, and this is what it hands back.

    `candidates` is every explanation the model offered, best first, and is
    never empty - an investigation that identified no cause says so in one
    candidate carrying the reason. Whether any of them is worth acting on is
    the mitigate threshold's business, not this type's.

    `already_read` is what a later round cannot work out for itself. A round is
    bought by a refutation, not by a wider window, and the round that follows
    should know what the one before it saw - both so it does not pay again for
    the same evidence, and so that a channel nobody asked for stays
    distinguishable from one that was asked and came back empty.

    A contract rather than the Investigator's own type, because the walk names
    it too: the node that investigates hands one to the node that decides, and
    a shape kept inside the agent is one the Orchestrator installs an agent to
    read.
    """

    candidates: list[Hypothesis]
    already_read: list[Reading]
