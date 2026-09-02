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
from agent_investigator.budget import Budget
from agent_investigator.retrieval import fetch_change_events, fetch_logs, fetch_metrics
from argus_core.events import Publisher, nobody
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.change_event import ChangeEvent
from argus_core.models.metrics import MetricBucket

from .budget import a_budget
from .incident import an_alert

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
                    publisher: Publisher = nobody) -> Findings:
        return investigate(
            alert or an_alert(),
            incident_id=incident_id or new_id(),
            fetch_metrics=self.metrics_fetcher,
            fetch_logs=self.log_fetcher,
            fetch_change_events=self.change_fetcher,
            converse=self.model,
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
        metrics_fetcher=create_autospec(fetch_metrics, return_value=[]),
        log_fetcher=create_autospec(fetch_logs, return_value=NO_LOGS),
        change_fetcher=create_autospec(fetch_change_events, return_value=[]),
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
