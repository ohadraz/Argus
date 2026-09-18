"""What memory is allowed to do to a walk, which is to change an order.

A subject that was changed on a similar incident and did not help goes to the
back of the list. Everything else keeps the order confidence gave it, so a walk
with no matching record behaves exactly as a walk with no memory at all - which
is what lets the benchmark (§21) compare the two.

**Demoted, never removed.** A past incident is evidence about a past incident,
the same flag can break the service twice, and a walk that refused to try the
only candidate it had - on the strength of a different incident's result - would
end in an escalation it had the means to avoid. The set of candidates tried is
identical with memory and without it; only the order differs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from argus_core.models import Hypothesis, Verdict

from incident_memory.records import RememberedIncident


@dataclass(frozen=True)
class Reordering:
    """The candidates in the order to try them, and what moved them.

    `on_the_strength_of` is the past incident whose record demoted something,
    and `None` where nothing moved - which is the ordinary case and the one that
    must stay silent. A walk that tried its second-best candidate first with
    nothing saying why is a walk a human reading the incident back cannot
    account for; a walk that says so on every incident is a timeline nobody
    reads.
    """

    candidates: list[Hypothesis]
    # The subject that moved, beside the record that moved it. Both or neither:
    # a line saying an order changed without saying what changed places is a
    # line a reader cannot check against the list in front of them.
    moved: str | None
    on_the_strength_of: str | None


def demoting_what_was_refuted(candidates: list[Hypothesis],
                              recalled: Sequence[RememberedIncident]) -> Reordering:
    """The candidates again, with anything refuted before moved to the back.

    Stable on both sides of the split: candidates memory says nothing about keep
    their order among themselves, and so do the demoted ones. Demotion is
    relative, so demoting every candidate demotes none of them - and the walk
    still tries them all, which is the point.

    A candidate naming no subject is left where it is. There is nothing for a
    record to match it against, and moving it would be moving it for a reason
    nobody could read back.
    """
    refuted_by = _what_refuted_each_subject(recalled)
    kept = [
        candidate for candidate in candidates
        if candidate.subject is None or candidate.subject not in refuted_by
    ]
    demoted = [
        candidate for candidate in candidates
        if candidate.subject is not None and candidate.subject in refuted_by
    ]
    reordered = [*kept, *demoted]

    if reordered == candidates:
        return Reordering(candidates=candidates, moved=None, on_the_strength_of=None)

    # The first candidate that actually moved, and the record that moved it.
    # One of each rather than all of them: the line this becomes is read during
    # an incident, and "because of these four" is a list a person scanning a
    # timeline does not follow.
    moved = str(demoted[0].subject)

    return Reordering(
        candidates=reordered,
        moved=moved,
        on_the_strength_of=refuted_by[moved]
    )


def _what_refuted_each_subject(
    recalled: Sequence[RememberedIncident]
) -> dict[str, str]:
    """Each subject a recalled incident acted on and refuted, and which one did.

    Only a refutation. A confirmation says changing that subject once fixed an
    incident, which is no reason at all to try it later - and the two verdicts
    are the only ones a record can carry, because nothing else was ever a
    judgement about the subject.

    The nearest record wins a subject two of them name, since `recalled` arrives
    ordered by similarity and the more alike incident is the better evidence.
    """
    refuted_by: dict[str, str] = {}

    for incident in recalled:
        for attempt in incident.tried:
            if attempt.verdict is Verdict.REFUTED:
                refuted_by.setdefault(attempt.subject, incident.incident_id)

    return refuted_by
