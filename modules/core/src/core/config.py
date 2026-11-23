from __future__ import annotations

from functools import lru_cache
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.models.code_search import CodeSearch
from core.models.model_policy import DEFAULT_EFFORT, Reasoning

# The longest Mitigation stands by with nothing measured: a change still
# arriving, a read tier not answering. Named here because two settings are stated
# in terms of it - the wait itself, and the lease a stopped worker's run sits
# unwalked for.
_VERIFICATION_TIMEOUT_SECONDS: Final = 180.0

# How many of those waits a claim survives before another worker may take the
# run back. More than one, because a walk can verify more than one action; small
# enough that a worker killed mid-walk does not leave its incident sitting for
# an hour.
_LEASES_PER_LONGEST_WAIT: Final = 4

# How long a client to each MCP tier waits for a tool's answer before it takes
# the call to be lost - above the slowest tool that tier serves. Named here
# because each is said twice: the setting, and the endpoint slice a test may
# build without one. The read tier's slowest reads a whole repository archive,
# under a thirty-second timeout of its own; the write tier's is a restart - two
# requests, then sixty looks a second apart, each up to the platform's
# ten-second timeout, about eleven and a half minutes - after waiting up to
# five seconds for its run to be free.
_READ_MCP_ANSWERED_WITHIN_SECONDS: Final = 120.0
_WRITE_MCP_ANSWERED_WITHIN_SECONDS: Final = 720.0


