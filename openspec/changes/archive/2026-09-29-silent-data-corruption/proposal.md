## Why

FM-26 silent data corruption is the largest family with nothing built in it, and
the first entry in the backlog chosen by share rather than by elimination -
foundational integrity is 12%, and every family above it is covered entire.

It is also the first mode Argus **cannot currently be told about at all**. Every
scenario so far announces itself in a series the detector already judges: an
error rate steps, a quantile climbs, a heap grows. Here nothing fails, no rate
moves, no quantile moves, the process is healthy, and the shop goes on reporting
itself well while what it writes is wrong. No alert rule fires, so no walk ever
starts.

That makes the mode a question about the shape of the system rather than about
the Investigator's judgement: what pages somebody when the only evidence is a
value, and what may Argus do about an answer it cannot check.

## What Changes

- **`FailureMode.SILENT_DATA_CORRUPTION`** - a ninth mode. What is wrong is
  neither the code's availability nor its speed but the correctness of what it
  has already written, and the damage outlives the change that caused it. Every
  other mode in the set ends when its condition ends; this one leaves a residue
  no mitigation reaches.

- **A data-integrity check in the Target Service, and the alert it fires.** The
  shop runs a scheduled job that re-adds each shopper's purchases and compares
  the sum to the running monthly total it stores. Where enough of them disagree
  it fires an alert of its own - a rule in the same monitoring stack, a payload
  in the same Grafana shape, and nothing about it browser-shaped.

- **The alert carries the onset.** Its summary names how many totals disagree,
  the largest gap, and **the oldest affected purchase** - which is the minute
  the bad writes began, read off the data rather than off the clock. The check
  runs weekly, so when it fired says nothing about when the fault started; the
  oldest disagreement is the only thing in the incident that does.

- **The finding rides in the alert rather than behind a read tool, and that is a
  decision rather than an economy.** A sixth retrieval channel would change the
  tool list every scenario's model sees, which makes every existing recording an
  answer from a model that never had it - a full re-record of eleven corpora at
  roughly five dollars each. Argus never needs to ask the check twice, because it
  is never going to act, so the one reading the alert carries is the whole
  channel.

- **An onset taken from the alert rather than measured from the metrics.**
  Today `find_onset` is asked of the retrieved buckets and a `None` ends the walk
  before a model is ever called, which is right for a window with nothing in it
  and wrong here: the metrics are flat *by construction* and the onset is a fact
  the alert already states. Argus SHALL accept an onset it was told, SHALL say in
  the opening message that no series corroborates it, and SHALL keep measuring
  the onset itself wherever the alert states none. **This is the one change on a
  path every existing scenario walks.**

- **`IncidentStatus.RECOMMENDED`** - a new terminal status, and a new way for a
  walk to end. Argus names the action and does not take it. That is not
  escalation, whose own definition is Argus running out of moves: here there is a
  move, and the reason to decline it is that the only thing that would confirm it
  is the next run of a weekly check. An action nobody can check is an action
  nobody should take autonomously, however confident the diagnosis - and an
  organisation that would not accept that from a person should not accept it from
  an agent.

- **Verification decides autonomy, and it is stated as a rule rather than as this
  scenario's exception.** Where the evidence that would confirm an action cannot
  arrive inside the verification window, the action is recommended and not taken.

- **A `silent-data-corruption` scenario in the Target Service.** A flag turns on
  a write path that records a purchase without adding it to the shopper's
  monthly total. `average_spend_per_item` recomputes from the purchases and stays
  right; `average_spend_per_item_this_month` reads the stored total and is
  quietly low. Nothing throws, so the error rate never moves; nothing waits, so
  no quantile does; and the account page renders a number that is wrong.

- **The flag case first, and the deploy case named as its sibling.** A flag can
  be put back a week later; a deployment a week old cannot be rolled back without
  discarding a week of work. So the flag is the version with an action worth
  recommending, and the deploy version - whose only response is a fix rolled
  forward - is a second scenario rather than a variant of this one.

