"""The feature-flag provider, held in memory: a double of the port, for suites.

A second adapter of `flag_provider`'s port, and never one a process runs: a
provider whose toggle succeeds in memory would have Argus report a mitigation
that never happened, so it lives where nothing that ships can install it. It is
held to the port by the port's own suite, which runs it beside the vendor's
adapter over one seed and asks both the same questions.

`ProviderState` is the seed - what the provider holds before anybody asks, its
history among it as `RecordedToggle`s - and `InMemoryFlagProvider` answers every
port from it, each write changing what the reads then answer.
"""

from __future__ import annotations

from flag_provider_double.in_memory import InMemoryFlagProvider
from flag_provider_double.state import ProviderState, RecordedToggle

__all__ = [
    "InMemoryFlagProvider",
    "ProviderState",
    "RecordedToggle"
]