class Settings(BaseSettings):
    """How Argus is configured, in Argus's own terms.

    Every setting here names no vendor. What a vendor needs - its address, its
    credential, the names in its own catalogue - is its adapter's settings
    (`AdapterSettings`), read by the process that builds the adapter (`apps`),
    so a vendor swapped is an adapter and a root edited and never this schema.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_user: str = Field(default="argus")
    database_password: str = Field(default="argus")
    database_host: str = Field(default="localhost")
    database_port: int = Field(default=5432)

    target_service_url: str = Field(default="http://localhost:8080")

    read_mcp_host: str = Field(default="localhost")
    read_mcp_port: int = Field(default=8090)
    # How long a client waits for a read tool's answer, in seconds.
    read_mcp_answered_within_seconds: float = Field(
        default=_READ_MCP_ANSWERED_WITHIN_SECONDS, gt=0.0
    )

    write_mcp_host: str = Field(default="localhost")
    write_mcp_port: int = Field(default=8092)
    # How long a client waits for a write tool's answer, in seconds. A call
    # that meets it is asked again only where asking again is harmless, so
    # one below the slowest tool hands a restart that is still being made to a
    # person.
    write_mcp_answered_within_seconds: float = Field(
        default=_WRITE_MCP_ANSWERED_WITHIN_SECONDS, gt=0.0
    )

    # The branch a fix is cut from and proposed onto - the one that is actually
    # deployed, since a fix against anything else patches a repository nobody
    # is running. So it is also the branch the index describes and the one a
    # push to is a push of what is deployed.
    deployed_branch: str = Field(default="main")
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
    # Forty rather than twelve, because twelve bound every walk of a recorded
    # corpus - all eight that reached Code-Fix stopped on the call count, and
    # the four that did submit did so only on the last-call nudge, which is a
    # fix written under duress rather than one arrived at. A bound that every
    # run reaches is measuring itself; this one is set wide enough that what
    # the next corpus shows is how long the work actually takes.
    codefix_max_tool_calls: int = Field(default=40, gt=0)
    # Larger than the investigation's, because what this agent reads is source
    # rather than windows of metrics, and it carries every file it has read
    # for the rest of the run - so the spend grows with the square of the call
    # count, and widening the call bound above is what made this one bind.
    #
    # Measured across a recorded corpus of eleven real incidents. The largest
    # walk that reached a fix spent 265,054; the two largest overall, 436,604
    # and 421,818, are floors rather than figures - both stopped *because* they
    # hit the old 400,000, so what they would have spent is unknown. Doubled
    # off the larger floor, which makes this a ceiling against a runaway rather
    # than a tight fit, and that is the right direction for a bound whose job
    # is to stop one.
    #
    # In money, at Opus 5 rates ($5/$25 per million, cache reads a tenth of
    # input and writes a quarter above it): the walk this was measured from
    # cost $1.11, and a walk that ran all the way to this bound at the same mix
    # would cost about $2.20. The number to hold in mind is $4.35, which is
    # what it costs if the caching stops working - 870,000 tokens all billed as
    # fresh input. That is the real exposure of widening this, and the reason
    # the figure is written down rather than left to be rediscovered from a
    # bill.
    codefix_max_tokens: int = Field(default=870_000, ge=1)
    # Longer than the investigation's, and for the opposite reason to the
    # bound above: nobody is waiting on this one. The incident is already
    # mitigated by the time Code-Fix runs, so what this protects is the
    # worker's own progress rather than a human's patience.
    #
    # The longest walk in the corpus took 538 seconds and proposed a fix, so
    # ten minutes was within a minute of refusing work that was about to
    # succeed. Doubled off that measurement.
    codefix_max_seconds: float = Field(default=1_100.0, gt=0.0)
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
    # Which directories of the service's repository hold the service itself, comma
    # separated. Empty is the whole repository, and is right whenever the
    # repository is nothing but the service.
    #
    # The demo's is not: `Argus-Demo-Target-App` ships the shop beside the rig
    # that stages incidents against it, and a fix agent reading the rig is
    # reading how its own incidents are generated. A real deployment points
    # Argus at a service repository and leaves this empty.
    service_source_paths: str = Field(default="")

    # Where that repository's source is kept as something searchable by
    # meaning: under what name, in the vector store whose address is its
    # adapter's. A store of its own rather than a table: what it answers is
    # "which passages are nearest this one", and no amount of SQL makes that a
    # cheap question.
    #
    # One collection per deployment, named for what it holds rather than for
    # the repository: the index describes the Target Service's source, and a
    # deployment pointed at a different repository is a different index.
    repository_index_collection: str = Field(default="target_service_source")
    # How often the catch-up loop looks. A bound on how long the index may
    # describe yesterday's code while nobody is telling it otherwise, rather
    # than a performance knob: where a push delivery arrives the gap closes on
    # the next pass anyway, and where none ever arrives - no tunnel, a webhook
    # nobody configured - this interval is the whole of what keeps the index
    # honest.
    repository_index_interval_seconds: float = Field(default=60.0, gt=0.0)
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
    repository_index_embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    # How a file whose structure nothing here understands is cut into passages,
    # in lines, and how many lines of each window the next one repeats. The
    # overlap is what keeps a fault straddling a cut whole inside one passage.
    #
    # These govern the fallback only. Python is cut at its own definitions,
    # because a function is as long as it is and one truncated to fit a window
    # is a passage that stops mid-statement.
    repository_index_max_lines: int = Field(default=60, gt=0)
    repository_index_chunk_overlap: int = Field(default=10, ge=0)

    # Long-term memory: what earlier incidents were done about (spec §11.2).
    # The same Qdrant as the index above, in a collection of its own - two
    # corpora with nothing to do with each other, and one server.
    incident_memory_collection: str = Field(default="incidents_remembered")
    # Whether what incidents tried is searchable, and whether it is consulted.
    # Off is a real configuration rather than a way of disabling a broken
    # feature: the §21 benchmark's whole question is what memory is worth, and
    # two runs that differ in exactly one thing are how it is asked. Every walk
    # files its record either way - what is switched off is carrying the records
    # to the store and reading them back - so a deployment that turns memory on
    # later has every incident it walked in the meantime.
    incident_memory_enabled: bool = Field(default=True)
    # How often the deliverer looks for filed records the store does not hold,
    # in seconds. The longest a finished incident is filed and unsearchable
    # while nothing is failing; a look that finds nothing is one query.
    incident_memory_delivery_interval_seconds: float = Field(default=2.0, gt=0)
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
    # How many times one search is asked in all when the store fails it for
    # itself (a 5xx), and how many seconds apart. Qdrant failed a search with
    # "Expected at least one response for one query" while the record was there.
    # Both are starting guesses: why it failed is unshown, so nothing yet says
    # how long such a failure lasts.
    incident_memory_recall_attempts: int = Field(default=3, gt=0)
    incident_memory_recall_retry_seconds: float = Field(default=0.5, ge=0.0)

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

    # How far back Mitigation looks for the flag change or the deployment an
    # incident is about - one span for both histories, so that which change is
    # undone never depends on which of them reached further. Far shorter than
    # `change_lookback_minutes`, and deliberately so: that one asks "how far back
    # may a cause plausibly lie" for an investigation, where this asks "what did
    # someone just change" about an incident happening now. Widening it makes an
    # ambiguous environment - two flags changed, so no action - the common case
    # rather than the exception.
    mitigation_change_lookback_minutes: int = Field(default=60, gt=0)

    # How long Mitigation waits while nothing has been measured - a change still
    # arriving, a read tier that will not answer. It is not how long the service
    # is watched for: that is measured off the window the service answers with
    # (§16), because how many clear minutes a recovery has to show is a fact
    # about the incident and a flapping service needs more of them than any
    # figure anybody would pick. What is left here is the stretch with no window
    # to measure anything from, where a configured bound is the only bound there
    # is. Long enough to cover a rolling update reaching every replica.
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

    # How many minutes after a minute ends the metrics source reports it. One for
    # a real Prometheus, which answers a minute once it is over; mitigation's
    # recovery wait is extended by it, or the wait ends before the minute that
    # decides it can be read. Zero where the source also reports the minute in
    # progress, as the Target Environment's stand-in does by default.
    metrics_reporting_lag_minutes: int = Field(default=1, ge=0)

    # How long a worker waits before asking the queue again, having found it
    # empty. The wait a real alert pays before anything starts on it, so it is
    # short - and it is only paid when there is nothing to do, since a worker
    # that found work looks again immediately.
    run_poll_interval_seconds: float = Field(default=2.0, gt=0.0)

    # How long a claim holds a run before another worker may take it back. A
    # worker renews this while it walks, so it bounds how long a *stopped*
    # worker's run sits unwalked - not how long a run may take.
    #
    # A multiple of the longest wait a walk takes with nothing measured, so a
    # claim is not lost to one of them while the renewal thread happens to be
    # between renewals. The renewal is what covers a *long* wait, and it has to
    # be: how long a verification watches is measured off the incident, so a
    # service that will not hold still is watched for as many clear minutes as its
    # own rhythm demands and no figure here bounds it.
    run_lease_seconds: float = Field(
        default=_VERIFICATION_TIMEOUT_SECONDS * _LEASES_PER_LONGEST_WAIT, gt=0.0
    )

    # How many times a run is tried where its walk could not get an answer from
    # the model for now, and how long it waits before the second try. Each wait
    # after that is five times the one before. Only a model that could not be
    # reached for now is tried again - nothing else would be answered
    # differently a minute later - and every try is paid for, which is why the
    # count is small: three tries, each of which the model client retries twice
    # itself, is nine requests at most.
    run_attempts: int = Field(default=3, gt=0)
    run_first_retry_wait_seconds: float = Field(default=60.0, gt=0.0)

    # How hard the model answering each agent is asked to think, on Argus's own
    # scale. Which model answers is the provider's to say - a model is named in
    # that provider's catalogue, and each provider's adapter names its own
    # (`llm_anthropic`, Anthropic's) - but how much effort an agent's kind of work earns
    # is Argus's, and the same five levels whichever provider answers.
    #
    # Per agent rather than once, because the agents are not the same shape of
    # work. The postmortem writes one piece of prose with every figure already
    # measured and no tools to explore; the investigator runs a tool loop whose
    # whole judgement is which evidence would settle the question; Code-Fix is
    # agentic coding, where more effort is said to earn its cost. A single level
    # across the three is wrong for at least one of them, and which one is not
    # knowable from here - it is a thing to measure against the eval, which is
    # why these are configuration rather than constants.
    #
    # `high` is what every agent used when there was one setting for all of
    # them, and is also the API's own default, stated rather than relied on.
    # Code-Fix stays at `high` too, and that is measured rather than argued.
    # It was moved to `higher` on the reasoning that agentic coding is where
    # more effort earns its cost; a matched pair of recorded corpora -
    # same scenarios, same bounds, effort the only difference - said the
    # opposite. At `high` it proposed a fix in six of the eight walks that
    # reached it, in 9 to 31 calls; at `higher` in three, in 13 to 29, and with
    # roughly twice the tokens. The case whose answer is a whole large file is
    # among the three it lost. More thinking per call bought more reading and
    # fewer conclusions, which is the shape of an agent exploring rather than
    # deciding.
    investigation_effort: Reasoning = Field(default=DEFAULT_EFFORT)
    codefix_effort: Reasoning = Field(default=DEFAULT_EFFORT)
    # How much room one fix gets to be written in. Alone among the agents
    # Code-Fix answers with whole files, and the largest in the Target
    # Service - `monthly_statement.py` - is 21,593 tokens, 23,735 with the test
    # a fix is asked to bring with it, so the 16,000 every other agent is happy
    # with makes a whole class of fix impossible rather than tight, and no
    # retry helps because the same request overflows the same ceiling every
    # time. That pair alone is past 21,333, where the answer
    # is streamed, which is the only way the SDK will carry one that large;
    # 128,000 is the model's own ceiling and
    # a ceiling is not a reservation, so asking for all of it costs nothing
    # for the fixes that turn out to be small.
    codefix_max_output_tokens: int = Field(default=128_000, gt=0)
    postmortem_effort: Reasoning = Field(default=DEFAULT_EFFORT)
    # The grounding judge, which reads a write-up and an overview against what
    # they were written from, thinking: checking each claim against a record is
    # reasoning, and a judge at low effort, which did not think, flagged claims
    # its own record supported in every write-up of the pilot.
    judge_effort: Reasoning = Field(default=Reasoning.MEDIUM)

    # How hard the model classifying what a person wrote in an incident's thread
    # thinks, and how often the intent reader looks for something new to
    # understand. One short question with five answers; the pause is the delay
    # between a person writing and Argus offering to resolve, paid only when
    # there was nothing new.
    intent_effort: Reasoning = Field(default=DEFAULT_EFFORT)
    intent_poll_seconds: float = Field(default=2.0, gt=0.0)

    # Where Argus answers, as somebody outside it reaches it - what a message
    # in a channel links back to. Configured rather than observed, as it is for
    # everything that links into itself: the relay never serves a request to
    # learn a host from, and behind a proxy the host a request arrived on is
    # not the one a reader can click anyway. Empty means a message carries no
    # link, which is a demo without one rather than a broken one in a channel.
    argus_base_url: str = Field(default="")

    # How many hours of work a year a salary is quoted against, which is what
    # turns an annual band into what a minute of it costs. 2080 is the standard
    # full-time year - 40 hours a week, 52 weeks - and it is configuration
    # because it is a fact about an organisation's working norms rather than
    # about this code. Whatever it is set to is stated on the document, since a
    # figure derived from a divisor is only reproducible with the divisor.
    working_hours_a_year: float = Field(default=2080.0, gt=0.0)

    # The currency a postmortem states its loss estimate in, and the base every
    # rate is quoted against. A shop paid in several currencies has no total
    # until one of them is chosen, and choosing is a business decision rather
    # than an arithmetic one - so it is configured, and the document discloses
    # what it converted at to get there. Held lower case, as every currency
    # Argus compares is spelled (`_a_currency_as_argus_spells_one`).
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
    # length.
    #
    # Measured rather than reasoned: across a recorded corpus of eleven real
    # incidents the most expensive investigation round spent 98,433, on the
    # red-herring scenario - the walk that genuinely needs its turns. Nothing
    # in that corpus came near the old 150,000, so the figure was never tested
    # by the runs that were supposed to justify it. Doubled, because a bound
    # this one only has to survive a truncation retry, and a bound that binds
    # a walk which would otherwise have finished costs a whole investigation
    # to learn nothing.
    investigation_max_tokens: int = Field(default=200_000, ge=1)

    # How long an investigation may run before it is called off, whatever it
    # has or has not spent. This is the bound that answers to the human
    # waiting on the incident rather than to the accountant.
    investigation_max_seconds: float = Field(default=300.0, gt=0.0)

    # How often the Investigator reads the metrics again when they stop before
    # the minute the alert fired in, and how long it keeps trying. A source that
    # reports a minute only once it is over has nothing yet for that minute, and
    # an alarm is called false only over a window that reaches it. Given up on,
    # the alarm is investigated instead.
    metrics_recheck_interval_seconds: float = Field(default=15.0, gt=0.0)
    metrics_recheck_max_wait_seconds: float = Field(default=120.0, ge=0.0)

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

    # Where the Target Service's rendered-summary cache answers. The first
    # address here that is a datastore rather than a control plane: every other
    # write goes through a platform that acts on Argus's behalf, and this one is
    # spoken to directly, in the store's own protocol.
    #
    # The shop holds a different address for the same cache, and that is correct
    # rather than drift. The shop reads its own deployment configuration and
    # dials the cluster service name there; Argus runs beside the environment
    # rather than inside it and reaches the published port, exactly as the shop's
    # own monitoring posts to `host.docker.internal` to reach a host Argus runs
    # on. Two addresses for one cache, because the two parties are in different
    # places.
    #
    # No credential, for the reason the service register has none: what is in
    # here is a figure the account page would have worked out for itself, and a
    # store holding a cheaper copy of public arithmetic is not a secret.
    cache_url: str = Field(default="redis://localhost:6379")

    # Where the organisation's service register answers. The demo Target Service
    # stands in for one, so the default points at it - and unlike the deployment
    # platform's settings there is nothing here to authenticate with, because a
    # register of what calls what is not secret inside the organisation keeping
    # it.
    service_registry_base_url: str = Field(default="http://localhost:8080")
    # A template, as the deploy reader's paths are, so a register with one route
    # per service and one with a single route are the same setting at different
    # values. A path carrying no placeholder formats to itself.
    service_registry_service_path: str = Field(
        default="/registry/services/{service}"
    )

    # How far back to look for changes. Wide on purpose, and far wider than
    # any log window: a cause precedes its symptoms by an unbounded lag - a
    # flag toggled at 09:00 that only breaks under the 14:00 peak - and
    # changes are sparse, so a day of them is a handful of rows where a day of
    # logs is millions of lines.
    change_lookback_minutes: int = Field(default=1440, gt=0)

    # Where every process writes its traces, metrics and logs, as OTLP JSON
    # lines - always, whether or not a backend below is configured. The files
    # are for a person debugging, and a directory that only filled when someone
    # remembered to stand up a collector would be empty the day it was needed.
    # Relative paths resolve against the process's working directory, which is
    # the repository root for everything nox starts; the repository ignores it.
    telemetry_directory: str = Field(default=".telemetry")

    # A general OTLP backend, which receives all three signals over HTTP beside
    # the files. Named as OTel names them everywhere else, so whoever configures
    # a collector already knows these. Empty sends nothing anywhere: the
    # default is a deployment that keeps its telemetry to itself.
    #
    # The headers are OTel's own format - comma-separated `key=value` pairs -
    # and are where a backend's credential goes.
    otel_exporter_otlp_endpoint: str = Field(default="")
    otel_exporter_otlp_headers: str = Field(default="")

    # The lowest level a process logs at, by the stdlib's own names. INFO is a
    # production's audit trail; DEBUG is for the incident somebody is chasing,
    # and is switched on by restarting the process with this lowered.
    log_level: str = Field(default="INFO")

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

    @field_validator("reporting_currency")
    @classmethod
    def _a_currency_as_argus_spells_one(cls, currency: str) -> str:
        """The reporting currency lower case, as the revenue source's keys,
        the rate table and the pay bands spell theirs. Read as written, a
        deployment that configured "USD" would match none of them: on a day
        the rates could not be read, its own currency's takings would be
        stated as nothing."""
        return currency.lower()

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
        if self.repository_index_chunk_overlap >= self.repository_index_max_lines:
            raise ValueError(
                f"repository_index_chunk_overlap ({self.repository_index_chunk_overlap}) must be "
                f"smaller than repository_index_max_lines ({self.repository_index_max_lines}), "
                f"or a window repeats everything it was meant to advance past"
            )

        return self


@lru_cache
def get_settings() -> Settings:
    """The kernel's settings, read from the environment once per process.

    Called by a process's root (`apps`), and otherwise only where the layering
    guard allows it with its reason: the database's connection
    (`postgres.connect_from_env`) and Alembic's entry script
    (`postgres.migrations.env`).
    Everything below a root is handed the slice it reads.
    """
    return Settings()


class AdapterSettings(BaseSettings):
    """What one vendor's adapter needs, declared by that adapter.

    The kernel's `Settings` names no vendor; each adapter declares its own
    settings on this base - the address it reaches, the credential it holds, the
    names in its vendor's catalogue - and a process's root reads them, once,
    beside the kernel's. So swapping a vendor is an adapter and its roots edited,
    and never this schema.

    A field is read from the variable named for it, as the kernel's are - a
    deployment configures `SLACK_BOT_TOKEN` whichever class declares it - unless
    the adapter's settings say a prefix of their own, as Unleash's do
    (`UNLEASH_BASE_URL` for `base_url`).
    Read from `.env` as `Settings` is, ignoring every variable another class
    declares, and frozen, as a slice is - configuration is read at the top of a
    process, and a value that could be edited on the way down would be a second
    way to configure Argus.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)


