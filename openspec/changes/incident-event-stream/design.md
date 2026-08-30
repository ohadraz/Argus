## Context

Postgres holds four things about an incident: the incident row, the hypotheses formed for it, the actions taken, and the status transitions. That is a record of conclusions. The work that produced them - the Investigator asking for a metrics window, finding an onset in it, widening because the window provably did not contain the start, reading the log lines around that onset, reading what changed on the service - happens inside `agent_investigator.investigate()` and leaves no trace anywhere.

So a page can report that an incident went `investigating → mitigating → resolved` and which candidate it blamed, and can say nothing about how. This change records the work itself, as spec §4 principle 8, and the live view is its first reader.

It is not §4 principle 6's `REPLAY_LOG`, which stays unbuilt and stays a different thing: that is a tape of every external call, request and response, at a granularity that lets a benchmark be re-scored without spending tokens. This stream is an account of the walk for a reader - it carries what a retrieval returned and not the call that fetched it, and nothing replays from it.

The constraint that shapes the design is §7.1's single-writer rule. Nothing may become a second writer of incident state - which is why the components publish rather than write, and one subscriber does the writing.

## Goals / Non-Goals

**Goals:**
- What Argus read and decided is written down as it happens, in order, per incident.
- Somebody can watch an incident being reasoned about, not just read its outcome.
- Adding a publisher to a component costs one injected parameter and changes nothing about what that component decides.
- The evidence shown on the page is the evidence Argus read, byte for byte.

**Non-Goals:**
- A message broker. The interface is designed so one can be dropped in; installing one now buys a demo nothing and costs it a service.
- Replaying an incident - re-running it from its recorded events. The stream is an account, not a command log.
- Metrics, tracing, or anything about Argus's own performance. This is about what it concluded, not how fast.
- Editing, acknowledging or acting from the page. Still no writes, still no buttons.

## Decisions

### Components publish; one subscriber writes

Each component takes a publisher the way it already takes its collaborators - a default-argument parameter with a real default. `agent_investigator.investigate()` already receives `fetch_metrics` and `fetch_logs` this way; a `publish` beside them is the same seam, and a test passes a double without touching a module-level name.

The subscriber is the only writer. It appends to one table and touches nothing else, which is what keeps §7.1 true: the incident, hypothesis, action and timeline rows still have exactly one writer between them, and the event table has exactly one of its own.

**Alternative considered:** components write their own event rows directly. Rejected - it makes every agent a database client, and the reason agents have no database dependency today is that a component which can write can write the wrong thing.

### The transport is an interface, and today it is a function call

A `Publisher` Protocol with one method. The default implementation dispatches in-process to the subscriber, synchronously. A broker later implements the same Protocol, and no publisher and no reader changes.

Synchronous because the alternative - a queue and a thread - buys latency relief nothing here needs, and costs the guarantee that an event published before a decision is recorded before it. A demo watching a walk move in order deserves that ordering to be real rather than usually-true.

**Alternative considered:** Kafka, or Redis streams, now. Rejected on the same grounds as the second dashboard process: a demo has an audience, and a second thing to start is a second thing to fail in front of them.

### Publishing cannot fail an incident

The publisher's contract is that it raises nothing. A subscriber that throws is caught and dropped at the seam, because the account of the work must never be able to stop the work. This is the one place in the codebase where swallowing an exception is correct, and it is worth a comment saying why.

### An event carries the whole payload it is about

A retrieval event stores what the channel actually returned - every bucket, every log line - not a reference to fetch again at render time. Re-fetching would let the page show something Argus never saw, since the log store moves on, and "the value shown is the one that was recorded" is the property the whole view rests on.

The cost is row size: a widened log window is a few hundred lines, stored twice if two candidates read overlapping windows. That is acceptable against a database that is dropped on every `down -v`, and the alternative fails the one requirement the view exists to satisfy.

**Alternative considered:** cap and truncate. Rejected for now - a truncated event is no longer the account it claims to be, and nothing here is near a size that needs it. Worth revisiting if a real deployment ever keeps incidents for months.

### The front page is the newest incident that has not finished

No new "current incident" state, no pointer to keep correct. The rule is: the newest non-terminal incident; if none is running, the newest incident overall, shown as finished. It is right whenever one incident runs at a time, which is the demo, and it degrades sensibly when that stops being true rather than showing nothing.

**Alternative considered:** strictly empty unless something is running. Rejected because a resolved incident would vanish from the front page the moment it resolved - exactly when everyone in the room is looking at it.

### Each component narrates what only it knows

The graph publishes agent invocations and status changes; the Investigator publishes its own retrievals, onset and hypotheses; Mitigation publishes its action and verdict. The Orchestrator cannot report a window the Investigator chose inside its own loop, and a design where it tried would either leak that loop into the graph or narrate a guess.

### Acknowledging the alert is an event, not a status

The moment Argus receives an alert and has not yet looked at anything is worth showing, and the narration shows it - as its first line, published when the incident is created. It is not made into a status: the status machine (spec §10) describes where an incident can go next, an acknowledgement adds nowhere to go, and giving it a status would rewrite the one assertion every existing lifecycle test makes for the sake of a label.

This is the general rule the stream exists for. Things that happened belong to the stream; states an incident can be in belong to the FSM, and the two are not the same list.

### The view reads events the way it reads everything else

Through a repository that owns the table, shaped by a builder, rendered by a template - the arrangement the incident page already uses. The narration is a list of view models built from event rows; the evidence tables are rendered from the payloads those rows carry, coloured the way the Target Service's console colours the same data, because two screens in a demo that colour the same thing differently make a reader translate between them.

### The evidence is gathered into tables, not shown under each retrieval

Each channel gets one table below the narration, holding every value that channel returned, said once. Evidence rendered inline under the retrieval that fetched it looked right for a single-pass investigation and wrong for the one that actually runs: a widening investigation re-reads overlapping windows, so the minutes around the onset came back four or five times and the page showed four or five copies of them.

What is lost by moving them out is which retrieval returned which row, and that is bought back by linking: the narration line names the row it is about - the onset its minute, an action the flag change it reverted, a cited finding the minute it names and that minute's log lines - so a reader who wants the evidence for a claim is one click from it rather than scrolling past its duplicates. Where a line cannot say which row it means without guessing, it gets no link: prose is never matched to a particular log line, because a link built by inference points confidently at the wrong evidence.

## Risks / Trade-offs

- **The stream drifts from the truth as components are added** - a new agent that publishes nothing is invisible on the page, and nothing fails → the requirement is per-component, and a component's own tests are where its publishing is asserted.
- **Row size on retrieval events**, stored whole → bounded in practice by the log window ceiling that already exists (`log_max_window_minutes`), and by a database that starts empty every run.
- **Synchronous publishing puts the subscriber in the investigation's path** → the subscriber does one insert and the seam swallows its failures, so the worst case is a slower incident with a gap in its story, not a failed one.
- **A second reader of the same facts** - the timeline table records status transitions and so does the stream → the timeline stays the FSM's own record and the stream stays the narration; where they overlap, the view reads the stream, and the duplication is one table's worth of small rows rather than a shared source both must agree on.
