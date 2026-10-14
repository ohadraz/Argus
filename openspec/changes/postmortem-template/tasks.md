Every behaviour task is TDD: propose the failing test in chat (the user applies
it), see it red for the right reason, then implement. Bottom-up: kernel,
gathering, agent, view, e2e.

## 1. Kernel

- [x] 1.1 `PostmortemDocument` parts: chain step, contributing factor, action
      item (`AI-n`, type, owner, tracking, status), lessons, timeline entry with
      marker, hypothesis considered, resolution row, detection, trigger,
      evidence count (D8; the review criterion lands with 4.5)
- [x] 1.2 Migration `001`: the new columns (`checklist_complete` goes with 4.5)
- [x] 1.3 Postmortem repository round-trips every new part

## 2. Gathering (D1)

- [x] 2.1 Timeline as narration lines, candidates and actions structured
- [x] 2.2 The retrieved changes gathered (the alert time is `started_at`)
- [x] 2.3 Timeline lines said in full (`said_in_full`: the move, the candidates)
- [x] 2.4 An action dated by its `ActionTaken` line, not the claim row, and said
      in words (`what_was_done`)

## 3. Agent: facts by code

- [x] 3.1 Detection: onset, alert, rule, gap; none without an onset
- [x] 3.2 Trigger: the confirmed candidate's change, dated; none established
- [x] 3.3 Resolution rows from the actions
- [x] 3.4 Record-implied action items, numbered first (D3)
- [x] 3.5 Timeline with its four markers, each left out when unknown
- [x] 3.6 Hypotheses considered from the candidates
- [x] 3.7 Supporting links and the evidence count (the count is the number of
      labels, so it lands with 4.1; the links are the view's, with 5.1)
- [x] 3.8 Pay-band assumption without figures
- [x] 3.9 Impact: the duration, whether it is measured, a lower bound or
      unobserved, and the peak error rate - carried, not left to the view
- [x] 3.10 Impact: requests failed over the broken minutes
- [x] 3.11 Trigger: the change's kind and actor; the MITIGATED marker sorts
      after the line that took it

## 4. Agent: prose by the model

- [x] 4.1 Prompt labels evidence per kind (`T`, `C`, `M`) and log lines grouped
      by message under a content label (`G3fa2`, `log_groups`), and lists the
      record's action items (D2, D3)
- [x] 4.2 `submit_postmortem` gains chain, factors, proposed items, lessons;
      `SubmittedPostmortem` reads each at the cost of that field only
- [x] 4.3 Faults: chain step citing nothing or an unknown label; factor
      unanswered or naming an unknown item
- [x] 4.4 Faults: any digit in any prose field outside a label (D4) - replaces
      the given-number and currency checks, whose verdict varied by run
- [x] 4.5 Review checklist computed (D6)
- [x] 4.6 `write_postmortem` assembles every section
- [x] 4.7 `symptom` field: the model's words, the title adds the trigger
- [x] 4.8 A refusal answers every call in the turn
- [x] 4.9 A standing brief (`briefing.py`): the five whys from the symptom, and
      the record outranks a candidate; bound in `assembling` via
      `postmortem_policy`
- [x] 4.10 Prompt: production changes under `P` labels (T, P, G, C, M); a line
      that formed candidates names them by label (`TimelineEntry.candidates`)
- [x] 4.11 Prompt: instants to the second, spans in days, hours and minutes
- [x] 4.12 Prompt: a rise at or below zero reads as none; the paging series
      named by its alert, and the harm where errors did not rise; why an error
      rate is not known (`error_rates_unmeasured`)
- [x] 4.13 Prompt: a span exact to the second, in days, hours, minutes and
      seconds; a revision is a name to the digit check, not a figure
- [x] 4.14 Prompt: the alert's own finding (`alert_finding`, carried by
      gathering), with `alert_summary` renamed `alert_title`
