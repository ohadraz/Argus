## Why

Propagation is 28% of the published taxonomy and Argus covers half of it.
`upstream-dependency-failure` is FM-01, where the failing dependency belongs to
another company and the only honest outcome is to name it and hand it over.
FM-23 is the other half and the more common one: the dependency is a service
**you own**, nobody remembered it was on the request path, and there is
something Argus can do about it. Closing it closes the family.

It is also the first incident where the thing to act on is not the thing that
was paged. Every strategy today takes the subject from the alert -
`RestartService(service=service)`, `RollBackDeployment(application=service)` -
because until now the alerting service and the faulty service have always been
the same one. FM-23 is the case where they are not, and it is the whole of the
difficulty: Argus has to name a service it was not paged about, and be able to
defend touching it.

## What Changes

- **A new failure mode, `internal-dependency-failure`.** The alerting service is
  well; a service it calls, and which the same organisation owns, is not.
  Distinct from `upstream-dependency-failure` in exactly one thing, and it is
  the thing that decides the response: who owns the dependency. A reader
  distinguishes them, which is the test a mode has to pass.
- **No new action kind.** The answer is a restart, aimed elsewhere.
  `RestartService` already carries the service it addresses; what is missing is
  a way for that service to come from the investigation rather than from the
  alert.
- **A hypothesis may name the service at fault.** A new typed field, separate
  from `subject`, because `subject` is the model's *description* of what went
  wrong and this is an **address** - something a platform call is sent to. The
  distinction is the one the restart strategy's docstring already argues: "kuki
  heap (memory_used_bytes / heap of 2048MiB limit)" is a description, and a
  restart sent to it asks a platform about a resource nobody has.
- **A service catalogue, read like any other evidence.** A new read tool
  answering what a service calls and who owns each of them. It is the channel
  this failure mode is diagnosed from - the coupling is hidden precisely because
  nobody reads the catalogue until an incident - and it is also what separates
  FM-23 from FM-01 when the telemetry does not.
- **The gate gains a second question, and keeps the first.** Membership of the
  closed set of generic mitigations stays a property of the *kind*. What is new
  is that an action addressed to a service outside the alerting service's own
  owned dependencies is refused whatever its kind: the catalogue bounds what
  Argus may touch, so a model naming a third party, or naming prose, cannot get
  a restart sent to it.
- **The restart reaches a second service.** The platform resource a restart
  names is derived from the service rather than configured once as `io-shop`,
  and the process-start time a restart is confirmed by is read per service -
  otherwise restarting the dependency would be confirmed by watching the shop.
- **A new scenario, `pricing-service-degraded`.** The demo app grows a second
  internal service of its own on the account page's path, which degrades into
  slowness while the shop stays correct, and which a restart puts right.
- **An e2e case**, rehearsed free on fabricated answers, then recorded once
  against the real API so it replays.

## Capabilities

### New Capabilities
- `internal-dependency-scenario`: the demo app's second service, what puts it on
  the request path, what its degradation does to the shop's telemetry, what the
  shop's own log lines attribute to it, and that a restart of the dependency -
  and nothing else - ends it.
- `service-dependency-catalogue`: what a service calls, who owns each
  dependency, and how that reaches the Investigator as typed evidence rather
  than as prose.
- `dependency-restart-mitigation`: the mode, the strategy that answers it by
  restarting the service the hypothesis names, the address the hypothesis
  carries, and the refusal when that address is not an owned dependency of the
  alerting service.

### Modified Capabilities
- `generic-mitigation-tier`: autonomy gains a second condition - the kind is
  admitted *and* the subject is within the blast radius the catalogue defines.
  The existing requirement is unchanged in what it says about kinds; what is
  added is that an admitted kind addressed outside that radius is still refused,
  and that the refusal says which of the two failed.
- `restart-mitigation`: the service restarted is not necessarily the one the
  alert names, so the platform resource and the process-start observation are
  both derived from the service being restarted.
- `investigator-cause-detection`: an internal dependency's failure is a
  determinable cause, and determining it obliges the hypothesis to name which
  service - a mode of this kind without an address is not a diagnosis anything
  can act on.

## Impact

- `argus_core.models`: `FailureMode.INTERNAL_DEPENDENCY_FAILURE` and its
  meaning; the address field on `Hypothesis`; the catalogue's own type, which is
  a contract two modules name and therefore belongs here.
- `agent_mitigation`: the new strategy and its registration; `admitting` for the
  blast-radius question; the refusal's wording.
- `agent_investigator`: the answer tool's schema and the prose that tells the
  model when an address is required.
- `read_mcp_server` / `read_mcp_client`: the catalogue tool and its typed client
  function.
- `write_mcp_server`: the restart's resource name and the process-start
  observation, both per service.
- `argus_narration`: the sentence said about restarting something other than the
  service the incident is about - a reader must not be left thinking the shop
  was restarted.
- Revision `001` of the schema, edited in place, for the hypothesis's new column
  and the persisted mode value; no migration, since the schema is applied by
  dropping it.
- `Argus-Demo-Target-App`: the second service, its telemetry and process clock,
  the catalogue endpoint, the scenario, and the demo suite covering the new code
  after the fact.
- `docs/spec-and-architecture.md` §7.3 and §13, and the backlog's propagation
  row.
- One paid `record` run, for the new e2e case only.
