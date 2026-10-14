"""A person telling Argus, in the incident's thread, what they know.

Two flags moved in the same minute. A person who thinks they know which one
broke the shop says so. What they say is a lead - weighed by the Investigator,
never obeyed - and these cases are about it arriving, being weighed, the person
being told in their thread how, and being reported in the write-up under their
name with the standing it was given and what it changed.

Two moments it can arrive at, because the Investigator reads leads at two: as
it opens, where every lead written so far is in its first message, and between
its turns, where a lead written since rides on the next result.

Both are put in an order rather than raced. Nothing in Argus stands between an
alert and the Investigator's opening, so for the first the case suspends the
worker before the alert and resumes it once the lead is understood - the
thread, the ingestion and the intent agent all run without it. For the second
the walk's model holds its first call, so the person writes after the opening
has gone out and before its answer has come back - and the lead rides on the
results of that first turn.

Which standing the lead is given is not asserted, nor what the write-up says
it changed. Those are the model's judgement of the evidence, and a replay
proves only that the pipeline carried the lead to one and reported it; whether
a lead moves the model is the eval's question.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx2
import psycopg
import pytest
from argus_core.models import PostmortemLead, ThreadMessage
from argus_incidents.repository import conversation, postmortems
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    DATABASE_URL,
    RECORDED_LEAD_BEFORE_THE_WALK,
    RECORDED_LEAD_MID_INVESTIGATION,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_is_triggered_with_alert,
    argus_wrote_a_postmortem,
    incident_id_from,
    the_held_call_arrived,
    the_held_model_answers_from,
    the_model_answers_from,
    the_model_is_held,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.chat import (
    RECORDED_INTENT_INFORMATION,
    THE_WORDS_CLASSIFIED_AS_INFORMATION,
    a_person_writes,
    posted_to_slack,
    the_chat_platform_knows,
    the_intent_agent_answers_from,
    the_message_became_a_lead,
    the_thread_of,
)
from tests.e2e.framework.worker import the_worker_is_paused, the_worker_resumes
from tests.e2e.framework.world import a_scenario_was_seeded

_THE_SCENARIO = "competing-flag-changes"


@pytest.mark.e2e
def test_a_lead_written_before_the_walk_is_in_the_investigations_opening() -> None:
    # The person writes before anything has walked the incident, so the lead is
    # in the Investigator's first message rather than arriving later. It is
    # weighed, the person is told how in their thread, and the write-up reports
    # it under their name with the standing it was given and what it changed.
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name="HighErrorRate",
                                            severity="critical")
    some_person_id = "U0SOMEONE"
    some_name = "Some Person"

    Scenario() \
        .given(
            calling(a_scenario_was_seeded(_THE_SCENARIO,
                                          as_recorded_in=RECORDED_LEAD_BEFORE_THE_WALK)),
            calling(the_model_answers_from(RECORDED_LEAD_BEFORE_THE_WALK)),
            calling(the_intent_agent_answers_from(RECORDED_INTENT_INFORMATION)),
            calling(the_chat_platform_knows(some_person_id, some_name)),
            calling(the_worker_is_paused())
        ) \
        .when(
            _argus_is_told_before_it_investigates(some_alert, some_person_id)
        ) \
        .then(
            eventually(
                all_of(
                    argus_wrote_a_postmortem(),
                    _the_lead_was_weighed(),
                    _the_thread_was_told_how_the_lead_was_weighed(),
                    _the_postmortem_reports_the_lead(written_by=some_name)
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


@pytest.mark.e2e
def test_a_lead_written_mid_investigation_reaches_the_next_turn() -> None:
    # The person writes while the investigation is under way - after its
    # opening has gone out and before the answer to it has come back - so the
    # lead reaches the model with its first turn's results rather than in its
    # opening, and is weighed, told and reported the same as one there from
    # the start.
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name="HighErrorRate",
                                            severity="critical")
    some_person_id = "U0SOMEONE"
    some_name = "Some Person"

    Scenario() \
        .given(
            calling(a_scenario_was_seeded(_THE_SCENARIO,
                                          as_recorded_in=RECORDED_LEAD_MID_INVESTIGATION)),
            calling(the_model_is_held()),
            calling(the_intent_agent_answers_from(RECORDED_INTENT_INFORMATION)),
            calling(the_chat_platform_knows(some_person_id, some_name))
        ) \
        .when(
            _argus_is_told_while_its_first_turn_is_held(some_alert, some_person_id)
        ) \
        .then(
            eventually(
                all_of(
                    argus_wrote_a_postmortem(),
                    _the_lead_was_weighed(),
                    _the_thread_was_told_how_the_lead_was_weighed(),
                    _the_postmortem_reports_the_lead(written_by=some_name)
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _argus_is_told_before_it_investigates(
    alert: dict[str, object],
    person_id: str
) -> Callable[[], httpx2.Response]:
    """Fires the alert with the worker paused, writes the lead in the thread,
    waits for it to be understood, and lets the worker go."""
    def step() -> httpx2.Response:
        response = argus_is_triggered_with_alert(alert)()
        incident_id = incident_id_from(response)

        a_person_writes(person_id, THE_WORDS_CLASSIFIED_AS_INFORMATION,
                        in_thread=the_thread_of(incident_id))
        the_message_became_a_lead(incident_id)
        the_worker_resumes()

        return response

    return step


def _argus_is_told_while_its_first_turn_is_held(
    alert: dict[str, object],
    person_id: str
) -> Callable[[], httpx2.Response]:
    """Fires the alert, waits for the walk's first call to be held, writes the
    lead in the thread, waits for it to be understood, and answers the walk."""
    def step() -> httpx2.Response:
        response = argus_is_triggered_with_alert(alert)()
        incident_id = incident_id_from(response)
        thread = the_thread_of(incident_id)

        the_held_call_arrived()
        a_person_writes(person_id, THE_WORDS_CLASSIFIED_AS_INFORMATION, in_thread=thread)
        the_message_became_a_lead(incident_id)
        the_held_model_answers_from(RECORDED_LEAD_MID_INVESTIGATION)()

        return response

    return step


def _the_lead_was_weighed() -> Assertion[httpx2.Response]:
    """The investigation gave the lead a standing, on the row the agents read
    it from - whichever standing the evidence left it."""
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        lead = _the_one_lead_of(incident_id)

        if lead.weighing is None:
            raise AssertionError(
                f"Expected the lead [{lead.text}] to have been weighed by the "
                f"investigation, and it carries no weighing."
            )

        return True

    return assertion


def _the_thread_was_told_how_the_lead_was_weighed() -> Assertion[httpx2.Response]:
    """The person who wrote the lead was told, in the thread they wrote it in,
    why it stands where it does - the reason kept on the lead's row, said there."""
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        lead = _the_one_lead_of(incident_id)
        _, thread = the_thread_of(incident_id)

        if lead.weighing is None:
            raise AssertionError(f"The lead [{lead.text}] was never weighed, so nothing "
                                 f"could be told of it.")

        said = [message["text"] for message in posted_to_slack()
                if message.get("thread_ts") == thread]

        if not any(lead.weighing.reason in text for text in said):
            raise AssertionError(
                f"Expected the thread to be told why the lead stands "
                f"[{lead.weighing.standing}] - [{lead.weighing.reason}] - and it was "
                f"told {said}."
            )

        return True

    return assertion


