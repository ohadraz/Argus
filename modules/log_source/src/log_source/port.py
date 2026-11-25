"""Wherever a service's log lines are read from, as the read tier asks for them.

Named for the role, and answered by one adapter named for whose wire it reads.
What crosses is the lines themselves, as the service wrote them - the window an
incident is read over is the read tier's to cut, never the source's.
"""

from __future__ import annotations

from typing import Protocol


class LogSource(Protocol):
    """A service's logs, for the one question the read tier asks of them.

    A `Protocol` rather than a `Callable` alias, so a test stands it in with
    `create_autospec` - and a no-argument call, so a lambda stands it in too.
    """

    def __call__(self) -> list[str]:
        """Every line the service has to give.

        Raises on any failure to get them - an address nobody answers at, an
        error status, a body that is not a list of lines. None of them may
        arrive as a service that wrote nothing.
        """
        ...
