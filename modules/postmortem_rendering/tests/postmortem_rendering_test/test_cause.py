"""Why it happened: the root cause, the chain of whys under it with what each
rests on, and the factors that let it.

All of it the model's prose, said as prose - a destination may link the labels
it cites - and each item a step cites said the way its own row says it, under
its label. Each case is one postmortem and what one part of the section says.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from argus_core.models import ChainStep, CitedEvidence, ContributingFactor, RuledOut
from argus_testkit import Assertion, Scenario, the_answer_was
from postmortem_rendering.cause import (
    CauseSection,
    ChainLink,
    Factor,
    RuledOutLine,
    the_cause,
)
from postmortem_rendering.lines import Line, Role, Run

from postmortem_rendering_test.framework.builders import a_postmortem

# What the rows of a document say, for a case about something else.
DONT_CARE_ROWS: Mapping[str, Line] = {}


@pytest.mark.unit
def test_the_root_cause_is_said_as_the_model_s_prose() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(root_cause="An empty month divided by zero, per C1.")
        ) \
        .when(
            lambda: the_cause(some_postmortem, DONT_CARE_ROWS).root_cause
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="An empty month divided by zero, per C1.",
                                          role=Role.PROSE),))))


@pytest.mark.unit
def test_a_document_with_no_root_cause_says_none() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(root_cause=None)
        ) \
        .when(
            lambda: the_cause(some_postmortem, DONT_CARE_ROWS).root_cause
        ) \
        .then(
            the_answer_was(None))


@pytest.mark.unit
def test_the_chain_starts_at_the_symptom_and_asks_why_of_each_step_with_its_evidence() -> None:
    # Each cited item said the way its own row says it, under its label, which
    # leads to the row - not in the words the model was briefed in.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(causal_chain=[
                ChainStep(text="account pages failed",
                          cites=[CitedEvidence(label="T1", text="as briefed")]),
                ChainStep(text="the monthly average divided by zero",
                          cites=[CitedEvidence(label="G3fa2", text="as briefed"),
                                 CitedEvidence(label="P1", text="as briefed")])]),
            some_rows := {"T1": Line(runs=(Run(text="500s on /account"),)),
                          "G3fa2": Line(runs=(Run(text="ZeroDivisionError"),)),
                          "P1": Line(runs=(Run(text="no items this month"),))}
        ) \
        .when(
            lambda: the_cause(some_postmortem, some_rows).chain
        ) \
        .then(
            the_answer_was((
                ChainLink(place="symptom",
                          claim=Line(runs=(Run(text="account pages failed", role=Role.PROSE),)),
                          evidence=(_cited("T1", "500s on /account"),)),
                ChainLink(place="why 1",
                          claim=Line(runs=(Run(text="the monthly average divided by zero",
                                               role=Role.PROSE),)),
                          evidence=(_cited("G3fa2", "ZeroDivisionError"),
                                    _cited("P1", "no items this month"))))))


@pytest.mark.unit
def test_a_row_cited_again_down_the_chain_is_said_there_by_its_label_alone() -> None:
    # Whole where the chain first cites it, and after that by the label that
    # leads to it - what a step was ruled out on included: a row every step
    # rests on, said whole under each, is one paragraph read again at every step.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(causal_chain=[
                ChainStep(text="dont care",
                          cites=[CitedEvidence(label="AL1", text="as briefed")]),
                ChainStep(text="dont care",
                          cites=[CitedEvidence(label="AL1", text="as briefed")],
                          ruled_out=[RuledOut(text="dont care",
                                              cites=[CitedEvidence(label="AL1",
                                                                   text="as briefed")])])]),
            some_rows := {"AL1": Line(runs=(Run(text="240 of 240 totals are off"),))}
        ) \
        .when(
            lambda: [evidence
                     for link in the_cause(some_postmortem, some_rows).chain
                     for evidence in (link.evidence,
                                      *(ruled.evidence for ruled in link.ruled_out))]
        ) \
        .then(
            the_answer_was([(_cited("AL1", "240 of 240 totals are off"),),
                            (_by_its_label("AL1"),),
                            (_by_its_label("AL1"),)]))


@pytest.mark.unit
def test_a_cited_label_with_no_row_keeps_the_words_it_was_briefed_in() -> None:
    # Nothing cited disappears: the label says what was cited, and leads
    # nowhere, there being nowhere to lead.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(causal_chain=[
                ChainStep(text="dont care",
                          cites=[CitedEvidence(label="E9", text="as briefed")])])
        ) \
        .when(
            lambda: the_cause(some_postmortem, {}).chain[0].evidence
        ) \
        .then(
            the_answer_was((Line(runs=(Run(text="E9"), Run(text=" "),
                                       Run(text="as briefed"))),)))


@pytest.mark.unit
def test_a_row_said_whole_above_the_chain_is_cited_in_it_by_its_label_alone() -> None:
    # What the alert found is said whole under Impact, above the chain: said
    # again at the symptom, it is one paragraph read twice.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(causal_chain=[
                ChainStep(text="dont care",
                          cites=[CitedEvidence(label="AL1", text="as briefed")])]),
            some_rows := {"AL1": Line(runs=(Run(text="240 of 240 totals are off"),))}
        ) \
        .when(
            lambda: the_cause(some_postmortem, some_rows,
                              said_above=frozenset({"AL1"})).chain[0].evidence
        ) \
        .then(
            the_answer_was((_by_its_label("AL1"),)))


@pytest.mark.unit
def test_a_label_with_no_row_cited_again_keeps_its_words_there_too() -> None:
    # A label leading nowhere said alone says nothing: its words are the only
    # place what was cited is said.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(causal_chain=[
                ChainStep(text="dont care",
                          cites=[CitedEvidence(label="E9", text="as briefed")]),
                ChainStep(text="dont care",
                          cites=[CitedEvidence(label="E9", text="as briefed")])])
        ) \
        .when(
            lambda: the_cause(some_postmortem, {}).chain[1].evidence
        ) \
        .then(
            the_answer_was((Line(runs=(Run(text="E9"), Run(text=" "),
                                       Run(text="as briefed"))),)))


@pytest.mark.unit
def test_what_a_step_ruled_out_is_said_under_it_with_what_ruled_it_out() -> None:
    # Under the step it was ruled out at, and its citations said as the step's
    # are: by their rows, under their labels.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(causal_chain=[
                ChainStep(text="dont care", cites=[],
                          ruled_out=[RuledOut(text="the earlier deploy",
                                              cites=[CitedEvidence(label="T5",
                                                                   text="as briefed")])])]),
            some_rows := {"T5": Line(runs=(Run(text="metrics read healthy"),))}
        ) \
        .when(
            lambda: the_cause(some_postmortem, some_rows).chain[0].ruled_out
        ) \
        .then(
            the_answer_was((
                RuledOutLine(claim=Line(runs=(Run(text="the earlier deploy", role=Role.PROSE),)),
                             evidence=(_cited("T5", "metrics read healthy"),)),)))


@pytest.mark.unit
def test_a_rule_out_the_record_says_cites_its_rows_by_label_alone() -> None:
    # Its claim is the rows' own lines already; said whole beside it, they
    # would be read twice. Neither the words it was briefed in nor its row's
    # are shown.
    some_claim = "A rollout still under way: the Investigator Agent read how far it rolled out."
    some_label = "T5"
    dont_care_step = "dont care"
    dont_care_briefed_as = "dont care how it was briefed"
    dont_care_row_says = "dont care what the row says"

    Scenario() \
        .given(
            some_postmortem := a_postmortem(causal_chain=[
                ChainStep(text=dont_care_step, cites=[],
                          ruled_out=[RuledOut(text=some_claim,
                                              cites=[CitedEvidence(label=some_label,
                                                                   text=dont_care_briefed_as)],
                                              said_by_the_record=True)])]),
            some_rows := {some_label: Line(runs=(Run(text=dont_care_row_says),))}
        ) \
        .when(
            lambda: the_cause(some_postmortem, some_rows).chain[0].ruled_out
        ) \
        .then(
            the_answer_was((
                RuledOutLine(claim=Line(runs=(Run(text=some_claim, role=Role.PROSE),)),
                             evidence=(_by_its_label(some_label),)),)))


@pytest.mark.unit
def test_a_step_that_ruled_nothing_out_says_nothing_of_it() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(causal_chain=[ChainStep(text="dont care", cites=[])])
        ) \
        .when(
            lambda: the_cause(some_postmortem, DONT_CARE_ROWS).chain[0].ruled_out
        ) \
        .then(
            the_answer_was(()))


@pytest.mark.unit
def test_the_chain_and_the_factors_are_headed_and_the_evidence_labelled() -> None:
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: the_cause(dont_care_postmortem, DONT_CARE_ROWS)
        ) \
        .then(
            _it_is_headed("Causal chain", "Contributing factors", "Evidence:", "Ruled out:"))


@pytest.mark.unit
def test_no_chain_says_none_was_written() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(causal_chain=[])
        ) \
        .when(
            lambda: the_cause(some_postmortem, DONT_CARE_ROWS).chain_absent
        ) \
        .then(
            the_answer_was("No causal chain was written."))


@pytest.mark.unit
def test_a_chain_written_says_nothing_of_its_absence() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(causal_chain=[ChainStep(text="dont care", cites=[])])
        ) \
        .when(
            lambda: the_cause(some_postmortem, DONT_CARE_ROWS).chain_absent
        ) \
        .then(
            the_answer_was(None))


@pytest.mark.unit
def test_a_factor_names_the_items_that_answer_it() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(contributing_factors=[
                ContributingFactor(text="no test covered an empty month",
                                   addressed_by=["AI-2", "AI-3"])])
        ) \
        .when(
            lambda: the_cause(some_postmortem, DONT_CARE_ROWS).factors
        ) \
        .then(
            the_answer_was((
                Factor(text=Line(runs=(Run(text="no test covered an empty month",
                                           role=Role.PROSE),)),
                       addressed_by=Line(runs=(Run(text="(AI-2, AI-3)", role=Role.PROSE),))),)))


@pytest.mark.unit
def test_a_factor_nothing_answers_names_no_items() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(contributing_factors=[
                ContributingFactor(text="dont care", addressed_by=[])])
        ) \
        .when(
            lambda: the_cause(some_postmortem, DONT_CARE_ROWS).factors[0].addressed_by
        ) \
        .then(
            the_answer_was(None))


@pytest.mark.unit
def test_no_factors_says_none_were_named() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(contributing_factors=[])
        ) \
        .when(
            lambda: the_cause(some_postmortem, DONT_CARE_ROWS).factors_absent
        ) \
        .then(
            the_answer_was("No contributing factors were named."))


def _cited(label: str, *said: str) -> Line:
    """A cited item as the chain says it: its label, leading to its row, and
    then what that row says."""
    return Line(runs=(Run(text=label, role=Role.CITATION, address=label),
                      Run(text=" "),
                      *(Run(text=words) for words in said)))


def _by_its_label(label: str) -> Line:
    """A cited item the chain has said whole already: its label alone, leading
    to its row."""
    return Line(runs=(Run(text=label, role=Role.CITATION, address=label),))


def _it_is_headed(chain: str, factors: str, evidence: str,
                  ruled_out: str) -> Assertion[CauseSection]:
    def assertion(cause: CauseSection) -> bool:
        said = (cause.chain_heading, cause.factors_heading, cause.evidence_label,
                cause.ruled_out_label)

        if said != (chain, factors, evidence, ruled_out):
            raise AssertionError(f"Expected the chain headed [{chain}], the factors "
                                 f"[{factors}], the evidence labelled [{evidence}] and "
                                 f"what was ruled out [{ruled_out}], got {said}.")

        return True

    return assertion
