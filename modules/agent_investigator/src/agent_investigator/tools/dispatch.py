"""What happens when the model calls one of the tools it was offered.

One call in, one result out, the routing between them, and a record of what
has been read. Every channel's own behaviour - its window, its default, its
ceiling - stays with the channel; what lives here is which name reaches which
channel, what happens to a name that reaches none, and what the investigation
has to show for itself afterwards.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from argus_core.events import Narrator, RetrievalChannel, nobody
from argus_core.models.reading import Reading
from argus_core.models.transcript import ToolResult
from argus_core.models.turn import ToolCall
from argus_core.replay import CallType, Replay

from agent_investigator.retrieval import (
    ChangeFetcher,
    LogFetcher,
    MetricsFetcher,
    fetch_change_events,
    fetch_logs,
    fetch_metrics,
)
from agent_investigator.tools.answer import ANSWER_TOOL
from agent_investigator.tools.changes import CHANGES_TOOL, read_changes
from agent_investigator.tools.logs import LOGS_TOOL, read_logs
from agent_investigator.tools.metrics import METRICS_TOOL, read_metrics
from agent_investigator.tools.results import Served, could_not_serve

# Reading the clock, so a test can hand over one that does not tick. A
# `Callable` rather than a Protocol because it takes no arguments: there are no
# keywords to name and nothing for `create_autospec` to get wrong.
Clock = Callable[[], float]

_MILLISECONDS_PER_SECOND = 1000


class Dispatcher:
    """One tool call in, one tool result out.

    It holds the three facts a window is anchored on - the service, the onset
    the loop measured, and the moment the alert fired - so that a model naming
    no window still gets the right one rather than the retrieval source's own
    idea of a default.

    `having_read` is what the investigation read before the model's first
    turn - in practice the metrics, which the loop reads itself to locate the
    onset. Told here so that the record of what was read is one record, and so
    that a model asking for the same fixed span again is refused like any other
    repeat: those minutes are already in front of it, in the opening message.

    It also remembers what it has served, which does two jobs. A window asked
    for twice is refused rather than read again: the model already has those
    lines, and serving them costs a retrieval and a turn's worth of tokens to
    tell it nothing. And what was read is what a later round is shown, so that
    a round bought by a refutation does not pay again for the same evidence.

    The memory is per investigation, not per incident. A later round is told
    what an earlier one read in its opening message, but is free to read it
    again - the evidence is not in *its* transcript, and re-reading is how it
    gets there.

    The fetchers are default-argument seams, as everywhere else in this module:
    the real read-tier calls in production, doubles in a test, and no
    monkeypatching either way.

    `replay` is where a served retrieval leaves its receipt (spec §4 principle
    6), and defaults to one that reaches nobody, exactly as the narrator beside
    it does. Kept here rather than in each channel because this is the one place
    every call passes through: three channels each keeping their own receipt
    would be three chances to forget, and a fourth added later would arrive
    silent.

    A monotonic clock, not a wall clock: what is measured is how long a
    retrieval took, and a wall clock can step sideways mid-call and record a
    read that finished before it started.

    `final_answer` never arrives here. It is the loop's exit and produces no
    evidence, so a call to it that reached this far would be a mistake in the
    loop rather than in the model - and it is reported as a call this cannot
    serve, like any other name that is not a channel.
    """

    def __init__(self,
                 service: str,
                 onset: str,
                 alert_time: str | None,
                 narrator: Narrator | None = None,
                 replay: Replay | None = None,
                 having_read: Sequence[Reading] = (),
                 fetch_metrics: MetricsFetcher = fetch_metrics,
                 fetch_logs: LogFetcher = fetch_logs,
                 fetch_change_events: ChangeFetcher = fetch_change_events,
                 clock: Clock = time.monotonic) -> None:
        self._service = service
        self._onset = onset
        self._alert_time = alert_time
        self._narrator = narrator if narrator is not None else Narrator("", nobody)
        self._replay = replay if replay is not None else Replay("")
        self._clock = clock
        self._fetch_metrics = fetch_metrics
        self._fetch_logs = fetch_logs
        self._fetch_change_events = fetch_change_events
        self._readings: list[Reading] = list(having_read)

    @property
    def channels_unread(self) -> list[RetrievalChannel]:
        """The channels this investigation never asked about.

        Derived from what was served rather than tracked separately: a channel
        is unread exactly when nothing it produced is in the record, and two
        accounts of the same fact would eventually disagree.
        """
        read = {reading.channel for reading in self._readings}

        return [channel for channel in RetrievalChannel if channel not in read]

    @property
    def readings(self) -> list[Reading]:
        """What this investigation has read, in the order it read it.

        A copy, because it is a record: something reading it later must not be
        able to edit what happened, and this list is still being appended to.
        """
        return list(self._readings)

    def dispatch(self, call: ToolCall) -> ToolResult:
        """Serves one call the model made, labelled with the call it answers.

        A name that is not a channel comes back as a failed result rather than
        as an exception: a model that invented a tool has misunderstood
        something the correction is cheap for - but only if it is told, and
        silently ignoring the call would leave it waiting on a result that
        never comes.

        A receipt is kept for what was served and for nothing else. A reading is
        exactly the evidence that a channel was actually read - a tool name that
        is no channel, a window that ends before it starts, a window already
        read, all come back without one - and a row for those would be a receipt
        for a call nobody made, in a table something later counts retrievals in.
        """
        started_at = self._clock()
        answer = self._serve(call)

        if answer.reading is not None:
            self._readings.append(answer.reading)
            self._record(call, answer.reading, answer.result, since=started_at)

        return answer.result

    def _record(self,
                call: ToolCall,
                reading: Reading,
                result: ToolResult,
                since: float) -> None:
        """Writes down one retrieval, timed from `since` to now.

        The window recorded is the one that was read, not the one that was
        asked for. They differ whenever a default was supplied or a ceiling
        applied, and an entry naming the arguments alone stands in for a call
        that was never made. What the model asked for is kept beside it, since
        the gap between the two is the whole account of what a channel did with
        a request.

        The reading is taken as an argument rather than read back off the
        result, because it is what says the call was served at all - a
        signature that could be handed a retrieval which never happened would
        need a guard here, and the caller has already made that decision.
        """
        self._replay.record(
            call_type=CallType.MCP,
            target=call.name,
            request={
                "arguments": dict(call.arguments),
                "window_start": reading.window_start,
                "window_end": reading.window_end
            },
            response={"content": result.content},
            latency_ms=int((self._clock() - since) * _MILLISECONDS_PER_SECOND)
        )

    def _serve(self, call: ToolCall) -> Served:
        if call.name == METRICS_TOOL:
            return read_metrics(
                call, self._alert_time, self._fetch_metrics, self._readings, self._narrator
            )

        if call.name == LOGS_TOOL:
            return read_logs(
                call, self._onset, self._alert_time, self._fetch_logs,
                self._readings, self._narrator
            )

        if call.name == CHANGES_TOOL:
            return read_changes(
                call, self._service, self._onset, self._fetch_change_events,
                self._readings, self._narrator
            )

        return could_not_serve(
            call,
            f"there is no tool called {call.name!r}. The tools available are "
            f"{METRICS_TOOL}, {LOGS_TOOL}, {CHANGES_TOOL} and {ANSWER_TOOL}."
        )
