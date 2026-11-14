"""Asks the grounding judge again what it makes of write-ups it already judged.

Run as `uv run python -m scripts.rejudge <out dir> [--plants <file>]
[--ask-from <judge recording>=<recording>] <judge recording> [...]`, each name
a judge recording under the Anthropic double's recordings - for example
`judge-both-silent-data-corruption judge-both-silent-data-corruption-2`. Paid:
every name, and every planted error, is one call to the real API, at the
judge's configured model and effort, under the judge code in the tree.

What a recording holds is the question the judge was asked when it was made:
the record, the answer by field, and what was not to be judged. Those three are
read back out of it and asked again through `flags_on`, so a change to the
judge's brief, tool or model is measured on exactly the write-ups the last one
was measured on, with no stack and no walk. The rows a flag may cite are every
label the record prints, in brackets or bare.

`--ask-from` takes an overview's ask - the part of its record before the
postmortem - from another recording: an overview judged over a write-up the
replay derailed is judged again over the ask its own recording answered.

`--as-the-page-shows-it` takes the answer a write-up's judge recording judged
from the writer's recording of it (`<judge recording>=<writer recording>`) and
shows the judge its root cause and each step as the page shows them: the root
cause with the document's sentence saying it is unverified, where it rests on a
reading nothing ran, and each step and rule-out beside what it cites. A recording made
before the judge was shown them is judged again as the judge now reads it.

`--plants` names a JSON list of planted errors, each a copy of one recording's
answer with one fact changed (`name`, `field`, `find`, `replace`, `label`). A
judge that flags nothing passes every clean answer, so each plant is a positive
control: it passes only where a flag kept quotes words the change put in.

For each call it writes `<out dir>/<name or label>.json`: whether the judge
answered with its tool and why not, the flags kept, everything it submitted
(its supported claims included), its reasoning, and the four token counts. It
prints one line per call and the cost of the run, and exits non-zero where any
judge did not answer or any plant went unflagged.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from os.path import commonprefix
from pathlib import Path
from typing import Any, Final

from agent_postmortem.grounding import (
    DID_NOT_ANSWER,
    FLAGS_FIELD,
    JUDGE_TOOL_NAME,
    flags_on,
    judge_policy,
)
from agent_postmortem.prompting import (
    CAUSAL_CHAIN_FIELD,
    ROOT_CAUSE_FIELD,
    RULED_OUT_FIELD,
    SUBMIT_TOOL_NAME,
    SubmittedPostmortem,
)
from argus_core import LLMSettings, Settings
from argus_core.llm import LLMClient, build_llm_client
from argus_core.models import ToolDefinition, Transcript, Turn

RECORDINGS: Final = (Path(__file__).resolve().parents[1] / "modules" / "anthropic_double"
                     / "recordings")

# The sections of the ask the recordings were made with, in order. The answer's
# head and the close each in both spellings: the pilot's recordings say "The
# answer" and "Answer by calling", the judge since then "The document" and
# "Judge every claim".
_THE_RECORD: Final = "The record:\n"
_THE_ANSWER: Final = ("\n\nThe answer, by field:\n", "\n\nThe document, by field:\n")
_NOT_JUDGED: Final = "\n\nNot to be judged:\n"
_THE_CLOSE: Final = ("\n\nAnswer by calling ", "\n\nJudge every claim")
# Where an overview's record turns from its ask to the postmortem.
_THE_POSTMORTEM: Final = "\n\nThe postmortem it is written from:\n"
# A field of the answer as the ask printed it: a name of the answer's own
# (`root_cause`, `contributing_factors 3 had_it_been_otherwise`) and a colon.
_A_FIELD: Final = re.compile(r"^([a-z_]+(?: \d+)?(?: [a-z_]+)?): ", re.MULTILINE)
_A_LABEL: Final = re.compile(r"\[([A-Za-z][A-Za-z0-9.]*)\]")
# A row's label as a postmortem prints it bare - AL1, C2, T14, U3, G7e5d - for
# the overview, whose record is the document. Wider than the labels the walk
# hands the judge, so a flag the walk would drop for its rows is kept here: a
# measurement that errs towards a flag kept.
_A_BARE_LABEL: Final = re.compile(r"\b(?:[A-Z]{1,3}\d+|G[0-9a-f]{4})\b")
_A_NOTE: Final = "  - "
# What the writer is told at the end of a heading, which the judge's code says
# no heading beside a citation: of Code-Fix's reading, and of the candidates.
_WRITER_TOLD: Final = re.compile(r"(?:, and what it claims| - name them by their labels).*$")
# Citations as the judge was shown them before their headings: labels alone.
_BARE_CITES: Final = re.compile(r" \(cites [A-Za-z0-9.]+(?:, [A-Za-z0-9.]+)*\)$")
# How the judge's code folds a quote and the text it is looked for in: its
# quote marks and dashes, and its spacing. Said again here rather than reached
# for, since the judge's own are its private business.
_TYPOGRAPHY: Final = re.compile("[\"'`\u2018\u2019\u201c\u201d\u00ab\u00bb"
                                "\\-\u2010\u2011\u2012\u2013\u2014\u2015\u2212]")
_SPACING: Final = re.compile(r"\s+")

# Dollars per million tokens: input, cache write, cache read, output.
_RATES: Final = {
    "claude-opus-5-5": (4.00, 5.00, 0.20, 20.00),
    "claude-sonnet-5-5": (2.00, 2.50, 0.20, 10.00)
}


class _Keeping:
    """The judge's client, keeping every turn it answered with."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self.turns: list[Turn] = []

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int | None = None) -> Turn:
        turn = self._client.converse(transcript, tools, max_tokens)
        self.turns.append(turn)
        return turn


