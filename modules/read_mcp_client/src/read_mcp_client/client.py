from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from types import TracebackType
from typing import Final, Self

from core import ReadMcpEndpoint
from core.mcp_transport import Asking, McpClient
from core.models import (
    AlertRuleStanding,
    ChangeEvent,
    CodeOutsideThePatch,
    DeploymentChanges,
    MetricBucket,
    PodPlacement,
    RolloutAccount,
    RolloutProgress,
    ServiceDependency,
    ToolDefinition,
)
from pydantic import TypeAdapter

from read_mcp_client.offering import offered

# What each tool answers with, said once. The transport hands back whatever the
# server put in its structured content, and these are what turn that into the
# values this module's signatures promise - one adapter per tool rather than a
# `cast` at every call site and a `model_validate` in a comprehension beside it.
_LOG_LINES: Final = TypeAdapter(list[str])
_METRIC_BUCKETS: Final = TypeAdapter(list[MetricBucket])
_CHANGE_EVENTS: Final = TypeAdapter(list[ChangeEvent])
_FLAG_NAMES: Final = TypeAdapter(list[str])
_SERVICE_DEPENDENCIES: Final = TypeAdapter(list[ServiceDependency])
_FILE_PATHS: Final = TypeAdapter(list[str])
_WHAT_A_DEPLOYMENT_CHANGED: Final = TypeAdapter(DeploymentChanges)
_ROLLOUT_STATE: Final = TypeAdapter(RolloutAccount)
_ROLLOUT_PROGRESS: Final = TypeAdapter(RolloutProgress)
_ALERT_RULE: Final = TypeAdapter(AlertRuleStanding)
_PLACEMENTS: Final = TypeAdapter(list[PodPlacement])
_PASSAGES: Final = TypeAdapter(list[str])
_NOTICE: Final = TypeAdapter(str)
_SOURCE: Final = TypeAdapter(str)
_CONTAINED: Final = TypeAdapter(bool)
_CODE_OUTSIDE: Final = TypeAdapter(CodeOutsideThePatch)

# Where the server's tools are served, under the address the endpoint names.
# Here rather than at each call because it is the read tier's own spelling of
# one fact, and four copies of it are four chances to disagree.
_MCP_PATH: Final = "/mcp"


def read_mcp(endpoint: ReadMcpEndpoint,
             builds_client: Callable[..., McpClient] = McpClient) -> ReadTier:
    """The read tier, over one session held to `argus-read-mcp`.

    Built where a process starts, held for as long as that process reads
    anything, and closed on the way out. The endpoint is read once, here, so
    that nothing below this line has to know how an address is configured -
    which is the whole of what a tool needs from a deployment.

    Each call waits as long as the endpoint says for its answer: above the
    slowest tool this tier serves, a read of the repository's whole archive
    (`get_code_outside_the_patch`) under a thirty-second timeout of its own.
    Every read may be asked again, so one that meets it is asked once more.
    `builds_client` builds the session, and is a parameter so that what it was
    built with can be asserted without building one.
    """
    return ReadTier(builds_client(f"{endpoint.read_mcp_url}{_MCP_PATH}",
                                  answered_within=endpoint.read_mcp_answered_within_seconds))


