from __future__ import annotations

from typing import Final

import psycopg

# Mirrors spec §11.1's ERD: INCIDENT, HYPOTHESIS, ACTION, INCIDENT_RUN,
# TIMELINE_EVENT, INCIDENT_EVENT, POSTMORTEM, REPLAY_LOG - and EXCHANGE_RATE,
# which belongs to no incident and hangs off nothing there either.

DDL = """
CREATE TABLE IF NOT EXISTS incident (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_payload JSONB NOT NULL,
    status TEXT NOT NULL,
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
    -- Nullable: not every cause names something this system can identify.
    subject TEXT,
    -- The two ends of the change blamed on that subject - `off` and `on` for a
    -- flag, two versions for a deployment. Both null together: not every cause
    -- is a move from one state to another, and half a transition is a position.
    from_state TEXT,
    to_state TEXT,
    -- Where this hypothesis came in its investigation's ordering, best first.
    -- Defaulted rather than nullable: every hypothesis has a rank, and a row
    -- that does not say otherwise is first.
    rank INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per action, written before the action is taken rather than after:
-- the insert is what claims the right to take it. The unique index below is
-- therefore the guard against a resumed walk acting twice - a second insert
-- for the same candidate writes nothing, and writing nothing is how the walk
-- that lost learns the action is already somebody's.
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

-- What makes one action one action. A partial index rather than a table
-- constraint, because the insert that claims a candidate names the same
-- predicate in its `ON CONFLICT ... WHERE hypothesis_id IS NOT NULL` arbiter,
-- and that only infers a partial index. It says the same thing either way:
-- two actions belonging to no candidate are two actions, where two claiming
-- the same candidate are one attempt written twice.
CREATE UNIQUE INDEX IF NOT EXISTS action_once_per_candidate_idx
    ON action (incident_id, hypothesis_id)
    WHERE hypothesis_id IS NOT NULL;

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

-- What Argus did, as it did it (spec §4 principle 8) - the account beside the
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
    -- means. The first two are estimates and carry their assumptions; the
    -- minutes and the tokens are measurements (spec §21.3).
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
    -- (spec §21) will aggregate responders as readily as it aggregates
    -- minutes.
    engineer_minutes INTEGER,
    responders INTEGER,
    -- What those responders were called by their profession, never who they
    -- were. A list rather than a column apiece: it is read whole, by a page
    -- that prints it, and nothing aggregates across titles.
    responder_titles JSONB,
    -- What those minutes were worth, priced at the pay band of each
    -- responder's title. Three columns rather than one, because a band is a
    -- range: the midpoint is the figure, and the two beside it are the same
    -- minutes at the bottom and top of the same bands. Stored rather than
    -- re-derived, for the same reason the loss estimate is - bands are
    -- republished, and a figure recomputed next year would describe a
    -- different incident.
    responder_cost_estimate NUMERIC,
    responder_cost_minimum NUMERIC,
    responder_cost_maximum NUMERIC,
    -- Its own currency rather than `estimate_currency`: the bands come from a
    -- different source than the takings, and nothing here converts one figure
    -- into the other.
    responder_cost_currency TEXT,
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

-- One walk of the graph, waiting to be taken or being taken. The alert
-- endpoint writes the row and answers; a worker claims it and invokes the
-- graph. The row is what makes an investigation outlive the request that
-- asked for it - and what lets a worker that died be told from one that is
-- still working.
--
-- Beside the incident rather than inside it: an incident's status says what
-- Argus knows about the failure, and a run's state says whether anything is
-- currently thinking about it. Folding the second into the first would make
-- "nobody is walking this" and "this is resolved" the same column.
CREATE TABLE IF NOT EXISTS incident_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incident(id),
    -- queued, running, done or failed. Text like every other state in this
    -- schema: the vocabulary lives in the code that reads it, and a check
    -- constraint here would be a second place to change it.
    state TEXT NOT NULL,
    -- Who holds it and until when. Both null while queued. The lease is what
    -- separates a worker still walking a run from one that stopped mid-walk:
    -- a lock cannot say that, because a dead worker's lock dies with its
    -- connection and leaves the row looking held by nobody.
    claimed_by TEXT,
    leased_until TIMESTAMPTZ,
    -- Why a run stopped, where it stopped badly. Recorded against the run
    -- rather than left in a log: an incident whose walk failed is then
    -- distinguishable from one still being worked by asking the database,
    -- which is the question every reader of a run actually asks.
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- What a worker asks for, every interval, forever: the runs it could take.
CREATE INDEX IF NOT EXISTS incident_run_state_idx ON incident_run (state);

-- How far each reader of `incident_event` has got. A relay delivering an
-- incident's account somewhere else asks the log what has happened since it
-- last looked, and this is the whole of its state: lose it and the relay
-- either repeats an incident from the beginning of time or starts from now
-- and silently drops whatever was published while it was down.
--
-- One row per reader rather than one row, because two destinations fall
-- behind at different rates and a shared place would let the slower of them
-- decide what the faster has already said.
--
-- Hangs off no incident, like `exchange_rate`: it is a fact about a reader.
-- Written and read by `agent_communicator` alone - the DDL is here because
-- this file is where the schema is stated, not because the incident record
-- owns the table.
-- Which Slack conversation an incident is being told in. Slack has no thread
-- id: a reply names the timestamp of the message it replies to, so the first
-- message an incident got is its thread, and every later line has to find that
-- timestamp again - in another pass, another process, another day.
--
-- A row rather than a column on `incident`, because an incident knows nothing
-- about Slack and should not learn: a second destination adds a mapping of its
-- own shape here instead of a column on the table every part of this system
-- reads. Written and read by `agent_communicator` alone.
CREATE TABLE IF NOT EXISTS slack_thread (
    incident_id UUID NOT NULL REFERENCES incident(id),
    channel TEXT NOT NULL,
    -- Slack's own shape for a message's identity - seconds and microseconds -
    -- kept as text because that is what a reply has to send back, to the
    -- digit. A number would round it and address nothing.
    ts TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One conversation per incident per channel. The key is the guard: a
    -- second opening message - two relays at once, a pass repeated after a
    -- crash - writes nothing, and the conversation people are already reading
    -- stays the one the rest of the incident goes into.
    PRIMARY KEY (incident_id, channel)
);

CREATE TABLE IF NOT EXISTS event_cursor (
    reader TEXT PRIMARY KEY,
    -- A place in `incident_event.seq`, not a foreign key to it: the row a
    -- reader stopped at can be a row that no longer needs to exist, and a
    -- cursor that could not point past the end of the log could not be set
    -- to where the log ends.
    seq BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def create_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cursor:
        cursor.execute(DDL)
    conn.commit()


def reset_schema(conn: psycopg.Connection) -> None:
    """Throws the schema away and applies it again, leaving nothing behind.

    What a suite starts a run from, where `create_schema` is what a deployment
    starts one from. The difference is the database being started against: a
    suite adopts whatever container was left over, and the DDL is
    `CREATE TABLE IF NOT EXISTS` throughout, so a table that already exists is
    never altered. A column added or renamed since that container was last
    used would silently never appear, and the suite would run against a schema
    no file in this repo describes.

    It empties the tables as a consequence, which is the other half. Emptying
    between tests happens *after* each test, so that a failure leaves its rows
    to be read - which means a run that was killed leaves its last test's rows
    for the next run's first test to find. Starting from nothing is what makes
    the manner of the previous run's death stop mattering.

    Here rather than in a conftest because naming the schema is exactly what
    `create_schema` exists to spare its callers, and four suites naming it
    would be four places to fix on the day it is no longer `public`.

    Bounded by a lock timeout, because the drop waits for whatever holds a
    table rather than failing on it. Anything still connected to an adopted
    container - a worker a killed run left behind, a suite someone started in
    another terminal - would otherwise stop this at the first statement of a
    session-scoped fixture, before pytest has printed a line, and a run hung
    with no output is the hardest kind of failure to place. Given a bound it
    says which statement waited and for how long.
    """
    with conn.cursor() as cursor:
        cursor.execute(f"SET LOCAL lock_timeout = '{_SECONDS_TO_WAIT_FOR_A_LOCK}s'")
        cursor.execute("DROP SCHEMA public CASCADE")
        cursor.execute("CREATE SCHEMA public")
    conn.commit()

    create_schema(conn)


# How long the reset waits for a table somebody else is holding. Long enough
# to outlast a connection on its way out - a process that has just been killed
# still holds its locks until the server notices - and short enough that a
# suite blocked behind a live one reports it while somebody is still watching.
_SECONDS_TO_WAIT_FOR_A_LOCK: Final = 10