def _the_postmortem_reports_the_lead(written_by: str) -> Assertion[httpx2.Response]:
    """The write-up carries the lead under the name of whoever wrote it, with
    the standing the investigation gave it and a sentence on what it changed -
    the person who wrote it is owed the line."""
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        lead = _the_one_lead_of(incident_id)
        reported = _the_lead_reported_in(incident_id, lead)

        if reported.weighing != lead.weighing or reported.person_name != written_by \
                or not reported.effect:
            raise AssertionError(
                f"Expected the postmortem to report the lead [{lead.text}] written by "
                f"[{written_by}], weighed [{lead.weighing}], with what it changed, and it "
                f"reports {reported}."
            )

        return True

    return assertion


def _the_lead_reported_in(incident_id: str, lead: ThreadMessage) -> PostmortemLead:
    """The postmortem's line for this lead, found by its words."""
    with psycopg.connect(DATABASE_URL) as conn:
        postmortem = postmortems.get_by_incident(conn, incident_id)

    if postmortem is None:
        raise AssertionError(f"No postmortem exists for incident [{incident_id}].")

    reported = [line for line in postmortem.leads if line.text == lead.text]

    if len(reported) != 1:
        raise AssertionError(
            f"Expected the postmortem to report the lead [{lead.text}] once, and it "
            f"reports {[line.text for line in postmortem.leads]}."
        )

    return reported[0]


def _the_one_lead_of(incident_id: str) -> ThreadMessage:
    """The incident's lead, of which each case writes exactly one."""
    with psycopg.connect(DATABASE_URL) as conn:
        leads = conversation.get_leads_by_incident(conn, incident_id)

    if len(leads) != 1:
        raise AssertionError(
            f"Expected incident [{incident_id}] to hold the one lead the case wrote, "
            f"and it holds {[lead.text for lead in leads]}."
        )

    return leads[0]
