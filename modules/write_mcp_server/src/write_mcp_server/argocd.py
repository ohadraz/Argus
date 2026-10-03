"""What every action against the deployment platform has to know about it.

Not a tool and not an action - the vocabulary the platform's own API is spoken
in, and the two or three facts about it that are easy to get subtly wrong. Two
actions now change live state under a GitOps controller, and both have to suspend
its reconciliation first; a second copy of how that is spelled is a second copy
that comes to disagree with the first about what "syncing" means.

What is deliberately *not* here is any exception policy. A rollback that cannot
reach the platform and a scale-out that cannot reach it raise different things,
because the caller's next move differs and each module's own name for the failure
is what its callers catch. So these are pure functions over a body and a url, and
every request stays in the module that owns the action.
"""

from __future__ import annotations

from typing import Any, Final

import httpx2

# Argo CD's own wire vocabulary for the parts of an application both actions read
# and write. Named once rather than spelled at each lookup: they are another
# project's field names, and a typo in one is a silent `None` rather than an error.
SPEC: Final = "spec"
SYNC_POLICY: Final = "syncPolicy"
AUTOMATED: Final = "automated"

REQUEST_TIMEOUT_SECONDS = 10.0

# The lowest status a server uses to say the failure is its own rather than the
# request's. Below it the platform has read what was asked and rejected it, which
# is the platform working.
_THE_SERVERS_OWN_FAULT: Final = 500


def the_url_of(base_url: str, path_template: str, application: str) -> str:
    """Where one of the platform's routes is, for one application.

    Templates rather than fixed routes throughout, because the demo's stand-in
    and a real server are one setting with two values.
    """
    return f"{base_url}{path_template.format(application=application)}"


def headers_for(auth_token: str) -> dict[str, str]:
    """No token means no header at all, as every Argo CD adapter here does."""
    return {"Authorization": f"Bearer {auth_token}"} if auth_token else {}


def could_not_be_reached(error: Exception) -> bool:
    """Whether a failed request means the platform was not there to receive it.

    Three failures and one answer, because the question a caller is asking is
    not what went wrong but whether anything can still be acted through this. A
    refused connection, a request that ran out of time and the platform
    reporting its own API unavailable are the same answer to that: no, and not
    for any reason to do with the action that happened to be carrying it.

    A status of the platform's own rather than a list of them. `502` and `503`
    are the same outage seen at different hops, `504` is it seen through a proxy
    that waited, and which one arrives is a fact about how the platform is
    fronted. What separates them from everything below is whose fault the
    server says it is.

    Anything that is not the platform failing to answer is not this - a rejected
    action, an application it has never heard of, and a bug of Argus's own
    reading a response it did not expect. The last is the one worth guarding:
    read as unreachability it would pass over four actions because a parse went
    wrong here.

    Vocabulary and not policy, so this decides what the platform said and raises
    nothing. Each action names its own failure, and that name is what the
    action's callers catch.
    """
    if isinstance(error, httpx2.HTTPStatusError):
        return error.response.status_code >= _THE_SERVERS_OWN_FAULT

    return isinstance(error, httpx2.TransportError)


def is_reconciling_itself(application_state: dict[str, Any]) -> bool:
    """Whether the platform syncs this application on its own.

    Argo CD spells it as the *presence* of an `automated` object rather than as a
    boolean, so this is a lookup for a key and not a truthiness test - an
    `automated` of `{}` means automated, and reading it as false would leave an
    action to be refused by a server this had just called compliant.

    The single most repeatable mistake about this API, which is why it is here
    rather than in either of the modules that asks.
    """
    policy = application_state.get(SPEC, {}).get(SYNC_POLICY, {})

    return policy.get(AUTOMATED) is not None


def a_sync_policy(reconciling: bool) -> dict[str, Any]:
    """The body that turns the platform's own reconciliation on or off.

    Spelled here for the reason reading it is: suspending sync is the *removal* of
    a key rather than a flag set to false, and a body that said `false` would be
    accepted and change nothing.
    """
    return {SYNC_POLICY: {AUTOMATED: {}} if reconciling else {}}