- [x] 4.15 The digit check refuses figures only (amounts, shares, times,
      dates, durations, counts); names with digits pass. Revisions are held to
      the ones the incident read (`revisions.py`): one a character off is
      corrected by code, one starting like none is refused
- [x] 4.16 Rows carry the labels the prompt cited them by (`C`, `M`, `T` via
      `label_of`); a marker carries none
- [x] 4.17 A trigger nothing tested, where the leading candidate is untested
      and its change was read, is `suspected`; never in the title
- [x] 4.18 "Root-cause analysis complete" needs a confirmed cause
- [x] 4.19 Loss against the incident's own hours whole weeks earlier
      (`weeks_back_for`); a shortfall within the shop's own variation is a
      measured zero, disclosed (`normal variation`)
- [x] 4.20 Onset marker says the incident began, not that the service failed
- [x] 4.21 Figures by name (`figures.py`): every figure the model is shown has
      a name (Argus's by meaning, the alert's `A1..An` by position) and code
      writes it in, in digits, as this run measured it
- [x] 4.22 Prompt: each figure shown with its name; the tool asks for the name,
      never a figure in digits or spelled out
- [x] 4.23 Check: a figure spelled out in words is refused, and so is a name
      the incident never gave (`Given.figures`)
- [x] 4.24 Conversation: the answer kept has its figures written in

## 5. View

- [x] 5.1 Postmortem view carries every section; resolution read from the
      record (D7)
- [x] 5.2 Template in the agreed order, header with ID and the two times
- [x] 5.3 Money to two decimal places (D9); the cost range not shown
- [x] 5.4 Header as the mock: title, Incident, Date (+ local), Status
      (Draft/Final), Written by, Ended by; sections in Google's order
- [x] 5.5 The response cost not shown at all (cost ÷ minutes is a pay rate)
- [x] 5.6 Look: cards for impact and cost, causal chain as symptom/why rows,
      lessons in columns, timeline markers coloured, PR row in Resolution
- [x] 5.7 Spans to the second, rolled up to days (`as_span`)
- [x] 5.8 Every cited label in prose links to its row (`with_references`);
      hypotheses show their C label; a suspected trigger says so; a loss over
      an incident that never ended says "at least"
