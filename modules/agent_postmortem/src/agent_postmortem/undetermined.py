"""What a postmortem says of the cause where the investigation named none.

The document's own words rather than the model's. Asked for a root cause and a
plain-words cause with nothing to put in them, a write-up filled them with what
was checked - a flag provider's history said as though it covered more than the
hour it did - and the reader took a check for a finding.

So where nothing was named, the model is not asked: the document says the cause
was not determined, and what was read and where the evidence stops stays where
it already is, in the chain and in Supporting information.
"""

from __future__ import annotations

from typing import Final

from agent_postmortem.evidence import IncidentEvidence

# Said only of what the gate below holds: that the investigation named nothing.
# Not that the record shows nothing - a walk that ran out of budget after reading
# deploys and logs may hold a likely cause it never named.
NOT_DETERMINED: Final = "Not determined: the investigation named no cause."
# For a reader who does not work on the service, and of any alert: "the errors"
# would assume one that fired on errors.
NOT_KNOWN: Final = "The cause is not known."


def named_no_cause(evidence: IncidentEvidence) -> bool:
    """Whether the investigation ended naming no cause: candidates, and every
    one with no failure mode and no confidence - the shape an investigation
    gives its honest "nothing identified", whether it ran out, was cut short,
    was declined, was stopped, or had nothing to read.

    Not of a disproven alarm, whose candidate is shaped the same: its cause
    sentence says why the alarm was false, and that is the model's to write.
    Not of an incident with no candidates, which never reached an investigation
    and has no "named" to speak of.
    """
    return (not evidence.disproven
            and bool(evidence.candidates)
            and all(candidate.failure_mode is None and candidate.confidence is None
                    for candidate in evidence.candidates))
