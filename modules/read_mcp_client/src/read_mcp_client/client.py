from __future__ import annotations

from typing import Final

from argus_core import ReadMcpEndpoint
from argus_core.mcp_transport import McpClient
from argus_core.models import ChangeEvent, MetricBucket
from pydantic import TypeAdapter

# What each tool answers with, said once. The transport hands back whatever the
# server put in its structured content, and these are what turn that into the
# values this module's signatures promise - one adapter per tool rather than a
# `cast` at every call site and a `model_validate` in a comprehension beside it.
_LOG_LINES: Final = TypeAdapter(list[str])
_METRIC_BUCKETS: Final = TypeAdapter(list[MetricBucket])
_CHANGE_EVENTS: Final = TypeAdapter(list[ChangeEvent])
_FLAG_NAMES: Final = TypeAdapter(list[str])
_FILE_PATHS: Final = TypeAdapter(list[str])
_SOURCE: Final = TypeAdapter(str)

# Where the server's tools are served, under the address the endpoint names.
# Here rather than at each call because it is the read tier's own spelling of
# one fact, and four copies of it are four chances to disagree.
_MCP_PATH: Final = "/mcp"


def read_mcp(endpoint: ReadMcpEndpoint) -> McpClient:
    """A client holding one session to `argus-read-mcp`.

    Built where a process starts, held for as long as that process reads
    anything, and closed on the way out. The endpoint is read once, here, so
    that nothing below this line has to know how an address is configured -
    which is the whole of what a tool function needs from a deployment.
    """
    return McpClient(f"{endpoint.read_mcp_url}{_MCP_PATH}")


def get_log_lines(alert_time: str | None = None,
                  window_start: str | None = None,
                  window_end: str | None = None,
                  filters: str | None = None,
                  *,
                  client: McpClient) -> list[str]:
    """Reads the Target Service's log lines for one window of an incident.

    Phase two of spec §16's two-phase retrieval - see `argus-read-mcp`'s
    `get_log_lines` for how the window is derived and clamped. Times are
    ISO-8601 strings. Retrieval is by window only: a window anchored on the
    onset a `get_metrics_summary` result located, reaching back before it.
    """
    return client.call(
        "get_log_lines",
        _LOG_LINES.validate_python,
        alert_time=alert_time,
        window_start=window_start,
        window_end=window_end,
        filters=filters,
    )


def get_metrics_summary(alert_time: str | None = None,
                        window_start: str | None = None,
                        window_end: str | None = None,
                        *,
                        client: McpClient) -> list[MetricBucket]:
    """Reads per-minute aggregated metrics for one window of an incident.

    Phase one of spec §16's two-phase retrieval: the buckets it returns show
    which minutes are anomalous, and the earliest anomalous one gives the
    onset a follow-up `get_log_lines` window is anchored on.
    """
    return client.call(
        "get_metrics_summary",
        _METRIC_BUCKETS.validate_python,
        alert_time=alert_time,
        window_start=window_start,
        window_end=window_end)


def get_change_events(service: str,
                      window_start: str,
                      window_end: str,
                      *,
                      client: McpClient) -> list[ChangeEvent]:
    """Reads what changed on a service within one window of an incident.

    The third retrieval channel (spec §16). Its window is deliberately far
    wider than a log window's: a deploy or a flag flip can precede the symptoms
    it causes by an unbounded lag, and there are only ever a handful of changes
    to read where there would be millions of log lines.

    Raises rather than returning an empty list when the change source cannot be
    reached, because "nothing changed" is a conclusion a caller will act on.
    """
    return client.call(
        "get_change_events",
        _CHANGE_EVENTS.validate_python,
        service=service,
        window_start=window_start,
        window_end=window_end,
    )


def get_enabled_flags(*, client: McpClient) -> list[str]:
    """Reads which feature flags are currently evaluating true.

    Evaluated per call rather than cached, so it reflects a change made by
    anyone - a human in the provider's console, or Mitigation through the write
    tier - as of now. Mitigation reads this to learn which flag an incident is
    about; the flag is never named in Argus's own configuration.

    Raises rather than returning an empty list when the provider cannot be
    reached: an outage read as "no flag is on" would look like an environment
    with nothing to revert.
    """
    return client.call("get_enabled_flags", _FLAG_NAMES.validate_python)


def list_repository_files(ref: str, *, client: McpClient) -> list[str]:
    """Reads every file in the Target Service's repository at `ref`.

    The first half of localizing a fault (spec §7.4): one call names the whole
    repository, and what a fix needs to read next is picked out of it.

    Raises rather than returning a short list when the repository could not be
    listed in full - a listing missing files reads exactly like a repository
    that does not have them, and the fix goes to the wrong file.
    """
    return client.call(
        "list_repository_files",
        _FILE_PATHS.validate_python,
        ref=ref,
    )


def read_repository_file(path: str, ref: str, *, client: McpClient) -> str:
    """Reads what one file in the Target Service's repository says, at `ref`.

    On the read client because reading source is reading: the credential behind
    this call cannot push, so the repository becoming visible to Argus does not
    make the read tier capable of changing it (§13). Writing a fix is the write
    tier's `commit_to_new_branch`.

    Raises rather than answering emptily for a path that is not there. A file
    that exists and says nothing is a real thing a repository holds, and a model
    that cannot tell the two apart patches a module it never read.
    """
    return client.call(
        "read_repository_file",
        _SOURCE.validate_python,
        path=path,
        ref=ref,
    )
