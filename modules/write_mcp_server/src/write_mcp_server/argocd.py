"""What every action against the deployment platform has to know about it.

Not a tool and not an action - the vocabulary the platform's own API is spoken
in, and the two or three facts about it that are easy to get subtly wrong. Three
actions change live state under a GitOps controller, and each has to suspend its
reconciliation first; a second copy of how that is spelled is a second copy
that comes to disagree with the first about what "syncing" means.

What is deliberately *not* here is any exception policy. A rollback that cannot
reach the platform and a scale-out that cannot reach it raise different things,
because the caller's next move differs and each module's own name for the failure
is what its callers catch. So these are pure functions over a body and a url, and
every request stays in the module that owns the action.
"""

from __future__ import annotations

import json
from typing import Any, Final

import httpx2

# Argo CD's own wire vocabulary for the parts of an application the actions read
# and write. Named once rather than spelled at each lookup: they are another
# project's field names, and a typo in one is a silent `None` rather than an error.
SPEC: Final = "spec"
SYNC_POLICY: Final = "syncPolicy"
AUTOMATED: Final = "automated"
# The switch Argo CD 3.1 put inside `automated`, so that automated sync can be
# turned off while what it was configured to do - `prune`, `selfHeal` - is kept.
# Absent means on.
ENABLED: Final = "enabled"

# The fields of `ApplicationPatchRequest`, the body of
# `PATCH /api/v1/applications/{name}` (bound with `body: "*"`). The patch itself
# travels as a JSON-encoded string and is applied to the whole application.
PATCH_REQUEST_NAME: Final = "name"
PATCH_REQUEST_PATCH: Final = "patch"
PATCH_REQUEST_TYPE: Final = "patchType"
# That route's name for an RFC 7386 merge patch. Not the resource route's
# `application/merge-patch+json`: the two routes spell the same kind of patch
# differently, and one constant for both would send one of them a type it refuses.
APPLICATION_MERGE_PATCH: Final = "merge"

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

    Read exactly as Argo CD's own `SyncPolicy.IsAutomatedSyncEnabled` reads it: an
    `automated` object whose `enabled` is absent or true. The presence of the
    object is a lookup for a key and not a truthiness test - an `automated` of
    `{}` means automated, and reading it as false would leave an action to be
    refused by a server this had just called compliant. And `enabled: false`
    means configured and not syncing, so there is nothing to suspend.

    The single most repeatable mistake about this API, which is why it is here
    rather than in any of the modules that asks.
    """
    policy = application_state.get(SPEC, {}).get(SYNC_POLICY) or {}
    automated = policy.get(AUTOMATED)

    return automated is not None and automated.get(ENABLED) is not False


def a_sync_patch(application: str, reconciling: bool) -> dict[str, Any]:
    """The request that turns the platform's own reconciliation off or back on.

    A merge patch of the switch alone, for `PATCH /api/v1/applications/{name}`.
    Not the spec route: that takes its body as the *whole* spec and replaces the
    application's with it, so a body carrying only a sync policy fails validation
    or, unvalidated, erases the source and destination. And not an `automated`
    object of Argus's own: the one the operator declared carries their `prune`
    and `selfHeal`, and writing another would replace it.

    Off is `enabled: false`. Back on is a `null`, which a merge patch reads as
    removing the key and the platform reads as on - what was found, since an
    application syncing itself had `enabled` absent or true.
    """
    switch = None if reconciling else False

    return {
        PATCH_REQUEST_NAME: application,
        PATCH_REQUEST_PATCH: json.dumps(
            {SPEC: {SYNC_POLICY: {AUTOMATED: {ENABLED: switch}}}}
        ),
        PATCH_REQUEST_TYPE: APPLICATION_MERGE_PATCH
    }
