## Context

The Investigator has four channels: metrics, logs, changes, and the service
register. Three are windows over time; the register is a fact about how the
service is built. All four describe the *service*. None describes a *change* in
any detail beyond its own summary line - a kind, a moment, a reference, a
sentence.

That is enough for every cause in the taxonomy except one pair. A flag toggle
names its own flag and its own direction. A leak is visible in the metrics. A
dependency's failure is settled by the register. But a deployment that broke a
service has two readings in the vocabulary - `bad-deployment` and
`config-induced-failure` - and what separates them is inside the commit, which
nothing retrieves.

The attempt already in the working tree tried to answer it from what the change
channel has: Argo reports a `source.path`, so the deploy's summary now says
`deployed revision <sha>, from <path>`, and the mode's description tells the model
to read code-or-configuration off that path. It does not work, and it cannot: an
Argo source path is the directory holding a deployment's manifests. Both demo
scenarios ship from `deploy` - the one whose commit moved a port in
`deploy/values-production.yaml`, and the one whose commit changed
`src/io_shop/spend_summary.py`. The path is constant across the distinction it was
asked to make.

The fixture was built for the channel this change adds. `ScenarioDeploy` carries
`previous_revision` and says why in its own docstring: "a rollback is addressed to
a history entry, so the entry before this one has to be a real commit whose diff
against this one is the diagnosis". Both commits are real in
`Argus-Demo-Target-App`, and the diffs are one file each -
`deploy/values-production.yaml` for the cache case,
`src/io_shop/spend_summary.py` plus its test for the bad deployment.

## Goals / Non-Goals

**Goals:**

- The Investigator can ask what one deployment changed, naming a revision the
  change channel already put in front of it.
- The answer distinguishes a configuration change from a code change by showing
  what changed, not by classifying it.
- Both ends of the comparison are found server-side: the model names one
  revision, never two.
- A deployment that cannot be compared says so, and says it differently from a
  deployment that changed nothing.
- The cache-misconfiguration case reaches `config-induced-failure` from evidence.

**Non-Goals:**

- Classifying paths as "code" or "config". Which directories hold configuration
  is the deployed repository's business, and an adapter deciding it is wrong the
  first time somebody keeps values beside source.
- Extending this to flag toggles. A flag change has no commit and no diff; asked
  about one, the channel says so.
- Comparing arbitrary pairs of commits. This answers about a deployment, and the
  base is whatever was deployed before it.
- Code-Fix's retrieval. It reads the repository at a ref through its own tools and
  is unchanged.

## Decisions

**The channel is keyed to a revision, not to a window.** Every other windowed
channel exists because the interesting span is the model's judgement. Here there
is nothing to widen: a deployment changed exactly what it changed. The argument is
the `reference` of a `ChangeEvent` the change channel served, which makes the two
channels compose - read what changed, then read what one of those changes
contained - and means the model never has to hold two revisions at once.

*Alternative considered:* take two revisions and let the model name both. Rejected:
the previous revision is in Argo's history, which the model cannot see. It would
have to be guessed, and a comparison against a guessed base is a diff of the wrong
thing that reads exactly like a diff of the right one.

**The base revision comes from Argo's history, on the server.** Argo returns an
application's whole revision history; the entry before the named one is the
revision that was running before it. The read tier already holds that connection
for the change channel.

*Alternative considered:* the commit's own parent, from the repository. Rejected:
a deployment is not a commit, it is a state change between two deployed states.
Several commits can land between two syncs, and the parent would then describe a
fraction of what the deployment actually shipped.

**The answer carries each file's patch, not only its path.** A path list is the
cheaper answer and the one `paths_changed_between` already gives, but
`deploy/values-production.yaml` still leaves the model inferring configuration
from a directory name - which is the inference that just failed. A patch showing
`port: 6379` becoming `port: 6380` is evidence rather than a cue.

*Alternative considered:* paths only. Rejected on the measured failure above. The
patch is what makes the answer self-evidencing, and it is also what a later
mitigation or postmortem quotes.

**Bounded in two places, and the bound is said in the answer.** GitHub's compare
API lists at most 300 files and gives no flag when it stopped there, which
`paths_changed_between` already refuses to read as complete. A patch adds a second
bound: one deployment can be a formatting sweep, and a channel that returns it
whole would spend a turn's entire context. So a per-file patch is truncated at a
configured size, the number of files is capped, and whatever was left out is
stated - because a diff silently shortened is a diff the model reads as the whole
change.

