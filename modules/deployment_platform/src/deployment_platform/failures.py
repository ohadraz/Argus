"""How the deployment platform fails to answer, in two kinds.

Two because a caller has one question to ask of a failure beyond that it
happened: whether anything can still be done through this platform. A platform
that is not there to receive a request fails every action that goes through it,
and a caller that knows so reaches for one that goes somewhere else rather than
spending a request each to learn it again. A platform that answered and said no
has failed this request and nothing more.

What to raise about either is each caller's own. These say what the platform did;
an action names its own refusal, and that name is what its callers catch.
"""

from __future__ import annotations


class DeploymentPlatformError(Exception):
    """The platform did not answer what was asked, for either reason below.

    Caught by name where the difference does not matter - a read that has to
    refuse rather than answer emptily refuses the same way for both.
    """


class PlatformUnreachable(DeploymentPlatformError):
    """The request never got an answer.

    A refused connection, a request that ran out of time, and the platform
    reporting a fault of its own (a 5xx) are one answer to the question a caller is
    asking: no, and not for any reason to do with the request that carried it.
    """


class PlatformRefused(DeploymentPlatformError):
    """The platform answered, and the answer was not what was asked for.

    A request it read and rejected (a 4xx), and an answer that does not say what the
    question needed - a body that is not JSON, a manifest missing the count asked
    about. The second is the one worth keeping out of `PlatformUnreachable`: read as
    an outage, a parse gone wrong here would pass over every action through a
    platform that is perfectly well.
    """
