from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from argus_core.db import connect
from argus_core.schema import create_schema
from fastapi import FastAPI
from orchestrator.entrypoint import create_incident_and_run

from argus_web.grafana import parse_grafana_alert


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    with connect() as conn:
        create_schema(conn)
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/webhooks/alerts", status_code=202)
def receive_alert(payload: dict[str, Any]) -> dict[str, str]:
    """`argus_web`'s only incident-domain entrypoint (spec §7.9): validates
    and normalizes the payload into an `Alert` domain object, then calls the
    Orchestrator's entrypoint in-process - never the raw payload."""
    alert = parse_grafana_alert(payload)
    incident_id = create_incident_and_run(alert)
    return {"incident_id": incident_id}
