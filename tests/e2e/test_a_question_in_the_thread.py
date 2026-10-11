"""A person asking, in the incident's thread, what happened.

Argus answers in the same thread, from what the incident's record holds and
nothing else. The question is asked once the incident has ended, the case a
question most has to survive: the walk is over, nothing is waiting on the
thread, and the answer still comes - with the whole record there to answer
from.

What the answer says is not asserted. That is the model's reading of the
record, and a replay proves only that the pipeline carried the question to one
and the answer back to the thread; whether it stayed inside the record is the
eval's question.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx2
import psycopg
import pytest
from agent_intent.understanding import COULD_NOT_ANSWER
from argus_core.events import QuestionAnswered
from argus_incidents.repository import events
from argus_testkit import Assertion, Scenario, calling, eventually

from tests.e2e.framework.argus import (
    DATABASE_URL,
    RECORDED_FLAG_TOGGLE,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_is_triggered_with_alert,
    argus_wrote_a_postmortem,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.chat import (
    RECORDED_INTENT_QUESTION,
    THE_WORDS_CLASSIFIED_AS_QUESTION,
    a_person_writes,
    posted_to_slack,
    the_intent_agent_answers_from,
    the_thread_of,
)
from tests.e2e.framework.world import a_scenario_was_seeded

# How long the intent agent has to read the question and answer it: two model
# calls and a poll either side, with room for a loaded machine.
_LONG_ENOUGH_TO_ANSWER = 60.0


@pytest.mark.e2e
def test_a_question_asked_after_the_incident_ended_is_answered_in_its_thread() -> None:
    # The walk has written its postmortem, so nothing in Argus is waiting on the
    # thread. The person asks what happened, and is answered where they asked -
    # the answer the incident's account keeps, said there, and not the line a
    # person is given when the model could not answer.
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name="HighErrorRate",
                                            severity="critical")
    some_person_id = "U0SOMEONE"

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("feature-flag-toggle")),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE)),
            calling(the_intent_agent_answers_from(RECORDED_INTENT_QUESTION))
        ) \
        .when(
            _a_question_is_asked_once_the_incident_has_ended(some_alert, some_person_id)
        ) \
        .then(
            eventually(_the_thread_was_told_the_answer(), timeout=_LONG_ENOUGH_TO_ANSWER)
        )


def _a_question_is_asked_once_the_incident_has_ended(
    alert: dict[str, object],
    person_id: str
) -> Callable[[], httpx2.Response]:
    """Fires the alert, waits for the walk's postmortem - the last thing it
    writes - and asks in the incident's thread."""
    def step() -> httpx2.Response:
        response = argus_is_triggered_with_alert(alert)()
        thread = the_thread_of(incident_id_from(response))

        eventually(argus_wrote_a_postmortem(), timeout=WALK_TIMEOUT_SECONDS)(response)
        a_person_writes(person_id, THE_WORDS_CLASSIFIED_AS_QUESTION, in_thread=thread)

        return response

    return step


def _the_thread_was_told_the_answer() -> Assertion[httpx2.Response]:
    """The one answer the incident's account keeps, said in the thread the
    question was asked in - and an answer, not the line for having none."""
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        _, thread = the_thread_of(incident_id)

        with psycopg.connect(DATABASE_URL) as conn:
            recorded = events.get_by_incident(conn, incident_id)

        answers = [event.answer for event in recorded if isinstance(event, QuestionAnswered)]

        if len(answers) != 1:
            raise AssertionError(
                f"Expected incident [{incident_id}]'s account to hold one answer to "
                f"the question asked, and it holds {answers}."
            )

        if answers[0] == COULD_NOT_ANSWER:
            raise AssertionError(
                f"Expected the question to be answered, and the person was told the "
                f"model could not answer it: [{answers[0]}]."
            )

        said = [message["text"] for message in posted_to_slack()
                if message.get("thread_ts") == thread]

        if not any(answers[0] in text for text in said):
            raise AssertionError(
                f"Expected the thread to be told the answer [{answers[0]}], and it "
                f"was told {said}."
            )

        return True

    return assertion
