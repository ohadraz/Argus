"""How a stored value is written for a reader.

Here rather than in the document because formatting belongs to whatever shows a
value: the postmortem keeps every amount at the precision it was computed to,
and only the page rounds. Registered as the templates' filters, so every amount
on every page is written one way.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from markupsafe import Markup, escape

_A_CENT: Final = Decimal("0.01")

# A whole commit as git names one: forty hex digits, lower case.
_A_WHOLE_COMMIT: Final = re.compile(r"[0-9a-f]{40}")

# How much of a commit git shows, and so how much a reader pastes back into it.
_A_SHORT_COMMIT: Final = 7


def as_money(amount: Decimal) -> str:
    """An amount to the cent, its thousands grouped: `1,736.68`.

    Half a cent rounds up, as a reader checking the figure by hand rounds it.
    """
    return f"{amount.quantize(_A_CENT, rounding=ROUND_HALF_UP):,}"


def as_span(span: timedelta) -> str:
    """A stretch of time to the second, from its largest unit down: `2m 40s`,
    `1h 0m 5s`, `7d 0h 3m 5s`, `45s`.

    Every unit below the first is said, zero or not, so each sits where a
    reader expects to find it.
    """
    seconds = round(span.total_seconds())
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    if days:
        return f"{days}d {hours}h {minutes}m {seconds}s"

    if hours:
        return f"{hours}h {minutes}m {seconds}s"

    if minutes:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"


def as_revision(revision: str) -> str:
    """A whole commit by its first seven characters, as git shows one:
    `26f1d7e`. Anything else as written.

    Only a whole commit is cut: a deployment's state is whatever the
    investigation called it, and a tag or a commit already short would lose
    the part that names it.
    """
    if _A_WHOLE_COMMIT.fullmatch(revision):
        return revision[:_A_SHORT_COMMIT]

    return revision


def with_references(prose: str, labels: Collection[str]) -> Markup:
    """Prose with every label it cites linked to the row of that name: `C1`
    becomes `<a href="#C1">C1</a>`.

    Only `labels` are linked - the ones with a row on the page - so a label
    the prose names and the page does not show stays plain text rather than
    a link to nowhere. A label is matched whole, so `AI-1` never links the
    start of `AI-12`. The prose is escaped first; only the links are markup.
    """
    escaped = str(escape(prose))
    if not labels:
        return Markup(escaped)

    named = "|".join(re.escape(label) for label in labels)
    cited = re.compile(rf"(?<!\w)(?:{named})(?!\w)")
    return Markup(cited.sub(lambda found: f'<a href="#{found[0]}">{found[0]}</a>', escaped))
