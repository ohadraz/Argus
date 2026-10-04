Every task that adds behaviour is preceded by its failing test. Tests under
`tests/`, `modules/*/tests/`, `argus_testkit` and either double are proposed in
chat for the user to paste - whole file, never a fragment.
`Argus-Demo-Target-App` is outside that rule and its tests are written directly,
after the code.

**The default is the conservative direction, and that is what makes the order
below safe.** An alert that says nothing about the kind of claim it makes is a
series claim, and `Findings` reports no disproof unless an investigation puts one
there. So every group up to 4 leaves every existing walk deriving exactly what it
derives today, and the one behaviour that changes changes in 4.

## 1. The claim an alert makes

- [x] 1.1 Add the typed field to `argus_core.models.Alert` saying whether the
      alert reports a condition measured on a series or a finding of the rule's
      own, with the series reading as the default - the value every alert that
      exists today has, and the one a monitoring stack saying nothing about itself
      almost certainly means. Named for what the rule looked at rather than for
      what Argus does with it
- [x] 1.2 Name the annotation key and its two values as `Final` constants in the
      module that reads them, not inline at the read site. They are a vocabulary
      two parties share - the shop's rules write them, `argus_web` reads them -
      and the shop's own copy is a separate declaration in a separate repo
- [x] 1.3 Read the annotation in `argus_web.grafana`, beside `onset`, mapping an
      absent or unrecognised value to the series reading. An unrecognised value is
      not an error: a rule from a stack nobody here configured is exactly the case
      the default exists for
- [x] 1.4 Set the annotation on the three rules in `Argus-Demo-Target-App` that
      carry findings of their own - the spend integrity check, the cache
      reconciliation, and the absence of readings. Two of them also state an onset
      and so never reach the branch this change adds; they set it anyway, because
      a rule describing itself should not depend on which other field it filled in

## 2. The disproof, in the investigation

- [x] 2.1 Add the typed field to `argus_core.models.Findings` reporting that the
      alarm was disproven, beside `readings_cover_the_incident` and for the same
      reason - only an investigation holds both halves, the alert's claim and the
      window. `None` by default, not a flag: a disproof carries its grounds, so
      the field is the evidence or it is absent. Appended last, after
      `readings_cover_the_incident`, so no existing field's position moves
- [x] 2.2 Carry the signals judged and the window judged over on the same
      reporting, so a disproof is reviewable. Both are in hand where the decision
      is made; a disproof that recorded neither could not be told from one made
      over a window too narrow to contain the condition
- [x] 2.3 Split the branch in `agent_investigator.investigation` that today
      returns `_nothing_to_say`. Where the alert reports a series condition, report
      the disproof; where it reports a finding of its own, open the conversation
      and investigate with no onset. The existing path for a window nobody could
      read is untouched - that one disproves nothing, and was split out from this
      same branch for the same reason. **Both new branches are gated on the window
      holding minutes, and that gate is load-bearing rather than defensive:** a
      series alarm over an empty window is disproved by nothing *and* anchored by
      nothing, so it falls through to where every undated incident already ended.
      The one time the second condition was missing, such a walk anchored on the
      alarm's own firing minute and investigated a service nothing had been read
      about
- [x] 2.4 Leave the departure arithmetic in `anomaly.py` alone. What counts as a
      departure is not what this change is about: it reads that arithmetic's
      answer and reports it differently. **What did change there:** the five
      series it judges now carry the names they are judged under, published as
      `THE_JUDGED_SIGNALS` and derived from the one declaration the accessors
      come from. A disproof has to say what it was made over, and the only other
      home for that list is the investigator - which would be the same fact in
      two modules, with the copy that drifted being the one no reader can check

## 3. The status

- [x] 3.1 Add `DISPROVEN` to `argus_core.models.IncidentStatus`, with the comment
      that distinguishes it from `ESCALATED` - an escalation hands over an
      incident nobody explained, this hands over nothing because the finding is
      that there was no incident. Not `REFUTED`: that word already means a
      mitigation attempt the evidence undid
- [x] 3.2 Derive it in the status function from the field added in 2.1, never from
      the undetermined candidate's reason string. A status derived from prose is
      one that changes when somebody edits a sentence
- [x] 3.3 Check the withdrawal override still wins over it, as it wins over every
      status the walk would derive. **It wins structurally rather than by
      precedence:** `narrating` asks whether the incident is still wanted before
      the node runs and returns `withdrawn` without deriving anything, so no
      ending the walk could derive reaches that question. The spec delta says so
      rather than asserting a precedence that does not exist
- [x] 3.4 Add the narration line for the ending, saying which condition the rule
      reported and that the judged signals held no departure

## 4. The walk's ending

- [x] 4.1 Reach the ending from the investigating step without passing through
      mitigating, and publish the transition as every other transition is
      published - so a timeline and a dashboard account for it with no special
      case
- [x] 4.2 Form no candidate, attempt no mitigation and seek no fix on a disproven
      alarm. The whole of the finding is that there was no incident
- [x] 4.3 Write the postmortem, as every ending does. What was ruled out is what
      the next responder needs, and here what was ruled out is the alarm - so the
      document names the condition the rule reported, what the judged signals held
      instead, and that the rule rather than the service is what to look at.
      **No change was needed:** the route out of the investigating node leads to
      remembering and then to the write-up, `postmortem_node` writes from the
      incident id alone, and the agent reads already-rendered timeline lines - so
      the disproof's narration line reaches the document as every other line does.
      Remembering is a no-op by its own rule, since nothing was tried
