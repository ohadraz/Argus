## Context

The agreed mock is https://claude.ai/artifact/3Jp9XdPuqg9YTBmajDTHnA. Today the
agent takes `IncidentEvidence` - lists of already-rendered lines - measures, asks
the model once (two attempts) through `submit_postmortem`, and assembles a
`PostmortemDocument`. Every figure is computed; the model writes the root cause,
the summary, extra assumptions and what each lead changed. The page renders
root cause, summary, PR, leads, assumptions, cost and a checklist flag.

## Goals / Non-Goals

**Goals:** the template's sections, stored and shown; facts by code, prose by
the model; checks that make the prose answerable to the evidence.

**Non-Goals:** the PDF and its download; posting it to Slack; editing action
items in Argus; an eval of the prose.

## Decisions

### D1. Evidence carries structure, the prompt still gets lines

`IncidentEvidence.timeline`, `.candidates` and `.actions` become structured:
the narration as `TimelineEntry` (at, who, text), a `CandidateRecord`
(summary, failure mode, subject, from/to state, confidence, whether it was
tested, result) and an `ActionRecord` (taken at, the action in the narration's
words, reversible, verdict, whether it stands). The prompt renders them to the same lines it sends
today. Alternative - parsing the lines back - is the defect the module's
docstrings already warn against.

Gathering adds the retrieved changes (`ChangesRetrieved`) so the trigger can be
dated. The alert time is the evidence's existing `started_at`.

### D2. Evidence is labelled once, and the labels are the citation

The prompt labels every timeline line, log line, candidate and action `E1..En`
in the order shown, as leads are labelled `L1..`. `labelled()` in
`argus_core.models` already does this for leads; it is reused. The document
stores each chain step with its cited labels **and the text they named**, so a
reader of the stored row never needs the prompt.

### D3. Record-implied action items are numbered before the model is asked

Code builds the record's items (D-spec order: confirmed actions, the PR, the
recommendation) and numbers them `AI-1..AI-k`. The prompt lists them, so the
model's contributing factors can name them and its own proposals are numbered
`AI-k+1..` by position. The model never writes a number for an item; it writes
a factor's `addressed_by` as labels, which the check validates against the
whole list.

### D4. The prose names a figure and never writes one

Comparing the prose's numbers with the prompt's refuses a recorded answer
whenever a replay measures differently, and accepts "about twenty minutes" for
an incident six long while refusing a true "about 20". So the prose writes no
figure at all - not in digits, not in a run of number words, not in one word
that measures something - and names one instead: every figure shown carries a
name in braces (Argus's by what it is, the alert's and each piece of
evidence's by its place), and code writes it in. A figure the incident never
gave as one is a working of two it did, one binary operation typed by kind and
worked out from the figures as shown, so the result never disagrees with them
by a rounding. Two refusals read the run rather than the answer - a working
below nothing, or dividing by nothing - which is safe only because a replay
rebuilds its recording's world exactly.

### D5. Root cause stays a sentence above the chain

`root_cause` is kept - Google's template has a Root Causes paragraph, and
`PostmortemWritten` and the Slack line read it. The chain and factors sit under
it.

### D6. The review checklist is stored as named criteria

`checklist_complete BOOLEAN` becomes `review JSONB`: five entries, each
`{criterion, met}` with `met` true, false, or null for "left for a person".
Null rather than false for the two Argus cannot meet: a box that is always
failed teaches the reader to ignore the checklist.

### D7. Human resolution is read when shown, not stored

The proposal's first draft stored a person's resolution in the document. It
cannot be: an escalated incident is written up first and resolved later
(`human-resolution`). The view reads it from the record, as it does today,
and places it in the header and the Resolution table.

### D8. Schema: revision 001 edited in place

New JSONB columns: `impact`, `causal_chain`, `contributing_factors`,
`action_items`, `lessons`, `timeline`, `hypotheses`, `resolution`, `detection`,
`trigger`, `review`; an `evidence_read INTEGER`; drop `checklist_complete`.
Supporting information has no column: its links are the view's, built from the
request, and its count is `evidence_read`. The responder cost range
columns stay; they are stored and not shown. `001` is the whole chain, so it is
edited and `nox -s schema` re-applies it.

### D9. Formatting belongs to the view

Two decimal places and grouping are a Jinja filter in `argus_web`, applied to
every amount. Stored values keep full precision.

## Risks / Trade-offs

- [The tool grows, so every recorded postmortem answer goes stale] →
  re-record each mode's postmortem calls once (paid), after the free suites are
  green; the replay double is FIFO, so a stale answer fails loudly.
- [Longer output, more tokens per postmortem] → measured on the first record
  run and reported.
- [The model cites a label that exists but does not support the step] → not
  checkable by code; the stored cited text lets a reader see it.
- [A single responder's midpoint cost still implies their band's midpoint, with
  the minutes beside it] → the agreed scope removes the endpoints and the range;
  the midpoint figure stays, as decided.

## Migration Plan

`nox -s schema` (destructive, as always). No data migration: postmortems are
rewritten by running incidents again.
