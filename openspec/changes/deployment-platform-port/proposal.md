## Why

Argus speaks to Argo CD from six modules across both MCP servers: 16 requests,
each building its own URL, auth header, timeout, GET-and-parse and error
mapping. Fixing one request touched about 12 files, and FM-33 is about to add
more reads (pod placement, node labels). Wrapping the platform once, behind a
port named for its role, is cheaper now than after FM-33 adds to the spread.

## What Changes

- New module `deployment_platform`:
  - **Port** at its front door: `DeploymentPlatformReads` and
    `DeploymentPlatformWrites` Protocols. Their methods are named for what
    Argus wants (the replicas running, roll back to an entry, the newest pod's
    start time...), and they return typed values. No Argo JSON crosses them.
  - **Adapter** in `deployment_platform.argocd`: `ArgoCd`, which implements
    both over one `httpx2.Client` (base URL, auth header and timeout set once).
    It owns every Argo route, selector, patch body and parse.
  - Two exceptions, `PlatformUnreachable` (transport error or 5xx) and
    `PlatformRefused` (anything else), with a common base.
- The read server is handed only the reads port, and the write server the
  writes port. The write actions keep their own refusal types and map the two
  exceptions onto them. Only each server's wiring may import the adapter.
- Removed: `write_mcp_server.argocd`, `could_not_be_reached`, the six
  `HttpGet`/`HttpPost`/`HttpPatch` aliases, the three `headers_for` copies,
  the `argocd_*` fields on six settings slices, and `FetchApplication` /
  `FetchLiveDeployment` / `ObserveStartTime`.
- No behaviour change: the same requests, the same refusals, and the same
  unreachable marks.

## Capabilities

### New Capabilities
- `deployment-platform-port`: how Argus reaches the deployment platform, and
  how the platform's failures are told apart.

### Modified Capabilities

None.

## Impact

- New: `modules/deployment_platform/` (with `root_packages` and a layering
  contract).
- `write_mcp_server`: `scaling.py`, `pinning.py`, `rolling_back.py`,
  `restarting.py`, `server.py`; `argocd.py` deleted.
- `read_mcp_server`: `argocd.py`, `rollouts.py`, `deployments.py`,
  `server.py`.
- Tests, hand-applied:
  - new `deployment_platform` suite;
  - rewrites of the write tier's `test_scaling`, `test_pinning`,
    `test_rolling_back`, `test_restarting` and `test_argocd`;
  - the read tier's `test_argocd`, `test_rollouts`, `test_deployments` and
    `test_server`;
  - import lines in `write_mcp_client`'s fake platform and two e2e files.
- Unchanged: the demo app's stand-in, which still speaks Argo CD's wire shape.
