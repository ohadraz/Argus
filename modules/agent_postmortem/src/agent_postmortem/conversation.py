"""The one exchange with the model, and how much of it is worth keeping.

The model is asked for prose and answers with a tool call. Everything here is
about that call arriving in the shape the document needs - asked once, refused
once where it did not, and read for an answer either way.

Nothing here computes a figure, and the prose writes none: it names the figures
the incident gave, and the answer kept has each written in as this run
measured it (`figures`).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import Final, NamedTuple

from argus_core import A_REVISION
from argus_core.llm import LLMClient
from argus_core.models import (
    Ask,
    ChangeKind,
    CitedChange,
    OpenedPullRequest,
    ThreadMessage,
    TimelineEntry,
    Transcript,
    Turn,
)
from argus_narration import the_short_forms

from agent_postmortem.checking import (
    Given,
    faults_by_check,
    faults_in_the_turn,
    names_the_flag,
    rates_named_in,
)
from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.figures import (
    Figure,
    names_in,
    the_day_said_off_the_page,
    with_figures_written,
    with_figures_written_with_every_day,
)
from agent_postmortem.grounding import Flag, faults_of, flags_on
from agent_postmortem.log_groups import LOG_GROUP_PREFIX
from agent_postmortem.measuring import Measurements
from agent_postmortem.ordering import ORDER_TOOL_NAME, put_in_order
from agent_postmortem.prompting import (
    CAUSAL_CHAIN_FIELD,
    LOGS_SHOW_SERVING_AS_BEFORE_FIELD,
    ROOT_CAUSE_FIELD,
    RULED_OUT_FIELD,
    STOPS_THE_HARM_FIELD,
    SUBMIT_TOOL_NAME,
    WENT_WELL_FIELD,
    WENT_WRONG_FIELD,
    WHY_IT_DID_NOT_HELP_FIELD,
    SubmittedPostmortem,
    figures_shown,
    opening_ask,
    opening_ask_again,
    rejecting,
    submit_postmortem_for,
    the_candidates_labelled,
    the_change_that_set_it_off,
    the_changes_labelled,
    the_evidence_labelled,
    the_files_as_they_ran_labelled,
    the_headings_of,
    the_uses_outside_labelled,
)
from agent_postmortem.pull_requests import with_the_pull_request_named
from agent_postmortem.revisions import revisions_of, with_revisions_corrected
from agent_postmortem.ruling import is_said_by_code, with_what_the_record_rules_out
from agent_postmortem.sections import (
    ACTION_PREFIX,
    AS_IT_RAN_PREFIX,
    CODE_READING_PREFIX,
    DEPLOYMENT_CHANGES_PREFIX,
    PRODUCTION_CHANGE_PREFIX,
    USES_OUTSIDE_PREFIX,
    a_put_back_left_the_harm,
    as_the_timeline_shows_it,
    labels_of_the_narration,
    logs_in_the_gap_of,
    record_action_items_of,
)
from agent_postmortem.timing import is_said_as_its_row, with_each_moment_timed
from agent_postmortem.undetermined import NOT_DETERMINED, NOT_KNOWN, named_no_cause

logger = logging.getLogger(__name__)

# Every tool the write-up's calls answer with: the answer itself, and the
# order of its chain asked after it. Declared here, where both calls are made,
# so whatever reads a recorded write-up knows all of it by one name - and a
# call the write-up gains is not taken for the walk going on.
WRITE_UP_TOOLS: Final = frozenset({SUBMIT_TOOL_NAME, ORDER_TOOL_NAME})

# The check the grounding judge's flags are filed under, beside the code's.
_GROUNDING: Final = "grounding"

# What the grounding judge is told not to judge in a write-up: what code fills
# in, and what is a proposal or a verdict rather than a claim. What supports a
# claim is the judge's own brief, said once there for every answer.
WRITE_UP_SCOPE: Final = (
    "Names in braces, such as {T5.1} or {duration}, are figures code writes in from the "
    "row they name. They are not judged.",
    "Action items propose what to do; they make no claim about the record.",
    "Whether something went well, went wrong or was lucky is a judgement. Only a fact it "
    f"states is judged, and whether a {WENT_WRONG_FIELD} item is one its field excludes."
)

# The prefixes of evidence outside the timeline a rule-out can be of.
_OUTSIDE_THE_TIMELINE: Final = frozenset({
    PRODUCTION_CHANGE_PREFIX, DEPLOYMENT_CHANGES_PREFIX, LOG_GROUP_PREFIX, AS_IT_RAN_PREFIX,
    USES_OUTSIDE_PREFIX, CODE_READING_PREFIX, ACTION_PREFIX})


def answer_worth_writing(llm: LLMClient,
                         evidence: IncidentEvidence,
                         measured: Measurements,
                         judge: LLMClient | None = None
                         ) -> tuple[SubmittedPostmortem, list[str]]:
    """The model's answer, and whatever is still wrong with it.

    Two attempts, and a third only for what the second got wrong that the
    first was never told of (spec §7.6). The second is worth making because the
    faults are nameable - a missing field, a figure Argus never computed - and
    a model told which is a model that can fix it. A rewrite told to fix one
    thing got another wrong that its first answer had right, and was kept with
    it: it was never told. Each fault is sent back once, so a third answer is
    kept whatever it holds - an answer wrong twice in ways it was told about is
    not one attempt away from right, and the incident is over either way.

    Returns the faults rather than acting on them, because the caller is the
    one writing the document that has to admit to them.

    An answer the checks pass is read by `judge`, where there is one, against
    the brief it was written from (`grounding`): a claim the record does not
    support is sent back as a fault like any other, once. On the answer kept
    a flag withholds nothing - the document has no review line for meaning -
    and is said in the log instead, flag by flag.
    """
    asked = opening_ask(evidence, measured)
    # The tool for this incident, which asks what each lead changed only where
    # people wrote any, how the logs show the service only where a line reaches
    # into a stretch the metrics did not watch, what the cause was only where
    # the investigation named one, and what stops the harm and why the change
    # did not help only where a change put back left the harm standing.
    cause_asked = not named_no_cause(evidence)
    submit = submit_postmortem_for(
        evidence.leads, logs_in_the_gap_of(evidence, measured),
        cause_asked=cause_asked,
        harm_left_standing=a_put_back_left_the_harm(evidence, measured.back_to_normal_at))
    # Every figure the answer may name, each written in as this run measured it.
    figures = figures_shown(evidence, measured)
    # And as the summary's paragraph says them, which the two sentences it
    # carries are written with.
    off_the_page = the_day_said_off_the_page(evidence, measured)
    given = _what_was_given(evidence, measured, figures).model_copy(update={
        "serving_as_before_asked": LOGS_SHOW_SERVING_AS_BEFORE_FIELD in submit.required,
        "stops_the_harm_asked": STOPS_THE_HARM_FIELD in submit.required,
        "why_it_did_not_help_asked": WHY_IT_DID_NOT_HELP_FIELD in submit.required,
        "cause_asked": cause_asked})
    submitted = llm.converse(asked, [submit])
    grounding = _Grounding(judge, asked, given, evidence.incident_id)

    first = _reading_of(submitted, evidence.leads, given, figures, off_the_page,
                        evidence.pull_request)
    told = first.faults or grounding.faults_in(first.shown)
    if not told:
        return _finished(llm, (first.answer, []), cause_asked=cause_asked)

    faults = _every_one_of(told)
    logger.warning("postmortem answer rejected", extra={"faults": faults})

    asked_again = _asking_again(asked, submitted, faults)
    resubmitted = llm.converse(asked_again, [submit])
    second = _reading_of(resubmitted, evidence.leads, given, figures, off_the_page,
                         evidence.pull_request)
    # Judged only where the checks passed, and its flags sent back only where
    # they never were: a claim told once and written again is kept, and said
    # in the log.
    found = second.faults or (grounding.faults_in(second.shown) if _GROUNDING not in told
                              else grounding.logged(second.shown))
    # Untold is what a check found that found nothing in the first answer: a
    # fault quotes the answer, so one it was told of in other words is new
    # text and the same fault.
    untold = _every_one_of({check: said for check, said in found.items() if check not in told})
    if not untold:
        return _finished(llm, (second.answer, _every_one_of(second.faults)),
                         cause_asked=cause_asked)

    logger.warning("postmortem answer rejected", extra={"faults": untold})

    # From the opening where the rewrite made no call: there is nothing in its
    # turn to refuse, and following the first refusal would ask about an answer
    # the model can no longer see. Starting over, it is told the first
    # refusal's faults again, or it can write them again and have them kept.
    asked_last = (rejecting(asked_again, resubmitted, untold) if resubmitted.tool_calls
                  else opening_ask_again(asked, faults + untold))
    third = _reading_of(llm.converse(asked_last, [submit]), evidence.leads, given, figures,
                        off_the_page, evidence.pull_request)
    if not third.faults:
        grounding.logged(third.shown)

    return _finished(llm, (third.answer, _every_one_of(third.faults)), cause_asked=cause_asked)


class _Reading(NamedTuple):
    """One turn read: the answer as kept, its faults by check, and its
    sentences as the grounding judge reads them."""

    answer: SubmittedPostmortem
    faults: dict[str, list[str]]
    shown: dict[str, str]


class _Grounding:
    """The grounding judge as the write-up's attempts call on it: once an
    answer the checks passed, with its flags as faults - or, on the answer
    kept, its flags said in the log. Nothing where there is no judge."""

    def __init__(self, judge: LLMClient | None, asked: Transcript, given: Given,
                 incident_id: str) -> None:
        self._judge = judge
        self._record = "\n".join(exchange.text for exchange in asked
                                 if isinstance(exchange, Ask))
        self._rows = given.labels | given.timeline_rows
        self._incident_id = incident_id

    def faults_in(self, shown: dict[str, str]) -> dict[str, list[str]]:
        flags = self._flags_on(shown)
        return {_GROUNDING: faults_of(flags)} if flags else {}

    def logged(self, shown: dict[str, str]) -> dict[str, list[str]]:
        for flag in self._flags_on(shown):
            logger.warning("postmortem claim not grounded", extra={
                "incident_id": self._incident_id, "fields": list(flag.fields),
                "quote": flag.quote, "rows": list(flag.rows), "why": flag.why})
        return {}

    def _flags_on(self, shown: dict[str, str]) -> list[Flag]:
        if self._judge is None:
            return []
        return flags_on(self._judge, record=self._record, answer=shown, rows=self._rows,
                        scope=WRITE_UP_SCOPE)


def _finished(llm: LLMClient,
              reading: tuple[SubmittedPostmortem, list[str]],
              *,
              cause_asked: bool) -> tuple[SubmittedPostmortem, list[str]]:
    """The answer kept: its chain in order, and - where the model was not asked
    what the cause was - the cause fields as the document writes them."""
    answer, faults = _with_its_chain_in_order(llm, reading)

    return (answer if cause_asked else _with_no_cause_named(answer)), faults


def _with_no_cause_named(answer: SubmittedPostmortem) -> SubmittedPostmortem:
    """The answer with the cause fields the document writes itself where the
    investigation named no cause (`undetermined`) - the model was not asked for
    them. No chain that reaches a cause and none resting on a reading nothing
    ran, so neither the chain nor the review's box claims a cause the root
    cause denies."""
    return answer.model_copy(update={
        "root_cause": NOT_DETERMINED,
        "cause_in_plain_words": NOT_KNOWN,
        "reaches_a_cause": False,
        "cause_rests_on_an_unrun_reading": False})


def _with_its_chain_in_order(llm: LLMClient,
                             reading: tuple[SubmittedPostmortem, list[str]]
                             ) -> tuple[SubmittedPostmortem, list[str]]:
    """The answer kept, with its causal chain in the order its whys answer each
    other (`ordering`) - after it is read, so the order is asked of the chain
    the document will carry."""
    answer, faults = reading
    if answer.causal_chain is None:
        return reading

    return (answer.model_copy(update={"causal_chain": put_in_order(llm, answer.causal_chain)}),
            faults)


def _what_was_given(evidence: IncidentEvidence,
                    measured: Measurements,
                    figures: dict[str, Figure]) -> Given:
    """What the answer is held to: the labels it could cite and which of them
    are hypotheses, the items already on the record, the revisions the incident
    read and the one the deploy that set it off went to, the figures it may
    name, each file shown as it ran - named by its first line, its path at
    its revision - each line outside Code-Fix's patch, under its label, each
    change only the walk read, under its label with the flag it switched, and
    each word the evidence holds in braces that names no figure.

    Not a walk-alone change whose flag a candidate blamed - its subject, or a
    flag its words name: the walk turns back only a flag a candidate named, so a
    causing flag switched just past the Investigator's own window is one the
    Investigator did name, and a sentence crediting it with that flag is true."""
    return Given(
        labels=frozenset(label for cited in the_evidence_labelled(evidence, measured)
                         for label in (cited.label, *cited.also)),
        hypotheses=frozenset(label for cited in the_candidates_labelled(evidence)
                             for label in (cited.label, *cited.also)),
        items_on_record=len(record_action_items_of(evidence, measured.back_to_normal_at)),
        revisions=revisions_of(evidence),
        trigger_revision=_the_deploy_s_revision(the_change_that_set_it_off(evidence)),
        figures=figures,
        as_it_ran={cited.label: cited.text.split("\n", 1)[0]
                   for cited in the_files_as_they_ran_labelled(evidence)},
        uses={cited.label: use
              for cited, use in zip(the_uses_outside_labelled(evidence), evidence.uses_outside,
                                    strict=True)},
        read_by_the_walk_alone={
            cited.label: cited.change.reference
            for cited in the_changes_labelled(evidence)
            if cited.change in evidence.changes_the_walk_alone_read
            and not any(candidate.subject == cited.change.reference
                        or names_the_flag(candidate.summary, cited.change.reference)
                        for candidate in evidence.candidates)},
        rates_the_logs_name=rates_named_in([cited.text for cited in
                                            the_evidence_labelled(evidence, measured)
                                            if cited.label.startswith(LOG_GROUP_PREFIX)]),
        speakers=frozenset(entry.who.split(" ", 1)[0] for entry in evidence.timeline
                           if entry.who),
        timeline_rows=frozenset(labels_of_the_narration(evidence.timeline)),
        rows=dict(zip(labels_of_the_narration(evidence.timeline), evidence.timeline,
                      strict=True)),
        rows_as_shown={label: as_the_timeline_shows_it(entry,
                                                       the_short_forms(
                                                           the_changes_labelled(evidence)),
                                                       evidence.pull_request)
                       for label, entry in zip(labels_of_the_narration(evidence.timeline),
                                               evidence.timeline, strict=True)},
        headings=the_headings_of(evidence, measured),
        quoted=frozenset(name for cited in the_evidence_labelled(evidence, measured)
                         for name in names_in(cited.text)
                         if name not in figures)
    )


def _the_deploy_s_revision(change: CitedChange | None) -> str | None:
    """The revision a change went to, where it is a deploy - and nothing for a
    flag, whose name is no revision."""
    if change is None or change.change.kind is not ChangeKind.DEPLOY:
        return None

    return change.change.reference if A_REVISION.fullmatch(change.change.reference) else None


def _asking_again(asked: Transcript, submitted: Turn, faults: list[str]) -> Transcript:
    """How the second attempt is put, which depends on what the first was.

    A submission is refused through the result of the call that made it, so
    the model sees its own answer and what was wrong with it. A model that
    made no call submitted nothing there is anything to refuse - so it is
    asked again from the start, which is the only shape left and the reason
    the choice lives here rather than in the prompt module.
    """
    if not submitted.tool_calls:
        return opening_ask_again(asked, faults)

    return rejecting(asked, submitted, faults)


def _reading_of(turn: Turn,
                leads: Sequence[ThreadMessage],
                given: Given,
                figures: dict[str, Figure],
                off_the_page: date | None,
                pull_request: OpenedPullRequest | None
                ) -> _Reading:
    """What one turn amounts to: its answer and whatever is wrong with it, by
    the check that found it (`faults_by_check`) - and its sentences as the
    grounding judge reads them.

    The leads go with it, because whether every one was answered is a fault of
    the turn too, and what was given, because a citation is checked against it.
    A turn that submitted twice is a fault of its own (`faults_in_the_turn`).
    A revision a few characters off is written as the real one first, since
    code knows which it was; only one starting like none is left to refuse.
    So is any pull request it names, as the one the record holds
    (`pull_request`): a replayed answer names its recording run's.

    The figures are written in last, after the check: it reads the names, and
    a figure written in before it would read as one the model wrote in digits.
    The two sentences the summary carries are written as it says its own
    (`off_the_page`, the day they are dated against where they need one):
    written in with the page's figures, a time in one was bare in a paragraph
    posted where no head dates the incident.
    """
    answer = with_the_pull_request_named(
        with_revisions_corrected(_answer_from(turn), given.revisions), pull_request)
    of_the_turn = faults_in_the_turn(turn)
    # What the record rules out said as the record says it, and each moment
    # that went well timed by code off the row the model named and said as that
    # row - both before the figures are written in, since a rule-out names a
    # change by its figure and the time is one. Checked as the model sent it,
    # which is what the check speaks of - less what code says instead
    # (`_as_checked`), whose words no reader sees.
    # Both in the rows as the timeline shows them, which the document says
    # beside them.
    ruled = with_what_the_record_rules_out(answer, given.rows_as_shown,
                                           _named_outside(given.labels))
    written = with_figures_written(with_each_moment_timed(ruled, figures, given.rows_as_shown),
                                   figures)
    in_the_summary = (written if off_the_page is None
                      else with_figures_written_with_every_day(answer, figures, off_the_page))

    return _Reading(answer=written.model_copy(update={
                        "cause_in_plain_words": in_the_summary.cause_in_plain_words,
                        "still_at_risk": in_the_summary.still_at_risk}),
                    faults={**({faults_in_the_turn.__name__: of_the_turn} if of_the_turn else {}),
                            **faults_by_check(_as_checked(answer, figures, given), leads,
                                              given=given)},
                    shown=_as_the_judge_reads_it(ruled, figures, given.rows, given.headings))


def _as_checked(answer: SubmittedPostmortem,
                figures: dict[str, Figure],
                given: Given) -> SubmittedPostmortem:
    """The answer as the checks read it: as the model sent it, less each place
    code says in the record's words or drops - an item of what went well said
    as its row, a rule-out said by the record or resting on nothing.

    A rule the model's words there broke is one no reader would see broken:
    "draft pull request 541", in an item code said as its row, sent a write-up
    back for a figure in digits that the document never printed. Each place
    decided on the answer as sent, where the checks count places."""
    named_outside = _named_outside(given.labels)
    timed_by = answer.went_well_timed_by or []

    return answer.model_copy(update={"said_by_code": frozenset({
        *(f"{CAUSAL_CHAIN_FIELD} {position} {RULED_OUT_FIELD} {ruled_at}"
          for position, step in enumerate(answer.causal_chain or [], start=1)
          for ruled_at, entry in enumerate(step.ruled_out, start=1)
          if is_said_by_code(entry, given.rows_as_shown, named_outside)),
        *(f"{WENT_WELL_FIELD} {position}"
          for position, row in enumerate(timed_by, start=1)
          if is_said_as_its_row(row, figures, given.rows_as_shown))})})


def _as_the_judge_reads_it(ruled: SubmittedPostmortem,
                           figures: dict[str, Figure],
                           rows: dict[str, TimelineEntry],
                           headings: dict[str, str]) -> dict[str, str]:
    """Each sentence of the answer by its place, as the grounding judge reads
    it: ruled, its placeholders kept - code fills those from their rows - and
    less the sentences code says in the record's words, which the model no
    longer says: a rule-out said by the record, and an item said as its row.

    The root cause, each step and each rule-out the model says as the page
    shows them: the root cause with the document's sentence saying it is
    unverified, where it rests on a reading nothing ran, and each step and
    rule-out beside what it cites, each citation under the heading its row is
    listed beneath (`headings`). Shown the model's words alone, the judge
    flagged as said flat a cause the page calls unverified, and a step the
    page shows as Code-Fix's reading - and shown bare labels, the step still."""
    timed_by = ruled.went_well_timed_by or []
    said_by_code = {
        *(f"{CAUSAL_CHAIN_FIELD} {position} {RULED_OUT_FIELD} {ruled_at}"
          for position, step in enumerate(ruled.causal_chain or [], start=1)
          for ruled_at, entry in enumerate(step.ruled_out, start=1) if entry.by_the_record),
        *(f"{WENT_WELL_FIELD} {position}"
          for position, row in enumerate(timed_by, start=1)
          if is_said_as_its_row(row, figures, rows))}
    as_the_page_shows_it = {
        **({ROOT_CAUSE_FIELD: as_written}
           if (as_written := ruled.root_cause_as_written()) is not None else {}),
        **{f"{CAUSAL_CHAIN_FIELD} {position}": _beside_its_cites(step.step, step.cites, headings)
           for position, step in enumerate(ruled.causal_chain or [], start=1) if step.cites},
        **{f"{CAUSAL_CHAIN_FIELD} {position} {RULED_OUT_FIELD} {ruled_at}":
           _beside_its_cites(entry.what, entry.cites, headings)
           for position, step in enumerate(ruled.causal_chain or [], start=1)
           for ruled_at, entry in enumerate(step.ruled_out, start=1) if entry.cites}}

    return {place: as_the_page_shows_it.get(place, prose)
            for place, prose in ruled.placed_sentences() if place not in said_by_code}