- [x] 5.9 Argus's own assumption lines begin with a capital
- [x] 5.10 A deployment trigger says the service and its revisions ("io-shop
      was deployed from 4c810f2 to 26f1d7e"), a whole commit cut to seven
      (`as_revision`); the title likewise ("while io-shop ran 26f1d7e")
- [x] 5.11 No link to the page itself in Supporting information
- [x] 5.12 No loss reads "none", or "none so far" where the incident never ended
- [x] 5.13 A timeline row on a new day says its date
- [x] 5.14 Impact shows what the alert found (`alert.summary`)

## 5a. Narration and the Investigator (found judging monthly-totals)

- [x] 5a.1 A retrieval window off its line's day keeps its date
- [x] 5a.2 A refusal said of the action names the action as its subject
- [x] 5a.3 A pod placed well after the onset is said to have started after it,
      in the timeline and in the Investigator's prompt (`started_after_the_onset`)
- [x] 5a.4 e2e replay shift in whole minutes (`tests/e2e/framework/argus.py`)
- [x] 5a.5 The postmortem reads a long incident's metrics in consecutive
      windows the read tier serves whole, each shared minute once
- [x] 5a.6 A pod started after the onset says when (`a_moment(beside=onset)`)

## 6. e2e and recordings

- [x] 6.1 e2e cases asserting the new sections (user writes them)
- [x] 6.2 Re-record the postmortem calls per mode, postmortem-only (paid)
- [x] 6.3 `record --replay` seeds rebased answers as the suite does
- [x] 6.4 A postmortem-only re-record holds the paid call (double
      `hold-when-dry`) and names where it is recorded before releasing it. The
      check that refused a replayed finding quoting an instant this run did
      not hold is gone: two runs act, judge and recover in different minutes,
      so no recording could pass it; the write-up states every time by name
- [x] 6.5 User applies the double's `hold-when-dry` (scratchpad drafts/server.py)
- [x] 6.6 Moot: the check it was to dry-run is gone (6.4)
- [x] 6.7 Dropped: the shop is not bent to make two worlds agree (`afaa63c`
      reverted in `074bfa3`); a scenario the findings check refuses gets a
      full re-record, which writes walk and postmortem in one world
- [x] 6.8 An attempt is dated by when its action was taken
      (`IncidentState.acted_at`), not by when the walk moved on
- [x] 6.9 The write-up check refuses a time written as a log or a clock
      writes it (`21:35–21:39`, `21:35Z`, `23h16`), and reads a number after
      "line"/"lines" as a place in a file
- [x] 6.10 A rate in digits (`5/s`, `120/min`) is a figure (`figures.py`)
- [x] 6.11 `record_incident` holds the dry call only once the walk has opened,
      fails fast on a failed run, and refuses to capture while a walk is live
      (`get_unsettled_runs`)
- [x] 6.12 The postmortem lists the flag changes the walk read before its first
      action, once each (`gathering._what_changed`) - two component tests in
      `test_gathering.py`, each shown to fail with its behaviour removed
- [x] 6.13 A recovery is never dated before the incident's onset
      (`find_recovery(..., since=)`, `Findings.onset`, `incident_began`)
- [x] 6.14 Whether the incident was read is asked of the stated onset wherever
      the alert states one, the minute the gate pairs it with
- [x] 6.15 Re-record `both-flag-revert-leaves-a-flap` postmortem-only, then
      replay it twice; keep it only if both pass
- [x] 6.16 A later Investigator round works from the onset the first
      established, grade and all (`EstablishedOnset`), and publishes none
- [x] 6.17 An incident Mitigation watched and never saw recover reports no
      recovery; the postmortem's own series check only where nobody watched or
      a recovery could not be dated (`watched_and_never_recovered`)
- [x] 6.18 A change read twice is one change, at its first place
      (`gathering._what_changed`)
- [x] 6.19 Owed, general: number the walk's changes by parsed instant, not
      read order (a later read reaching further back still renumbers). A
      logged replay of all 55 found no walk whose two orders differ (30 walks
      read changes), so no recording re-points
- [x] 6.20 The disproven case gets a recording of its own (it borrows
      no-evidence's, whose write-up cites a C1 the disproven walk never has).
      `alarm-disproven`, two replays green; the lifecycle file is `both`-only.
      Recording it surfaced `unobserved_from` read off minutes not yet
      reported - fixed in `measuring` with the source's lag in `Sources`
- [x] 6.21 The two resolved-mid-walk / resolved-in-PagerDuty cases get
      recordings of their own (they borrow feature-flag-toggle's, citing
      T22/T23 their shorter walks lack). The Slack one too. Recorder's
      `walk_from` + `resolved_by`; two replays of all three green; the file is
      `both`-only. Recorder now refuses a held call while the incident is not
      at its ending (Code-Fix's call was paid for as a write-up once)
- [x] 6.22 `test_incident_cost.py:133` matches `eur`; the disclosure now
      writes `EUR` (user's test edit)
- [x] 6.23 Write-ups refused inside passing tests: leaking service
      (`{errors_rise}` present in one run, absent in the next) and
      flag-toggle-uncorroborated (log group `Gad41`); tests do not assert the
      postmortem, so they pass anyway. Same class hangs
      `test_an_upstream_failure_is_escalated` (`Gad41`, "rendered normally",
      present only when a pre-onset minute drew no noise - the shop seeds noise
      by wall-clock minute). Born with this change (log-group labels and the
      unknown-label refusal). Agreed with argus-1b, user's to apply (tests/ and
      the double). Plan, agreed with the user: replays show the model the world
      its recording saw.
  - [x] Fail a case at once when its run fails, quoting `failure_reason`
  - [x] `modules/target_service_double`: in `e2e_replay` and `record` the
        shop's container serves through it; a seed with a staged anchor is
        pinned to anchor + whole minutes and its draws re-keyed by the shift
  - [x] The purchase grid: the stand-in asks the shop's three integrity
        checks the shift earlier and moves their answers' instants forward
        (`checks.py`), and refuses to start if `state` stops holding
        `integrity`'s own functions
  - [x] noxfile: both sessions lay `docker-compose.replay.yml` over the stack
        and set `TARGET_SERVICE_DOUBLE`; a postmortem-only `record` runs on
        the 10x clock
  - [x] Suite: every seed names its recording (`as_recorded_in=`); replaying
        a set with an anchor fails when the shop seeded from another
  - [x] `record_incident.py` stages the anchor for replaying and
        postmortem-only runs
  - [x] Contract test (`tests/contract/target_service/`): stand-in at A +
        shift equals the shop at A, for every generated scenario (still
        reads the shop's private `_the_window_now`; moving it to the public
        routes under the image's libfaketime is deferred)
  - [x] Timeline lines numbered by writer: the walk's stay T, lines outside
        the walk are XW; each recovery wait told by its last look. Every
        person-cuts-the-walk case acts during a wait, holds the walk, or pauses
        the worker
  - [x] Proof, free: two full `both` replays with zero differences in G,
        figures and T across all write-ups (41 compared, 0 differing; both
        runs 54/55, the one failure upstream-dependency-failure-14, a
        write-up recorded 10-13 outside its anchor's world citing `Gad41`)
  - [x] Paid: re-record upstream-dependency-failure's write-up
        postmortem-only, replay it twice (both green). No other write-up
        failed either full run, so none other was re-recorded; full `both`
        replay then 55/55
- [x] 6.24 Deferred to a change of its own (not minor): the figure check
      judges spelling, not truth - "about 20 minutes" refused, "about twenty
      minutes" accepted. Agreed direction: accept a number a figure the model
      was shown rounds to (read from the prompt text itself), name derived
      figures too, and decide whether a number matching nothing is refused or
      flagged. Brought into this change (argus-f9: the check is this change's
      own). Settled 2026-10-14 - the model never writes a number itself:
  - [x] 6.24.0 Write-ups recorded outside the replayed world.
        `both-resource-leak-10` named `{errors_rise}` and
        `both-flag-toggle-uncorroborated-10` cited `Gad41`; both were recorded
        10-13, before the stand-in (10-14 03:44), against noise the stand-in
        does not draw. The replay is not at fault: every replay since refused
        both identically (rebuilt world: errors 1.2% before, 1.0% while
        broken, so no rise at any onset). Test (user's): the e2e teardown fails
        a case any of whose walks failed, quoting the reason - red on exactly
        these two. Fixed by re-recording both write-ups `--postmortem-only`
        (~7.4k output tokens); both green.
  - [x] 6.24.1 Each figure carries its kind (instant, span, share, amount,
        count) and its value, not its name alone. Done as: the kind is read
        off the figure's name (`figures._KINDS`; the alert's figures have
        none) and the value off the figure as shown, so `Figure` is unchanged.
  - [x] 6.24.2 A placeholder may be an expression over figures (`-`, `/`,
        `+`), evaluated by type and formatted by Argus; a nonsensical one
        (instant + instant, share / span, division by zero) is refused with why.
        Settled with argus-f9: one binary operation, no literals, alert
        figures are no operands; instant-instant=span, instant+-span=instant,
        span+-span=span, share-share=percentage points (written so, never as
        a %), level-level=level; ratios of spans, shares and levels only,
        written "2.4 times"; computed from the figures as shown, so a result
        never disagrees with the figures beside it; a negative difference or a
        zero divisor is refused - which reads the run, so checking.py's "the
        rule reads the answer alone" is reworded. The submit tool's
        description tells the model so, with two examples.
  - [x] 6.24.3 Argus names the derived figures that matter (`{downtime}`), so
        the operands are not the model's choice. Already so: `{duration}` is
        the downtime (onset to recovery, shown as the stretch every impact
        figure is measured over), `{held}` the response, `{errors_rise}` the
        rise.
  - [x] 6.24.4 The word channel closes: a number word with a unit ("twenty
        minutes") and ratio words ("tripled", "halved", "a third") are refused;
        a compound adjective ("one-minute buckets") is not. Counts of things
        ("about a hundred shoppers") stay free. The submit tool's example of a
        rough size moved off "about a third" (untested wording).
  - [x] 6.24.5 Numbers with units in the evidence get names, so they can be
        quoted. Every figure in a piece of evidence is named after its label
        and place (`{Gbac1.2}`, `{P1.1}`), shown so, checked and written in
        like the alert's (`prompting.figures_shown`); none is worked with.
  - [x] 6.24.6 Re-record the both-mode write-ups the final rules refuse (4 by
        a scan) with `record(mode='both') -- --postmortem-only`, which exists:
        the walk replays, only the postmortem call is live, under $1. grep and
        meaning sets are left for later. A full replay found 3 (13 other
        refusals were answered by a recorded retry): lead-mid-investigation
        ("two minutes"), upstream-dependency-failure ("a third"),
        flag-toggle-uncorroborated ("three times"). Re-recorded (~14.8k output
        tokens); full `both` replay then 55/55, no walk failed, none incomplete.
  - [x] 6.24.7 An instant a piece of evidence states can be worked with
        (`{T21.1 - T18.1}`): a real model asked for exactly that while
        re-recording and was refused.
- [x] 6.25 The Investigator's disproof may close a window whose rows stop
      before the alert's minute (lag never read there) - argus-00, inferred
      from code; needs a failing test first. Fixed: a flat window short of the
      alert's minute is read again (`METRICS_RECHECK_INTERVAL_SECONDS`, 15;
      `METRICS_RECHECK_MAX_WAIT_SECONDS`, 120) and, never reaching it, is
      investigated rather than called false; six unit tests, lifecycle replay
      green at a one-minute lag
- [x] 6.26 A re-fired alert's notification key is dropped for the new
      incident (`incident_reference` PK is (source, kind, value)), so a
      PagerDuty resolution reaches only the oldest incident. Fix: a
      notification key may have several holders (partial unique index); a
      person's resolution resolves every holder whose lifespan overlaps the
      PagerDuty incident's, never an older one; engagement takes the one
      PagerDuty incident under the key overlapping the Argus incident (several
      answer "could not say"), the adapter reading every page with
      `date_range=all`; a page several incidents share is disclosed in each
      write-up's assumptions. Integration test `test_a_refired_alert.py`, full
      replay 55/55
- [x] 6.27 A still-firing alert's reminder after an ending opens a new
      incident and a new paid walk (intake joins only non-terminal
      incidents). Fix: each alert's (fingerprint, startsAt) is recorded as a
      name; a notification joins an incident of any status holding one of its
      pairs for the same service - except `mitigated`, which a still-firing
      alarm contradicts, so it opens a new incident

## 7. Close

- [x] 7.1 `docs/spec-and-architecture.md` §7.6: the template
- [x] 7.2 Cleanup: comments, docstrings, jargon, logs and docs aligned; no test
      missing, redundant or weak; design and specs match what was built.
      Two reviews of the staged change: 11 stale comments fixed; 10 test gaps
      closed (each new test shown to catch its behaviour broken on purpose),
      one redundant test removed
- [x] 7.3 Module suites, typecheck, lint, guard_layering green (2026-10-14:
      27 modules, 720 files typed, 10 contracts kept)
- [x] 7.4 `e2e_replay(mode='both')` green, in the background (55 of 55,
      2026-10-14 23:03, no walk failed, no write-up incomplete)
- [ ] 7.5 Specs synced on archive
