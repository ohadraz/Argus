## Context

Today the requests are spread like this:

| Where | Requests |
|---|---|
| Read server | 2: application history, live Deployment |
| Write server | 14, across `scaling`, `pinning`, `rolling_back`, `restarting` |

- Every call is `httpx2.get/post/patch`, injected as a default argument.
- Repeated today:
  - the auth header: 3 copies;
  - the timeout constant: 4 copies;
  - URL building: 4 styles;
  - GET-and-parse: 5 copies;
  - manifest parsing: 3 copies;
  - `_set_sync_policy`: 3 copies.
- `fetch_live_deployment` has no test.
- The tests fake HTTP functions and assert on `call_args`, so about 150 tests
  know Argo's JSON.

## Goals / Non-Goals

**Goals:**
- One place knows Argo CD.
- Callers depend on a role-named port.
- The read tier cannot type a write.
- FM-33's placement read becomes one port method plus one adapter method.

**Non-Goals:**
- Any behaviour change.
- The demo app's stand-in.
- The write actions' own `_refusing` and `_tried`, which are each action's
  policy rather than Argo knowledge.
- The e2e helpers' re-implementation of the sync check.

## Decisions

### D1. One module, port at the front door, adapter beside it
`modules/deployment_platform/` is laid out as:
- `__init__.py` exports the port, its values and its exceptions.
- `deployment_platform.argocd` holds the adapter.
- It depends on `argus_core` (for `SettingsSlice` and `RolloutProgress`) and
  `httpx2`.

The values live here rather than in `argus_core.models`, as
`repository_source`'s `SourceDifference` does: only the port's own callers
name them.

An import-linter contract forbids `read_mcp_server` and `write_mcp_server`
from importing `deployment_platform.argocd`. Only `*.server` is exempt, because
that is where the adapter is built.

### D2. Two ports, split by tier
```python
class DeploymentPlatformReads(Protocol):
    def deployments_of(self, application: str, /) -> list[DeploymentRecord]: ...
    def rollout_of(self, application: str, /) -> RolloutProgress: ...

class DeploymentPlatformWrites(DeploymentPlatformReads, Protocol):
    def is_syncing_itself(self, application: str, /) -> bool: ...
    def suspend_sync(self, application: str, /) -> None: ...
    def resume_sync(self, application: str, /) -> None: ...
    def scale(self, application: str, replicas: int, /) -> None: ...
    def roll_back(self, application: str, to_history_id: int, /) -> None: ...
    def restart(self, service: str, /) -> None: ...
    def newest_pod_started_at(self, service: str, /) -> float | None: ...
    def autoscaler_of(self, application: str, /) -> Autoscaler | None: ...
    def autoscaler_bounds(self, application: str, autoscaler: Autoscaler, /
                          ) -> AutoscalerBounds: ...
    def set_autoscaler_floor(self, application: str, autoscaler: Autoscaler,
                             floor: int, /) -> None: ...
```

**`deployments_of`**
- Returns entries in the order the platform serves them.
- The rollback reads the last two in that order, as it does now.
- The read tier sorts by `deployed_at`, as it does now.

**`DeploymentRecord`** has the fields `history_id`, `revision`, `deployed_at`,
`repo_url`, `path` and `initiated_by`.

**`rollout_of`**
- Returns the existing `RolloutProgress`.
- The manifest decoding, the conditions logic and the "no status reads as
  converged" rule move into the adapter unchanged.
- The scale-out reads `replicas_wanted` from it. Today that is the same request
  without selectors.

**The two autoscaler reads** stay two requests, as today:
- `autoscaler_of` returns `None` where the tree lists no autoscaler. The pin
  refuses that with its own words.
- The restore reads the autoscaler's address again, and does not read its bounds.

### D3. Two exceptions under one base
`DeploymentPlatformError` is the base, and it has two subclasses:
- `PlatformUnreachable`: an `httpx2.TransportError`, or a status of 500 or above.
- `PlatformRefused`: everything else. That covers 4xx, an unreadable body, and
  a manifest missing the field asked for.

The write actions map these onto their refusals:
- `_refusing` asks `isinstance(error, PlatformUnreachable)` where it now calls
  `could_not_be_reached`.
- `left_behind` travels as today.

The read tier catches the base, as it now catches `Exception`, and raises
`ChangeSourceUnavailable` or `RolloutUnreadable`.

### D4. `ArgoCd` over one `httpx2.Client`
- `ArgoCd(settings: ArgoCdSettings, transport: httpx2.BaseTransport | None = None)`
  builds its client once, with the base URL, the bearer header (or none for an
  empty token) and the 10 s timeout.
- Paths stay templates.
- Tests pass an `httpx2.MockTransport` and assert on the real request: method,
  path, query, headers and body.

**`ArgoCdSettings`** is one slice:
- `argocd_base_url`, `argocd_auth_token`;
- the five `argocd_*_path` settings;
- `restart_namespace`, `scale_namespace`.

It replaces the `argocd_*` fields on `ArgocdSettings`, `RolloutReadSettings`,
`RestartSettings`, `RollbackSettings`, `ScaleSettings` and `PinSettings`.
Slices left with no fields go.

The setting names and the environment variables are unchanged.

### D5. The callers
**Write actions:**
- They take `platform: DeploymentPlatformWrites`.
- `restart_service` also keeps `sleep`.
- `the_pod_start_time` and `ObserveStartTime` go, replaced by
  `platform.newest_pod_started_at`.

**Read server:**
- `fetch_deploys` and `the_revisions_deployed` take
  `platform: DeploymentPlatformReads` and map each `DeploymentRecord` to a
  `ChangeEvent`.
- `how_the_rollout_is_going` and `how_far_the_rollout_has_got` take the same
  port.
- `FetchApplication`, `FetchLiveDeployment` and `fetch_live_deployment` go.

**Wiring:** each `server.py` builds one `ArgoCd` and hands it out, typed as
its tier's port.

### D6. The wire constants move into the adapter
`SPEC`, `SYNC_POLICY`, `AUTOMATED` and `ENABLED` move from
`write_mcp_server.argocd` to `deployment_platform.argocd`. Three test files
import them and need their import lines changed:
- `write_mcp_client`'s fake platform;
- `tests/e2e/framework/world.py`;
- `test_withdrawing_an_incident.py`.

## Risks / Trade-offs

- The hand-applied test rewrite is large: about 9 files and about 170 tests.
  They are proposed one file at a time, bottom-up: the adapter first, then the
  read tier, then each write action.
- A request that is subtly different, such as a missing selector or a changed
  body shape, would pass the action tests, which no longer see HTTP. The
  adapter's own tests assert every request's exact shape, and `e2e_replay`
  runs the real stand-in.
