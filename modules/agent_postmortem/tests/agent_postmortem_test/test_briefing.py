"""What the postmortem's model is told once, ahead of every incident.

The brief is the half of the ask that never changes: how the cause is reasoned
out, and whose account to believe where two disagree. It travels as the
request's `system`, inside the policy the client is built with - so the agent
hands the policy out whole, and a composition root choosing the model and the
effort cannot leave the brief behind.

Asserted by its distinctive words rather than its sentences, so the prose is
free to be improved and the teaching is not.
"""

from __future__ import annotations

import pytest
from agent_postmortem import STANDING_BRIEF, postmortem_policy
from argus_core.models import Effort, ModelPolicy
from argus_testkit import Assertion, Scenario, the_answer_was

# The five whys, by the words that carry its rules: where the chain starts,
# where it stops, where a why the record cannot answer goes, that it never
# stops at a person, and what the root cause is - the mechanism, not the
# chain's last step, which is often the change that set it off.
THE_FIVE_WHYS = ("five whys", "symptom", "evidence stops", "contributing factor",
                 "at a person", "says the mechanism")

# Whose account wins where the candidates and the record disagree.
THE_RECORD_OUTRANKS_A_CANDIDATE = ("Investigator's account", "the record is right")


@pytest.mark.unit
def test_the_postmortem_is_asked_under_its_brief() -> None:
    # The model and the effort are the deployment's to choose, and the brief is
    # the agent's. Handed out as one policy, a composition root naming only the
    # two it chooses still asks the model with the third.
    some_model = "claude-haiku-4-5"
    some_effort: Effort = "low"

    Scenario() \
        .when(
            lambda: postmortem_policy(some_model, some_effort)
        ) \
        .then(
            the_answer_was(ModelPolicy(model=some_model, effort=some_effort,
                                       brief=STANDING_BRIEF, one_tool_call_per_turn=True))
        )


@pytest.mark.unit
def test_the_postmortem_is_asked_for_one_tool_call_per_turn() -> None:
    # Its one tool ends the conversation, so a second call beside the first is
    # never a second piece of work. One arrived anyway - a submission filled
    # with placeholders - and refusing the pair cost a whole turn every walk.
    dont_care_model = "dont care which model"
    dont_care_effort: Effort = "low"

    Scenario() \
        .when(
            lambda: postmortem_policy(dont_care_model, dont_care_effort).one_tool_call_per_turn
        ) \
        .then(
            the_answer_was(True)
        )


@pytest.mark.unit
def test_the_brief_teaches_the_five_whys() -> None:
    # A chain asked for as "why, of the step before" stopped wherever the prose
    # read well, and stopped at people where it reached one. The five whys says
    # where it starts - what users saw - and where it stops: where the evidence
    # does, with every why the record cannot answer kept as a contributing
    # factor, and never at a person, whose action is a why about the system
    # that let it do harm.
    Scenario() \
        .when(
            lambda: STANDING_BRIEF
        ) \
        .then(
            _the_brief_mentions(*THE_FIVE_WHYS)
        )


@pytest.mark.unit
def test_the_brief_says_the_record_outranks_a_candidate() -> None:
    # The candidates were written while the incident ran, before anything was
    # tried, and the record holds what happened after. A write-up reasoning from
    # a candidate the record contradicts repeats a guess the walk had already
    # disproved, in the one document read after the incident is over.
    Scenario() \
        .when(
            lambda: STANDING_BRIEF
        ) \
        .then(
            _the_brief_mentions(*THE_RECORD_OUTRANKS_A_CANDIDATE)
        )


@pytest.mark.unit
def test_the_brief_says_a_step_cites_the_record_and_never_a_candidate() -> None:
    # A candidate is a hypothesis. Cited as a step's evidence, a guess reads as
    # a fact in the chain, and a reader following the citation finds the
    # Investigator's opinion where an observation should be.
    Scenario() \
        .when(
            lambda: STANDING_BRIEF
        ) \
        .then(
            _the_brief_mentions("never a candidate")
        )


@pytest.mark.unit
def test_the_brief_says_two_things_are_the_same_only_where_the_record_s_figures_are() -> None:
    # A write-up said the errors were logged over "the same stretch" the flag
    # was on for every request, though they began a minute before it. Each
    # figure was right; the sameness was not.
    Scenario() \
        .when(
            lambda: STANDING_BRIEF
        ) \
        .then(
            _the_brief_mentions("only where the record's figures for them are the same")
        )


def _the_brief_mentions(*expected: str) -> Assertion[str]:
    def assertion(brief: str) -> bool:
        missing = [mention for mention in expected if mention not in brief]

        if missing:
            raise AssertionError(f"Expected the brief to mention {missing}, and it does not.")

        return True

    return assertion
