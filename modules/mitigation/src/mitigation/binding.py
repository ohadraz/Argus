"""Binding the Mitigator's capabilities to the tier they are performed over.

Every other module here states a capability and declares what it needs; this
one is where a deployment hands those needs a client. It exists because one of
those bindings is wanted in two places - the walk binds an undo so a refuted
mitigation can put itself back, and the worker binds one so a withdrawn
incident can - and two copies of a binding is how the second came to be missing
a collaborator the first had, with every gate green and the failure waiting on
the path nobody runs by accident.

Separate from `tools` rather than beside the other `*_over` functions, because
what it binds spans the package: `undo_change` lives in `kinds`, which imports
`tools`, so a binder living in `tools` would make the two import each other.
"""

from __future__ import annotations

from functools import partial

from core.mcp_transport import McpClient

from mitigation.kinds import undo_change
from mitigation.tools import putting_back_over
from mitigation.trying import UndoChange

__all__ = ["an_undo_over"]


def an_undo_over(client: McpClient) -> UndoChange:
    """Putting one recorded change back, over one connection to the write tier.

    Whole, which is the only property worth stating: the two callers that want
    one reach it on paths - a refuted mitigation, a withdrawn incident - that a
    green suite does not exercise. `PuttingBack` is what holds it whole, since
    a bundle missing a member is a type error rather than an undo that raises
    the first time somebody puts a change back.
    """
    return partial(undo_change, putting_back=putting_back_over(client))
