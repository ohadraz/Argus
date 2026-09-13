from __future__ import annotations

from argus_narration import NarrationLine

"""What a page adds to a line that every other destination does without.

The account is the same wherever it is read. A stylesheet and an anchor are
not: Slack has neither, and a renderer that produced them anyway would make
every destination carry the page's furniture - and would put the page's
vocabulary in the one module meant to outlast the choice of destination.

So this derives both from the line. The class comes off the word the line
already marks, the link off what the line is already about, and nothing here
knows an event from another.
"""

# How a marked word is dressed, by the kind of line it appears on. A status
# wears the badge the header gives it and a verdict wears red or green; every
# other marked word is a plain emphasis and wants no class at all.
_DRESSED_AS = {
    "status-changed": "moved-to",
    "verdict-reached": "verdict"
}

# What a link beside a line says, by the kind of line. A link points at a row
# or it does not exist: "show the metrics" beside a line that just read the
# metrics takes a reader to a table they were going to scroll to anyway.
_POINTS_AT = {
    "onset-detected": "show the minute",
    "action-taken": "the change it reverted"
}

# Which table a kind's row lives in, on the page below the account.
_ANCHORS = {
    "onset-detected": "minute",
    "action-taken": "flag"
}


class DecoratedLine(NarrationLine):
    """One line of the account, dressed for the page.

    A line with three more fields rather than a wrapper around one, so the
    template reads `line.who` and `line.emphasis_class` the same way and
    nothing downstream has to know which of the two it is holding.
    """

    # The class on the marked word. Empty where nothing is marked, or where
    # what is marked is a flag rather than a state the page has a colour for.
    emphasis_class: str = ""
    # Where the line points, when what it is about is in one of the tables
    # below it. An account that says "the incident started at 10:03" and leaves
    # a reader to find that minute is only half an account.
    link_target: str = ""
    link_label: str = ""


def decorated(line: NarrationLine) -> DecoratedLine:
    """One line, with the class and the link this page would give it."""
    target, label = _where_to_look(line)

    return DecoratedLine(
        **line.model_dump(),
        emphasis_class=_dressed_as(line),
        link_target=target,
        link_label=label
    )


def _dressed_as(line: NarrationLine) -> str:
    """How the marked word is styled, read off the word the line marked.

    From the line rather than from the event it came from, which is what keeps
    the two in step: the page cannot colour a status the account did not mark,
    and cannot mark one it did not colour.
    """
    dressed = _DRESSED_AS.get(line.kind)

    if dressed is None or not line.emphasis:
        return ""

    return f"{dressed} {line.emphasis.lower()}"


def _where_to_look(line: NarrationLine) -> tuple[str, str]:
    """The row a line points at, and what the link says.

    The onset names one minute out of ninety, and finding that minute by hand
    is the work the link saves. The action names one flag, so it points at that
    flag's own row - while the history line names all of them and points at
    none, because a link that cannot say which of four rows it means is
    furniture.
    """
    label = _POINTS_AT.get(line.kind)
    row = _the_row_named_by(line)

    if label is None or not row:
        return "", ""

    return f"#{_ANCHORS[line.kind]}-{row}", label


def _the_row_named_by(line: NarrationLine) -> str:
    """The value identifying the row this line is about, or nothing.

    The onset carries its minute as a fact about the incident; the action marks
    its flag as the word a reader scans for. Two fields because they are two
    different things, and neither exists to be linked.
    """
    if line.kind == "onset-detected":
        return line.names_minute

    return line.emphasis
