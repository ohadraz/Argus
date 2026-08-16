from __future__ import annotations


def propose_fix(hypothesis: str) -> str:
    """Stub Code-Fix (spec §7.4) - exists as a real graph node so the FSM's
    shape is complete (design.md Non-Goals), but this change's happy path
    never routes to it. No RAG, no PR, no `git-mcp` call."""
    raise NotImplementedError("Code-Fix is not driven end-to-end in the walking-skeleton change")
