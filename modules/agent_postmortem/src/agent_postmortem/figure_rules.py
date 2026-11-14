"""The rules that refuse a figure prose writes itself, over any sentences.

A figure the prose states is written in by code from the name the model gives
it (`figures`). Prose writing one itself - in digits, in a run of number words,
or in one word that measures something - is either repeating it or inventing
it, and a reader cannot tell which (`checking` says why at length). A name that
names no figure the incident gave is refused too: written in, it would be a
blank where a figure goes.

Over sentences rather than an answer, so the postmortem's checks and the
executive synopsis's run the same rules with the same words. Each rule's
faults come back under that rule's own name: a fault is sent back once per
rule, and one merged rule would keep a second answer a different rule would
refuse.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from itertools import pairwise
from typing import Final

from argus_core import the_revision_named

from agent_postmortem.figures import AROUND_A_WORD, Figure, is_a_figure, names_in

# A number said in a word: a count, a ten, a power of ten, or the fraction a
# decimal is read out in.
_A_NUMBER_WORD: Final = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
    r"|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty"
    r"|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million"
    r"|billion|tenths|hundredths|thousandths)\b"
)

# What joins two number words into one figure: a space or a hyphen, and an
# "and" only where a figure has one - after a power of ten ("a hundred and
# five"), or before the fraction it ends in ("and thirty-one hundredths").
# Anywhere else an "and" joins two numbers, each judged on its own: "between
# one and two replicas" is two counts of things, not one figure.
_A_JOIN: Final = (
    r"(?:\s+|-"
    r"|(?:(?<=hundred)|(?<=thousand)|(?<=million)|(?<=billion))\s+and\s+"
    rf"|\s+and\s+(?=(?:{_A_NUMBER_WORD}(?:\s+|-))*(?:tenths|hundredths|thousandths)\b))"
)

# A figure spelled out: number words, two or more, joined into one.
_A_FIGURE_SPELLED_OUT: Final = re.compile(
    rf"\b{_A_NUMBER_WORD}(?:{_A_JOIN}{_A_NUMBER_WORD})+",
    re.IGNORECASE
)

# What a number measures when one follows it: time, a share, or how many times
# another thing. Anything else after one is a count of things.
_A_UNIT: Final = (
    r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?"
    r"|percent|per\s+cent|percentage\s+points?|times)\b"
)

# A figure said in one word: a span of one unit ("a minute", "an hour and a
# half"); a number word, or a half, measuring something ("twenty minutes", "half
# an hour", "three times"); a word that is a multiple ("tripled", "twice"); or a
# fraction ("a third", "two thirds"). Joined to what it measures by a space only
# - "one-minute buckets" describes the buckets, and measures nothing.
#
# Only third, fifth and tenth, said singly, double as ordinals: "a
# third-party service", "a third time". Those are a fraction only where they
# are of something or more or fewer of it ("a third of the requests", "a third
# more requests"), or end the phrase - at a stop or a spaced dash ("fell by a
# third - the worst week"). A half, a quarter and every plural are fractions
# wherever they stand.
#
# The span is first, and takes its "and a half" with it, so that one figure is
# one fault rather than a span and a fraction. Its units are the ones Argus
# measures between its own instants: "a second" is an ordinal as often as a span
# ("a second candidate"), and "a month" is the shop's own noun for a statement
# period, which no span here reaches.
_A_FIGURE_IN_A_WORD: Final = re.compile(
    r"\b(?:a|an)\s+(?:minute|hour|day|week)(?:\s+and\s+a\s+half)?\b"
    rf"|\b(?:{_A_NUMBER_WORD}|half(?:\s+an?)?)\s+{_A_UNIT}"
    r"|\b(?:doubled|tripled|quadrupled|halved|twice|thrice)\b"
    r"|\b(?:a|one|two|three|four)\s+(?:half|halves|thirds|quarters?|fifths|tenths)\b"
    r"|\b(?:a|one|two|three|four)\s+(?:third|fifth|tenth)\b"
    r"(?=\s+(?:of|more|less|fewer|higher|lower)\b|\s+-|\s*(?:[.,;:!?)]|$))",
    re.IGNORECASE
)

# The words after which a number is a place in a source file, not a figure.
_A_PLACE_IN_A_FILE: Final = frozenset({"line", "lines"})

# What every fault about a figure asks for instead.
_STATE_IT_BY_ITS_NAME: Final = (
    "write a figure the incident gave as the name shown after it, braces and all, "
    "or a working of two such names ({a - b}, {a / b}), and say any other size with "
    "no number in it (\"most requests\", \"several minutes\")"
)


def figure_faults(sentences: Collection[str],
                  figures: Mapping[str, Figure],
                  *,
                  revisions: frozenset[str] = frozenset(),
                  quoted: Collection[str] = frozenset()) -> dict[str, list[str]]:
    """Every figure the sentences write themselves, and every name they give
    that no figure has, under the name of the rule that found it - only the
    rules that found something."""
    found = {
        "numbers_in_digits": numbers_in_digits(sentences, revisions),
        "figures_spelled_out": figures_spelled_out(sentences),
        "figures_said_in_a_word": figures_said_in_a_word(sentences),
        "figures_nobody_gave": figures_nobody_gave(sentences, figures, quoted)
    }

    return {rule: faults for rule, faults in found.items() if faults}


def numbers_in_digits(sentences: Iterable[str], revisions: frozenset[str]) -> list[str]:
    """Every word of the prose that is a figure written in digits.

    Word by word, so the fault names the number as the reader would see it -
    `33.8%`, `$1,200,000`, `21:45` - rather than a fragment of it.

    Not a line of source. "line 47" says where in a file, not how much of
    anything, and refused it could only be spelled out - which is refused too.

    Nor a revision the incident read, named by a start that happens to be all
    digits: one in about thirty begins with seven digits, and its short form is the
    name the evidence gives it.
    """
    return [
        f"your answer writes [{word}] in digits - {_STATE_IT_BY_ITS_NAME}"
        for prose in sentences
        for before, word in pairwise(
            ["", *(each.strip(AROUND_A_WORD) for each in prose.split())]
        )
        if is_a_figure(word)
        and before.lower() not in _A_PLACE_IN_A_FILE
        and the_revision_named(word, revisions) is None
    ]


def figures_spelled_out(sentences: Iterable[str]) -> list[str]:
    """Every run of number words in the prose that says one figure.

    The whole run, so the fault quotes the figure as the reader would meet it -
    `one thousand two hundred ninety-seven and thirty-one hundredths` - rather
    than a word of it.
    """
    return [
        f"your answer spells out [{spelled.group(0)}] in words - {_STATE_IT_BY_ITS_NAME}"
        for prose in sentences
        for spelled in _A_FIGURE_SPELLED_OUT.finditer(prose)
    ]


def figures_said_in_a_word(sentences: Iterable[str]) -> list[str]:
    """Every figure the prose says in one word, as it says it.

    Not one inside a figure already spelled out: "twenty-four hours" is one
    figure, refused once, as spelled out.
    """
    return [
        f"your answer says [{said.group(0)}] in words - {_STATE_IT_BY_ITS_NAME}"
        for prose in sentences
        for spelled in [[out.span() for out in _A_FIGURE_SPELLED_OUT.finditer(prose)]]
        for said in _A_FIGURE_IN_A_WORD.finditer(prose)
        if not any(start < said.end() and said.start() < end for start, end in spelled)
    ]


def figures_nobody_gave(sentences: Iterable[str],
                        figures: Mapping[str, Figure],
                        quoted: Collection[str]) -> list[str]:
    """Each figure's name in the prose that names no figure the incident gave.

    Written in, it would be a blank where a figure goes - and nothing here can
    know which figure it meant. Not a word the evidence itself holds in braces:
    that is the evidence's text, quoted, and is left as written.
    """
    return [
        f"your answer names [{{{name}}}], which is no figure you were given - write a "
        f"figure's name exactly as it is shown after the figure, or say the size "
        f"with no number in it"
        for prose in sentences
        for name in names_in(prose)
        if name not in figures and name not in quoted
    ]
