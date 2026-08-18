## ADDED Requirements

### Requirement: `Argus-Demo-Target-App` exists as a separate, standard-bootstrap repository
The system SHALL provide `Argus-Demo-Target-App` as its own git repository, sibling to this repo on disk, containing `pyproject.toml`, `.gitignore`, `LICENSE`, `Dockerfile`, and `README.md`.

#### Scenario: Repository is cloned and inspected
- **WHEN** `Argus-Demo-Target-App` is cloned as a sibling directory to this repo
- **THEN** it contains `pyproject.toml`, `.gitignore`, `LICENSE`, `Dockerfile`, and `README.md` at its root

### Requirement: README identifies the repo as an Argus test fixture, not an independent project
The system SHALL state in `Argus-Demo-Target-App`'s `README.md` that it exists as a test/demo fixture for Argus and link back to this repo for design rationale, carrying no `openspec/` tracking of its own.

#### Scenario: README is read in isolation
- **WHEN** `Argus-Demo-Target-App`'s `README.md` is read without any other context
- **THEN** it identifies the repository as a fixture for Argus and links to this repo

### Requirement: The application boots and exposes a health-check endpoint
The system SHALL run a minimal FastAPI application in `Argus-Demo-Target-App` that starts successfully and responds to a health-check request.

#### Scenario: Health check succeeds after startup
- **GIVEN** `Argus-Demo-Target-App`'s application has started
- **WHEN** its health-check endpoint is requested
- **THEN** it responds with a success status

### Requirement: The Target Service builds and runs as a container
The system SHALL provide a `Dockerfile` in `Argus-Demo-Target-App` that builds an image capable of running the application.

#### Scenario: Image builds and serves the health check
- **WHEN** `Argus-Demo-Target-App`'s `Dockerfile` is built into an image and run
- **THEN** the resulting container responds to the health-check endpoint

### Requirement: `docker-compose up` in this repo brings up the Target Service alongside Postgres
The system SHALL extend this repo's `docker-compose.yml` with a service definition that builds `Argus-Demo-Target-App` from a sibling-checkout relative path, so it starts together with the existing Postgres service.

#### Scenario: Local dev stack includes the Target Service
- **GIVEN** `Argus-Demo-Target-App` is checked out as a sibling directory to this repo
- **WHEN** `docker-compose up` is run in this repo
- **THEN** both the Postgres service and the Target Service start and the Target Service's health-check endpoint is reachable
