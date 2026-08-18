## 1. Repository bootstrap

- [x] 1.1 `git init` `Argus-Demo-Target-App` as a sibling directory to this repo
  (spec §15.1/§20; design.md's "separate git repository" decision)
- [x] 1.2 Add `pyproject.toml` (Python 3.14, FastAPI + uvicorn as the initial
  dependency, matching `argus_web`'s existing stack per design.md's framework
  decision)
- [x] 1.3 Add `.gitignore`
- [x] 1.4 Add `LICENSE` (MIT, matching this repo)
- [x] 1.5 Add `README.md` stating this repo is a test/demo fixture for Argus,
  linking back to this repo for design rationale, and noting it carries no
  `openspec/` tracking of its own (design.md's "planning artifacts live here"
  decision)

## 2. Minimal runnable app

- [x] 2.1 Implement a minimal FastAPI app exposing a health-check endpoint
- [x] 2.2 Confirm the app boots locally (`uvicorn`) and the health-check
  responds successfully (spec target-service-bootstrap: "The application
  boots and exposes a health-check endpoint")

## 3. Containerization

- [x] 3.1 Add a `Dockerfile` building an image that runs the app
- [x] 3.2 Confirm the built image runs and its health-check endpoint is
  reachable (spec target-service-bootstrap: "The Target Service builds and
  runs as a container")

## 4. Wire into this repo's local dev stack

- [x] 4.1 Add a service block to this repo's `docker-compose.yml`, building
  `Argus-Demo-Target-App` from a `../Argus-Demo-Target-App` relative context
  (design.md's sibling-checkout decision)
- [x] 4.2 Confirm `docker-compose up` in this repo brings up both the existing
  Postgres service and the new Target Service together, with the Target
  Service's health-check reachable (spec target-service-bootstrap:
  "`docker-compose up`... brings up the Target Service alongside Postgres")

## 5. Verification

- [x] 5.1 Confirm every requirement in `specs/target-service-bootstrap/spec.md`
  is satisfied by manually walking each scenario
- [x] 5.2 Confirm `Argus-Demo-Target-App`'s `README.md`, read with no other
  context, correctly identifies the repo as an Argus fixture and links back
  here
