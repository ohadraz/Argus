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

    Three answers, not two, because "nothing was written" has two meanings and
    a caller's next move differs between them. `LEFT_AS_FOUND` is a decision:
    the flag holds something Argus did not set, so somebody changed it and it
    is no longer Argus's to restore. `NOT_ESTABLISHED` is an absence: the
    provider could not say what the flag holds, and writing on a reading that
    never came back is the blind restore the check exists to prevent.

    Reported rather than raised. An unwind runs over every change an incident
    made, and one flag nobody can read must not stop the others being put back.
    """

    RESTORED = "restored"
    LEFT_AS_FOUND = "left-as-found"
    NOT_ESTABLISHED = "not-established"
