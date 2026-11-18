"""The mark a platform write is made under, read off the call that asked for it.

The action is the walk's, and arrives in the call's `_meta` beside the fence,
because the tool's own arguments are what a model is offered and this is not the
model's to say. The moment is the stack's clock, read where the tier writes -
the one a claim and the platform's history are dated by, a replay's simulated
one included. A call naming no action has no mark to give and says so rather
than having one made up for it: a write marked for an action nobody took is
worse than one never marked.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from core import utc_now
from core.mcp_transport import ACTION_META_KEY
from deployment_platform import Mark


def the_action_in(meta: Mapping[str, Any] | None) -> str | None:
    """The action a call's `_meta` names, by its row's id, or `None` where it
    names none.

    One reading for the refusal before a marked change runs and for the mark the
    change is then made under, so the two cannot disagree about whether a call
    named one.
    """
    action_id = (meta or {}).get(ACTION_META_KEY)

    return action_id if isinstance(action_id, str) else None


def the_mark_in(meta: Mapping[str, Any] | None,
                now: Callable[[], datetime] = utc_now) -> Mark:
    """The action `meta` names, marked at `now()`, or a `ValueError` where it
    names none.

    `now` is the clock, a parameter so a moment can be asserted.
    """
    action_id = the_action_in(meta)

    if action_id is None:
        raise ValueError(f"the call named no action under [{ACTION_META_KEY}]")

    return Mark(action_id=action_id, written_at=now())