class _Hearing(logging.Handler):
    """Every reason the judge's code gave for a judge that did not answer."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.failures: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage() == DID_NOT_ANSWER:
            self.failures.append(str(getattr(record, "failure", "")))


@dataclass(frozen=True)
class _Asked:
    record: str
    answer: dict[str, str]
    scope: list[str]


def _text_of(name: str) -> str:
    request = json.loads((RECORDINGS / f"{name}.request.json").read_text(encoding="utf-8"))
    body = request.get("body", request)
    return "".join(block.get("text", "") for message in body["messages"]
                   for block in (message["content"] if isinstance(message["content"], list)
                                 else [{"text": message["content"]}]))


def asked_in(name: str, ask_from: str | None = None) -> _Asked:
    """The record, the answer by field, and what was not judged, as the
    recording `name` was asked them - its overview's ask taken from
    `ask_from` where one is given."""
    text = _text_of(name)
    head = next(spelt for spelt in _THE_ANSWER if spelt in text)
    close = next(spelt for spelt in _THE_CLOSE if spelt in text)
    record = text[text.index(_THE_RECORD) + len(_THE_RECORD):text.index(head)]
    answered = text[text.index(head) + len(head):text.rindex(_NOT_JUDGED)]
    notes = text[text.rindex(_NOT_JUDGED) + len(_NOT_JUDGED):text.rindex(close)]

    if ask_from is not None:
        record = _text_of(ask_from) + record[record.index(_THE_POSTMORTEM):]

    starts = list(_A_FIELD.finditer(answered))
    answer = {start.group(1): answered[start.end():(starts[at + 1].start() if at + 1 < len(starts)
                                                    else len(answered))].rstrip("\n")
              for at, start in enumerate(starts)}
    scope = [line.removeprefix(_A_NOTE) for line in notes.splitlines()
             if line.startswith(_A_NOTE)]

    return _Asked(record, answer, scope)


@dataclass(frozen=True)
class _Judged:
    kept: list[dict[str, Any]]
    cost: float
    answered: bool
    output_tokens: int


def _judged(label: str, asked: _Asked, settings: Settings, out: Path) -> _Judged:
    """Asks the judge about `asked`, writes what it said under `label`, and
    returns the flags kept, what the call cost, whether it answered, and how
    many tokens it answered with."""
    rows = frozenset(_A_LABEL.findall(asked.record)) | frozenset(
        _A_BARE_LABEL.findall(asked.record))
    judge = _Keeping(build_llm_client(
        policy=judge_policy(settings.judge_model, settings.judge_effort),
        settings=LLMSettings(anthropic_api_key=settings.anthropic_api_key,
                             anthropic_base_url="")))
    hearing = _Hearing()
    logging.getLogger("agent_postmortem.grounding").addHandler(hearing)
    try:
        flags = flags_on(judge, record=asked.record, answer=asked.answer, rows=rows,
                         scope=asked.scope)
    finally:
        logging.getLogger("agent_postmortem.grounding").removeHandler(hearing)

    turn = judge.turns[-1] if judge.turns else None
    calls = [call.arguments for call in (turn.tool_calls if turn else [])
             if call.name == JUDGE_TOOL_NAME]
    answered = bool(calls) and isinstance(calls[0].get(FLAGS_FIELD), list) \
        and not hearing.failures
    rates = _RATES[settings.judge_model]
    cost = 0.0 if turn is None else (
        turn.input_tokens * rates[0] + turn.cache_write_tokens * rates[1]
        + turn.cache_read_tokens * rates[2] + turn.output_tokens * rates[3]) / 1_000_000
    kept = [flag.model_dump() for flag in flags]
    (out / f"{label}.json").write_text(json.dumps({
        "answered": answered,
        "why_not": hearing.failures or (None if answered else
                                        ["no call to the tool" if turn else "no turn"]),
        "fields": list(asked.answer),
        "flags_kept": kept,
        "submitted": calls,
        "reasoning": turn.reasoning if turn else "",
        "tokens": None if turn is None else {
            "input": turn.input_tokens, "cache_write": turn.cache_write_tokens,
            "cache_read": turn.cache_read_tokens, "output": turn.output_tokens},
        "cost": cost
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    return _Judged(kept, cost, answered, turn.output_tokens if turn else 0)


def as_the_page_shows_it(asked: _Asked, writer: str) -> _Asked:
    """`asked`, its root cause, steps and rule-outs as the page shows them,
    from the write-up the writer's recording `writer` submitted - each
    citation under the heading the record lists its row beneath.

    An ask recorded since the judge was shown any of this already carries
    some: the unverified sentence is not added twice, and bare citations
    are replaced."""
    recorded = json.loads((RECORDINGS / f"{writer}.json").read_text(encoding="utf-8"))
    submitted = SubmittedPostmortem.model_validate(next(
        block["input"] for block in recorded["content"]
        if block.get("type") == "tool_use" and block.get("name") == SUBMIT_TOOL_NAME))
    headings = _the_headings_in(asked.record)
    answer = dict(asked.answer)
    as_written = submitted.root_cause_as_written()
    if submitted.root_cause is not None and as_written is not None:
        rest = as_written[len(submitted.root_cause):]
        if rest and not answer[ROOT_CAUSE_FIELD].endswith(rest):
            answer[ROOT_CAUSE_FIELD] += rest
    for position, step in enumerate(submitted.causal_chain or [], start=1):
        place = f"{CAUSAL_CHAIN_FIELD} {position}"
        if step.cites and place in answer:
            answer[place] = _beside(answer[place], step.cites, headings)
        for ruled_at, entry in enumerate(step.ruled_out, start=1):
            ruled = f"{place} {RULED_OUT_FIELD} {ruled_at}"
            if entry.cites and ruled in answer:
                answer[ruled] = _beside(answer[ruled], entry.cites, headings)

    return _Asked(asked.record, answer, asked.scope)


def _the_headings_in(record: str) -> dict[str, str]:
    """What the heading each label in `record` is listed beneath says it is:
    a line of its own ending in a colon, then its rows, each a note leading
    with its label in brackets - less the colon and what the writer is told
    there, as the judge's code leaves them out."""
    headings: dict[str, str] = {}
    heading: str | None = None
    for line in record.splitlines():
        if line.endswith(":") and not line.startswith(" "):
            heading = _WRITER_TOLD.sub("", line.removesuffix(":"))
        elif heading is not None and line.startswith(_A_NOTE) and (
                listed := _A_LABEL.match(line.removeprefix(_A_NOTE))):
            headings.setdefault(listed.group(1), heading)
        elif not line.strip():
            continue
        elif not line.startswith(" "):
            heading = None
    return headings


