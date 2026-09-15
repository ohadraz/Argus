"""The Code-Fix agent: a permanent fix for the cause, where there is one.

The last thing tried, and the only one that outlives the incident - a reverted
flag is a change somebody has to come back to, and a fix is the reason they do
not. Still a stub (spec §7.4): it answers that it has nothing to propose, which
is an answer rather than an absence, and the walk reports what it said.
"""

from __future__ import annotations

from agent_codefix.proposing import propose_fix

__all__ = ["propose_fix"]