def _beside_its_cites(said: str, cites: list[str], headings: dict[str, str]) -> str:
    """A sentence with what it cites after it, as the judge reads it: each
    label under the heading its row is listed beneath, and bare where it has
    none."""
    cited = [f'{label}, under "{headings[label]}"' if label in headings else label
             for label in cites]
    return f"{said} (cites {'; '.join(cited)})"


def _named_outside(labels: frozenset[str]) -> frozenset[str]:
    """The labels of evidence outside the timeline a rule-out may rule out by
    naming it: a change, what a deployment changed, a log group, a file as it
    ran, a use outside the patch, Code-Fix's reading, an action. Not the
    alert, which every rule-out is weighed against, nor a candidate."""
    return frozenset(label for label in labels
                     if label[:1] in _OUTSIDE_THE_TIMELINE and not label[1:2].isupper())


def _every_one_of(faults: dict[str, list[str]]) -> list[str]:
    """Every fault, whichever check found it, in the order they were found."""
    return [fault for found in faults.values() for fault in found]


def _answer_from(turn: Turn) -> SubmittedPostmortem:
    """What the model submitted, or nothing at all.

    A turn carrying no call to the tool it was offered is an answer in the
    wrong shape rather than a failure to answer, and it is read as an empty
    one: the document is then written incomplete, which is what its review
    exists to say.
    """
    for call in turn.tool_calls:
        if call.name == SUBMIT_TOOL_NAME:
            return SubmittedPostmortem.model_validate(call.arguments)

    return SubmittedPostmortem()
