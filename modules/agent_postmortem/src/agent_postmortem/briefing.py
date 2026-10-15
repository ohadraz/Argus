"""What the postmortem's model is told once, ahead of every incident.

The standing half of the ask: how the cause is reasoned out, and whose account
to believe where two disagree. Neither changes between incidents, so neither
belongs in the message describing one - and sent as the request's `system`
(see `ModelPolicy.brief`), the words are byte-identical for every incident this
agent writes up.

The policy is handed out whole rather than the brief alone. The model and the
effort are the deployment's to choose, and a composition root handed the brief
as a separate value is one that can build a client without it - the model then
answers in exactly the same shape, from the incident alone, and nothing
downstream can tell.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import Effort, ModelPolicy

from agent_postmortem.prompting import (
    CAUSAL_CHAIN_FIELD,
    ROOT_CAUSE_FIELD,
    SUBMIT_TOOL_NAME,
    SYMPTOM_FIELD,
)

# Every point is here because a write-up went wrong without it, and nothing
# about a particular incident may ever be added: what makes the prefix worth
# caching is that these bytes do not change, and one interpolated detail would
# end that silently, with every test still passing.
#
# The record outranks a candidate because the candidates were written before
# anything was tried, and write-ups reasoned from ones the actions had since
# disproved. The five whys replaced "stop where the next why is about people",
# which ended chains at a person and wherever the prose read well.
STANDING_BRIEF: Final = "\n\n".join([
    f"You write the postmortem for an incident Argus has already handled. One "
    f"message describes it - what Argus did and read, the candidate causes, the "
    f"actions and what they came to, and every figure already measured - and you "
    f"answer by calling {SUBMIT_TOOL_NAME}. Nothing is left to look up.",

    "The candidates are the Investigator's account, written while the incident "
    "ran and before anything was tried. The record - the lines saying what Argus "
    "did, the changes, the log lines, the actions and their verdicts - is what "
    "happened. Where the two disagree, the record is right.",

    f"Write {CAUSAL_CHAIN_FIELD} as the five whys. The first step is the symptom: "
    f"what the people using the service saw, with the evidence that shows it. "
    f"The {SYMPTOM_FIELD} field is that step in a few words, and the two must "
    f"agree. Each step after it answers why the step before happened - one "
    f"cause, no jumps - and cites its evidence from the record, never a "
    f"candidate: a candidate is a hypothesis, and the chain says what happened. "
    f"Five is a guide, not a quota: "
    f"stop where the evidence stops. The {ROOT_CAUSE_FIELD} field is the last "
    f"step of the chain.",

    "A why the record cannot answer - a missing test, a missing safeguard, an "
    "alert that came late - is a contributing factor rather than a step, and "
    "each contributing factor names an action item that answers it. Where one "
    "why has several answers, follow the one that leads to the fault and make "
    "the others contributing factors.",

    "Never stop at a person. Where somebody's action set the incident off, ask "
    "why the system let that action do harm - why it was possible at all - and "
    "carry on from there."
])


def postmortem_policy(model: str, effort: Effort) -> ModelPolicy:
    """The postmortem's model at the deployment's choice of model and effort,
    asked under the agent's own brief."""
    return ModelPolicy(model=model, effort=effort, brief=STANDING_BRIEF)
