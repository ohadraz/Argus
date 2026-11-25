"""The deployment platform, held in memory: a double of the port, for suites.

A second adapter of `deployment_platform`'s port, and never one a process
runs: a platform whose rollback succeeds in memory would have Argus report a
mitigation that never happened, so it lives where nothing that ships can
install it. It is held to the port by the port's own suite, which runs it
beside the vendor's adapter over one seed and asks both the same questions.

`PlatformState` is the seed - what the platform holds before anybody asks -
and `InMemoryPlatform` answers both ports from it, each write changing what
the reads then answer.
"""

from __future__ import annotations

from deployment_platform_double.in_memory import InMemoryPlatform
from deployment_platform_double.state import (
    ApplicationState,
    AutoscalerState,
    Container,
    HistoryEntry,
    Node,
    PlatformState,
    Pod,
    Rendering,
)

__all__ = [
    "ApplicationState",
    "AutoscalerState",
    "Container",
    "HistoryEntry",
    "InMemoryPlatform",
    "Node",
    "PlatformState",
    "Pod",
    "Rendering"
]