class SettingsSlice(BaseModel):
    """What one consumer is allowed to know about how Argus is configured.

    A view over `Settings` - and, for a slice that reads one, a vendor's
    settings beside it (`of`) - not a part of it: the environment stays one flat
    surface, and the relationships stated across it - the windows that have to
    admit each other - are still checked in one place by one validator. A
    consumer declares the fields it reads and receives those, so a process that
    cannot change anything does not name the credential that could.

    The narrowing is the point rather than the packaging. `read_mcp_server`
    holding a `Settings` names `database_password` whether or not it ever
    connects with it - and the day somebody wires it in, nothing objects.
    Holding a slice, it cannot name it at all.

    Frozen, because configuration is read at the top of a process and a value
    that could be edited on the way down would be a second way to configure
    Argus that nothing declares.
    """

    model_config = ConfigDict(frozen=True)

    @classmethod
    def of(cls, settings: Settings, *more: BaseModel) -> Self:
        """Narrows the whole configuration to this slice of it.

        Called at a composition root, which is the one place that holds both
        the whole and the parts. Fields are taken by name, so a slice naming
        something none of them has fails here, as a missing field, rather than
        at the moment the value was going to be used.

        `more` is a vendor's settings, for a slice that reads one of its fields
        beside the kernel's - the model an agent is answered by is named in the
        provider's catalogue, so the investigator's and Code-Fix's slices take
        it from the provider's settings. A field two of them both declare is
        refused rather than taken from either: which one the slice meant is not
        something a name can say.

        Read by attribute so that a slice may name a derived property as
        readily as a stored field - `database_url` is one, and is what every
        holder of it actually wants.
        """
        sources = (settings, *more)
        values: dict[str, object] = {}

        for name in cls.model_fields:
            holding = [source for source in sources if hasattr(source, name)]

            if len(holding) > 1:
                raise ValueError(
                    f"[{name}] is configured by each of "
                    f"{[type(source).__name__ for source in holding]}, so which one "
                    f"{cls.__name__} reads cannot be told"
                )

            if holding:
                values[name] = getattr(holding[0], name)

        return cls.model_validate(values)


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
    dials the URL they compose into - and waits as long as it says for an
    answer, which only the caller reads.
    """

    read_mcp_host: str
    read_mcp_port: int
    read_mcp_url: str
    read_mcp_answered_within_seconds: float = _READ_MCP_ANSWERED_WITHIN_SECONDS


class WriteMcpEndpoint(SettingsSlice):
    """Where `argus-write-mcp` listens, and where a caller reaches it.

    Separate from the read tier's endpoint, as the servers are. Two addresses
    rather than one, though - not two tiers: what makes the write tier the
    write tier is that it holds the admin credential and the read server is
    issued none, and that nothing outside the declared set of generic
    mitigations has a function on either (spec §12.1, §13). An address is how a
    caller finds a server, and finding one authorizes nothing. How long a
    caller waits for an answer is here too, and only the caller reads it.
    """

    write_mcp_host: str
    write_mcp_port: int
    write_mcp_url: str
    write_mcp_answered_within_seconds: float = _WRITE_MCP_ANSWERED_WITHIN_SECONDS


class TelemetrySettings(SettingsSlice):
    """Where a process's traces, metrics and logs go.

    The directory every signal is written under, the general OTLP backend that
    may receive them as well, and the level below which nothing is logged.
    Handed to `telemetry` at the top of each process, which is the only reader:
    instrumented code speaks the OTel API and never learns where what it
    emitted ended up. A vendor's backend is that vendor's settings, read by the
    process's root beside these.
    """

    telemetry_directory: str
    otel_exporter_otlp_endpoint: str
    otel_exporter_otlp_headers: str
    log_level: str
