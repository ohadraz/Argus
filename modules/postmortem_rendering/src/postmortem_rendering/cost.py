"""What the response cost: the people's minutes and what they were, and Argus's
tokens.

What the minutes cost in pay is not here, though it is stored: divided by the
minutes, any figure for it is a responder's rate of pay - and with one
responder and their title beside it, that person's band.
"""

from __future__ import annotations

from argus_core.models import PostmortemDocument

from postmortem_rendering.impact import Card


def the_cost(postmortem: PostmortemDocument) -> tuple[Card, ...]:
    """The same cards as the impact, figure first: person-minutes, with how
    many people and what they were, and the tokens Argus spent."""
    label = "engineer time"
    if postmortem.responders:
        label += f", {postmortem.responders} responder{'' if postmortem.responders == 1 else 's'}"
    if postmortem.responder_titles:
        label += f" ({', '.join(postmortem.responder_titles)})"

    minutes = postmortem.engineer_minutes
    tokens = postmortem.tokens_spent

    return (Card(value=f"{minutes} min" if minutes is not None else "not recorded", label=label),
            Card(value=f"{tokens:,}" if tokens is not None else "not recorded",
                 label="tokens spent by Argus"))
