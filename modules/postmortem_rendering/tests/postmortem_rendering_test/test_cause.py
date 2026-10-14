"""Why it happened: the root cause, the chain of whys under it with what each
rests on, and the factors that let it.

All of it the model's prose, said as prose - a destination may link the labels
it cites - and the evidence beside each step in the record's words. Each case
is one postmortem and what one part of the section says.
"""

from __future__ import annotations

import pytest
from argus_core.models import ChainStep, CitedEvidence, ContributingFactor
from argus_testkit import Assertion, Scenario, the_answer_was
from postmortem_rendering.cause import CauseSection, ChainLink, Factor, the_cause
from postmortem_rendering.lines import Line, Role, Run

from postmortem_rendering_test.framework.builders import a_postmortem


@pytest.mark.unit
def test_the_root_cause_is_said_as_the_model_s_prose() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(root_cause="An empty month divided by zero, per C1.")
        ) \
        .when(
            lambda: the_cause(some_postmortem).root_cause
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
            lambda: the_cause(some_postmortem).root_cause
        ) \
        .then(
            the_answer_was(None))


@pytest.mark.unit
def test_the_chain_starts_at_the_symptom_and_asks_why_of_each_step_with_its_evidence() -> None:
    # Without the prompt's labels: they named the evidence for the model, and
    # mean nothing to a reader.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(causal_chain=[
                ChainStep(text="account pages failed",
                          cites=[CitedEvidence(label="E1", text="500s on /account")]),
                ChainStep(text="the monthly average divided by zero",
                          cites=[CitedEvidence(label="E3", text="ZeroDivisionError"),
                                 CitedEvidence(label="E4", text="no items this month")])])
        ) \
        .when(
            lambda: the_cause(some_postmortem).chain
        ) \
        .then(
            the_answer_was((
                ChainLink(place="symptom",
                          claim=Line(runs=(Run(text="account pages failed", role=Role.PROSE),)),
                          evidence=("500s on /account",)),
                ChainLink(place="why 2",
                          claim=Line(runs=(Run(text="the monthly average divided by zero",
                                               role=Role.PROSE),)),
                          evidence=("ZeroDivisionError", "no items this month")))))


@pytest.mark.unit
def test_the_chain_and_the_factors_are_headed_and_the_evidence_labelled() -> None:
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: the_cause(dont_care_postmortem)
        ) \
        .then(
            _it_is_headed("Causal chain", "Contributing factors", "Evidence:"))


@pytest.mark.unit
def test_no_chain_says_none_was_written() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(causal_chain=[])
        ) \
        .when(
            lambda: the_cause(some_postmortem).chain_absent
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
            lambda: the_cause(some_postmortem).chain_absent
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
            lambda: the_cause(some_postmortem).factors
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
            lambda: the_cause(some_postmortem).factors[0].addressed_by
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
            lambda: the_cause(some_postmortem).factors_absent
        ) \
        .then(
            the_answer_was("No contributing factors were named."))


def _it_is_headed(chain: str, factors: str, evidence: str) -> Assertion[CauseSection]:
    def assertion(cause: CauseSection) -> bool:
        said = (cause.chain_heading, cause.factors_heading, cause.evidence_label)

        if said != (chain, factors, evidence):
            raise AssertionError(f"Expected the chain headed [{chain}], the factors "
                                 f"[{factors}] and the evidence labelled [{evidence}], "
                                 f"got {said}.")

        return True

    return assertion
