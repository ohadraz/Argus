## Why

Argus names two causes for a deployment that broke a service - the code in it was
bad, or a configuration value in it was - and has no evidence that tells them
apart. Four retrieval channels describe the service (its metrics, its logs, what
changed on it, what it calls); none of them says what a deployment's commit
actually touched. So the cache-misconfiguration case answers `bad-deployment`
where the fault is a port in a values file, and it answers it *confidently*: the
model read every channel it was offered and the distinction was in none of them.

The current discriminator is worse than missing, it is false. `failure_mode.py`
tells the model that which of the two landed "is the path the deployment shipped
from", and `argocd.py` says that path in each deploy's summary. But an Argo source
path is where a deployment's manifests live, not what its commit changed: both
demo scenarios deploy from `path="deploy"`, the bad-deployment one included. A
model following that instruction faithfully reaches the wrong answer, and a paid
walk did.

## What Changes

- **A fifth Investigator retrieval channel: what a deployment changed.** Given a
  revision the change channel already offered, it answers with the files that
  differ between that revision and the revision deployed before it, and what
  changed in each. It is the first channel keyed to a thing rather than to a
  window, and the first that reads the Target Service's own history rather than
  its telemetry.
- **A read-tier tool behind it.** The revision deployed before is found in Argo's
  own history; the difference is read from the repository. Both ends stay on the
  server, so the Investigator names one revision and nothing else.
- **`repository_source` learns to answer what changed, not only where.**
  `paths_changed_between` reports paths; a path list alone still leaves the model
  inferring "configuration" from a directory name. The new answer carries each
  file's patch, bounded in size, so that a moved port is read rather than guessed.
- **The false discriminator is withdrawn.** `config-induced-failure` is separated
  from `bad-deployment` by what the deployment changed - source code, or the
  values it shipped with - and the model is told to read that rather than to
  interpret the path a deployment shipped from.
- **BREAKING for every Investigator recording.** Adding a channel changes the tool
  list, which changes the prompt digest, which invalidates every `both-*`,
  `grep-*` and `meaning-*` corpus. They need a paid re-record before
  `e2e_replay` is green again.

## Capabilities

### New Capabilities
- `deployment-diff-retrieval`: what one deployment changed, as evidence - the
  revision deployed before it, the files that differ, and each file's patch,
  bounded so that one call cannot spend a turn's whole context.

### Modified Capabilities
- `investigator-cause-detection`: a config-induced failure becomes a determinable
  cause with its own requirement, and what separates it from a bad deployment is
  stated as what the deployment changed rather than as the path it shipped from.
- `read-mcp-server`: exposes the new tool over MCP, and the typed client exposes
  it as a function.

## Impact

- `modules/repository_source/` - a second comparison reader, answering with
  patches rather than paths. Same credential, same failure type.
- `modules/read_mcp_server/` - a new module for the tool, reading Argo's history
  for the base revision and the repository for the difference; registered in
  `server.py`. `modules/read_mcp_client/` - one more typed function.
- `modules/agent_investigator/` - a fifth `Protocol` in `retrieval.py`, a
  `tools/deployments.py`, a branch in `Dispatcher`, an entry in
  `investigator_tools()`, and `BRIEF` corrected from "three ways to read
  evidence" - already stale at four.
- `modules/argus_core/` - the `config-induced-failure` meaning, and `Reading`
  only if the channel records one.
- `modules/anthropic_double/recordings/` - every Investigator corpus re-recorded,
  at roughly $3.60 per retrieval mode.
- `tests/e2e/test_a_misconfigured_cache_is_rolled_back.py` - currently the one red
  case in `e2e_replay(mode='both')`, and the reason this change exists.
