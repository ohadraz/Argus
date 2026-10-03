"""Deploy history, read from an Argo CD server (spec §16).

The change channel's first source, and the only place in Argus that knows what
Argo CD's wire shape looks like. Everything above the port sees `ChangeEvent`.

Two layers, both public, because they fail and are tested for different
reasons: `fetch_argocd_application` makes the HTTP request and is where a
credential, a URL and an outage live, while `fetch_deploys` maps the response
onto Argus's model and applies the window. Mapping is ordinary deterministic
code - never a model. A hallucinated deploy is a fabricated cause, and the
verdict would then rest on evidence that never existed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import httpx2
from argus_core import SettingsSlice, parse_iso
from argus_core.models import ChangeEvent, ChangeKind

from read_mcp_server.change_source import ChangeSourceUnavailable


class ArgocdSettings(SettingsSlice):
    """Where deploy history is read from, and under what credential.

    The path is a template rather than a fixed route, so that the demo's
    stand-in and a real server's `/api/v1/applications/{application}` are one
    setting with two values. The token may be empty, which means no credential
    is sent at all - see `_headers_for`.
    """

    argocd_base_url: str
    argocd_application_path: str
    argocd_auth_token: str


HttpGet = Callable[..., httpx2.Response]


class FetchApplication(Protocol):
    """What `fetch_deploys` needs from whatever asks Argo CD.

    A `Protocol` rather than a `Callable` alias for the reason `FetchToggles`
    is one: a test stands it in with `create_autospec`, which needs something
    introspectable. Naming an application is all this asks - where that server
    is and under what credential was decided where the process started.
    """

    def __call__(self, application: str, /) -> dict[str, Any]: ...

REQUEST_TIMEOUT_SECONDS = 10.0


def fetch_argocd_application(
    application: str,
    settings: ArgocdSettings,
    get: HttpGet = httpx2.get,
) -> dict[str, Any]:
    """Asks an Argo CD server for one application's current state.

    The path is a template, so the demo stand-in's route and a real server's
    `/api/v1/applications/{application}` are the same setting with different
    values; a path naming no application formats to itself.

    Any failure to get an answer - unreachable host, error status, unreadable
    body - becomes `ChangeSourceUnavailable`. None of them may become "no
    changes".
    """
    url = f"{settings.argocd_base_url}{_application_path(settings, application)}"

    try:
        response = get(
            url,
            headers=_headers_for(settings.argocd_auth_token),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
    except Exception as error:
        raise ChangeSourceUnavailable(
            f"could not read deploy history for [{application}] from [{url}]: {error}"
        ) from error

    return body


def the_revisions_deployed(application: str,
                           *,
                           fetch: FetchApplication) -> list[ChangeEvent]:
    """Every deploy of one application, oldest first, with no window applied.

    The whole history, because what one deployment is compared against is the
    revision deployed before it - and that revision is under no obligation to
    fall inside whatever window an investigation happens to be reading. Windowed,
    the comparison would quietly be against the window's oldest entry instead: a
    diff of the wrong thing, in exactly the shape a diff of the right thing has.

    Ordered here rather than taken as Argo CD served it. Which order its history
    arrives in is Argo CD's business and not a promise a diagnosis may rest on,
    and "the one before this" is meaningless without one.

    `deployedAt` anchors each event: Argo CD always sets it, where
    `deployStartedAt` is a pointer in its own type and may be absent. A deploy is
    "at" the moment it landed, which is the moment the symptoms could start.
    """
    application_state = fetch(application)

    # `history` is `omitempty` in Argo CD's own type, so an application that
    # has never deployed simply has no such key - an ordinary answer, not a
    # malformed one.
    history = application_state.get("status", {}).get("history", [])

    return sorted(
        (_a_deploy_from(entry) for entry in history),
        key=lambda deploy: parse_iso(deploy.occurred_at)
    )


def fetch_deploys(
    application: str,
    *,
    window_start: str,
    window_end: str,
    fetch: FetchApplication,
) -> list[ChangeEvent]:
    """The deploys of one application within one window, as `ChangeEvent`s.

    The window is applied here rather than in the request because Argo CD's
    API takes no time parameters at all - it answers with an application's
    entire revision history - so filtering is the adapter's own job. A source
    that can filter server-side would do so and this function would shrink;
    nothing above the port would notice either way.

    The history itself comes from `the_revisions_deployed`, which is the same
    read without the window. Two functions rather than one with an optional
    window: a channel asking about a stretch of time and a channel asking what
    one deployment replaced are different questions, and a defaulted window is
    how the second one silently becomes the first.
    """
    window_opened = parse_iso(window_start)
    window_closed = parse_iso(window_end)

    return [
        deploy
        for deploy in the_revisions_deployed(application, fetch=fetch)
        if window_opened <= parse_iso(deploy.occurred_at) <= window_closed
    ]


def _application_path(settings: ArgocdSettings, application: str) -> str:
    return settings.argocd_application_path.format(application=application)


def _headers_for(auth_token: str) -> dict[str, str]:
    """No token means no header at all.

    The stand-in needs no credential, and inventing a placeholder would send a
    real server something meaningless to reject.
    """
    return {"Authorization": f"Bearer {auth_token}"} if auth_token else {}


def _a_deploy_from(entry: dict[str, Any]) -> ChangeEvent:
    revision = entry["revision"]
    source = entry.get("source", {})
    repo_url = source.get("repoURL")
    path = source.get("path")

    return ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=entry["deployedAt"],
        reference=revision,
        summary=_what_it_shipped(revision, path),
        actor=entry.get("initiatedBy", {}).get("username"),
        source=f"{repo_url}/{path}" if repo_url and path else repo_url,
    )


def _what_it_shipped(revision: str, path: str | None) -> str:
    """A deployment said as the two facts that locate it: its revision and where
    it was synced from.

    Both are addresses rather than descriptions. The revision is what a later
    channel is asked about - what this deployment changed is answered by naming
    it - and the path is where in the repository the manifests it applied live,
    which is what a person opens.

    The path is not what the deployment changed, and nothing here should be read
    as saying so. An application syncs from one directory for the life of the
    application: every deployment of the shop reports `deploy`, the ones whose
    commits rewrote source code included. So the path is constant across the one
    distinction a reader of a deployment most needs - code or configuration - and
    a model asked to draw that distinction from it will draw it wrongly, which a
    paid walk duly did.

    Said rather than classified, for the reason it is said rather than
    interpreted. Which directories hold configuration is that repository's
    business and changes between them, so a `path` mapped here to "code" or
    "config" would be this adapter deciding something it cannot know - and
    deciding it wrongly the first time somebody keeps their values beside their
    source.
    """
    if not path:
        return f"deployed revision {revision}"

    return f"deployed revision {revision}, from {path}"
