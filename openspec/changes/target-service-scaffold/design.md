## Context

`Argus-Demo-Target-App` doesn't exist yet in any form. Spec §15 describes a fairly complete eventual system (business logic, scenario control, real feature-flag checkpoints, a log query API, metrics emission) - but none of that has anywhere to live yet. This design covers only the smallest slice that gets a second, separate, runnable repository onto disk and reachable from Argus's local dev stack, so later changes have a real foundation to build the actual Target Service behavior into.

This repo (`Argus-Demo-Target-App`) is explicitly a test/demo fixture for Argus, not an independent project - see proposal.md's Why. That framing drives several decisions below.

## Goals / Non-Goals

**Goals:**
- `Argus-Demo-Target-App` exists as its own git repository, sibling to this repo on disk, with standard bootstrap files (`pyproject.toml`, `.gitignore`, `LICENSE`, `Dockerfile`, `README.md`).
- The app boots and responds to at least a health-check request - proof the repo, its dependency setup, and its container build all actually work, nothing more.
- `docker-compose up` in this repo brings up Postgres (existing) and the Target Service (new) together, for local dev convenience.
- The new repo's `README.md` states plainly what it is (a fixture for Argus) and links back here for design/spec context - it carries no `openspec/` tracking of its own.

**Non-Goals:**
- Any real business logic, scenario control, or chaos-injection API (§15.2) - future change.
- The flag backend (Unleash), metrics backend (OTel Collector + Prometheus), or the log query API (§16) - future changes, each substantial enough to warrant its own proposal.
- Wiring Argus's own e2e tests to hit this service for real - `tests/e2e/test_incident_lifecycle.py` keeps using the Grafana-webhook-only flow until a later change deliberately extends it.
- CI wiring across the two repos (e.g., Argus's GitHub Actions checking out `Argus-Demo-Target-App` too) - not needed until a change actually makes Argus's CI depend on it. This change's `docker-compose.yml` addition is for local dev only.
- Publishing a Docker image anywhere - the `Dockerfile` exists and builds, but nothing pushes it to a registry yet.

## Decisions

**Separate git repository, not a `modules/*` workspace member or a subdirectory of this repo.** Matches spec §15.1/§20 explicitly, and for reasons beyond "the spec says so": independent deployability (§19 - it deploys as its own Docker Compose/Railway service, and in a real deployment would simply be swapped for actual production infra), and the evaluation-integrity boundary (§18.3) - the runtime Code-Fix agent is meant to have write-access to this repo's tests later, a rule that only makes clean sense if it isn't the same repo where Argus's own dev-time TDD block applies. Alternative considered: a plain sibling subdirectory inside this repo, not joining the uv workspace - rejected per team discussion, since it would blur both of those boundaries for no real gain given local dev is already solved by the sibling-checkout approach below.

**Sibling-checkout via a relative `docker-compose.yml` build context, not a git submodule or a published image, for now.** Both repos are local-only at this stage - there's no CI dependency yet (Non-Goals) and no stable image worth publishing. A relative `build: ../Argus-Demo-Target-App` context is the least machinery that gets `docker-compose up` working for local dev. Alternatives considered: git submodule - rejected as unnecessary ceremony (pinning, `--recurse-submodules` footguns) for something that isn't yet consumed by CI or released independently; published image - rejected as premature, nothing to version or publish yet. Revisit once a later change actually needs Argus's CI to reach this service (open question below).

**Planning artifacts (proposal/design/specs/tasks) live in this repo's `openspec/`, not a separate store or the new repo's own `openspec/`.** Per team decision (see proposal.md): the Target Service has no independent life of its own outside Argus, so splitting its design rationale into a repo nobody will read standalone would only orphan it. The new repo gets a short pointer `README.md` instead of its own spec tracking.

**FastAPI + uvicorn, matching `argus_web`'s existing stack, not a different framework.** Spec §18.1 mandates Python throughout; picking a different web framework here would add a second HTTP-serving convention to the system for no benefit. Alternative considered: a bare-bones framework (Flask, or stdlib `http.server`) for something this minimal - rejected since FastAPI is already a proven, typed, `mypy --strict`-friendly choice in this codebase, and later changes will need real endpoints (log query, scenario control) where FastAPI's request/response typing earns its keep anyway.

## Risks / Trade-offs

- **[Risk]** The relative `docker-compose.yml` build context (`../Argus-Demo-Target-App`) breaks if someone doesn't check out the sibling repo at exactly that relative path → **Mitigation**: document the required layout in this repo's README/CONTRIBUTING; low stakes since nothing in CI depends on it yet (Non-Goals).
- **[Risk]** Keeping design docs in this repo while the code lives in another means the two can drift (a future change to `Argus-Demo-Target-App` made without a corresponding openspec change here) → **Mitigation**: this is a process discipline risk, not a technical one - same discipline already required for `modules/*` changes, just crossing a repo boundary. No new tooling proposed to enforce it in this change.
- **[Risk]** Scaffolding a whole second repo is more ceremony than scaffolding a subdirectory would have been → **Mitigation**: accepted trade-off per the Decisions above; the ceremony buys the independent-deployability and evaluation-integrity properties spec §15/§18.3 actually need later.

## Migration Plan

N/A - net-new repository, nothing existing to migrate. Rollback is deleting the `Argus-Demo-Target-App` directory and reverting the added service block in this repo's `docker-compose.yml` - the only file this change touches outside the new repo.

## Open Questions

- When a later change wires Argus's CI (or its e2e tests) to depend on `Argus-Demo-Target-App`, how does that CI reach it - checkout-with-token (private repo access from Argus's workflow), or a published image by then? Deliberately left open; not needed for this change's local-dev-only scope.
