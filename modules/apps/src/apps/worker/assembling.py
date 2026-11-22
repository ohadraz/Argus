"""Where the worker supplies what a walk is supplied with.

`orchestrator.walk.collaborators` says what a walk takes; this builds the real
ones, for a process that has a database, a model and two tiers - and is the
one place in the worker that builds what a walk reaches a vendor through: the
model provider, the on-call platform, the payment provider, the rate provider,
the HR source and the store long-term memory is searched in. Every one of them
is built here and handed to the agents and the postmortem's sources as its port.
The backends telemetry sends to are the process's, not the walk's, and are
named where it starts (`apps.worker.process`).

Part of the worker's root rather than of the Orchestrator, because choosing
what a process runs against is the root's: a library that built its own
adapters is a library nobody can install without its vendors.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from functools import partial

from codefix_agent import FixSettings, fixes_over
from core import Holding, Settings, SettingsSlice
from core.anomaly import AnomalyThresholds
from core.autonomy import admit
from core.llm import ModelProvider, build_llm_client, conversations_through
from core.vector_store import VectorSearch
from embedding_fastembed import an_embedder
from exchange_rate_source.frankfurter import FrankfurterSettings, rates_published_for
from incident_memory.records import RememberedIncident
from incident_record import (
    calls_into,
    ended_by_a_person_via,
    events_into,
    events_into_connection,
    still_held_via,
    waiting_for_people_via,
)
from investigation_agent import InvestigationSettings, changes_from, read_tier_tools_over
from investigation_agent import investigate as _investigate
from llm_anthropic import AnthropicProvider, AnthropicSettings
from mitigation import (
    MitigationSettings,
    an_undo_over,
    arrival_of,
    fetch_recent_deployments,
    fetch_recent_flag_changes,
    performing_writes_over,
    plan_action,
    settle_the_refutation,
    still_argus_s,
    take_action,
    watch_what_was_performed,
    whether_it_was_made,
)
from oncall_source.pagerduty_adapter import pagerduty_from
from oncall_source.pagerduty_settings import PagerDutySettings
from orchestrator.gathering import write_postmortem_for, write_synopsis_for
from orchestrator.records import Records
from orchestrator.sources import the_real_sources
from orchestrator.walk.collaborators import Collaborators
from orchestrator.walk.ports import RecallSimilar, Resuming
from pay_band_source.bamboohr_adapter import pay_bands
from pay_band_source.bamboohr_settings import BambooHrSettings
from postgres import Connections
from postmortem_writing import Sources, judge_policy, postmortem_policy, synopsis_policy
from read_mcp_client import ReadTier
from revenue_source.stripe_adapter import charges_between
from revenue_source.stripe_settings import StripeSettings
from write_mcp_client import WriteTier

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Vendors:
    """Every vendor's settings a walk is built from, beside the kernel's: the
    model provider's, and those of the four sources a postmortem reads.
    Telemetry's backends are the process's and are read where it starts.

    Read once, where the process starts (`read`), and handed to `against` with
    the kernel's - so a test hands over the ones it means, and nothing below
    reads the environment. The vector store's is read only where memory is on
    (`the_store_for`).
    """

    model_settings: AnthropicSettings
    oncall: PagerDutySettings
    revenue: StripeSettings
    rates: FrankfurterSettings
    pay_bands: BambooHrSettings

    @classmethod
    def read(cls) -> Vendors:
        """Each vendor's settings, as this process's environment says them."""
        return cls(model_settings=AnthropicSettings(),
                   oncall=PagerDutySettings(),
                   revenue=StripeSettings(),
                   rates=FrankfurterSettings(),
                   pay_bands=BambooHrSettings())


class IncidentMemorySettings(SettingsSlice):
    """Whether earlier incidents are searched, in what, and how forgivingly.

    Seven fields rather than the whole of `Settings`, for the reason every other
    slice is narrow: what it takes to ask whether an incident like this one has
    been seen before is a collection and a model, and nothing that reads only
    those should be able to name a credential. Which store holds the collection
    is the store's adapter's.

    Declared here rather than in `incident_memory`, whose walk-side modules
    read no configuration at all - they are handed a store and an embedder,
    and deciding what those are for a walk is this module's job. The deliverer
    reads a slice of its own (`apps.deliverer`), being a process of its own.
    """

    incident_memory_enabled: bool
    incident_memory_collection: str
    incident_memory_embedding_model: str
    incident_memory_recall_limit: int
    incident_memory_similarity_floor: float
    incident_memory_recall_attempts: int
    incident_memory_recall_retry_seconds: float


@contextmanager
def the_store_for(settings: IncidentMemorySettings) -> Generator[VectorSearch | None]:
    """The one vector store a process holds, for as long as it runs. Or none.

    Opened where a process starts and closed when it stops, beside the pool and
    the two MCP sessions - because that is what it is: a session to a server,
    and a resource with two openers and no closer is the one nobody owns.

    `None` where this deployment searches no long-term memory, which is a real
    configuration rather than a switched-off feature (§21 asks what memory is
    worth, and two runs differing in exactly one thing are how that is asked).
    Read here rather than by the factory below, so that whether there is a
    store to speak of is settled once, by the process, before a graph exists.

    Opened through the reading side of the store's adapter, which is the only
    side a walk may know, and yielded as the port, which can only search: the
    walk searches what is there and files the rest. The adapter is imported
    here, where it is built, and only once memory is on - a worker with memory
    off loads no store's client. So are its settings, which name where the
    store is: importing them imports the client.
    """
    if not settings.incident_memory_enabled:
        _logger.info("incident memory disabled")

        yield None

        return

    from vector_store_qdrant.searching import the_search_at
    from vector_store_qdrant.settings import QdrantSettings

    with the_search_at(QdrantSettings().qdrant_url,
                       settings.incident_memory_collection) as store:
        yield store


def the_models_at(settings: AnthropicSettings) -> ModelProvider:
    """Whoever answers this process's model calls, reached where `settings` say.

    The one place the worker names a model vendor. Built here and handed to
    every agent as the port, so that which provider answers is decided once,
    where the process is assembled, rather than by a default inside each agent.
    Its adapter is imported at the top, as every adapter a root builds is:
    nothing imports a root, so the SDK it loads is loaded for this process
    alone.
    """
    return AnthropicProvider(settings)


def against(connections: Connections,
            read: ReadTier,
            write: WriteTier,
            store: VectorSearch | None,
            holding: Holding,
            *,
            settings: Settings,
            vendors: Vendors) -> Collaborators:
    """The real ones, for a process that has a database, a model and two tiers.

    Built once where the process starts. Everything derived from `connections`
    is a closure over it rather than an open connection, so assembling a graph
    reaches nothing - a walk is what opens one, when a node actually runs. The
    two tiers are the same bargain: each is one session to one server, opened
    by the process that owns it and handed here rather than dialled per call -
    and typed apart, so the two cannot be handed over in each other's place.
    So is the store, which recall is handed rather than opening one: `None`
    there says this process searches no memory. Filing is not handed it - what
    the incident tried is a row, written through `connections` like every other.

    Being handed the store is what keeps a test off the network, and not only
    tidy. Opening the store's client starts a daemon thread that asks the
    configured address for its version, and every failure of that thread is
    swallowed into a warning - so a unit test that built one reached out, and
    reached out silently. Passing `None`, or a double, is the only way that
    does not happen, and it is available only because nothing here constructs
    a client.

    `holding` is the run the process is walking, which is all a walk asking
    whether its run is still its own needs to be answered.

    `settings` is the deployment's configuration and `vendors` each vendor's,
    handed in by whoever started the process rather than read here, so that what
    a binding was given - the address each model provider reaches, above all -
    can be told apart in a test that names two.

    Which tier answers which question is decided here and nowhere else. A seam
    that is one tool's call is bound to the tier's own method for it; one that
    is more than a call - the change channel, the wait for a change to arrive,
    the way back - to a function of the agent's own over it. The read tier serves
    every retrieval channel and the verification metrics; the write tier serves
    the writes Argus makes and the provider's own history of who made a flag
    change - which lives on the write tier because the provider serves that
    history to admin credentials alone (spec §12.1). A method looked up on the
    wrong tier is not there, which the type checker says before anything runs.
    """
    mitigation = MitigationSettings.of(settings)
    memory = IncidentMemorySettings.of(settings)
    # One register, read by the model during the investigation and by the walk
    # on the gate's behalf. Bound once rather than at each of the two, because
    # two bindings are two registers as far as an incident is concerned - and
    # the failure that produces is the model defending a service the gate has
    # never heard of.
    register = read.get_service_dependencies
    # Where the algorithm draws its lines, read from the deployment and
    # handed to both agents that measure against them. A domain value
    # rather than a slice: `core.anomaly` decides what counts as an
    # incident starting, and that rule has no business reading config.
    thresholds = AnomalyThresholds(
        deviations_from_baseline=settings.anomaly_deviations_from_baseline,
        persistence_minutes=settings.anomaly_persistence_minutes,
        recovery_fraction_of_the_rise=settings.recovery_fraction_of_the_rise
    )
    records = Records(connections, events_into_connection)
    recorder = calls_into(connections)
    # Every write that performs a mitigation, and the plans they are written
    # from, over the write tier - bound once, because the plan and the write it
    # is handed back to are one collaboration.
    writes = performing_writes_over(write)
    # What puts a change back, bound once for the live walk's taking and a
    # resumed walk's watch and put-back alike: two copies of it is how one came
    # to be missing a collaborator the other had.
    undo = an_undo_over(write)
    # Built once rather than per postmortem: which provider answers which
    # question is a fact about the deployment, and the only thing that differs
    # between two incidents is which incident is being written up.
    sources = the_sources_for(settings, vendors, connections, read, thresholds)
    # Whoever answers every agent's model calls, chosen once for the process.
    models = the_models_at(vendors.model_settings)
    # The grounding judge both writers are read by, at its own model and
    # address. Its address is settled here, where the process starts, so one
    # pointed at the agents' stand-in and at nothing for the judge refuses to
    # start rather than judging out of the writer's recordings.
    judging = partial(build_llm_client,
                      the_models_at(vendors.model_settings.for_the_judge()),
                      policy=judge_policy(vendors.model_settings.judge_model,
                                          settings.judge_effort))

    return Collaborators(
        # Bound here because this is where a deployment's configuration meets
        # the agents it configures. `Collaborators` says nothing is defaulted,
        # and an investigation that read its own budget would be a default in
        # everything but name.
        investigate=partial(
            _investigate,
            settings=InvestigationSettings.of(settings, vendors.model_settings),
            thresholds=thresholds,
            # The six channels, each over the tier that answers it. The change
            # channel takes both, because a deploy and a flag flip are recorded
            # by two systems and the Investigator reads one history - the flags
            # off the write tier, which the Investigator never holds.
            fetch_metrics=read.get_metrics_summary,
            fetch_logs=read.get_log_lines,
            fetch_change_events=changes_from(read.get_change_events,
                                             write.get_recent_flag_changes),
            fetch_dependencies=register,
            fetch_what_a_deployment_changed=read.get_what_a_deployment_changed,
            fetch_rollout=read.get_rollout_state,
            # And the one the loop reads for itself after the onset, which no
            # model is offered: where each replica runs, over the read tier.
            fetch_placements=read.get_placements,
            # The three channels above that are the read tier's, offered to the
            # model as that tier declares them.
            read_tier_tools=read_tier_tools_over(read),
            # The model, over the process's provider. The agent builds its
            # conversation from it per incident, under its own policy.
            conversations=conversations_through(models)
        ),
        record_hypothesis=records.hypothesis,
        # The same channel the investigation reads, asked again by the walk -
        # this time about the service that was paged, and for the gate rather
        # than for the model.
        fetch_dependencies=register,
        # Mitigation's three collaborators, each bound to the configuration
        # this deployment holds. The lookback, the name Argus writes under and
        # the wait for the service are read once, here, rather than by the
        # agent every time it is asked a question.
        fetch_flag_changes=partial(
            fetch_recent_flag_changes, mitigation, write.get_recent_flag_changes
        ),
        # The other change a service has, over the same lookback and read over
        # the read tier the Investigator's change channel uses.
        fetch_deployments=partial(
            fetch_recent_deployments, mitigation, read.get_change_events
        ),
        record_outcome=records.outcome,
        # The gate's question, answered by the autonomy policy rather than by
        # any agent - the Mitigator least of all, being the one it constrains.
        # Bound here rather than imported by the gate, so that the one check
        # standing between a proposal and production is asked of something a
        # test can replace with a refusal.
        admit=admit,
        attempts_per_subject=mitigation.mitigation_attempts_per_subject,
        take=partial(
            take_action,
            settings=mitigation,
            thresholds=thresholds,
            # Which arrival to wait for is chosen per action, so this binds the
            # choosing rather than a choice: until the change is in force the
            # minutes describe the code it was meant to replace, and a verdict read
            # off them is a verdict about the wrong deployment. Over the read tier,
            # since it is a read.
            arrivals=partial(arrival_of, rollouts=read.get_rollout_progress),
            # Every write that performs a mitigation, assembled once over the
            # one tier they all use. Separately was a value taken apart for
            # the journey and put back together by the callee, and it grew by a
            # parameter every time Argus learned a new thing to do.
            writes=writes,
            fetch_metrics=read.get_metrics_summary,
            # Where the alert rule that paged stands, which is what an action on
            # a series alert is judged by. Over the read tier, since it is a read.
            read_rule=read.get_alert_rule,
            # The agent's own binding rather than one assembled here, because
            # the worker wants the same one for a withdrawal - and two copies
            # of it is how one came to be missing a collaborator the other had.
            undo=undo
        ),
        # Over the same writes the action is then taken through, because a plan
        # is asked of the tier that writes from it: it is what that write
        # compares the estate with.
        plan_action=partial(plan_action, writes=writes),
        record_action=records.claim_action,
        complete_action=records.complete_action,
        already_taken=records.claimed_action,
        advance_action=records.advance_action,
        owe_a_put_back=records.owe_a_put_back,
        resuming=Resuming(
            # The write's own rule on the claim's plan, and whether a change
            # made still stands, both read over the writes the action is taken
            # through - the tier that compares is the tier that is asked.
            whether_it_was_made=partial(whether_it_was_made, writes=writes),
            still_argus_s=partial(still_argus_s, writes=writes),
            # The wait and the put-back from where an earlier worker stopped,
            # bound to what the live walk's own taking is bound to.
            watch=partial(
                watch_what_was_performed,
                settings=mitigation,
                thresholds=thresholds,
                fetch_metrics=read.get_metrics_summary,
                arrivals=partial(arrival_of, rollouts=read.get_rollout_progress),
                read_rule=read.get_alert_rule,
                undo=undo
            ),
            settle=partial(settle_the_refutation, undo=undo),
            announced=records.action_announced,
            plan_the_claim=records.plan_the_claim,
            metrics_window=timedelta(minutes=settings.metrics_window_minutes)
        ),
        acting_for=holding.acting_for,
        # Both tiers, because proposing a fix is the one act that spans them:
        # the repository is read from the process that cannot write, and the
        # branch and the draft pull request come from the one that can (§13).
        propose_fix=fixes_over(read, write, FixSettings.of(settings, vendors.model_settings),
                               conversations_through(models), recorder),
        actions_taken=records.actions_taken,
        recall_similar=_recalling(memory, store),
        # Filed whether or not this deployment searches memory: the store is a
        # view of the rows, and memory switched on later delivers them all.
        remember_incident=records.memory,
        write_postmortem=partial(
            write_postmortem_for,
            connections=connections,
            sources=sources,
            # The postmortem's own model and effort, bound here because
            # this is where an agent is assembled. It is the cheapest of
            # the three to serve and the clearest candidate for a lower
            # effort: one piece of prose, every figure already measured,
            # and no tools to explore with. The brief is the agent's, and
            # arrives inside the policy it hands out.
            client_for=partial(
                build_llm_client,
                models,
                policy=postmortem_policy(vendors.model_settings.postmortem_model,
                                         settings.postmortem_effort)
            ),
            judge_for=judging,
            recorder=recorder),
        record_postmortem=records.postmortem,
        # The postmortem's model and effort - one short paragraph, every figure
        # already worded - under no brief of the postmortem's.
        write_synopsis=partial(
            write_synopsis_for,
            connections=connections,
            sources=sources,
            client_for=partial(
                build_llm_client,
                models,
                policy=synopsis_policy(vendors.model_settings.postmortem_model,
                                       settings.postmortem_effort)
            ),
            judge_for=judging,
            address_of=partial(_the_page_of, settings.argus_base_url),
            recorder=recorder),
        record_synopsis=records.synopsis,
        transition_incident=records.transition,
        publisher=events_into(connections),
        recorder=recorder,
        ended_by_a_person=ended_by_a_person_via(connections),
        still_held=still_held_via(connections, holding),
        wait_for_people=waiting_for_people_via(connections, events_into(connections)),
        leads_of=records.leads,
        record_weighing=records.weighing,
        what_argus_did=records.what_argus_did,
        max_rounds=settings.investigation_max_rounds
    )


def the_sources_for(settings: Settings,
                    vendors: Vendors,
                    connections: Connections,
                    read: ReadTier,
                    thresholds: AnomalyThresholds) -> Sources:
    """Every source a postmortem reads, each answered by the provider this
    deployment is configured for.

    Each provider is handed only its own vendor's settings. A provider that
    never learns a credential's name cannot leak it into a postmortem, and one
    holding every vendor's would be able to read every credential Argus has in
    order to ask about money. Which is why this takes all of them, and is meant
    to: it is the narrowing itself, and the one place each provider's vendor is
    named. Binding a provider to its settings reaches nothing; each asks only
    when a postmortem does.
    """
    return the_real_sources(
        settings, connections, read, thresholds,
        # The worker reads the platform and never hears from it, so it holds
        # no webhook secret - an empty one refuses every delivery, and none
        # ever reaches this process to refuse.
        oncall=pagerduty_from(vendors.oncall, webhook_secret=""),
        charges=partial(charges_between, settings=vendors.revenue),
        published=partial(rates_published_for, settings=vendors.rates),
        bands=partial(pay_bands, vendors.pay_bands)
    )


def _the_page_of(argus_at: str, incident_id: str) -> str:
    """Where an incident's page is, as somebody outside Argus reaches it - or,
    where nobody configured that, as Argus's own pages address it."""
    return f"{argus_at.rstrip('/')}/incidents/{incident_id}"


def _recalling(settings: IncidentMemorySettings,
               store: VectorSearch | None) -> RecallSimilar:
    """What earlier incidents this one resembles, or nothing at all.

    Nothing where the process holds no store, and nothing where the store
    cannot answer. The two are the same answer on purpose: every decision
    recall informs has an answer without it, and an incident that stalled
    because a cache of old incidents was unreachable would be a worse system
    than one with no memory.

    Deliberately every exception. What can go wrong is a store that is down, a
    collection that does not exist yet, or a model that will not load, and none
    of them is a fact about the incident in front of the walk.
    """
    if store is None:
        return lambda dont_care_description, dont_care_service: []

    from incident_memory.recalling import recalling_from

    recall = recalling_from(
        store,
        an_embedder(settings.incident_memory_embedding_model),
        limit=settings.incident_memory_recall_limit,
        floor=settings.incident_memory_similarity_floor,
        attempts=settings.incident_memory_recall_attempts,
        retry_seconds=settings.incident_memory_recall_retry_seconds
    )

    def recall_what_it_can(described_as: str, service: str) -> list[RememberedIncident]:
        try:
            return recall(described_as, service)
        except Exception:
            _logger.warning("long-term memory could not be searched", exc_info=True)

            return []

    return recall_what_it_can
