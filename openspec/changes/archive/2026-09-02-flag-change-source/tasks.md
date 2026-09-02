## 1. The change kind

- [x] 1.1 Add `FLAG_TOGGLE` to `ChangeKind`, beside `DEPLOY`. The two stay separate
      because what follows differs: a toggle has a reversible action behind it and a
      deploy does not.

## 2. The second source

- [x] 2.1 Add `argus-write_mcp_client` as a workspace dependency of `agent_investigator`,
      with the reason stated where it is declared - the provider serves its history to
      admin credentials only.
- [x] 2.2 Give `fetch_change_events` both histories as default-argument seams, and merge
      them into one list in time order.
- [x] 2.3 Map a `FlagChange` onto a `ChangeEvent`: the flag as `reference`, the direction
      spelled out in the summary, the actor carried across.
- [x] 2.4 Apply the window's far end at the caller - the provider takes a `since` and
      nothing else.
- [x] 2.5 Let a flag history that cannot be read raise, as the deploy source does.

## 3. Tests

Under the TDD policy these are proposed in chat and added by the human.

- [x] 3.1 A toggle arrives as a `FLAG_TOGGLE` change naming the flag.
- [x] 3.2 The direction is stated both ways, so a summary hardcoded to one of them fails.
- [x] 3.3 A deploy alone still comes through untouched - the case a second source is most
      likely to break.
- [x] 3.4 Deploys and toggles arrive as one history in time order.
- [x] 3.5 A toggle past the window's end is not offered.
- [x] 3.6 The flag history is asked about the window it was given.
- [x] 3.7 The actor the provider named survives into the change.
- [x] 3.8 A flag history that cannot be read fails the investigation.

## 4. Documentation

- [x] 4.1 State in §16 that a provider serving history only to a write-capable credential
      is read through the write tier, and why that bends placement rather than the
      boundary.
