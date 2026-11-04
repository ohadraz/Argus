"""A write to GitHub, made again where GitHub failed it for a moment.

GitHub answered 500 to one pull request in a live run, during an incident of
its own, and a fix Code-Fix had written was reported as one that could not be
proposed. A server's passing fault is no refusal, so a write that never reached
GitHub, or that GitHub answered with a 5xx, is made again - as many times and
as far apart as configured. What the repository refused, a 4xx, is made once:
asked again, a refusal is refused again.

A failure can come back for a write the server carried out. Made again, a pull
request or a branch is then refused as one that exists - so before each retry
the write is looked for, and one that landed is the answer. A look that fails
too is no answer either way, and the write is made again: what it risks is a
refusal, never a second pull request or a second branch.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Final

import httpx2

logger = logging.getLogger(__name__)

HttpGet = Callable[..., httpx2.Response]
HttpPost = Callable[..., httpx2.Response]
Sleep = Callable[[float], None]

# The first status a server answers its own fault with, rather than the
# request's.
_A_SERVER_FAULT: Final = 500

_MILLISECONDS_IN_A_SECOND: Final = 1000


def with_retries[T](attempt: Callable[[], T],
                    *,
                    retries: int,
                    wait_ms: int,
                    landed: Callable[[], T | None] | None = None,
                    sleep: Sleep = time.sleep) -> T:
    """What `attempt` answers, made again up to `retries` times - tries after
    the first - where GitHub failed it for a moment, `wait_ms` before each.

    `landed` is asked before each retry whether the write took effect after
    all, and what it answers, where it answers anything, is returned instead.

    Raises the failure as it came for anything else, and for the last try.
    """
    for tries_left in range(retries, -1, -1):
        try:
            return attempt()
        except Exception as error:
            if not tries_left or not _a_passing_fault(error):
                raise

            logger.warning("write to GitHub failed, trying again",
                           extra={"failure": said_of(error), "tries_left": tries_left})

        sleep(wait_ms / _MILLISECONDS_IN_A_SECOND)

        if (found := _what_landed(landed)) is not None:
            return found

    raise AssertionError("unreachable: the last try returns or raises")


def said_of(error: Exception) -> str:
    """A failed write as GitHub answered it - its status and the words for it -
    or the failure's own words where there was no answer.

    The HTTP library's sentence names the address again and sends a reader to
    a page about status codes, on a line that already says where it wrote.
    A failure with no words of its own - a timeout raised bare - is said by
    its kind, so the line still says what went wrong.
    """
    if isinstance(error, httpx2.HTTPStatusError):
        answered = error.response

        return f"GitHub answered {answered.status_code} {answered.reason_phrase}".rstrip()

    return str(error) or type(error).__name__


def _a_passing_fault(error: BaseException | None) -> bool:
    """Whether a failure is GitHub's for a moment rather than the request's: a
    write that never reached it, or one it answered with a 5xx - itself, or
    what it was raised from, since a step says its own failure in words of its
    own over GitHub's."""
    if error is None:
        return False

    if isinstance(error, httpx2.HTTPStatusError):
        return error.response.status_code >= _A_SERVER_FAULT

    return isinstance(error, httpx2.TransportError) or _a_passing_fault(error.__cause__)


def _what_landed[T](landed: Callable[[], T | None] | None) -> T | None:
    if landed is None:
        return None

    try:
        return landed()
    except Exception:
        logger.warning("could not look for a write GitHub may have carried out", exc_info=True)

        return None
