"""The Code-Fix agent: a permanent fix for the cause, where there is one.

The last thing tried, and the only one that outlives the incident - a reverted
flag is a change somebody has to come back to, and a fix is the reason they do
not (spec §7.4).

It reads the service's source over the read tier, writes a patch to a branch of
its own over the write tier, and opens a draft pull request. That is as far as
it goes, by construction rather than by restraint: merging is a deploy, and the
tool for it exists nowhere on either server (§13).
"""

from __future__ import annotations

from agent_codefix.proposing import (
    FixNotAnswered,
    FixSettings,
    fixes_over,
    propose_fix,
)

__all__ = ["FixNotAnswered", "FixSettings", "fixes_over", "propose_fix"]
