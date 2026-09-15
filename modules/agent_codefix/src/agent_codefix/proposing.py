"""Proposing a permanent fix for the cause an incident was traced to."""

from __future__ import annotations


def propose_fix(hypothesis: str) -> str | None:
    """Stub Code-Fix (spec §7.4) - exists as a real graph node so the FSM's
    shape is complete (design.md Non-Goals). No RAG, no PR, no `git-mcp` call.

    Returns `None`: there is no fix to propose yet. It reports that rather than
    raising, because `fixing` is a state incidents actually reach now - a
    mitigation the metrics refuted routes here - and an incident that was
    correctly investigated, correctly mitigated and correctly refuted must
    reach a human as an incident in `fixing`, not as a stack trace out of the
    webhook that dropped everything already learned about it.

    Whoever calls this reads the answer. `None` is a fix that was looked for
    and not found, which is a different thing from one nobody looked for, and
    the day this returns something the caller carries it.
    """
    return None