**No `Reading` and no new `RetrievalChannel`.** `Reading` records which minutes are
already in front of the model, and this channel has no minutes. The register
channel set that precedent for the same reason. The consequence is that asking
twice about one revision is not refused - accepted, because the alternative is
either a `Reading` whose window fields are both null and whose identity is really
a revision, or a second kind of memory in the dispatcher. If repeats show up in a
recording, the fix is a revision-keyed refusal in the channel, not a window.

*Consequence:* `channels_unread` will not report this channel, exactly as it does
not report the register. That is consistent rather than an omission - it answers
"which windows were never read", and there is no window here to leave unread.

**`repository_source` gains a second comparison reader rather than a flag on the
existing one.** `paths_changed_between` answers a catch-up pass's question - what
must be re-embedded - and returns `None` for "I cannot say". This answers an
investigation's question and needs per-file content, a different failure story, and
a different bound. One function with a `with_patches` switch would be two functions
sharing a signature.

**The bound lives at the read tier, not in `repository_source`.** The repository
reader answers what changed; the tool composes the answer a model reads and is
where "and more, not listed" already lives for `search_repository`. The
configuration for the tier lives there too. So `repository_source` returns every
file the comparison listed with its patch, and the tool decides how much of that
one turn can afford.

**The service's source scope must not be applied here.** `github_source_paths`
narrows `search_repository` and the index to the directories holding the service
itself, which is right for reading code and inverting for this. It is
`src/io_shop,tests/io_shop` in every deployment of the demo, and the cache
scenario's whole diagnosis is `deploy/values-production.yaml` - outside it. A
scoped comparison would answer that the deployment changed nothing, which is not a
weaker answer than the truth but its opposite, and the model would rule the
deployment out. Configuration a deployment ships lives outside the source tree by
definition, so this is general rather than a quirk of one fixture.

**The mode's description says what to read, not what to conclude.** The withdrawn
sentence told the model where to look and named the wrong place. Its replacement
names the channel: what separates the two is what the deployment changed, and
there is a tool that answers it.

## Risks / Trade-offs

- **The channel is offered and the model does not call it** → `BRIEF` and the
  `config-induced-failure` description both point at it, and the mode's own
  description is what a model reads when weighing the pair. If a re-record shows
  it unread, the next lever is the change channel's own answer saying that a
  deploy's contents are readable - a cue at the point the revision is in hand.
- **The patch is read and the model still prefers `bad-deployment`** → this is the
  argument the last paid walk actually made: an optional cache merely unreachable
  should not cost 160ms, so something must be blocking on it. A diff touching no
  source file answers it directly - there is no new code to block - but only if the
  model treats "no source file changed" as decisive. The eval case for the pair
  should assert the answer, not the reasoning, and one paid sample is not the
  claim being proven.
- **Every Investigator recording is invalidated** → known and priced. The tool list
  is part of the prompt digest by design, so this is the mechanism working. `both`
  is the mode `grade_fixes` and the red e2e case need; `grep` and `meaning` are
  refreshed only if retrieval modes are compared again.
- **A repository the read tier cannot reach** → the same failure the source
  channels already have, reported as a channel that could not be read rather than
  as a deployment that changed nothing. "Nothing changed" is a conclusion something
  acts on.
- **A revision with no predecessor in the history** → a first deployment, and a
  real answer: there is nothing to compare it against. Said as that, not as an
  empty diff.

## Migration Plan

1. Land the channel with every free check green - `lint`, `typecheck`,
   `guard_layering`, module suites, `guard_recordings`.
2. Revert the false discriminator in the same change, so no commit ever carries an
   instruction that was measured not to work.
3. Re-record `both` against the real API, confirm the cache case answers
   `config-induced-failure`, and run `e2e_replay(mode='both')` green.
4. `grep` and `meaning` corpora follow only if their modes are needed.

Rollback is the commit: the channel is additive, and removing it restores the
four-channel tool list - which invalidates the recordings again, so a rollback
costs a re-record too.

## Open Questions

- What per-file patch size, and what file count, is the right bound? A figure
  picked here would be guessed; the first paid recording of the cache case is what
  says whether the answer read comfortably or crowded the turn.
- Should the change channel's own answer mention that a deploy's contents are
  readable? It is a cue at the moment the revision is in hand, and it is also one
  more sentence in a channel that is answered many times per investigation.
