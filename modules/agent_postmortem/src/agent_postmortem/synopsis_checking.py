"""What is wrong with the executive synopsis's overview, said in words the
model can act on.

The postmortem's figure rules, run by the same code (`figure_rules`), and three
of the synopsis's own: an overview with nothing in it; one leaving out a figure
the record holds and a reader of it is owed - how long it lasted, what it cost
the business, what it cost the people who responded; and one speaking as "we".
Asked to write a summary, a model once left out how long the incident ran, and
both first overviews said "we" - once crediting a team with Argus's revert.

Each fault comes back under the rule that found it, so the conversation can
send each rule's faults back once.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

from agent_postmortem.figure_rules import figure_faults
from agent_postmortem.figures import Figure, names_in
from agent_postmortem.synopsis_prompting import required_figures

# The first person plural, as a word of its own: "US" dollars and "Argus" are
# not it.
_WE: Final = re.compile(r"\b(?:[Ww]e|[Oo]ur(?:s|selves)?|[Uu]s)\b")

# Words in quotation marks, straight or curly: a person's own, as the
# Resolution list quotes whoever ended the incident - their "we" is theirs.
_QUOTED: Final = re.compile("\"[^\"]*\"|“[^”]*”")


def overview_faults(overview: str, figures: Mapping[str, str]) -> dict[str, list[str]]:
    """Everything about the overview that has to be put right, under the rule
    that found it - only the rules that found something."""
    if not overview.strip():
        return {"an_empty_overview": ["your overview is empty - write the paragraph"]}

    found = figure_faults([overview],
                          {name: Figure(given=written, written=written)
                           for name, written in figures.items()})

    named = set(names_in(overview))
    unnamed = [f"your overview does not name [{{{name}}}] - name it where it goes"
               for name in required_figures(figures) if name not in named]
    if unnamed:
        found["figures_left_unnamed"] = unnamed

    as_we = [f'you wrote [{word}] - say "Argus", or who did it, never "we", "our" or "us"'
             for word in dict.fromkeys(_WE.findall(_QUOTED.sub("", overview)))]
    if as_we:
        found["speaking_as_we"] = as_we

    return found
