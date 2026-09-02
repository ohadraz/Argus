from __future__ import annotations

import pytest
from agent_investigator import Findings
from argus_core.events import (
    ChannelsUnread,
    HypothesisFormed,
    IncidentEvent,
    LogsRetrieved,
    MetricsRetrieved,
    OnsetDetected,
    RetrievalChannel,
    RetrievalRequested,
)
from argus_core.models.metrics import MetricBucket
from argus_testkit import Assertion, Scenario, all_of

from .framework.builders.incident import a_window_that_starts_calm, the_onset_of
from .framework.builders.investigation import Investigation, an_investigation
from .framework.builders.model import (
    CHANGES_TOOL,
    LOGS_TOOL,
    WINDOW_END_ARG,
    WINDOW_START_ARG,
    a_model_that_says,
    a_turn_answering,
    a_turn_calling,
    an_explanation,
)

"""The investigation, narrated as it happens.

Control flow is the model's now, so two runs of one incident can read
different evidence - which makes a bug reproduce intermittently and the
transcript the only way to see why. That is what raises narration here from
principle to necessity: an account naming every window asked for, in order, is
what an investigation can be reconstructed from afterwards.

The other half is what was *not* read. A channel nobody asked for and a
channel that came back empty leave the same silence behind and mean opposite
things, so the investigation says which channels it never asked.
"""


@pytest.mark.unit
def test_each_retrieval_is_published_with_the_window_it_asked_for() -> None:
    # In order, and naming the windows the model chose rather than any the
    # loop would have chosen for it. This is the record a rerun that read
    # something different is compared against.
    some_window_start = "2026-08-20T10:30:00Z"
    some_window_end = "2026-08-20T11:00:00Z"
    an_earlier_window_start = "2026-08-20T09:30:00Z"
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(LOGS_TOOL, {WINDOW_START_ARG: some_window_start,
                                       WINDOW_END_ARG: some_window_end}),
            a_turn_calling(LOGS_TOOL, {WINDOW_START_ARG: an_earlier_window_start,
                                       WINDOW_END_ARG: some_window_end}),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_windows_asked_about_were(
                published,
                RetrievalChannel.LOGS,
                (some_window_start, some_window_end),
                (an_earlier_window_start, some_window_end)
            )
        )


@pytest.mark.unit
def test_what_a_retrieval_returned_is_published_with_it() -> None:
    # The lines themselves, not a reference to fetch them again: the log store
    # moves on, and a page that re-asked would show what the service says now
    # rather than what Argus read.
    some_lines = ["11:02 ERROR checkout failed", "11:03 ERROR checkout failed"]
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(LOGS_TOOL),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm()),
            investigation.logs_showed(some_lines)
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_lines_published_were(published, some_lines)
        )


@pytest.mark.unit
def test_the_metrics_the_loop_read_itself_are_published() -> None:
    # The one retrieval the model did not choose. It still belongs in the
    # account: the onset every window is anchored on was measured from these
    # minutes, and a reader who cannot see them cannot check it.
    some_metrics = a_window_that_starts_calm()
    published: list[IncidentEvent] = []
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            investigation.metrics_showed(some_metrics)
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_buckets_published_were(published, some_metrics)
        )


@pytest.mark.unit
def test_the_onset_it_found_is_published() -> None:
    # A measurement, and the anchor of every window that follows - so it is
    # stated in the account rather than left to be re-derived from the buckets
    # by whoever reads it.
    some_metrics = a_window_that_starts_calm()
    published: list[IncidentEvent] = []
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            investigation.metrics_showed(some_metrics)
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_onset_published_was(published, the_onset_of(some_metrics))
        )


@pytest.mark.unit
def test_every_candidate_it_formed_is_published_with_what_it_rests_on() -> None:
    # Every one, not only the one the walk tries first: a runner-up that never
    # reached the table is a finding a human picking the incident up cannot
    # otherwise see Argus ever having had. Each carries its own evidence,
    # because a claim published without it is an assertion.
    the_best_explanation = "the payments flag was switched on at 11:10"
    the_runner_up = "the 11:04 deploy changed the checkout path"
    some_evidence = ["11:10 INFO flag payments-v2 enabled"]
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_answering(
                an_explanation(summary=the_best_explanation,
                               confidence=0.8,
                               supporting_evidence=some_evidence),
                an_explanation(summary=the_runner_up, confidence=0.6)
            )
        )
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            all_of(
                _the_candidates_published_were(published, the_best_explanation, the_runner_up),
                _the_first_candidate_published_rests_on(published, some_evidence)
            )
        )


@pytest.mark.unit
def test_a_channel_that_was_never_asked_for_is_published_as_unread() -> None:
    # "Nobody asked" and "asked, and nothing came back" leave the same silence
    # in an account and mean opposite things - one is a gap in the
    # investigation, the other is a finding about the service.
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(LOGS_TOOL),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_channels_published_as_unread_were(published, RetrievalChannel.CHANGES)
        )


@pytest.mark.unit
def test_a_channel_that_came_back_empty_is_not_published_as_unread() -> None:
    # The other half of the same distinction. A channel that was read and had
    # nothing in it was not a gap in the investigation, and reporting it as one
    # would send a human looking for evidence Argus already went and got.
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(CHANGES_TOOL),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm()),
            investigation.no_changes_were_recorded()
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_channels_published_as_unread_were(published, RetrievalChannel.LOGS)
        )


