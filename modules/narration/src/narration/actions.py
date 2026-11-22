"""What an action was for and whether it left something to put back, in the
words every place showing it uses."""

from __future__ import annotations


def for_the_candidate(label: str) -> str:
    """Which candidate an action was for, in the words every place showing it
    uses - the page's resolution and the brief the model writes from. Here for
    `whether_it_can_be_put_back`'s reason: two spellings of one fact read as
    two facts."""
    return f"for {label}"


def whether_it_can_be_put_back(has_a_way_back: bool, left_behind_known: bool) -> str:
    """Whether an action left something to put back, in the words every place
    showing it uses.

    Not "reversible" and "irreversible": those two name the autonomy tier
    (spec §13), where irreversible is the kind of action Argus never takes
    unasked. A restart has nothing to put back and is on the safe side of that
    line, and a page calling it irreversible said Argus had broken its own rule.

    Here rather than with whoever shows it, because the page and the brief the
    model writes from both say it, and two spellings of one fact read as two
    facts.

    An action nobody can account for is not said to leave nothing: it may have
    changed something nobody recorded. What it does carry can be put back.
    """
    if has_a_way_back:
        return "can be put back"

    return "nothing to put back" if left_behind_known else (
        "not known whether anything is left to put back"
    )