class ReadTier:
    """`argus-read-mcp`, one method per tool it serves.

    A type of its own rather than the session it is asked over, because the
    two tiers are two authorities and a session is a session: held as a bare
    client, the read tier and the write tier were interchangeable to the type
    checker, and a seam bound to the wrong one failed only when it was asked -
    for a rollout's progress, once the walk had already changed production.
    Nothing here can write, and the write tier's class has none of these
    methods, so binding a read to the wrong tier is a type error.

    Each method is the tool's own calling shape, so a bound method is what an
    agent's seam is bound to - `read.get_placements` where the Investigator
    asks where the replicas run - with nothing between them to re-spell it.
    """

    def __init__(self, session: McpClient) -> None:
        self._session = session

    def __enter__(self) -> Self:
        return self

    def __exit__(self,
                 exc_type: type[BaseException] | None,
                 exc: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self._session.close()

    def offered(self, holds: Mapping[str, Collection[str]]) -> list[ToolDefinition]:
        """The tools `holds` names, as this tier declares them, in the order
        `holds` names them - each less the arguments `holds` says its caller
        fills in (`offering.offered`)."""
        return offered(holds, self._session.list_tools())

    def get_log_lines(self,
                      *,
                      alert_time: str | None = None,
                      window_start: str | None = None,
                      window_end: str | None = None,
                      filters: str | None = None) -> list[str]:
        """Reads the Target Service's log lines for one window of an incident.

        Phase two of spec §16's two-phase retrieval - see `argus-read-mcp`'s
        `get_log_lines` for how the window is derived and clamped. Times are
        ISO-8601 strings. Retrieval is by window only: a window anchored on the
        onset a `get_metrics_summary` result located, reaching back before it.

        Keyword-only, all four, because all four are the same type: a seam that
        passed two of them by position would type-check against this and read
        the wrong window.
        """
        return self._session.call(
            "get_log_lines",
            _LOG_LINES.validate_python,
            asking=Asking.READ,
            alert_time=alert_time,
            window_start=window_start,
            window_end=window_end,
            filters=filters,
        )

    def get_metrics_summary(self,
                            *,
                            alert_time: str | None = None,
                            window_start: str | None = None,
                            window_end: str | None = None,
                            rule: str | None = None) -> list[MetricBucket]:
        """Reads per-minute aggregated metrics for one window of an incident.

        Phase one of spec §16's two-phase retrieval: the buckets it returns show
        which minutes are anomalous, and the earliest anomalous one gives the
        onset a follow-up `get_log_lines` window is anchored on. `rule` is the uid
        of the alert rule that paged; where its series can be followed, each bucket
        carries that series' reading as `rule_reading`.

        Keyword-only, for `get_log_lines`'s reason: a rule passed by position
        would arrive as the alert's time.
        """
        return self._session.call(
            "get_metrics_summary",
            _METRIC_BUCKETS.validate_python,
            asking=Asking.READ,
            alert_time=alert_time,
            window_start=window_start,
            window_end=window_end,
            rule=rule)

    def get_change_events(self,
                          service: str,
                          window_start: str,
                          window_end: str) -> list[ChangeEvent]:
        """Reads what changed on a service within one window of an incident.

        The third retrieval channel (spec §16). Its window is deliberately far
        wider than a log window's: a deploy or a flag flip can precede the symptoms
        it causes by an unbounded lag, and there are only ever a handful of changes
        to read where there would be millions of log lines.

        Raises rather than returning an empty list when the change source cannot be
        reached, because "nothing changed" is a conclusion a caller will act on.
        """
        return self._session.call(
            "get_change_events",
            _CHANGE_EVENTS.validate_python,
            asking=Asking.READ,
            service=service,
            window_start=window_start,
            window_end=window_end,
        )

    def get_what_a_deployment_changed(self, service: str, revision: str) -> DeploymentChanges:
        """Reads what one deployment of a service changed - the files that differ
        from the revision deployed before it, and the change made to each - and
        whether the answer names every one of them.

        The evidence that separates a bad deployment from a broken configuration, and
        the only evidence that does. Both arrive as a deployment and are put right the
        same way; what differs is whether the commit touched source code or the values
        it shipped with, and that is inside the commit. A deploy's own summary cannot
        say - an application syncs from one directory for its whole life, so the path
        is the same whatever the commit changed.

        `revision` is the deploy's reference as the change channel reported it. What
        it is compared against is not passed: the revision deployed before it lives in
        the deployment history, which the caller cannot see, so naming it would be
        naming a guess - and a diff against a guessed base describes the wrong change
        in the shape a right one has.

        A revision no deployment has, a deployment with nothing before it, and a
        deployment that changed nothing all come back as answers, because each is a
        fact about the deployment history and each calls for something different.
        Raises when the repository could not be compared: "it changed nothing" rules a
        deployment out as a cause, and an outage is not evidence for that.
        """
        return self._session.call(
            "get_what_a_deployment_changed",
            _WHAT_A_DEPLOYMENT_CHANGED.validate_python,
            asking=Asking.READ,
            service=service,
            revision=revision,
        )

    def get_rollout_state(self, service: str) -> RolloutAccount:
        """Reads whether the deployment a service is running has finished arriving.

        The evidence that separates a revision which is wrong from two revisions
        serving at once, and the only evidence that does. The deploy history reports
        that a revision was deployed and cannot report whether it reached every
        replica: a history records syncs that completed, and a rollout is a stretch
        rather than an instant.

        Worth reading whenever a deployment precedes the onset - before the revision
        is named as the fault, and before returning it is proposed. A deployment that
        converged is an answer too: it rules the split out and leaves the revision
        itself as the subject.

        What comes back describes and does not judge. Every deployment is part way
        through for a minute or two, so the answer says what the platform reports and
        when the state began, and whether that is too long is the caller's to decide
        against an onset this channel has never seen. It is a value - the counts, and
        the revision going out and the one before it - and saying it is the caller's.

        Raises rather than answering that the deployment converged when the platform
        could not be reached. That answer rules a mode out, so an outage read as
        convergence sends a walk to blame a revision that is not at fault.
        """
        return self._session.call(
            "get_rollout_state",
            _ROLLOUT_STATE.validate_python,
            asking=Asking.READ,
            service=service
        )

    def get_rollout_progress(self, service: str) -> RolloutProgress:
        """Reads how many of a service's replicas have reached the revision being
        rolled out, as counts.

        The same channel as `get_rollout_state` and the other half of its audience.
        That one names the revisions a reader weighs; this answers a caller in
        numbers alone, and reads no history to do it.

        Who waits on it: an agent that has just changed something and may not measure
        anything until the change has arrived. A rollback is accepted long before it
        has converged, so the minutes between are minutes the previous revision was
        still serving, and a verdict read off them is a verdict about the wrong code.

        Converged is not *stuck*. This reports a count reaching its target; how long
        that may take is a judgement the read tier declines to make, and nothing here
        makes it on the way past.

        Raises rather than answering that the rollout arrived when the platform could
        not be reached, for the reason the sentences do - except that it matters more
        here, because a caller told the change has landed begins judging at once.
        """
        return self._session.call(
            "get_rollout_progress",
            _ROLLOUT_PROGRESS.validate_python,
            asking=Asking.READ,
            service=service
        )

    def get_alert_rule(self, rule: str) -> AlertRuleStanding:
        """Reads whether an alert rule has stopped firing, as of its last
        evaluation, and how the rule reads its service.

        What Mitigation judges an action on a series alert by: the rule that paged
        defines what is acceptable for the service. `rule` is the reference the
        alert carried, whichever vendor's rule it is. Raises rather than answering
        normal when the rule cannot be read.
        """
        return self._session.call("get_alert_rule", _ALERT_RULE.validate_python,
                                  asking=Asking.READ, rule=rule)

    def get_placements(self, service: str) -> list[PodPlacement]:
        """Reads where each of a service's replicas runs - its node, that node's
        card, and when the pod started.

        The evidence for the one failure mode whose cause is a placement: a replica
        moved onto another card with nothing deployed is in no history, no diff and
        no flag log. The Investigator reads it on every incident, before its model is
        asked anything, and puts each start either side of the onset.

        Raises rather than answering that the service runs nowhere when the platform
        could not be reached: an empty answer finds no replica that moved, which is
        an outage read as an all-clear.
        """
        return self._session.call(
            "get_placements",
            _PLACEMENTS.validate_python,
            asking=Asking.READ,
            service=service
        )

    def branch_contains_revision(self, branch: str, revision: str) -> bool:
        """Reads whether `revision` is in `branch`'s history.

        What Code-Fix is told before it reads anything: the revision running when the
        alert fired may have been deployed from a branch never merged into the
        one it reads, and then the files it opens are not the files that ran.

        Raises rather than answering that the branch does not contain it when the
        repository could not be reached: told so, Code-Fix hedges every claim it
        makes about the code, on a fact nobody established.
        """
        return self._session.call(
            "branch_contains_revision", _CONTAINED.validate_python, asking=Asking.READ,
            branch=branch, revision=revision
        )

    def get_enabled_flags(self) -> list[str]:
        """Reads which feature flags are currently evaluating true.

        Evaluated per call rather than cached, so it reflects a change made by
        anyone - a human in the provider's console, or Mitigation through the write
        tier - as of now. Mitigation reads this to learn which flag an incident is
        about; the flag is never named in Argus's own configuration.

        Raises rather than returning an empty list when the provider cannot be
        reached: an outage read as "no flag is on" would look like an environment
        with nothing to revert.
        """
        return self._session.call("get_enabled_flags", _FLAG_NAMES.validate_python,
                                  asking=Asking.READ)

    def get_service_dependencies(self, service: str) -> list[ServiceDependency]:
        """Reads what a service calls, and whose each of those is.

        The one channel that answers whether a failing dependency is the
        organisation's own, which is what separates a propagation incident somebody
        here can end from one only a telephone call can. Nothing else carries it: a
        host name is a spelling somebody chose, and the owning team does not settle
        it either, since somebody here owns the integration with a vendor.

        Read by the Orchestrator before a mitigation is chosen as well as by the
        Investigator while it works, and for two different reasons. The
        investigation needs it to name the cause; the choice of action needs it to
        know what Argus may address at all, and needs it in hand *before* the choice
        so that the gate can refuse without anything having been called.

        A service the register holds no entry for depends on nothing as far as
        anybody here knows, which is a real answer. Raises rather than returning an
        empty list when the register cannot be reached: an outage read as "it calls
        nothing" leaves the estate looking empty, and an empty estate is one where
        every address is out of reach - so an outage would silently forbid every
        mitigation instead of reporting itself.
        """
        return self._session.call(
            "get_service_dependencies",
            _SERVICE_DEPENDENCIES.validate_python,
            asking=Asking.READ,
            service=service,
        )

    def search_repository(self, query: str, ref: str) -> list[str]:
        """Reads every line in the Target Service's repository at `ref` holding
        `query`, as `path:line: text`.

        What turns a named cause into a place to look (spec §7.4). The
        investigation hands Code-Fix a flag, a function or a message; without this
        the only way to act on that name is to list every path and open files by
        guessing, which spends a reading budget on the wrong files.

        Raises rather than returning nothing when the source could not be read: a
        query that matches nothing is a fact about the repository and a useful one,
        where a repository that could not be fetched is not, and answered the same
        way it teaches a caller the cause is not in the code.
        """
        return self._session.call(
            "search_repository",
            _FILE_PATHS.validate_python,
            asking=Asking.READ,
            query=query,
            ref=ref,
        )

    def get_repository_index_freshness(self, ref: str) -> str:
        """Reads what has to be said about the index of the Target Service's source
        before anything it answers is acted on - empty when there is nothing.

        For assembling a prompt rather than for a model mid-task. The index is
        built off any incident's path (spec §11), so it can describe an older
        commit than the one being fixed, and Code-Fix states that up front rather
        than letting a model discover it from a patch against a file that has
        moved.
        """
        return self._session.call(
            "get_repository_index_freshness",
            _NOTICE.validate_python,
            asking=Asking.READ,
            ref=ref,
        )

    def search_repository_by_meaning(self, description: str, ref: str) -> list[str]:
        """Reads the passages of the Target Service's source nearest a description
        of what the code does, as `path:start-end` and the source itself.

        The channel for a cause with no name to match on (spec §7.4, §11). An
        investigation concluding "the discount is divided by a count that can be
        zero" gives `search_repository` nothing to search for - the word may appear
        nowhere - and this finds the code that behaves that way. The two are worth
        using together: one matches characters, the other meaning.

        An answer may open with a `note:` line saying the index describes an older
        commit than `ref`, in which case code that changed in between may not be
        findable here yet - the index is built off any incident's path, so it can
        lag the branch it describes.

        Raises rather than answering emptily when the index could not be searched.
        Nothing near enough is a fact about the repository; a store that could not
        be reached is not, and answered the same way it teaches a caller that the
        cause is not in the code.
        """
        return self._session.call(
            "search_repository_by_meaning",
            _PASSAGES.validate_python,
            asking=Asking.READ,
            description=description,
            ref=ref,
        )

    def get_code_outside_the_patch(self, files: dict[str, str], ref: str) -> CodeOutsideThePatch:
        """Reads how the Target Service's own code at `ref` uses what a patch -
        `files`, each path's whole new content - changes, line by line with what
        each line does, and every function and class defined outside the patch's
        files.

        For Code-Fix rather than for its model: what each line outside a patch does
        with what the patch changes is the syntax tree's to say, so a submission
        speaking of several of those pieces at once is sent back with these rows.

        Raises rather than answering that nothing uses what changed when the source
        could not be read - the silent answer says the patch touches nothing anybody
        reads.
        """
        return self._session.call(
            "get_code_outside_the_patch",
            _CODE_OUTSIDE.validate_python,
            asking=Asking.READ,
            files=files,
            ref=ref,
        )

    def list_repository_files(self, ref: str) -> list[str]:
        """Reads every file in the Target Service's repository at `ref`.

        The first half of localizing a fault (spec §7.4): one call names the whole
        repository, and what a fix needs to read next is picked out of it.

        Raises rather than returning a short list when the repository could not be
        listed in full - a listing missing files reads exactly like a repository
        that does not have them, and the fix goes to the wrong file.
        """
        return self._session.call(
            "list_repository_files",
            _FILE_PATHS.validate_python,
            asking=Asking.READ,
            ref=ref,
        )

    def read_repository_file(self, path: str, ref: str) -> str:
        """Reads what one file in the Target Service's repository says, at `ref`.

        On the read tier because reading source is reading: the credential behind
        this call cannot push, so the repository becoming visible to Argus does not
        make the read tier capable of changing it (§13). Writing a fix is the write
        tier's `commit_to_new_branch`.

        Raises rather than answering emptily for a path that is not there. A file
        that exists and says nothing is a real thing a repository holds, and a model
        that cannot tell the two apart patches a module it never read.
        """
        return self._session.call(
            "read_repository_file",
            _SOURCE.validate_python,
            asking=Asking.READ,
            path=path,
            ref=ref,
        )
