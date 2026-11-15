from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Disproof:
    """The window that held none of what an alarm claimed, said so it can be read.

    An alarm reporting a condition on a series the system also retrieves can be
    contradicted by that series. This is the contradiction: what was asked, of
    what, over how long. It exists at all because the claim it carries cannot be
    resolved against anything later - a reader handed only "the alarm was wrong"
    has to take it on trust, and a disproof made over a window too narrow to
    contain the condition reads exactly like a sound one.

    A contract rather than the Investigator's own type, because the walk, the
    status function, the narration and the postmortem all name it.

    `signals_judged` are the series a departure was looked for in, under the
    names the detector publishes them as - never a list restated here, which
    would let a disproof report having judged a signal nobody judged.

    `earliest_minute` and `latest_minute` are the ends of the window, as bucket
    ids, and `minutes_judged` is how many minutes it actually held. The count is
    not the span: a window whose readings stop part way through has fewer minutes
    in it than its ends suggest, and a disproof over such a window is weaker than
    one over a window with every minute present. Both are carried so that a
    reader can see which they were handed.
    """

    signals_judged: tuple[str, ...]
    earliest_minute: str
    latest_minute: str
    minutes_judged: int