- **Code-Fix proposes two files in one pull request**: the fix to the write path,
  and a one-off repair script beside it. The repair is named as owed and is never
  run - it rewrites data, which is irreversible and outside Argus's autonomy by
  construction (§13). It is Code-Fix's rather than a new agent's because it is a
  patch in the same repository, reached by the same tools.

## Capabilities

### New Capabilities

- `data-integrity-scenario`: the Target Service staging a monthly total that
  drifts from the purchases behind it - what its telemetry does and does not do,
  what the scheduled check compares, why the alert carries the oldest affected
  purchase, why a restart and a rollback are both refuted, and what a flag flip
  leaves behind.
- `alert-supplied-onset`: an onset stated by the alert rather than measured from
  the series - when it is accepted, what the opening message says about a minute
  no metric corroborates, and why a measured onset still wins wherever one
  exists.
- `unverifiable-action-recommendation`: the rule that an action whose
  confirmation cannot arrive inside the verification window is named and not
  taken, the `RECOMMENDED` status this ends an incident on, and what separates it
  from escalation.

### Modified Capabilities

- `investigator-cause-detection`: silent data corruption is a determinable mode,
  and the requirement says what evidence names it - a reconciliation finding with
  a date on it, a change history around that date, and a diff that shows a write
  path that stopped keeping two things in step.
- `incident-status-derivation`: `RECOMMENDED` is derived from a state in which an
  action was named and none was taken, and it is terminal.
- `code-fix-agent`: a fix may carry a second file that repairs what the fault
  already wrote, and the requirement says that Argus proposes that repair and
  never runs it.

The scheduled check and its alert rule are requirements of the first new
capability rather than deltas on `target-service-scenario-control`, which is
where the rollback, the cache scenario, the scale-out and the pin all put theirs.

## Impact

- `argus_core.models`: `FailureMode` a ninth value; `IncidentStatus.RECOMMENDED`
  and its place in `is_terminal`. 69 files reference `IncidentStatus`; about ten
  of them are source.
- `agent_investigator`: the onset accepted from the alert, the `None` branch that
  currently ends the walk, and the sentence the opening message gains about a
  minute nothing corroborates.
- `orchestrator`: a sixth `Refusal` - the action cannot be confirmed - with its
  own row sentence, plus a route and a terminal state for a named-but-untaken
  action. No new node: Mitigation names an action as it always does, and the
  tier gate is what declines to execute it, which is the step it already exists
  to be. The one departure from the other five refusals is where it goes - they
  reach for the next candidate, this one stops, because a second candidate would
  be as unconfirmable as the first.
- `agent_mitigation`: `SILENT_DATA_CORRUPTION` mapped to the existing
  `RevertFeatureFlag` strategy in `DEFAULT_STRATEGIES`, and nothing else. The
  mapping is required rather than optional: a mode with no strategy registered
  answers `None`, which is refused as *nothing answers this mode* and escalates -
  leaving no action for the gate to decline and no recommendation to carry. So
  Mitigation chooses the flag revert it would choose for any flag-caused
  incident, and what differs is only that nothing takes it.
- `agent_codefix`: a pull request carrying a repair script beside the fix.
- `argus_web`, `argus_narration`, `agent_postmortem`: `RECOMMENDED` rendered, said
  and written up - including what is still owed, which is the whole of what the
  status is for.
- `Argus-Demo-Target-App`: the scenario; the drifting total behind a flag; the
  scheduled check and the alert it fires; the console entry under a foundational
  integrity family, which the rail does not have yet; the commits the diff is
  read from, pushed before anything reads them.
- Recordings: one new `both-silent-data-corruption` corpus. Every existing
  corpus stays valid, because the tool list does not move - which is what the
  alert-borne finding buys.
- Evals: an Investigator case for the new mode, and a case asserting that an
  action is recommended rather than taken where nothing can confirm it.
- `docs/failure-modes-backlog.md`: foundational integrity gains its first built
  member, and the deploy-caused sibling is written down as what follows it.
