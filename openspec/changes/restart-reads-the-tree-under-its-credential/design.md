## Context

`restarting.the_pod_start_time` reads the resource tree with no headers;
`restart_service` and every other Argo CD read in the write and read tiers send
`headers_for(argocd_auth_token)`.

## Goals / Non-Goals

**Goals:** the tree read is authenticated as the restart is.

**Non-Goals:** the Argo CD adapter that would make one request code path for all
of these - deferred by the user.

## Decisions

### D1. The shared `headers_for`
The restart module held a private copy of `argocd.headers_for`, word for word.
It is removed and the shared one used for both requests, so the two cannot come
to disagree about what "no credential" means.

## Risks / Trade-offs

None.