@pytest.mark.unit
def test_an_investigation_nobody_is_listening_to_concludes_the_same_thing() -> None:
    # Narration is an account of the work, never a participant in it. The
    # investigation with a publisher and the one without must reach the same
    # answer, or the account is changing what it describes.
    the_answer = "the payments flag was switched on at 11:10"
    heard = _an_investigation_answering(the_answer)
    unheard = _an_investigation_answering(the_answer)

    Scenario() \
        .given(
            heard.metrics_showed(a_window_that_starts_calm()),
            unheard.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: (
                heard.investigate(publisher=lambda dont_care_event: None),
                unheard.investigate()
            )
        ) \
        .then(
            _both_concluded_the_same()
        )


def _an_investigation_answering(summary: str) -> Investigation:
    """One incident, arranged twice - so the only difference between the two
    runs is whether anybody is listening."""
    return an_investigation(
        a_model_that_says(
            a_turn_calling(LOGS_TOOL),
            a_turn_answering(an_explanation(summary=summary))
        )
    )


def _the_windows_asked_about_were(published: list[IncidentEvent],
                                  channel: RetrievalChannel,
                                  *windows: tuple[str, str]) -> Assertion[Findings]:
    """Every request on one channel, in the order it was made."""
    def assertion(dont_care_findings: Findings) -> bool:
        asked = [
            (event.window_start, event.window_end)
            for event in published
            if isinstance(event, RetrievalRequested) and event.channel == channel
        ]
        if asked != list(windows):
            raise AssertionError(f"Expected {list(windows)} to have been asked for, got {asked}.")

        return True

    return assertion


def _the_lines_published_were(published: list[IncidentEvent],
                              lines: list[str]) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        retrieved = [event for event in published if isinstance(event, LogsRetrieved)]
        if not retrieved:
            raise AssertionError(
                "Expected the lines that came back to be published, and none were."
            )

        retrieved_lines = retrieved[0].lines
        if retrieved_lines != lines:
            raise AssertionError(f"Expected the lines {lines}, got {retrieved_lines}.")

        return True

    return assertion


def _the_buckets_published_were(published: list[IncidentEvent],
                                buckets: list[MetricBucket]) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        retrieved = [event for event in published if isinstance(event, MetricsRetrieved)]
        if not retrieved:
            raise AssertionError(
                "Expected the metrics that were read to be published, and none were."
            )

        retrieved_buckets = retrieved[0].buckets
        if retrieved_buckets != buckets:
            raise AssertionError(f"Expected the buckets {buckets}, got {retrieved_buckets}.")

        return True

    return assertion


def _the_onset_published_was(published: list[IncidentEvent], onset: str) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        detected = [event for event in published if isinstance(event, OnsetDetected)]
        if not detected:
            raise AssertionError("Expected the onset to be published, and it was not.")

        detected_onset = detected[0].onset
        if detected_onset != onset:
            raise AssertionError(f"Expected the onset [{onset}], got [{detected_onset}].")

        return True

    return assertion


def _the_candidates_published_were(published: list[IncidentEvent],
                                   *summaries: str) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        formed = [
            event.summary for event in published if isinstance(event, HypothesisFormed)
        ]
        if formed != list(summaries):
            raise AssertionError(f"Expected the candidates {list(summaries)}, got {formed}.")

        return True

    return assertion


def _the_first_candidate_published_rests_on(published: list[IncidentEvent],
                                            evidence: list[str]) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        formed = [event for event in published if isinstance(event, HypothesisFormed)]
        if not formed:
            raise AssertionError("Expected a candidate to be published, and none was.")

        formed_evidence = formed[0].evidence
        if formed_evidence != evidence:
            raise AssertionError(
                f"Expected the candidate to rest on {evidence}, got {formed_evidence}."
            )

        return True

    return assertion


def _the_channels_published_as_unread_were(published: list[IncidentEvent],
                                           *channels: RetrievalChannel) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        unread = [event for event in published if isinstance(event, ChannelsUnread)]
        if not unread:
            raise AssertionError("Expected the unread channels to be published, and they were not.")

        unread_channels = unread[0].channels
        if unread_channels != list(channels):
            raise AssertionError(
                f"Expected {list(channels)} to be reported unread, got {unread_channels}."
            )

        return True

    return assertion


def _both_concluded_the_same() -> Assertion[tuple[Findings, Findings]]:
    """The account is not a participant: it changes nothing about the answer."""
    def assertion(concluded: tuple[Findings, Findings]) -> bool:
        heard, unheard = concluded
        said = [candidate.summary for candidate in heard.candidates]
        said_unheard = [candidate.summary for candidate in unheard.candidates]
        if said != said_unheard:
            raise AssertionError(
                f"Expected the same conclusion either way, got {said} and {said_unheard}."
            )

        if heard.already_read != unheard.already_read:
            raise AssertionError(
                f"Expected the same evidence to be read either way, got "
                f"{heard.already_read} and {unheard.already_read}."
            )

        return True

    return assertion
