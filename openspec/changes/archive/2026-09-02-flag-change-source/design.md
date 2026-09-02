## Context

Spec §16 says the three retrieval channels live in `argus-read-mcp`, and §12.1 says why:
autonomy tier is a property of the server, so a process that only reads is a process
that cannot mutate, and that is checkable from the outside. One change source per change
type - deploys from Argo CD, flag flips from the flag provider's audit log.

The flag half of that could not be built as written.

## The gap the provider imposes

Unleash serves its event history at `/api/admin/events`, and only to an **admin** token.
The evaluation token the read tier holds is refused: `403 invalid token: expected a
different token type for this endpoint`. There is no scope between the two - Unleash's
token types are client, frontend and admin, and reading history requires the last of
them, which is also the one that can create, archive and toggle flags.

So the source Argus wants to read is reachable only with a credential that can write. A
design that puts every read in the read tier and every credential-that-can-write in the
write tier has no placement for it.

## What was considered

**Give `argus-read-mcp` an admin token.** Rejected outright. It would put a flag-mutating
credential inside the process whose entire claim is that it cannot mutate, and the claim
is what §13's guardrails and every approval gate rest on. A boundary that holds only
because the code inside it chooses not to make a request is not a boundary.

**Have the read server call the write server.** Rejected. It makes the read tier depend
on the write tier at runtime, so the read path fails when the write path is down, and it
buries a tier crossing inside a server rather than leaving it visible at the caller.

**Proxy the history through Argo-style polling into a store of our own.** Rejected as
disproportionate: a background sync, its own storage and its own staleness window, to
avoid one call.

**Read it through the write tier's client, and merge at the caller.** Chosen.
`write_mcp_client.get_recent_flag_changes` already exists - Mitigation uses it to learn
which flag an incident is about - and it is read-only. The Investigator calls it beside
`read_mcp_client.get_change_events` and merges the two into one history.

## Why this bends placement and not the boundary

The claim the tier split makes is *the read process cannot mutate*. That is untouched:
`argus-read-mcp` gains no credential and no new call.

What moves is where one read lives. The write tier can already change a flag, so being
able to read what changed is strictly less than it could do a moment ago - no privilege
is created by asking it. The failure this arrangement admits is availability, not
authority: if the write server is down, the Investigator loses the flag half of the
change channel, and it loses it loudly, because an unreachable change source raises
rather than reporting nothing.

Merging at the caller rather than in either server keeps both servers ignorant of each
other. `fetch_change_events` is one seam to the loop above it whichever systems answered,
which is the same property the read server's own multi-adapter change source has.

## Decisions

- **The far end of the window is applied by the caller.** The provider takes a `since`
  and nothing else, so a toggle after the window closes would otherwise be offered as a
  possible cause of an incident that began before it.
- **A flag toggle carries the flag's own name as `reference`.** Mitigation acts on that
  name; a name Argus invented identifies nothing.
- **The actor is carried across.** Argus writes under a credential of its own, and the
  actor is what tells its own revert from a human's - which is what stops it offering its
  own action as a cause of the incident it was acting on.
- **The summary states the direction in words.** Both directions are real - a feature is
  put back by switching it off, a withdrawn fallback by switching it on - and "the flag
  changed" leaves the model unable to say which state is now in effect.
- **A flag history that cannot be read fails the investigation**, exactly as the deploy
  source does. "Nothing changed" is a conclusion something acts on.

## Replay

One `get_changes` entry in `REPLAY_LOG` now stands for two calls out of the process. The
entry records what the model was shown - the merged history - which is the level a replay
is wanted at. Per-source rows would be a different granularity and are not part of this
change.
