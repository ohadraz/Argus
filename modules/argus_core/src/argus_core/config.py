from __future__ import annotations

from functools import lru_cache
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from argus_core.models.code_search import CodeSearch
from argus_core.models.model_policy import DEFAULT_EFFORT, DEFAULT_MODEL, Effort

# The longest single wait inside a walk: Mitigation standing by for the service
# to answer an action. Named here because two settings are stated in terms of
# it - the wait itself, and the lease that has to outlast it.
_VERIFICATION_TIMEOUT_SECONDS: Final = 180.0

# How many of those waits a claim survives before another worker may take the
# run back. More than one, because a walk can verify more than one action; small
# enough that a worker killed mid-walk does not leave its incident sitting for
# an hour.
_LEASES_PER_LONGEST_WAIT: Final = 4


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_user: str = Field(default="argus")
    database_password: str = Field(default="argus")
    database_host: str = Field(default="localhost")
    database_port: int = Field(default=5432)

    target_service_url: str = Field(default="http://localhost:8080")

    read_mcp_host: str = Field(default="localhost")
    read_mcp_port: int = Field(default=8090)

    # The feature-flag provider, read side. This credential can evaluate flags
    # and cannot change one, which is what makes `argus-read-mcp` incapable of
    # mutation rather than merely disinclined (spec §13, §14). The admin
    # credential belongs to `argus-write-mcp` alone and is not read here.
    unleash_base_url: str = Field(default="http://localhost:4242")
    unleash_frontend_token: str = Field(
        default="default:production.argus-demo-frontend-token"
    )
    # Which project and environment a flag change addresses. Read-side calls
    # need neither - the evaluation credential is already scoped to one
    # environment - but the admin API names both in its path.
    unleash_project: str = Field(default="default")
    unleash_environment: str = Field(default="production")
    # The credential that can change a flag. `argus-write-mcp` holds it and
    # `argus-read-mcp` is issued none: the tier boundary is enforced by which
    # process possesses which secret, not only by which code paths exist
    # (spec §13, §14). Empty by default so a misconfigured write server fails
    # loudly rather than silently authenticating as nobody.
    unleash_admin_token: str = Field(default="")
    # The name the provider attributes Argus's own flag writes to - the username
    # on the credential above, seeded by the Target Environment's compose file
    # and matched here exactly. It is what lets a change Argus made be told from
    # a change a human made, so that a later look at "what recently changed"
    # does not offer Argus its own action as a cause. Empty switches that
    # filtering off, which is the honest setting for a deployment where Argus
    # and its operators share one credential and the distinction cannot be made.
    unleash_actor: str = Field(default="Argus")

    write_mcp_host: str = Field(default="localhost")
    write_mcp_port: int = Field(default=8092)

    # The Target Service's repository, which is the only repository Argus may
    # propose a change to (spec §15.1). Named in full - `owner/name` - because
    # that is how the API addresses one, and because a deployment that had to
    # assemble it from two settings could assemble a different one.
    github_api_url: str = Field(default="https://api.github.com")
    github_repository: str = Field(default="")
    # The branch a fix is cut from and proposed onto - the one that is actually
    # deployed, since a fix against anything else patches a repository nobody
    # is running.
    github_base_branch: str = Field(default="main")
    # What one attempt at a fix may spend. Three bounds rather than one, for
    # the reason the investigation has three: they fail differently and none
    # implies the others, and this is the agent a call count alone cannot
    # bound. It reads whole files and writes whole files, so a run can be
    # frugal in calls and ruinous in tokens - a run that reads the three
    # largest files in the Target Service carries 47,950 tokens of source for
    # every remaining turn, which at twelve turns is most of a six-figure
    # bill nothing was counting.
    #
    # Calls rather than turns, because a model may ask for several files at
    # once and a bound counting turns would let it read several times what it
    # was allowed while still looking healthy. Never expressed to the model:
    # one it could ask to extend would not be a bound (spec §9).
    codefix_max_tool_calls: int = Field(default=12, gt=0)
    # Larger than the investigation's, because what this agent reads is source
    # rather than windows of metrics, and it carries every file it has read
    # for the rest of the run.
    codefix_max_tokens: int = Field(default=400_000, ge=1)
    # Longer than the investigation's, and for the opposite reason to the
    # bound above: nobody is waiting on this one. The incident is already
    # mitigated by the time Code-Fix runs, so what this protects is the
    # worker's own progress rather than a human's patience.
    codefix_max_seconds: float = Field(default=600.0, gt=0.0)
    # Which ways of finding code this deployment has: `grep`, `meaning` or
    # `both`. It decides more than what Code-Fix is offered - `grep` builds no
    # index, opens no vector store and registers no retrieval tool, so a
    # deployment that will not use RAG does none of that work rather than
    # doing it for nobody.
    #
    # `both` is the production setting. The model is handed both tools and
    # picks per question, which is the choice it is best placed to make: a
    # cause with a name is found faster by grep, and one that only has a
    # description is found at all by meaning.
    #
    # The single channels are for the benchmark (§21). Comparing two
    # retrievers means running each alone over the same incidents, which is
    # only a comparison if the choice can be taken away from the model.
    code_search: CodeSearch = Field(default=CodeSearch.BOTH)
    # The credential `argus-read-mcp` reads the Target Service's source with. It
    # can read a repository and cannot push to one, which is what lets the
    # source be read from a process that must remain incapable of mutation
    # (§13) - the same argument that keeps the flag evaluation token there and
    # the admin token out.
    github_read_token: str = Field(default="")
    # Which directories of that repository hold the service itself, comma
    # separated. Empty is the whole repository, and is right whenever the
    # repository is nothing but the service.
    #
    # The demo's is not: `Argus-Demo-Target-App` ships the shop beside the rig
    # that stages incidents against it, and a fix agent reading the rig is
    # reading how its own incidents are generated. A real deployment points
    # Argus at a service repository and leaves this empty.
    github_source_paths: str = Field(default="")
    # The credential that can push a branch and open a pull request. Scoped to
    # the repository above and to nothing else: "Argus cannot touch its own
    # codebase" is a property of what this token reaches, not of what the agent
    # was told (§15.1). Empty by default for the same reason the admin token is
    # - a misconfigured write server should fail loudly rather than quietly
    # authenticate as nobody. It can never merge what it opens (§13).
    github_token: str = Field(default="")
    # The secret GitHub signs its push deliveries with, so Argus can tell a
    # push from anybody who found the endpoint. Empty accepts nothing rather
    # than everything: with no secret configured no signature can match, which
    # is the right way round for a route open to the internet.
    github_webhook_secret: str = Field(default="")

    # Where that repository's source is kept as something searchable by
    # meaning, and under what name. A store of its own rather than a table:
    # what it answers is "which passages are nearest this one", and no amount
    # of SQL makes that a cheap question.
    #
    # Localhost by default, which is the developer's compose file; the
    # deployment names the service. Qdrant's HTTP port, not its gRPC one -
    # nothing here asks for gRPC.
    qdrant_url: str = Field(default="http://localhost:6333")
    # One collection per deployment, named for what it holds rather than for
    # the repository: the index describes the Target Service's source, and a
    # deployment pointed at a different repository is a different index.
    code_index_collection: str = Field(default="target_service_source")
    # How often the catch-up loop looks. A bound on how long the index may
    # describe yesterday's code while nobody is telling it otherwise, rather
    # than a performance knob: where a push delivery arrives the gap closes on
    # the next pass anyway, and where none ever arrives - no tunnel, a webhook
    # nobody configured - this interval is the whole of what keeps the index
    # honest.
    code_index_interval_seconds: float = Field(default=60.0, gt=0.0)
    # Which model turns a passage of code - and a question about it - into the
    # vector whose closeness is the whole of what "found by meaning" means.
    # Configured rather than fixed because it is the one hypothesis the §21
    # benchmark cannot test any other way: if retrieval by meaning
    # underperforms, "the model is small" is answered by naming a different one
    # here and indexing again.
    #
    # Changing it is a re-index, not a restart. The width of the collection and
    # the meaning of every stored vector both follow from the model, so points
    # embedded by the old one answer nothing sensible to a query embedded by the
    # new.
    code_index_embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    # How a file whose structure nothing here understands is cut into passages,
    # in lines, and how many lines of each window the next one repeats. The
    # overlap is what keeps a fault straddling a cut whole inside one passage.
    #
    # These govern the fallback only. Python is cut at its own definitions,
    # because a function is as long as it is and one truncated to fit a window
    # is a passage that stops mid-statement.
    code_index_max_lines: int = Field(default=60, gt=0)
    code_index_chunk_overlap: int = Field(default=10, ge=0)

    # Long-term memory: what earlier incidents were done about (spec §11.2).
    # The same Qdrant as the index above, in a collection of its own - two
    # corpora with nothing to do with each other, and one server.
    incident_memory_collection: str = Field(default="incidents_remembered")
    # Whether an incident is remembered at all, and whether what is remembered
    # is consulted. Off is a real configuration rather than a way of disabling a
    # broken feature: the §21 benchmark's whole question is what memory is
    # worth, and two runs that differ in exactly one thing are how it is asked.
    incident_memory_enabled: bool = Field(default=True)
    # Which model turns an incident's description into the vector a later
    # incident is compared against. A different corpus from the index's, so a
    # setting of its own - and changing it, like changing the index's, means
    # everything already stored answers a new query nonsensically.
    incident_memory_embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    # How many past incidents inform one ordering decision, and how unlike this
    # one a record may be and still be consulted.
    #
    # Both are starting guesses, stated as plainly as the anomaly thresholds
    # were before any incident had been measured. The floor is the one that
    # matters: a nearest-neighbour search always answers, so without it a corpus
    # holding one unrelated incident hands it back as the nearest thing it has,
    # and a candidate is demoted on the strength of it.
    incident_memory_recall_limit: int = Field(default=5, gt=0)
    incident_memory_similarity_floor: float = Field(default=0.5, ge=0.0, le=1.0)

    log_initial_lookback_minutes: int = Field(default=30)
    log_initial_lookahead_minutes: int = Field(default=10)
    # Ceiling on any log window. Widening is how a reasoning caller reaches an 
    # onset that predates its window; this stops that widening from degenerating 
    # into a full-log dump.
    log_max_window_minutes: int = Field(default=180)

    # Metrics are pre-aggregated - one minute is four numbers - so the summary
    # is fetched at one fixed, wide span rather than iterating. Expected to be
    # wider than the log ceiling: seeing an onset Argus cannot afford to read
    # logs for is a useful answer ("onset predates my log budget"), where not
    # seeing it at all is a silent miss.
    metrics_window_minutes: int = Field(default=360)

    # How far back Mitigation looks for the flag change an incident is about.
    # Far shorter than `change_lookback_minutes`, and deliberately so: that one
    # asks "how far back may a cause plausibly lie" for an investigation, where
    # this asks "what did someone just change" about an incident happening now.
    # Widening it makes an ambiguous environment - two flags changed, so no
    # action - the common case rather than the exception.
    flag_change_lookback_minutes: int = Field(default=60, gt=0)

    # How long Mitigation waits for the service to answer an action before
    # calling the hypothesis refuted. Expiry is a verdict, not an error: the
    # action was taken and did not visibly help in the time allowed, which is
    # what refuted means. Long enough to cover at least one whole metric minute
    # plus the lag before the service's behaviour changes.
    mitigation_verification_timeout_seconds: float = Field(
        default=_VERIFICATION_TIMEOUT_SECONDS, gt=0.0
    )

    # How often one incident may apply one kind of mitigation to one subject.
    # The control a repeatable mitigation needs: a restart can be taken again
    # and again, each one buying a few minutes, and a restart loop is the
    # failure mode operators actually guard against. One by default, and low on
    # purpose - a second attempt on a subject the first did not fix is a
    # hypothesis the evidence has already answered, and the walk has other
    # candidates to spend its time on.
    mitigation_attempts_per_subject: int = Field(default=1, gt=0)

    # How long a worker waits before asking the queue again, having found it
    # empty. The wait a real alert pays before anything starts on it, so it is
    # short - and it is only paid when there is nothing to do, since a worker
    # that found work looks again immediately.
    run_poll_interval_seconds: float = Field(default=2.0, gt=0.0)

    # How long a claim holds a run before another worker may take it back. A
    # worker renews this while it walks, so it bounds how long a *stopped*
    # worker's run sits unwalked - not how long a run may take.
    #
    # Comfortably longer than the longest single wait inside a walk, which is
    # Mitigation's verification: a lease that expired while a worker sat
    # waiting for a service to recover would hand the same incident to a second
    # worker at exactly the moment the first was about to answer.
    run_lease_seconds: float = Field(
        default=_VERIFICATION_TIMEOUT_SECONDS * _LEASES_PER_LONGEST_WAIT, gt=0.0
    )

    anthropic_api_key: str = Field(default="")

    # Where the Anthropic SDK sends its requests. Empty means the real API.
    # Pointing this at the test double is the *only* thing that selects it:
    # the seam sits below the SDK, so the real adapter, the real
    # `messages.parse` and the real schema transform still run.
    anthropic_base_url: str = Field(default="")

    # Which model answers each agent, and how hard it is asked to think.
    #
    # Per agent rather than once, because the agents are not the same shape of
    # work. The postmortem writes one piece of prose with every figure already
    # measured and no tools to explore; the investigator runs a tool loop whose
    # whole judgement is which evidence would settle the question; Code-Fix is
    # agentic coding, where the higher efforts earn their cost. A single level
    # across the three is wrong for at least one of them, and which one is not
    # knowable from here - it is a thing to measure against the eval, which is
    # why these are configuration rather than constants.
    #
    # `high` is what every agent used when there was one setting for all of
    # them, and is also the API's own default, stated rather than relied on.
    # It is still right for two of the three.
    investigation_model: str = Field(default=DEFAULT_MODEL)
    investigation_effort: Effort = Field(default=DEFAULT_EFFORT)
    codefix_model: str = Field(default=DEFAULT_MODEL)
    # Code-Fix is the exception: its answers are whole files, which is the
    # workload where a higher effort earns its cost rather than merely costing
    # more. A deployment that wants it cheaper still says so.
    codefix_effort: Effort = Field(default="xhigh")
    # How much room one fix gets to be written in. Alone among the agents
    # Code-Fix answers with whole files, and the largest in the Target
    # Service is 21,484 tokens - so the 16,000 every other agent is happy
    # with makes a whole class of fix impossible rather than tight, and no
    # retry helps because the same request overflows the same ceiling every
    # time. Past 21,333 the answer is streamed, which is the only way the
    # SDK will carry one that large; 128,000 is the model's own ceiling and
    # a ceiling is not a reservation, so asking for all of it costs nothing
    # for the fixes that turn out to be small.
    codefix_max_output_tokens: int = Field(default=128_000, gt=0)
    postmortem_model: str = Field(default=DEFAULT_MODEL)
    postmortem_effort: Effort = Field(default=DEFAULT_EFFORT)

    # The bot the Communicator posts as. Empty by default, and empty means it
    # says nothing: a workspace nobody configured is not a workspace to guess
    # at, and an incident is reported through a channel somebody chose.
    slack_bot_token: str = Field(default="")

    # Where the Slack SDK sends its requests. Empty means the real workspace,
    # for the reason `anthropic_base_url` works that way: pointing this at the
    # double is the only thing that selects it, so the real adapter, the real
    # client and the real argument encoding still run in every suite.
    slack_base_url: str = Field(default="")

    # Where an incident is reported and where its postmortem is delivered. Two
    # channels rather than one: an incident's traffic is for whoever is on, and
    # a postmortem is read afterwards by people who were not.
    slack_war_room_channel: str = Field(default="")
    slack_postmortem_channel: str = Field(default="")

    # How long the relay waits after finding the log unchanged. Short, because
    # it is the delay between something happening and a person hearing about
    # it - and paid only when there is nothing to say, since a pass that
    # delivered anything looks again at once.
    slack_relay_poll_seconds: float = Field(default=2.0, gt=0.0)

    # Where Argus answers, as somebody outside it reaches it - what a message
    # in a channel links back to. Configured rather than observed, as it is for
    # everything that links into itself: the relay never serves a request to
    # learn a host from, and behind a proxy the host a request arrived on is
    # not the one a reader can click anyway. Empty means a message carries no
    # link, which is a demo without one rather than a broken one in a channel.
    argus_base_url: str = Field(default="")

    # The credential the payment provider is read with. Empty by default, and
    # empty means the source reports that it could not answer: a postmortem
    # resting on money nobody can vouch for is worse than one saying the figure
    # is missing, and a default credential would be one nobody chose.
    stripe_api_key: str = Field(default="")

    # Where the Stripe SDK sends its requests. Empty means the real API.
    # Pointing this at the shop's own Stripe-shaped endpoint is the only thing
    # that selects it: the seam sits below the SDK, so the vendor's request
    # building, paging and object model all still run.
    stripe_base_url: str = Field(default="")

    # The credential the on-call provider is read with. Empty by default, for
    # the reason the payment credential is: a response time nobody can vouch
    # for is worse than one the document says it could not obtain, and a
    # default credential would be one nobody chose.
    pagerduty_api_key: str = Field(default="")

    # Where the PagerDuty SDK sends its requests. Empty means the real API.
    # Pointing this at the Target Service's PagerDuty-shaped endpoints is the
    # only thing that selects them: the seam sits below the SDK, so the
    # vendor's request building and error vocabulary still run.
    pagerduty_base_url: str = Field(default="")

    # Whether the on-call provider's certificate is checked. True everywhere
    # that matters: PagerDuty's own certificate is real, and so is the one a
    # platform issues a deployed stand-in. False only against the demo running
    # on this machine, whose TLS listener mints itself a certificate nobody has
    # any reason to trust - and which exists at all because the vendor's SDK
    # refuses a base URL that is not `https://`.
    pagerduty_verify_tls: bool = Field(default=True)

    # The credential the HR system's pay bands are read with. Empty by default,
    # for the reason the on-call credential is: a cost nobody can vouch for is
    # worse than one the document says it could not obtain.
    #
    # It only ever needs to read pay grades and bands. Compensation per person
    # is not read by anything here, so a deployment issuing this credential
    # should not grant it - what a *level* pays is all Argus asks.
    hr_api_key: str = Field(default="")

    # Where the pay bands are read from. The Target Environment's HR-shaped
    # endpoint by default, because that is what a demo has; a real deployment
    # points this at its own account.
    hr_base_url: str = Field(default="http://localhost:8080/bamboohr")

    # How long that read may take. Short: the bands are wanted while a
    # postmortem is being written, and a document that waits a minute for a
    # figure it can legitimately report as absent is worse than one without it.
    hr_timeout_seconds: float = Field(default=10.0, gt=0.0)

    # How many hours of work a year a salary is quoted against, which is what
    # turns an annual band into what a minute of it costs. 2080 is the standard
    # full-time year - 40 hours a week, 52 weeks - and it is configuration
    # because it is a fact about an organisation's working norms rather than
    # about this code. Whatever it is set to is stated on the document, since a
    # figure derived from a divisor is only reproducible with the divisor.
    working_hours_a_year: float = Field(default=2080.0, gt=0.0)

    # Where the day's exchange rates are read from. Frankfurter publishes the
    # European Central Bank's reference rates, needs no account and no key, and
    # answers a whole table in one request - so unlike every other provider
    # here it has a working default rather than an empty one, and a deployment
    # that configures nothing still converts.
    exchange_rate_base_url: str = Field(default="https://api.frankfurter.dev")

    # The currency a postmortem states its loss estimate in, and the base every
    # rate is quoted against. A shop paid in several currencies has no total
    # until one of them is chosen, and choosing is a business decision rather
    # than an arithmetic one - so it is configured, and the document discloses
    # what it converted at to get there.
    reporting_currency: str = Field(default="usd")

    # What bounds one investigation once the model, rather than a schedule,
    # decides what to read. Three of them, because they fail differently and
    # none implies the others: a model reading three-hour windows is cheap in
    # calls and ruinous in tokens, one looping on a narrow window is the
    # reverse, and one frugal in both can still leave a human waiting past the
    # point the answer was worth having.
    #
    # How many retrievals the model may make in total, across every turn.
    # Counted in calls rather than turns, since a model may ask for several
    # channels at once. Roughly four times what one round of the schedule this
    # replaces would read, because the point of the change is that a model
    # which needs a fourth look may take one.
    investigation_max_tool_calls: int = Field(default=12, ge=1)

    # The ceiling on what one investigation may cost, both directions summed.
    # Input dominates: the API is stateless, so every turn resends the whole
    # transcript, and a conversation's cost grows with the square of its
    # length. Set from the measured spend of the loop this replaces at its
    # maximum iterations, with room for the extra turns a tool loop takes -
    # the worst case is meant to start no worse than what it replaces.
    investigation_max_tokens: int = Field(default=150_000, ge=1)

    # How long an investigation may run before it is called off, whatever it
    # has or has not spent. This is the bound that answers to the human
    # waiting on the incident rather than to the accountant.
    investigation_max_seconds: float = Field(default=300.0, gt=0.0)

    # How many times one incident may be investigated. A round after the first
    # is bought by a refuted attempt, not by a wider window: Argus changed
    # production and the service did not answer, which is evidence the model has
    # never seen and cannot infer from any amount of reading. That is why this
    # is its own budget rather than whatever the widening schedule has left -
    # the schedule bounds what there is to *read*, and a hard incident spends it
    # all before answering, exactly when a second opinion is worth most.
    investigation_max_rounds: int = Field(default=3, ge=1)

    # How many of one verdict's explanations the walk will try, best first.
    # A ceiling rather than a quota: a verdict naming fewer is left alone, and
    # a verdict naming more keeps its most confident. How long an answer the
    # model gives is its own business, but what that answer costs is not - each
    # candidate is a real change to production and a wait for the service to
    # answer, and the graph's traversal budget is derived from this number.
    # One is the walk Argus had before it could walk: best explanation, then a
    # human.
    investigation_max_candidates: int = Field(default=4, ge=1)

    # How far a minute has to sit from the service's own calm baseline before
    # it counts as the incident starting. Measured in the baseline's own
    # spread, not in error-rate points, so one number works for a service that
    # idles at 0.5% errors and one that idles at 8% - an absolute threshold
    # would be wrong for both.
    # Must be positive: at zero every minute counts as anomalous, including
    # the calm ones the baseline is derived from.
    anomaly_deviations_from_baseline: float = Field(default=3.0, gt=0.0)

    # How many consecutive minutes have to stay departed before the first of
    # them counts as the incident starting. An incident is a state, so it
    # holds; a lone departed minute is sampling noise that had already
    # recovered by the next one. Two rather than more because the onset is
    # what every retrieval window is anchored on: a longer requirement buys
    # little against noise and starts missing brief real incidents.
    anomaly_persistence_minutes: int = Field(default=2, ge=1)

    # How far a minute has to have fallen back, as a fraction of the rise the
    # incident made, before Mitigation calls it recovery. Starting an incident
    # and ending one are asked of the same numbers and are not the same
    # question: the onset is the first minute to leave the quiet stretch, and a
    # service that has come down from a third of its requests failing to two in
    # a hundred has visibly recovered while still sitting above that stretch's
    # own noise. Judged there, a correct mitigation is refuted and put back.
    #
    # Below 1 by construction - at 1 this is the departure threshold again, and
    # the failure it exists to prevent returns.
    recovery_fraction_of_the_rise: float = Field(default=0.8, gt=0.0, lt=1.0)

    # Where deploy history is read from. The demo Target Service stands in for
    # a real Argo CD server, so the default points at it - but the adapter
    # makes the request a real Argo CD answers, and pointing these at one is
    # the only change needed.
    argocd_base_url: str = Field(default="http://localhost:8080")
    # A template, so the demo's stand-in and a real Argo CD's
    # `/api/v1/applications/{application}` are the same setting - only the
    # value differs. A path carrying no placeholder is formatted to itself.
    argocd_application_path: str = Field(default="/argocd/{application}")
    # Empty means no credential is sent at all, rather than an invented one -
    # the stand-in needs none, and a real Argo CD issues these to operators.
    argocd_auth_token: str = Field(default="")
    # Where a restart is asked for, as the same template. A real Argo CD's is
    # `/api/v1/applications/{application}/resource/actions/v2` - v2 rather
    # than the original, which takes the same fields as query parameters and
    # is deprecated since Argo CD 3.1.
    argocd_restart_action_path: str = Field(
        default="/argocd/{application}/resource/actions/v2"
    )
    # What the platform calls the thing that gets restarted, which is not what
    # the alert calls the service. There is no rule producing one from the
    # other, so it is configured - and the demo's stand-in ignores both, since
    # it has one service and no namespaces.
    restart_namespace: str = Field(default="production")
    restart_resource_name: str = Field(default="io-shop")
    # Where a rollback is asked for, and where the sync policy is written.
    # Two more templates rather than one: the platform's rollback and its
    # spec are different routes, and a real Argo CD's are
    # `/api/v1/applications/{application}/rollback` and `.../spec`.
    #
    # Both exist because a rollback is three requests, not one - the
    # application is read for which entry is running and whether the platform
    # is reconciling it, reconciliation is suspended because a real server
    # refuses a rollback while it is on, and only then is the rollback asked
    # for. The application itself is read through `argocd_application_path`
    # above, which the read tier already names.
    argocd_rollback_path: str = Field(default="/argocd/{application}/rollback")
    argocd_spec_path: str = Field(default="/argocd/{application}/spec")

    # How far back to look for changes. Wide on purpose, and far wider than
    # any log window: a cause precedes its symptoms by an unbounded lag - a
    # flag toggled at 09:00 that only breaks under the 14:00 peak - and
    # changes are sparse, so a day of them is a handful of rows where a day of
    # logs is millions of lines.
    change_lookback_minutes: int = Field(default=1440, gt=0)

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/argus"
        )

    @property
    def read_mcp_url(self) -> str:
        return f"http://{self.read_mcp_host}:{self.read_mcp_port}"

    @property
    def write_mcp_url(self) -> str:
        return f"http://{self.write_mcp_host}:{self.write_mcp_port}"

    @model_validator(mode="after")
    def _windows_must_be_consistent(self) -> Settings:
        """Rejects a configuration whose windows contradict each other.

        Three relationships have to hold for retrieval to make sense, and
        none of them is enforced by the individual fields:

        - The log ceiling must admit the window the server derives itself.
          Otherwise `get_log_lines` hands out a 40-minute derived window while
          refusing a 40-minute explicit one - the derived path does no
          clamping, so nothing else would catch it.
        - The metrics span must exceed that ceiling. Metrics exist to locate an
          onset the log budget may not reach; a metrics window no wider than
          the logs' can only ever confirm what the logs already showed.
        - The change lookback must exceed it too, for the same reason. The
          change channel exists to surface a cause the log window cannot
          reach; no wider than the ceiling, it can only repeat what the logs
          already carried.
        """
        derived_log_window_minutes = (
            self.log_initial_lookback_minutes + self.log_initial_lookahead_minutes
        )

        if self.log_max_window_minutes < derived_log_window_minutes:
            raise ValueError(
                f"log_max_window_minutes ({self.log_max_window_minutes}) must be at least the "
                f"derived log window of {derived_log_window_minutes} minutes "
                f"(log_initial_lookback_minutes + log_initial_lookahead_minutes)"
            )

        if self.metrics_window_minutes <= self.log_max_window_minutes:
            raise ValueError(
                f"metrics_window_minutes ({self.metrics_window_minutes}) must be wider than "
                f"log_max_window_minutes ({self.log_max_window_minutes})"
            )

        if self.change_lookback_minutes <= self.log_max_window_minutes:
            raise ValueError(
                f"change_lookback_minutes ({self.change_lookback_minutes}) must be wider than "
                f"log_max_window_minutes ({self.log_max_window_minutes})"
            )

        # A window that repeats as much as it advances never advances at all -
        # the chunker would cut the same lines forever. Caught here rather than
        # defended against where the cutting happens: it is a contradiction
        # between two settings, and the process should refuse to start on it.
        if self.code_index_chunk_overlap >= self.code_index_max_lines:
            raise ValueError(
                f"code_index_chunk_overlap ({self.code_index_chunk_overlap}) must be "
                f"smaller than code_index_max_lines ({self.code_index_max_lines}), or a "
                f"window repeats everything it was meant to advance past"
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


class SettingsSlice(BaseModel):
    """What one consumer is allowed to know about how Argus is configured.

    A view over `Settings`, not a part of it: the environment stays one flat
    surface, and the relationships stated across it - the windows that have to
    admit each other - are still checked in one place by one validator. A
    consumer declares the fields it reads and receives those, so a process that
    cannot change anything does not name the credential that could.

    The narrowing is the point rather than the packaging. `read_mcp_server`
    holding a `Settings` names `unleash_admin_token` whether or not the
    environment ever supplies one - and the day somebody wires it in, nothing
    objects. Holding a slice, it cannot name it at all.

    Frozen, because configuration is read at the top of a process and a value
    that could be edited on the way down would be a second way to configure
    Argus that nothing declares.
    """

    model_config = ConfigDict(frozen=True)

    @classmethod
    def of(cls, settings: Settings) -> Self:
        """Narrows the whole configuration to this slice of it.

        Called at a composition root, which is the one place that holds both
        the whole and the parts. Fields are taken by name, so a slice naming
        something `Settings` does not have fails here, as a missing field,
        rather than at the moment the value was going to be used.

        `from_attributes` so that a slice may name a derived property as
        readily as a stored field - `database_url` is one, and is what every
        holder of it actually wants.
        """
        return cls.model_validate(settings, from_attributes=True)


class DatabaseSettings(SettingsSlice):
    """Where Argus's database is - the one string that says so.

    The URL alone, and not the four fields it is composed from. Those four are
    the recipe rather than the ingredient: `db.py` reads the URL and nothing
    else, and a slice restating the parts would be handing over a second way to
    say the same thing for somebody to compose differently.

    Not a narrower credential, to be clear - the URL carries the password, as
    every connection string does. It is narrower in what it is *for*.
    """

    database_url: str


class ReadMcpEndpoint(SettingsSlice):
    """Where `argus-read-mcp` listens, and where a caller reaches it.

    Both sides of one fact, which is why it is a contract rather than the
    server's own: the server binds the host and port, and `read_mcp_client`
    dials the URL they compose into.
    """

    read_mcp_host: str
    read_mcp_port: int
    read_mcp_url: str


class WriteMcpEndpoint(SettingsSlice):
    """Where `argus-write-mcp` listens, and where a caller reaches it.

    Separate from the read tier's endpoint, as the servers are. Two addresses
    rather than one, though - not two tiers: what makes the write tier the
    write tier is that it holds the admin credential and the read server is
    issued none, and that nothing outside the declared set of generic
    mitigations has a function on either (spec §12.1, §13). An address is how a
    caller finds a server, and finding one authorizes nothing.
    """

    write_mcp_host: str
    write_mcp_port: int
    write_mcp_url: str


class LLMSettings(SettingsSlice):
    """What it takes to reach a model - the kernel's own, and nobody else's.

    `argus_core.llm` is behind a front door narrowed to the modules that
    declare the `llm` extra, and this is the configuration that door needs. An
    agent asks a model something through an `LLMClient` it was handed; which
    SDK answers, and with whose key, is the composition root's business.
    """

    anthropic_api_key: str
    anthropic_base_url: str
