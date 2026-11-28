"""The alerting platform, held in memory: a double of the port, for suites.

A second adapter of `alerting_platform`'s port, and never one a process runs: a
rule read as normal from memory would have Argus judge a mitigation by an
evaluation nobody ran, so it lives where nothing that ships can install it. It
is held to the port by the port's own suite, which runs it beside the vendor's
adapter over one seed and asks both the same questions.

`AlertingState` is the seed - each rule the platform evaluates, as a
`HeldRule`: its evaluation, and whether that evaluation measured anything - and
`InMemoryAlertingPlatform` answers the port from it.
"""

from __future__ import annotations

from alerting_platform_double.in_memory import InMemoryAlertingPlatform
from alerting_platform_double.state import AlertingState, HeldRule

__all__ = [
    "AlertingState",
    "HeldRule",
    "InMemoryAlertingPlatform"
]
