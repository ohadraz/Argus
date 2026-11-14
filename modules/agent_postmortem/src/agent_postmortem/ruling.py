"""What the record rules out, said as the record says it.

Asked what else the record ruled out, a write-up restates a read in its own
words, and restating is where it goes wrong: "flag changes before it were not
read", over a row that read them for the whole day before. So where a rule-out
rests on Argus's own reads alone, code says it - the class of change each read
found none of, which the narration worked out from what came back, then the
reads' own lines - and the model's words go.

Where it rests on anything else they stay, for the grounding judge to read: on
evidence of another kind, on a person's word, on a read that found something,
on an attempt judged refuted (whose subject may still be the cause), or on a
line of a document written before lines said what they ruled out. And where it
rests only on rows that never rule anything out - the metrics read, the onset,
the candidates formed - and names nothing that could be ruled out, it is no
rule-out at all, and is dropped.

Within one step, the rule-outs code says that share a read or a class are said
as one, where the first of them stood: said each alone, a read shared is said
twice, and a class shared heads two rule-outs, which reads as two things ruled
out.

On the answer as the model sent it: after the checks have read it, and before
the figures are written in, since a figure it names is how it names a change.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

from argus_core.models import RetrievalChannel, TimelineEntry

from agent_postmortem.prompting import SubmittedPostmortem, SubmittedRuledOut
from agent_postmortem.sections import said_as_a_clause

# The kinds of line the pairing reads, as the events name them.
_REQUESTED: Final = "retrieval-requested"
_CHANGES_READ: Final = "changes-retrieved"
# The lines that never rule anything out, whatever they found: what the
# service did, when the incident began, and what Argus made of it.
_NEVER_RULING: Final = frozenset({"metrics-retrieved", "logs-retrieved", "onset-detected",
                                  "anchored-on-the-alarm", "hypothesis-formed",
                                  "candidate-selected", "candidates-reordered"})


def with_what_the_record_rules_out(answer: SubmittedPostmortem,
                                   rows: Mapping[str, TimelineEntry],
                                   named_outside: frozenset[str]) -> SubmittedPostmortem:
    """The answer with each rule-out resting on Argus's reads alone said as
    the record says it - those in one step that share a read or a class said
    as one - each resting on nothing that rules out dropped, and the rest as
    the model wrote them.

    `rows` are the timeline's lines by label, in the order they happened;
    `named_outside` the labels of evidence outside the timeline a rule-out may
    name - a change, a log group - which makes one resting on the metrics a
    rule-out of that.
    """
    if not answer.causal_chain:
        return answer

    ordered = list(rows)

    return answer.model_copy(update={"causal_chain": [
        step.model_copy(update={
            "ruled_out": _ruled_step(step.ruled_out, rows, ordered, named_outside)})
        if step.ruled_out else step
        for step in answer.causal_chain]})


def is_said_by_code(entry: SubmittedRuledOut,
                    rows: Mapping[str, TimelineEntry],
                    named_outside: frozenset[str]) -> bool:
    """Whether code says this rule-out in the record's words, or drops it -
    either way, none of the model's words in it reach a reader.

    Decided entry by entry, on the answer as the model sent it: a dropped
    rule-out moves every later one in its step up a place, and so does one
    merged into an earlier one, so a place counted on the ruled answer names
    another entry of the answer as sent.
    """
    ruled = _ruled(entry, rows, list(rows), named_outside)
    return ruled is None or ruled.by_the_record


def _ruled_step(entries: list[SubmittedRuledOut],
                rows: Mapping[str, TimelineEntry],
                ordered: list[str],
                named_outside: frozenset[str]) -> list[SubmittedRuledOut]:
    """One step's rule-outs, ruled - those code says that share a read or a
    class said as one, in the place the first of them stood.

    Said each alone, two that share a read say it twice, and two that share a
    class head it twice, which reads as two things ruled out. Joined through
    any one that shares with two, so the one between them cannot leave a read
    said in two places. Those that share nothing stay apart, as the model gave
    them. Of the rest, `_ruled` keeps the model's own in their words and drops
    those resting on nothing that rules out.
    """
    said_by_code = {place: reads for place, entry in enumerate(entries)
                    if (reads := _the_reads_code_says(entry, rows, ordered)) is not None}
    merged = _merged(said_by_code, rows)
    ruled: list[SubmittedRuledOut] = []

    for place, entry in enumerate(entries):
        if place in merged:
            ruled.append(_said_by_the_record(
                [read for member in merged[place] for read in said_by_code[member]],
                rows, ordered))
        elif place not in said_by_code and (
                kept := _ruled(entry, rows, ordered, named_outside)) is not None:
            ruled.append(kept)

    return ruled


def _merged(said_by_code: Mapping[int, list[tuple[str, ...]]],
            rows: Mapping[str, TimelineEntry]) -> dict[int, list[int]]:
    """The places of the rule-outs code says, grouped by what they share,
    each group under the place of its first."""
    groups: list[list[int]] = []

    for place, reads in said_by_code.items():
        touching = [group for group in groups
                    if any(_share(reads, said_by_code[member], rows) for member in group)]
        groups = [group for group in groups if group not in touching] + [
            sorted({member for group in touching for member in group} | {place})]

    return {group[0]: group for group in groups}


def _share(reads: list[tuple[str, ...]],
           others: list[tuple[str, ...]],
           rows: Mapping[str, TimelineEntry]) -> bool:
    """Whether two rule-outs code says share a line of a read, or a class of
    change their reads found none of."""
    def labels(of: list[tuple[str, ...]]) -> set[str]:
        return {label for read in of for label in read}

    def classes(of: list[tuple[str, ...]]) -> set[str]:
        return {rows[read[-1]].rules_out for read in of}

    return bool(labels(reads) & labels(others) or classes(reads) & classes(others))


def _ruled(entry: SubmittedRuledOut,
           rows: Mapping[str, TimelineEntry],
           ordered: list[str],
           named_outside: frozenset[str]) -> SubmittedRuledOut | None:
    reads = _the_reads_code_says(entry, rows, ordered)
    if reads is not None:
        return _said_by_the_record(reads, rows, ordered)

    if _rests_on_nothing_that_rules_out(entry, rows, named_outside):
        return None

    return entry


def _the_reads_code_says(entry: SubmittedRuledOut,
                         rows: Mapping[str, TimelineEntry],
                         ordered: list[str]) -> list[tuple[str, ...]] | None:
    """The reads a rule-out rests on, where it rests on Argus's reads that
    ruled something out and nothing else - the reads code says it by;
    nothing where it rests on anything more."""
    if not _cites_only_the_walk(entry, rows):
        return None

    groups = [_the_read(cite, rows, ordered) for cite in entry.cites]
    if not all(group is not None for group in groups):
        return None

    return [group for group in groups if group is not None]


def _rests_on_nothing_that_rules_out(entry: SubmittedRuledOut,
                                     rows: Mapping[str, TimelineEntry],
                                     named_outside: frozenset[str]) -> bool:
    """Whether a rule-out rests only on rows that never rule anything out,
    naming nothing outside the timeline that could be ruled out."""
    return (_cites_only_the_walk(entry, rows)
            and all(_never_rules(rows[cite]) for cite in entry.cites)
            and not any(re.search(rf"\b{re.escape(label)}\b", entry.what)
                        for label in named_outside))


def _cites_only_the_walk(entry: SubmittedRuledOut, rows: Mapping[str, TimelineEntry]) -> bool:
    return bool(entry.cites) and all(cite in rows and not rows[cite].outside_the_walk
                                     for cite in entry.cites)


def _the_read(cite: str, rows: Mapping[str, TimelineEntry], ordered: list[str]
              ) -> tuple[str, ...] | None:
    """The read a cited row is part of, as the labels saying it - a changes
    read with the request it answered - where the read ruled something out;
    nothing where the row is no such read or the read found what it looked
    for."""
    row = rows[cite]
    if _asked_for_changes(row):
        answer = _the_read_that_answered(cite, rows, ordered)
        return (cite, answer) if answer is not None and rows[answer].rules_out else None

    if not row.rules_out:
        return None

    if row.kind == _CHANGES_READ:
        asked = _the_request_it_answered(cite, rows, ordered)
        return (asked, cite) if asked is not None else (cite,)

    return (cite,)


def _the_request_it_answered(cite: str, rows: Mapping[str, TimelineEntry],
                             ordered: list[str]) -> str | None:
    """The request for changes a changes read answered: the nearest before it
    with no other changes read between them - one that came after another read
    was answered by that one."""
    for label in reversed(ordered[:ordered.index(cite)]):
        if _asked_for_changes(rows[label]):
            return label
        if rows[label].kind == _CHANGES_READ:
            return None

    return None


def _the_read_that_answered(cite: str, rows: Mapping[str, TimelineEntry],
                            ordered: list[str]) -> str | None:
    """The changes read that answered a request for changes: the nearest after
    it with no other request between them - a read after a second request
    answered that one, and the first went unanswered."""
    for label in ordered[ordered.index(cite) + 1:]:
        if rows[label].kind == _CHANGES_READ:
            return label
        if _asked_for_changes(rows[label]):
            return None

    return None


def _said_by_the_record(reads: list[tuple[str, ...]],
                        rows: Mapping[str, TimelineEntry],
                        ordered: list[str]) -> SubmittedRuledOut:
    """One rule-out, said as its reads are: each class of change their reads
    found none of, once, then the lines of every read that found none of it,
    in order - the reads in the order they happened, and the classes in the
    order their first read did. Two reads of one class share one head: said
    before each, the class reads as two things ruled out. And a read another
    of them words alike, line for line, is said once: the same words again say
    nothing the first did not, and every read stays cited. A whole read, never
    one of its lines: two requests answered alike are two windows, and the
    second said without its answer reads as unanswered."""
    distinct = sorted(set(reads), key=lambda read: ordered.index(read[0]))
    by_class: dict[str, list[str]] = {}
    for read in distinct:
        said_reads = by_class.setdefault(rows[read[-1]].rules_out, [])
        said_read = "; ".join(said_as_a_clause(rows[label]) for label in read)
        if said_read not in said_reads:
            said_reads.append(said_read)
    said = ". ".join(f"{ruled_out}: " + "; ".join(said_reads)
                     for ruled_out, said_reads in by_class.items())

    return SubmittedRuledOut(what=f"{said}.",
                             cites=[label for read in distinct for label in read],
                             by_the_record=True)


def _asked_for_changes(row: TimelineEntry) -> bool:
    return row.kind == _REQUESTED and row.channel is RetrievalChannel.CHANGES


def _never_rules(row: TimelineEntry) -> bool:
    """Whether a line is of a kind that rules nothing out whatever it says -
    a request for anything but changes among them. A line with no kind is
    from a document written before lines said, and is not known never to."""
    return row.kind in _NEVER_RULING or (row.kind == _REQUESTED
                                         and row.channel is not RetrievalChannel.CHANGES)
