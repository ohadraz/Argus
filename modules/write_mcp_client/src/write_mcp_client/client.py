from __future__ import annotations

from typing import Any, cast

from argus_core.config import get_settings
from argus_core.mcp_transport import call_mcp_tool
from argus_core.models.flag_change import FlagChange


def set_feature_flag(flag: str, enabled: bool) -> dict[str, Any]:
    """Sets a feature flag on or off, returning the undo descriptor for the
    change.

    The reversible action of spec §7.3: Mitigation's response to a flag-toggle
    cause. The descriptor it returns records the state that existed before, and
    is what the Orchestrator's gate node requires before this call is reached
    at all (§13) - and what puts the flag back if the mitigation turns out to
    be refuted.

    `enabled` is the state to leave the flag in, so undoing a change is this
    same call with it reversed. Mitigation needs both directions: a flag that
    was switched off can cause an incident exactly as one switched on can, and
    is undone by switching it back on.

    Raises rather than returning quietly when the flag did not actually reach
    that state. A verdict formed against a service nothing was done to would
    describe an experiment that never ran.
    """
    settings = get_settings()
    result = call_mcp_tool(
        f"{settings.write_mcp_url}/mcp",
        "set_feature_flag",
        flag=flag,
        enabled=enabled,
    )
    return cast(dict[str, Any], result)


def get_recent_flag_changes(since: str) -> list[FlagChange]:
    """Reads the flag toggles the provider recorded since `since`, oldest first.

    How Mitigation learns which flag an incident is about, and in which
    direction it moved - neither of which current flag state can answer, since
    a flag switched off into an incident evaluates exactly like one that has
    been off for a year.

    On the write client rather than the read client because the provider serves
    its history to admin credentials only, and `argus-read-mcp` holds none by
    design. Reading is less than the write tier can already do; the tier split
    is the claim that the *read* process cannot mutate.

    Raises rather than returning an empty list when the provider cannot be
    reached: "nothing changed" is a conclusion the caller escalates on.
    """
    settings = get_settings()
    result = call_mcp_tool(
        f"{settings.write_mcp_url}/mcp",
        "get_recent_flag_changes",
        since=since,
    )
    return [FlagChange.model_validate(change) for change in cast(list[object], result)]