- [x] 4.4 Report a measured zero as zero in that document rather than leaving it
      absent, which is already reserved for a source that could not be reached.
      **Already true:** `loss_between` floors at zero and says in as many words
      that zero is a measurement rather than an absence, and `error_rates_over`
      returns `None` only where a side of the comparison is missing. A disproven
      incident has both sides and reports a rise of about nothing

## 5. What says so outside the walk

- [x] 5.1 Announce the ending in the war-room channel, and put the grounds in the
      thread. A message naming only the status would send a reader to a service
      Argus has established is well, so the node's narration - which is the whole
      reason the announcement gives - says that the alarm's own claim was not in
      the window. **The grounds are followed rather than announced,** which is a
      correction to the task as written: which signals were judged and over how
      long is the case for the ending rather than the ending, and every other
      finding's case is in the thread. The disproof event therefore needs an arm
      of its own in the policy - the wildcard would leave it unsaid, and a thread
      that jumped from an alert to a terminal status reads as the opposite finding
- [x] 5.2 Show the status on the dashboard. **The design's open question answered
      itself:** the view asks `is_terminal()` rather than naming statuses, so a
      disproven incident already lists and dates itself as an ending with no code
      at all. What was needed is the two colours - green and solid, like
      `resolved`: not dashed, because the dash is that page's mark for an ending
      with something owed and there is nothing, and not red, because a screen
      read from across a room must not show a well service in the colour of a
      failure

## 6. The case that changes

- [x] 6.1 Propose the e2e case for the ending in chat. **The task as written was
      wrong and the run is what proved it.** It assumed
      `test_firing_alert_with_no_cause_to_find_escalates_with_a_postmortem` was
      already staging this - no scenario seeded, a `HighErrorRate` alert, what
      reads like a well shop. An unseeded Target Service serves no metrics, so
      that window is empty rather than flat, and an empty window is an indication
      of nothing in either direction. That case therefore keeps `INVESTIGATING` →
      `ESCALATED` and only its name changed, to
      `test_an_alert_over_a_window_nobody_could_read_escalates_with_a_postmortem`.
      The disproof has a case of its own beside it in the same file, seeding
      `silent-data-corruption` for a window present and flat in all five judged
      signals and firing the suite's own plain alert, which states no onset and
      claims nothing about what it watched. Both pass
- [x] 6.2 Confirm no other green case reaches the branch, by reading rather than
      by running: `silent-data-corruption`, `cache-failed-over` and
      `monitoring-blind-spot` all have flat or absent windows and all state an
      onset, so all three take the branch that already exists for a stated onset.
      **Confirmed twice over:** all three also set the claim annotation, so even
      an onset gone missing would leave them on the branch that investigates
      rather than the one that closes. This is about each scenario's *own* alert,
      and 6.1's new case is not a counterexample: it borrows
      `silent-data-corruption`'s window and posts an alert of its own, which
      states no onset and sets no claim. The scenario's weekly check is never
      posted in that case, so neither of the two things keeping it off the branch
      is in play
- [x] 6.3 Re-record the e2e corpus only if a recording's own walk changes.
      **Nothing needs re-recording, checked against the corpus rather than
      assumed:** `both-no-evidence.json` holds a single answer and it is a
      `submit_postmortem` call, so today's walk for that case already asks no
      model in the investigation. The queue is unchanged. The opening message for
      a finding-carrying alert *did* gain a fourth onset paragraph, but no
      recorded case reaches it - the three finding-carrying scenarios all state
      an onset - so no recording's own walk moved

## 7. Verification

- [x] 7.1 `nox -s lint`, `typecheck`, `guard_layering`, `guard_e2e_boundary`
- [x] 7.2 `nox -s test_all` (19 suites, 1452 passed) and `integration` (8 passed)
- [x] 7.3 The demo app's own suite, after 1.4 - 591 passed
- [x] 7.4 `nox -s "e2e_replay(mode='both')"` in the background, reported as
      passed/failed/to-go with elapsed and measured ETA - 39 passed in 29m02s,
      against a 35.1 min baseline. Includes the disproof case end to end, which
      is what settled the two things reading could not: `silent-data-corruption`
      serves a window flat in all five judged signals and non-empty, and
      `both-no-evidence` covers a walk whose only model call is the postmortem.
      **Three earlier runs were red and no two on the same case** - the code-fix
      and rollout cases stalling in mitigation's verification for the full 1110s
      test timeout, and the blind-spot case failing an assertion whose text was
      never captured. All three pass alone, all three passed here, and a run of
      the first eight cases in suite order reproduced none of them (8 passed in
      10m49s). The diff is ruled out by a controlled pair - the two stalled cases
      alone, HEAD 181.60s versus the full tree 161.11s - so what remains is a
      flake this change uncovered rather than caused, recorded under "Known
      defects" rather than held against this change

## 8. The record

- [x] 8.1 Add the ending to the list in `docs/spec-and-architecture.md` of what an
      incident can end as, written as though the design had always said it
- [x] 8.2 Note in `docs/failure-modes-backlog.md` that the dateless-finding branch
      exists and what mode would use it, under "Measurements owed" or beside the
      FM-21 row that says the family is out of scope - the branch is not FM-21 and
      the doc should not read as though it were
