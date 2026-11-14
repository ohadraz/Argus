"""The shop's integrity checks, asked the question the recording asked them.

The checks hang every purchase on a grid anchored at a fixed instant, and a
shopper's prices on a sequence named after the shopper. Neither is a minute's
name, so moving the draws does not move them: a world moved by the shift would
find other purchases than the recorded one found - another shopper, another
amount, an onset off the flag's minute.

So a check is asked with every instant handed to it moved back by the shift,
which is the question the recording asked, and its answer is moved forward by
the same shift into the replay's time. Only instants move, never a shopper, an
amount or a count - and they move wherever they are held, in a stretch of a
flag's timeline or in a purchase inside an account inside a list.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any


def asked_as_recorded[T](check: Callable[..., T],
                         shift: Callable[[], timedelta]) -> Callable[..., T]:
    """`check`, asked `shift()` earlier and answering `shift()` later.

    The shift is read each time the check is asked, because it is the world's
    shift at that moment: none before a seed has moved anything, and whatever
    the last seed moved it by after. With none, the check is asked as it is and
    its answer handed back untouched - the shop, unchanged.
    """
    def asked(*arguments: Any, **keywords: Any) -> T:
        by = shift()

        if not by:
            return check(*arguments, **keywords)

        answer: T = _moved(check(*_moved(arguments, -by), **_moved(keywords, -by)), by)

        return answer

    return asked


def _moved(value: Any, by: timedelta) -> Any:
    """`value`, with every instant held anywhere in it `by` later."""
    if isinstance(value, datetime):
        return value + by

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.replace(value, **{
            field.name: _moved(getattr(value, field.name), by)
            for field in dataclasses.fields(value)
            if field.init
        })

    if isinstance(value, list | tuple):
        return type(value)(_moved(held, by) for held in value)

    if isinstance(value, dict):
        return {key: _moved(held, by) for key, held in value.items()}

    return value
