## Why

A restart is confirmed by reading the restarted service's pod creation time from
Argo CD's resource tree, and that read sent no `Authorization` header while the
restart's own request did. A real Argo CD answers 401 to a caller it cannot
identify, so on any platform but the demo's stand-in a restart could never be
confirmed.

## What Changes

- The tree read carries the same credential as the restart, and none where none
  is configured.
- The restart's private copy of `headers_for` goes; it uses the shared one in
  `argocd.py`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities
- `restart-mitigation`: the start time is read under the platform's credential.

## Impact

- `write_mcp_server`: `restarting.py`, and its test.
