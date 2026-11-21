"""How a channel fails, as this suite stands one in failing."""

from __future__ import annotations


class ChannelFailed(Exception):
    """A retrieval channel that could not be read.

    The suite's own class rather than the transport's error, because the
    Investigator tells no failure apart: it catches every exception a channel
    raises and reports the read as unanswered. A transport class here would be
    this suite naming a transport its agent never names.
    """
