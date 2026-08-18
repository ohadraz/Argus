## Why

Every sub-agent in Argus is currently a stub reasoning over synthetic data - there is nothing real for the Investigator to investigate or the Mitigation agent to act on. Spec §2/§15 call for a self-contained **Target Service and Target Environment** that Argus watches and controls, built deliberately as its own repository (independent deployability, and a clean evaluation-integrity boundary between Argus's own dev-time TDD rule and the Target Service's runtime rule, per §18.3). Before any agent can get real logic, that Target Service needs to exist as a runnable thing Argus can reach.

## What Changes

- Scaffold a new, separate git repository, `Argus-Demo-Target-App`, as a sibling directory to this repo - not a `modules/*` workspace member, not a submodule.
- Minimal runnable Python app in that repo: a basic HTTP server exposing a health-check endpoint, enough to prove it boots and is reachable - no business logic, no scenario control, no flag/metrics/log backends yet (those are later changes).
- Standard repo bootstrap for `Argus-Demo-Target-App`: `pyproject.toml`, `.gitignore`, `LICENSE`, a `Dockerfile`, and a `README.md` that identifies it as a test/demo fixture for Argus and points back to this repo for design rationale - no independent spec or `openspec/` tracking of its own (per team decision: its planning artifacts live here, in Argus's `openspec/`, since it has no life of its own outside Argus).
- Wire `Argus-Demo-Target-App` into this repo's `docker-compose.yml` via a sibling-checkout relative build context, so `docker-compose up` can bring up Postgres and the Target Service together locally.

Explicitly **out of scope** for this change: real business logic, scenario control/chaos injection, feature-flag backend (Unleash), metrics (OTel/Prometheus), the log query API, and wiring Argus's own e2e tests to hit it for real - each is substantial enough to warrant its own later change.

## Capabilities

### New Capabilities
- `target-service-bootstrap`: a minimal, runnable Target Service application exists in its own repository and can be brought up locally alongside Argus via `docker-compose`, ready for later changes to add real behavior against.

### Modified Capabilities
(none - checked against `openspec/specs/incident-lifecycle/spec.md`, the only existing capability; no requirement changes there)

## Impact

- New repository: `Argus-Demo-Target-App` (sibling directory, outside this repo's git history).
- This repo: `docker-compose.yml` gains a service definition referencing the sibling repo's build context. No changes to `modules/*` - agent wiring to a real Target Service is future work.
