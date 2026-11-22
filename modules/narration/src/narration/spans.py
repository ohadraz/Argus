"""A span of time said as a person says it: days, hours, minutes and seconds,
naming only the units it has.

One rule in one place, because the postmortem's figures and narration's windows
each say how long something lasted, and a span said two ways on one page - "1446
minutes" in one line and "1 day 6 minutes" in the next - is two figures to a
reader comparing them.
"""

from __future__ import annotations

from datetime import timedelta


def said_as_a_span(span: timedelta) -> str:
    """A span in the units it has and only those, exact to the second.

    Never a fraction of a unit. "0.10 hours" is six minutes a reader has to
    work out, and a model handed it either works it out or repeats the figure.
    Exact to the second, like every instant the model reads: what it is given
    is the measurement, not a rounding of it.
    """
    seconds = span // timedelta(seconds=1)

    if seconds < 1:
        return "less than a second"

    days, seconds = divmod(seconds, 24 * 60 * 60)
    hours, seconds = divmod(seconds, 60 * 60)
    minutes, seconds = divmod(seconds, 60)

    return " ".join(f"{count} {unit}{'s' if count != 1 else ''}"
                    for count, unit in ((days, "day"), (hours, "hour"),
                                        (minutes, "minute"), (seconds, "second"))
                    if count)
