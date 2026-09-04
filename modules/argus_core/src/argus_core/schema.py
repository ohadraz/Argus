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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- When the incident stopped being one, stamped on the transition that
    -- ended it. Null while it is still being worked - which `fixing` is,
    -- however terminal it reads. How long an incident lasted is reported
    -- rather than derived, because deriving it from the last row written
    -- would make it an accident of what happened to be logged last.
    ended_at TIMESTAMPTZ
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
    -- The candidate this action was taken for. Nullable because not every
    -- action need have one, never because the association is optional where it
    -- exists: an action taken on a hypothesis and not naming it leaves a reader
    -- to guess which candidate it belonged to by matching the flag the two
    -- happen to mention - which is only ever right because the walk refuses to
    -- act on one subject twice, a rule about retrying rather than about
    -- identity.
    hypothesis_id UUID REFERENCES hypothesis(id),
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

-- What Argus did, as it did it (spec §4 principle 6) - the account beside the
-- conclusions the other tables hold. Append-only: a line of the story is never
-- amended, because an account that can be edited afterwards is not one.
--
-- `seq` orders it rather than `at`. Two events can share a moment to the
-- microsecond, and "the order they were published in" is a promise the
-- narration rests on, so it is kept by the sequence the rows were written in
-- rather than by a clock that can tie.
--
-- The event is stored whole in `payload`, and `kind` beside it is what a
-- reader discriminates on. The columns are not a second copy to keep in step -
-- they are what the table is queried by.
CREATE TABLE IF NOT EXISTS incident_event (
    seq BIGSERIAL PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    incident_id UUID NOT NULL REFERENCES incident(id),
    kind TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

-- Every call Argus made out of its own process, kept so a run can be
-- re-examined without making them again (spec §4 principle 6, §11.1).
--
-- Not incident state and not narration. The domain tables hold what Argus
-- concluded and `incident_event` holds the account a human reads; this holds
-- the calls themselves, at a granularity nobody reads for pleasure - one row
-- per model completion or tool call, with both payloads whole. That is what
-- lets the eval harness re-score a benchmark run offline instead of paying for
-- it twice.
--
-- `seq` for the same reason `incident_event` has one: two calls can share a
-- timestamp to the microsecond, and the order they were made in is the only
-- thing that makes a conversation readable back.
--
-- Written by the process that made the call, never by an MCP server - the
-- servers stay pure, as spec §13's boundary requires.
--
-- No cost column. No API returns a price, so any figure here would come from a
-- rate card copied into this repo: right until the vendor moves it, silently
-- wrong after, and wrong in a column somebody would later sum with confidence.
-- The token counts are inside `response`, where they are what the model
-- actually reported, and pricing them is the reader's job at the rate of the
-- day they ask.
CREATE TABLE IF NOT EXISTS replay_log (
    seq BIGSERIAL PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    incident_id UUID NOT NULL REFERENCES incident(id),
    call_type TEXT NOT NULL,
    target TEXT NOT NULL,
    request JSONB NOT NULL,
    response JSONB NOT NULL,
    latency_ms INTEGER NOT NULL,
    at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS postmortem (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incident(id),
    root_cause TEXT,
    -- Three figures rather than one blob, and three rather than two: what the
    -- incident cost the business, what it cost the humans, and what it cost
    -- Argus are different quantities in different units, measured by different
    -- means. Only the first is an estimate.
    --
    -- Columns because the eval tier aggregates them - tokens across a
    -- benchmark run, minutes across a quarter - and a JSON blob would mean
    -- re-deriving that at query time, which is the same reason the tables
    -- beside this one are structured.
    --
    -- All nullable: a postmortem written before anyone recorded how long they
    -- spent is still a postmortem, and a zero would claim nobody spent
    -- anything.
    customer_loss_estimate NUMERIC,
    -- The currency that figure is in, stored beside it rather than read from
    -- configuration. The reporting currency is a setting, and a page that
    -- looked it up when it rendered would relabel every figure ever written
    -- the day somebody changed it.
    estimate_currency TEXT,
    -- Person-minutes, and the people they were spread across. Both, because
    -- one number cannot say the difference between a night one engineer lost
    -- and an hour four of them lost together - and because the eval tier
    -- aggregates responders as readily as it aggregates minutes.
    engineer_minutes INTEGER,
    responders INTEGER,
    -- What those responders were called by their profession, never who they
    -- were. A list rather than a column apiece: it is read whole, by a page
    -- that prints it, and nothing aggregates across titles.
    responder_titles JSONB,
    tokens_spent INTEGER,
    assumptions JSONB,
    executive_summary TEXT,
    checklist_complete BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per currency per day, against one base. The rates a document was
-- converted at have to survive the document: a reader checking the arithmetic
-- next month cannot re-fetch them, because the provider publishes today's and
-- an estimate quietly re-derived at today's rate would be a different figure
-- every time anybody looked.
--
-- Not an incident's table. Rates belong to a day and are shared by every
-- postmortem written about it, so this is keyed by what identifies a rate -
-- the base it is quoted against, the currency it prices, and the day the
-- provider published it - and by nothing about who happened to ask first.
--
-- NUMERIC, like the money it converts: a rate held as a float is a rate that
-- rounds differently depending on which figure it is multiplied into.
CREATE TABLE IF NOT EXISTS exchange_rate (
    base TEXT NOT NULL,
    currency TEXT NOT NULL,
    published_on DATE NOT NULL,
    per_unit NUMERIC NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (base, currency, published_on)
);
"""


def create_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cursor:
        cursor.execute(DDL)
    conn.commit()
