"""How each kind of evidence is labelled for citing, and the labels' own rules.

Beneath everything else in the package: the prompt gives the labels, the
document's rows carry them, and the model's answer cites them, so each of those
reads them from here rather than from one another.
"""

from __future__ import annotations

from typing import Final

# How an action item is named in conversation: `AI-1`, `AI-2`.
ACTION_ITEM_PREFIX = "AI-"

# How a contributing factor is labelled in the model's answer, for the items it
# proposes to name: `CF-1`, `CF-2`. Never shown to a reader.
CONTRIBUTING_FACTOR_PREFIX: Final = "CF-"

# How each kind of evidence is labelled for citing: a line of the narration
# `T1`, a change to production `P1`, a candidate `C1`, an action `M1` - and a
# group of log lines by its message, `G3fa2` (`log_groups`). Not `A` for an
# action: an action item is `AI-1`, and the two read alike. Not `C` for a
# change, which a candidate already is. Here rather than with the prompt,
# because the rows of the document carry the same labels the prompt gave, so
# the prose that cites one can be pointed at its row.
#
# A line of the narration outside the walk - a person's message, what was made
# of it, the relay failing to post - is `XW1`, counted apart from the walk's
# own: where one lands among them is timing, and counted with them a message
# written a second earlier would rename every line of the walk after it.
#
# What the alert said is `AL1`. Not `A`, which its figures are already named by
# (`{A1}`): a label and a figure's name that read alike are a citation of a
# number.
ALERT_PREFIX: Final = "AL"
NARRATION_PREFIX: Final = "T"
OUTSIDE_THE_WALK_PREFIX: Final = "XW"
PRODUCTION_CHANGE_PREFIX: Final = "P"
DEPLOYMENT_CHANGES_PREFIX: Final = "D"
CODE_READING_PREFIX: Final = "F"
AS_IT_RAN_PREFIX: Final = "S"
# How the code outside Code-Fix's patch uses what it changes, read off the code.
USES_OUTSIDE_PREFIX: Final = "U"
CANDIDATE_PREFIX: Final = "C"
ACTION_PREFIX: Final = "M"
# What the metrics show of a cause confirmed to be the load, measured by Argus:
# `R1`, R for its rows - not "reading", which is already a retrieval
# (`core.models.Reading`).
CAUSE_MEASURED_PREFIX: Final = "R"


def label_of(prefix: str, position: int) -> str:
    """What the evidence of one kind at `position` (from 1) is cited as."""
    return f"{prefix}{position}"


def is_a_code_reading(label: str) -> bool:
    """Whether `label` cites a reading of the source - one nothing ran."""
    return label.startswith(CODE_READING_PREFIX) and label[len(CODE_READING_PREFIX):].isdigit()


def action_item_number(position: int) -> str:
    """What the action item at `position` (from 1) is called in conversation."""
    return f"{ACTION_ITEM_PREFIX}{position}"


def contributing_factor_label(position: int) -> str:
    """The label the contributing factor at `position` (from 1) is given under."""
    return f"{CONTRIBUTING_FACTOR_PREFIX}{position}"
