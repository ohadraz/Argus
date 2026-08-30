from __future__ import annotations

import psycopg

# Mirrors spec §11.1's ERD (INCIDENT/HYPOTHESIS/ACTION/TIMELINE_EVENT/POSTMORTEM).
# `timeline_event.to_status` is an implementation addition beyond §11.1's sketch,
# needed to record which status each transition landed on (spec §10, §25);
# `created_at` plays the role of §11.1's conceptual `ts` field.
DDL = """
CREATE TABLE IF NOT EXISTS incident (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_payload JSONB NOT NULL,
    status TEXT NOT NULL,
    slack_channel_id TEXT,
    pr_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- `id` keeps its default for hand-written rows, but the application supplies
-- one: identity belongs to the entity, not to the table (argus_core.ids).
-- `summary` is §11.1's `description`, renamed to match the domain model.
CREATE TABLE IF NOT EXISTS hypothesis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incident(id),
    cause_type TEXT,
    summary TEXT,
    supporting_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    tested BOOLEAN NOT NULL DEFAULT false,
    result TEXT,
    confidence FLOAT,
    -- What the named cause is about - for a flag toggle, the flag itself.
    -- Nullable: not every cause names something this system can identify, and
    -- a hypothesis recorded before this column existed named nothing either.
    subject TEXT,
    -- Where this hypothesis came in its investigation's ordering, best first.
    -- Defaulted rather than nullable: a row written before this column existed
    -- was the only hypothesis its investigation had, which is rank 1.
    rank INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS action (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incident(id),
    type TEXT,
    target TEXT,
    reversible BOOLEAN NOT NULL DEFAULT true,
    tier TEXT,
    undo_descriptor JSONB,
    outcome TEXT,
    taken_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by TEXT
);

CREATE TABLE IF NOT EXISTS timeline_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incident(id),
    to_status TEXT NOT NULL,
    actor TEXT,
    action TEXT,
    result TEXT,
    confidence FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS postmortem (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incident(id),
    root_cause TEXT,
    cost_estimate JSONB,
    assumptions JSONB,
    executive_summary TEXT,
    checklist_complete BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def create_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cursor:
        cursor.execute(DDL)
    conn.commit()
