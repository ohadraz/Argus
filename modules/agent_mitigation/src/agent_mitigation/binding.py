"""Binding the agent's capabilities to the tier they are performed over.

Every other module here states a capability and declares what it needs; this
one is where a deployment hands those needs a client. It exists because one of
those bindings is wanted in two places - the walk binds an undo so a refuted
mitigation can put itself back, and the worker binds one so a withdrawn
incident can - and two copies of a binding is how the second came to be missing
a collaborator the first had, with every gate green and the failure waiting on
the path nobody runs by accident.

Separate from `tools` rather than beside the other `*_over` functions, because
what it binds spans the package: `undo_change` needs the seams `tools` declares
*and* the provider check `attribution` computes, so a binder living in `tools`
would make `tools` import `undoing`, which already imports `tools`.
"""

from __future__ import annotations

from functools import partial

from argus_core.mcp_transport import McpClient

from agent_mitigation.tools import (
    MitigationSettings,
    deployment_restorer_over,
    flag_changes_over,
    flag_setter_over,
    somebody_else_changed_flag_since,
)
from agent_mitigation.trying import UndoChange
from agent_mitigation.undoing import undo_change

__all__ = ["an_undo_over"]


def an_undo_over(client: McpClient, settings: MitigationSettings) -> UndoChange:
    """Putting one recorded change back, over one connection to the write tier.

    Whole, which is the only property worth stating: an undo bound short is a
    well-typed object that raises the first time somebody puts a change back,
    and the two callers that want one reach it on paths - a refuted mitigation,
    a withdrawn incident - that a green suite does not exercise.

    `set_state` is bound here even though `take_action` passes its own. The
    binding has to stand on its own for the caller that does not - a withdrawal
    holds no flag setter of its own - and a keyword the caller supplies wins
    over one bound here, so the two cannot disagree.
    """
    return partial(
        undo_change,
        changed_from_outside=partial(
            somebody_else_changed_flag_since,
            settings=settings,
            fetch=flag_changes_over(client)
        ),
        set_state=flag_setter_over(client),
        restore_deployment=deployment_restorer_over(client)
    )
