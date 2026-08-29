"""Setting a feature flag's state in the provider (spec §7.3, §12.1).

The write tier's one action, and the only place in Argus that knows the
provider's admin wire shape. Two credentials are used and they are not
interchangeable: the admin token *changes* the flag, and the evaluation token
*confirms* the change became visible. A read credential inside a write process
is harmless; the reverse is the thing the tier split exists to prevent.

One function serves both directions, because a flag causes an incident by
changing and the damaging direction is not always "on" - a flag switched off can
disable a fallback, or withdraw the very mitigation someone applied an hour ago.
Undoing such a change means switching the flag back on, and an agent that could
only clear flags could not mitigate that incident at all. It is also what makes
undoing a *mitigation* the same call with the state reversed.

Changing a flag is deliberately not "post and return". Unleash accepts the admin
call before the change reaches its evaluation API, so a caller that trusted the
POST would re-query the metrics against a flag still serving its old value, watch
the error rate stay where it was, and refute a hypothesis that was right.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
from argus_core.config import Settings, get_settings

HttpPost = Callable[..., httpx.Response]
HttpGet = Callable[..., httpx.Response]
EvaluateFlags = Callable[[], list[str]]

REQUEST_TIMEOUT_SECONDS = 10.0

# How long to keep asking whether the change became visible. Propagation is
# sub-second in practice; this is the bound on "it never did", not the expected
# wait.
_EVALUATION_ATTEMPTS = 25
_SECONDS_BETWEEN_ATTEMPTS = 0.2

EVALUATION_PATH = "/api/frontend"


class FlagNotSet(Exception):
    """The flag did not reach the requested state, whatever the reason.

    One exception for an unreachable provider, a rejected credential and a
    change that never became visible, because the caller's next move is the
    same for all three: the action did not happen, so nothing downstream may
    proceed as though it had. A change reported optimistically would have
    Mitigation confirm or refute a hypothesis against a service nothing was
    done to.
    """


def evaluated_flags(
    settings: Settings | None = None,
    get: HttpGet = httpx.get,
) -> list[str]:
    """The flags currently evaluating true, read with the evaluation credential.

    The write server's own check that its change landed. It duplicates what the
    read tier offers rather than calling it, because verifying one's own write
    is not a retrieval concern - and a write server that depended on the read
    server could not change a flag while the read server was down.
    """
    resolved = settings if settings is not None else get_settings()
    url = f"{resolved.unleash_base_url}{EVALUATION_PATH}"

    response = get(
        url,
        headers={"Authorization": resolved.unleash_frontend_token},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body: dict[str, Any] = response.json()

    return [
        toggle["name"]
        for toggle in body.get("toggles", [])
        if toggle.get("enabled", True)
    ]


def set_flag(
    flag: str,
    enabled: bool,
    settings: Settings | None = None,
    post: HttpPost = httpx.post,
    evaluate: EvaluateFlags = evaluated_flags,
) -> dict[str, Any]:
    """Sets `flag` on or off in the configured environment and waits until it is.

    Returns the undo descriptor: the state that existed before, which is what
    restores it. `was_enabled` is the opposite of what is being set rather than
    a fresh reading of the flag - this is only ever called to move a flag from
    one state to the other, and re-reading it here would open a window in which
    the answer changed between the two calls without making the record any
    truer.

    Raises `FlagNotSet` unless the provider accepted the change *and* the change
    became visible to evaluation.
    """
    resolved = settings if settings is not None else get_settings()
    url = f"{resolved.unleash_base_url}{_environment_path(resolved, flag, enabled)}"

    try:
        response = post(
            url,
            headers={"Authorization": resolved.unleash_admin_token},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except Exception as error:
        raise FlagNotSet(
            f"could not set flag [{flag}] {_state_name(enabled)} at [{url}]: {error}"
        ) from error

    _wait_until_evaluating(flag, enabled, evaluate)

    return {
        "tool": "set_feature_flag",
        "flag": flag,
        "environment": resolved.unleash_environment,
        "was_enabled": not enabled,
    }


def _wait_until_evaluating(flag: str, enabled: bool, evaluate: EvaluateFlags) -> None:
    for attempt in range(_EVALUATION_ATTEMPTS):
        try:
            if (flag in evaluate()) == enabled:
                return
        except Exception as error:
            raise FlagNotSet(
                f"could not confirm flag [{flag}] is {_state_name(enabled)}: {error}"
            ) from error

        if attempt + 1 < _EVALUATION_ATTEMPTS:
            time.sleep(_SECONDS_BETWEEN_ATTEMPTS)

    raise FlagNotSet(
        f"flag [{flag}] was accepted as {_state_name(enabled)} but still evaluates "
        f"{_state_name(not enabled)}"
    )


def _environment_path(settings: Settings, flag: str, enabled: bool) -> str:
    return (
        f"/api/admin/projects/{settings.unleash_project}"
        f"/features/{flag}"
        f"/environments/{settings.unleash_environment}/{_state_name(enabled)}"
    )


def _state_name(enabled: bool) -> str:
    """The provider's own word for a state - and the path segment that sets it,
    which is why one function names both."""
    return "on" if enabled else "off"
