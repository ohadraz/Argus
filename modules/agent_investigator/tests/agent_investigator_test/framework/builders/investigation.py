"""The investigation under test: its seams, and the call that uses them.

A builder rather than five locals per test. The loop takes three retrieval
seams, a model and a budget, and repeating their construction in every test
buried the one line each test is actually about. The `given` steps say what
each stand-in *reported*, so the arrangement still reads in the test rather
than hiding in a fixture.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple
from unittest.mock import Mock, create_autospec

from agent_investigator import Findings, Reading, investigate
from agent_investigator.budget import Budget, InvestigationSettings
from agent_investigator.retrieval import ChangeFetcher, LogFetcher, MetricsFetcher
from argus_core import new_id
from argus_core.events import Publisher, nobody
from argus_core.llm import Conversations, a_conversation_recorded_for
from argus_core.models import Alert, Attempt, ChangeEvent, MetricBucket

from agent_investigator_test.framework.builders.budget import a_budget
from agent_investigator_test.framework.builders.configuration import (
    some_investigation_settings,
    some_thresholds,
)
from agent_investigator_test.framework.builders.incident import an_alert

NO_LOGS: list[str] = []


class Investigation(NamedTuple):
    metrics_fetcher: Mock
    log_fetcher: Mock
    change_fetcher: Mock
    model: Mock
    budget: Budget

    def investigate(self,
                    alert: Alert | None = None,
                    incident_id: str | None = None,
                    already_refuted: list[Attempt] | None = None,
                    already_read: list[Reading] | None = None,
                    publisher: Publisher = nobody,
                    settings: InvestigationSettings | None = None,
                    conversations: Conversations | None = None) -> Findings:
        """The loop, run with whatever this investigation was built around.

        `conversations` is the one argument here that changes which seam is
        exercised rather than what it answers. Left out, the scripted model
        goes in as `converse` and the factory is never reached - which is what
        every test of the loop's own decisions wants. Named, the factory is
        under test and nothing is handed in already built, so what the loop
        asked to be built with is observable.
        """

        return investigate(
            alert or an_alert(),
            incident_id=incident_id or new_id(),
            fetch_metrics=self.metrics_fetcher,
            fetch_logs=self.log_fetcher,
            fetch_change_events=self.change_fetcher,
            settings=settings or some_investigation_settings(),
            thresholds=some_thresholds(),
            converse=None if conversations is not None else self.model,
            conversations=conversations or a_conversation_recorded_for,
            budget=self.budget,
            already_refuted=already_refuted,
            already_read=already_read,
            publisher=publisher
        )

    def metrics_showed(self, buckets: list[MetricBucket]) -> Callable[[], None]:
        return _returning(self.metrics_fetcher, buckets)

    def logs_showed(self, lines: list[str]) -> Callable[[], None]:
        return _returning(self.log_fetcher, lines)

    def changes_were(self, changes: list[ChangeEvent]) -> Callable[[], None]:
        return _returning(self.change_fetcher, changes)

    def no_changes_were_recorded(self) -> Callable[[], None]:
        return _returning(self.change_fetcher, [])

    def the_change_source_failed(self, error: Exception) -> Callable[[], None]:
        return _raising(self.change_fetcher, error)


def an_investigation(model: Mock, budget: Budget | None = None) -> Investigation:
    """The loop, with a scripted model and every channel answering emptily.

    The model is the one collaborator with no useful default: what it says is
    the whole subject of a loop test. The channels answer with nothing unless a
    test says otherwise, so a test about the model's choices cannot pass
    because of evidence it never mentioned.
    """
    return Investigation(
        metrics_fetcher=create_autospec(MetricsFetcher, instance=True, return_value=[]),
        log_fetcher=create_autospec(LogFetcher, instance=True, return_value=NO_LOGS),
        change_fetcher=create_autospec(ChangeFetcher, instance=True, return_value=[]),
        model=model,
        budget=budget or a_budget()
    )


def _returning(double: Mock, value: object) -> Callable[[], None]:
    """A `given` step that fixes what a stand-in answers with."""
    def step() -> None:
        double.return_value = value

    return step


def _raising(double: Mock, error: Exception) -> Callable[[], None]:
    """A `given` step for a channel that cannot be reached at all."""
    def step() -> None:
        double.side_effect = error

    return step
