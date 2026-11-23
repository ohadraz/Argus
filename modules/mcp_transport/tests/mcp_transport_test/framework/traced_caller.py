"""One call asked from a process with an SDK installed as the process's own, as
the worker's is.

Two halves in one file, as the double's are: the caller, run as
`python -m mcp_transport_test.framework.traced_caller <url> <tool>`, and the
function a test asks it through. A process of its own, because the MCP SDK
traces every request it sends with the process's tracer, not one anybody hands
it - and a process's tracer is installed once, for good. Installed in the
suite's own process it would be every case's after the first; left out, as it
is everywhere else in the suite, the SDK's span is the API's no-op, and a call
reaches the server inside its caller's trace whatever the client does about
the SDK's span.

What the caller reports is everything traced on its side - the call's span and
the SDK's, each with its ids and its parent's - and the tool's answer, which
for the double's `the_trace_i_am_in` is where the server found itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from mcp_transport import Asking, McpClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# How long the call waits for its answer: past any call the double answers.
PATIENT_PAST_ANY_CALL: Final = 60.0
# How long the caller has to start, ask and report before it is taken to hang:
# a guard, never waited out by a case that passes - a loaded machine's
# interpreter takes seconds to import the SDK, not minutes.
CALLER_TIMEOUT_SECONDS: Final = 180.0


@dataclass(frozen=True)
class TracedSpan:
    """One span as the caller's process saw it end, ids in hex as OTLP spells
    them, so a test compares them with the server's without converting."""

    name: str
    kind: str
    trace_id: str
    span_id: str
    parent_span_id: str


@dataclass(frozen=True)
class AskedTraced:
    """What a call asked from a traced process came to: the tool's answer, and
    every span its process ended."""

    answer: Any
    spans: list[TracedSpan]


def asked_from_a_traced_process(url: str, tool: str) -> AskedTraced:
    """`tool` asked once, as a read, of the server at `url` by a client in a
    process with an SDK of its own installed - and what came of it."""
    finished = subprocess.run(
        [sys.executable, "-m", __name__, url, tool],
        env={**os.environ, "PYTHONPATH": str(_suite_root())},
        capture_output=True,
        text=True,
        timeout=CALLER_TIMEOUT_SECONDS,
        check=False
    )

    if finished.returncode != 0:
        raise RuntimeError(
            f"the traced caller ended with [{finished.returncode}]: {finished.stderr}"
        )

    said = json.loads(finished.stdout)

    return AskedTraced(answer=said["answer"],
                       spans=[TracedSpan(**span) for span in said["spans"]])


def _said(span: ReadableSpan) -> dict[str, str]:
    """One finished span, as the caller reports it."""
    context = span.get_span_context()

    # Typed as optional by the SDK, and never left out of a span it finished.
    if context is None:
        raise RuntimeError(f"the span [{span.name}] carried no context")

    return {
        "name": span.name,
        "kind": span.kind.name,
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
        "parent_span_id": format(span.parent.span_id, "016x") if span.parent is not None else ""
    }


def _suite_root() -> Path:
    """`modules/mcp_transport/tests`, which is what makes this importable by name."""
    return Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    # The process's own SDK, installed before the client is built, as a
    # worker's root installs one: the client takes the process's tracer where
    # it is handed none, and the MCP SDK takes it always.
    _exported = InMemorySpanExporter()
    _provider = TracerProvider()
    _provider.add_span_processor(SimpleSpanProcessor(_exported))
    trace.set_tracer_provider(_provider)

    with McpClient(sys.argv[1], answered_within=PATIENT_PAST_ANY_CALL) as _client:
        _answer = _client.call(sys.argv[2], lambda answer: answer, asking=Asking.READ)

    json.dump({"answer": _answer,
               "spans": [_said(span) for span in _exported.get_finished_spans()]},
              sys.stdout)