def _beside(said: str, cites: list[str], headings: dict[str, str]) -> str:
    """`said` less any bare citations it already ends with, and its cites
    after it under their headings, as the judge's code writes them."""
    said = _BARE_CITES.sub("", said)
    cited = [f'{label}, under "{headings[label]}"' if label in headings else label
             for label in cites]
    return f"{said} (cites {'; '.join(cited)})"


def _folded(text: str) -> str:
    """Text as the judge's code matches a quote in it - folded, its quote
    marks and dashes made spaces, its spacing single - without the trim, so
    a part of a text folds to the length it takes up in the whole."""
    return _SPACING.sub(" ", _TYPOGRAPHY.sub(" ", text.casefold()))


def _caught(plant: dict[str, str], planted: str, flags: list[dict[str, Any]]) -> bool:
    """Whether a flag kept in the planted field quotes the change itself.

    The change is the plant's replacement less what it shares with what it
    replaced at either end, so a flag on the words around it - or on another
    sentence of the field that happens to share a word - does not count. A
    quote is found in the field as the judge's code finds it, folded, and
    counts where its span meets the change's by a character or more."""
    find, replace = plant["find"], plant["replace"]
    lead = len(commonprefix([find, replace]))
    tail = len(commonprefix([find[lead:][::-1], replace[lead:][::-1]]))
    at = planted.index(replace)
    start = len(_folded(planted[:at + lead]))
    end = len(_folded(planted[:at + len(replace) - tail]))
    field = _folded(planted)
    for flag in flags:
        if plant["field"] not in flag["fields"]:
            continue
        quote = _folded(flag["quote"]).strip()
        found = field.find(quote) if quote else -1
        if found != -1 and found < end and found + len(quote) > start:
            return True
    return False


