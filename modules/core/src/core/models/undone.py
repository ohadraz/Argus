"""What became of one attempt to put a change back.

Here rather than beside the code that undoes a flag, for the reason `Verdict`
is here: the agent that restores names it, the event that accounts for the
restore carries it, and the page reads it back. A vocabulary kept inside one of
those parties is one the others read by comparing spellings.
"""

from __future__ import annotations

from enum import StrEnum


class Undone(StrEnum):
    """What became of one attempt to put a change back.

    Five answers, not two, because "nothing was written" has several meanings
    and a caller's next move differs between them. `LEFT_AS_FOUND` is a
    decision: the subject holds something Argus did not set, so somebody
    changed it and it is no longer Argus's to restore - and nothing of Argus's
    is left standing beside it. `NOT_ESTABLISHED` is an absence: the provider or
    the platform could not say what the subject holds, and writing on a reading that never
    came back is the blind restore the check exists to prevent.

    `LEFT_STANDING` is the same decision with something of Argus's still in
    place. The subject was somebody else's since, so it was left as they set
    it - and the reconciliation Argus suspended to make its change still
    stands, because resuming it would have the platform re-apply git over
    theirs. Whether to turn it back on is a person's call, so it escalates; and
    it is settled, since a second pass would find the same and decide the same.

    `NO_UNDO_WAS_OWED` is the fifth, and it is the only one that is not the
    outcome of an attempt - it is the answer where no attempt was due. A
    discard of stale cached figures changed something real and owes nothing
    back: what it removed was derived from records it never touched, and
    writing those figures back would be recreating the incident rather than
    undoing it. Silence would have said this too, and said it in the same
    breath as an action the gate refused, which changed nothing at all. Those
    are different facts about a withdrawn incident and a reader should not have
    to tell them apart by what is missing.

    Reported rather than raised. An unwind runs over every change an incident
    made, and one flag nobody can read must not stop the others being put back.
    """

    RESTORED = "restored"
    LEFT_AS_FOUND = "left-as-found"
    LEFT_STANDING = "left-standing"
    NOT_ESTABLISHED = "not-established"
    NO_UNDO_WAS_OWED = "no-undo-was-owed"
