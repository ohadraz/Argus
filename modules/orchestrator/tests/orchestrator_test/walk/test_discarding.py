"""A step about to run takes back what its interrupted attempt wrote.

Keyed by the step the walk binds around the node, and refused outside one: a
discard wrapped in the wrong order would publish the line saying the step was
run again as nobody's, which a second attempt would then never take back.

What is taken back, and whether the line is said, is the port's - one write,
asserted where the rows are (`component/test_records`). What is asserted here
is what the port is asked, and when.
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_answer_was,
)
from core.events import IncidentEvent, StepRunAgain
from core.models import Alert, IncidentStatus
from incident_record import within_step
from orchestrator.walk.discarding import (
    Discard,
    discarding_first,
    discarding_the_interrupted_attempt,
)
from orchestrator.walk.ports import DiscardTheInterruptedAttempt
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.builders import an_incident_state

type Asked = tuple[str, int, IncidentEvent]

DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
SOME_INCIDENT_ID = "6c1e4a8e-2f0b-4d8e-9a51-0d6f3c2b7e11"
SOME_STEP = 4
SOME_NODE = "tier_gate"
SOME_RESULT = {"candidate_index": 1}
# What each stand-in notes doing, in the order it does it.
DISCARDED = "discarded"
RAN = "ran"


@pytest.mark.unit
def test_a_step_takes_back_its_own_interrupted_attempt_and_names_itself() -> None:
    # The incident's own, at the step bound around it, saying which step it
    # is in words the line can carry.
    asked: list[Asked] = []

    Scenario() \
        .given(
            the_discard := discarding_the_interrupted_attempt(SOME_NODE,
                                                              _a_port_noting(asked))
        ) \
        .when(lambda: _inside_step(SOME_STEP, lambda: the_discard(_a_state()))) \
        .then(_the_port_was_asked(asked, SOME_INCIDENT_ID, SOME_STEP,
                                  StepRunAgain(incident_id=SOME_INCIDENT_ID, step=SOME_NODE)))


@pytest.mark.unit
def test_a_discard_outside_any_step_is_refused_and_takes_nothing_back() -> None:
    asked: list[Asked] = []

    Scenario() \
        .given(
            the_discard := discarding_the_interrupted_attempt(SOME_NODE,
                                                              _a_port_noting(asked))
        ) \
        .when(attempting(lambda: the_discard(_a_state()))) \
        .then(all_of(
            an_error_was_raised(RuntimeError),
            _the_port_was_never_asked(asked)
        ))


@pytest.mark.unit
def test_a_node_not_wrapped_in_with_status_discards_before_it_runs() -> None:
    happened: list[str] = []

    Scenario() \
        .given(
            a_discarding_node := discarding_first(_a_discard_noting(happened),
                                                  _a_node_noting(happened))
        ) \
        .when(lambda: a_discarding_node(_a_state())) \
        .then(_it_happened_in_order(happened, [DISCARDED, RAN]))


@pytest.mark.unit
def test_a_node_not_wrapped_in_with_status_hands_back_what_it_returned() -> None:
    happened: list[str] = []

    Scenario() \
        .given(
            a_discarding_node := discarding_first(_a_discard_noting(happened),
                                                  _a_node_noting(happened))
        ) \
        .when(lambda: a_discarding_node(_a_state())) \
        .then(the_answer_was(SOME_RESULT))


def _a_state() -> IncidentState:
    return an_incident_state(DONT_CARE_ALERT, IncidentStatus.MITIGATING,
                             incident_id=SOME_INCIDENT_ID)


def _inside_step(step: int, call: Any) -> Any:
    with within_step(step):
        return call()


def _a_port_noting(asked: list[Asked]) -> DiscardTheInterruptedAttempt:
    def discard(incident_id: str, step: int, saying: IncidentEvent, /) -> bool:
        asked.append((incident_id, step, saying))

        return True

    return discard


def _a_discard_noting(happened: list[str]) -> Discard:
    def discard(dont_care_state: IncidentState, /) -> None:
        happened.append(DISCARDED)

    return discard


def _a_node_noting(happened: list[str]) -> Any:
    def node(dont_care_state: IncidentState) -> dict[str, Any]:
        happened.append(RAN)

        return SOME_RESULT

    return node


def _the_port_was_asked(asked: list[Asked],
                        incident_id: str,
                        step: int,
                        saying: StepRunAgain) -> Assertion[Any]:
    """The line by what it says: its id and moment are its own."""
    def assertion(dont_care_result: Any) -> bool:
        said = [(asked_for, at_step, type(line), line.incident_id, getattr(line, "step", None))
                for asked_for, at_step, line in asked]
        expected = [(incident_id, step, StepRunAgain, saying.incident_id, saying.step)]

        if said != expected:
            raise AssertionError(
                f"Expected the port asked once, as {expected}, it was asked {said}."
            )

        return True

    return assertion


def _the_port_was_never_asked(asked: list[Asked]) -> Assertion[Exception | None]:
    def assertion(dont_care_raised: Exception | None) -> bool:
        if asked:
            raise AssertionError(f"Expected nothing taken back, the port was asked {asked}.")

        return True

    return assertion


def _it_happened_in_order(happened: list[str], expected: list[str]) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        if happened != expected:
            raise AssertionError(f"Expected {expected}, in that order, got {happened}.")

        return True

    return assertion