def _said(label: str, verdict: str, judged: _Judged) -> None:
    print(f"{label}: {'answered' if judged.answered else 'DID NOT ANSWER'}, {verdict}"
          f"{len(judged.kept)} flag(s) kept, {judged.output_tokens} output tokens, "
          f"${judged.cost:.4f}")
    for flag in judged.kept:
        print(f"  [{flag['quote']}] against {flag['rows']} - {flag['why']}")


def main() -> None:
    arguments = sys.argv[1:]
    out = Path(arguments.pop(0))
    plants_file = None
    ask_from: dict[str, str] = {}
    written_by: dict[str, str] = {}
    names: list[str] = []
    while arguments:
        argument = arguments.pop(0)
        if argument == "--plants":
            plants_file = Path(arguments.pop(0))
        elif argument == "--ask-from":
            name, source = arguments.pop(0).split("=", 1)
            ask_from[name] = source
        elif argument == "--as-the-page-shows-it":
            name, writer = arguments.pop(0).split("=", 1)
            written_by[name] = writer
        else:
            names.append(argument)
    if not names and plants_file is None:
        sys.exit("usage: python -m scripts.rejudge <out dir> [--plants <file>] "
                 "[--ask-from <name>=<recording>] "
                 "[--as-the-page-shows-it <name>=<writer recording>] <judge recording> [...]")
    out.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    print(f"judge: {settings.judge_model} at {settings.judge_effort}")

    spent = 0.0
    failed: list[str] = []
    for name in names:
        asked = asked_in(name, ask_from.get(name))
        if name in written_by:
            asked = as_the_page_shows_it(asked, written_by[name])
        judged = _judged(name, asked, settings, out)
        spent += judged.cost
        _said(name, "", judged)
        if not judged.answered:
            failed.append(f"{name} did not answer")

    plants = json.loads(plants_file.read_text(encoding="utf-8")) if plants_file else []
    for plant in plants:
        label = f"plant-{plant['label']}"
        asked = asked_in(plant["name"], ask_from.get(plant["name"]))
        if plant["find"] not in asked.answer[plant["field"]]:
            sys.exit(f"{label}: [{plant['find']}] is not in {plant['name']}'s {plant['field']}")
        planted = _Asked(asked.record, {**asked.answer, plant["field"]: asked.answer[
            plant["field"]].replace(plant["find"], plant["replace"])}, asked.scope)
        judged = _judged(label, planted, settings, out)
        spent += judged.cost
        caught = _caught(plant, planted.answer[plant["field"]], judged.kept)
        _said(label, "CAUGHT, " if caught else "MISSED, ", judged)
        if not judged.answered:
            failed.append(f"{label} did not answer")
        elif not caught:
            failed.append(f"{label} was missed")

    print(f"spent: ${spent:.4f}")
    if failed:
        sys.exit("FAILED: " + "; ".join(failed))


if __name__ == "__main__":
    main()
