"""The layering guard's own rules that import-linter cannot hold, asked of
graphs and sources built here.

Four rules. No package that walks an incident may reach a store the fence
cannot reach - a vector store, a chat platform's SDK - except recall's one read.
No module but a vendor's adapter may import that vendor's SDK. Both are about
third parties, which import-linter sees only with a setting that is global and
turns every other contract against the standard library. No module but a
vendor's adapter, a process's root and the debts listed may name that vendor
in code, which is no import at all. No module outside the walk, the worker's
root and the kernel may make an admission: the Mitigator imports the autonomy
policy for the type its write accepts, and import-linter cannot allow the type
and forbid `admit` beside it. And no process's root may import a workspace
package its process does not install, which is an extra of `apps` - something
import-linter cannot read at all. Their failure is silent, like every guard's:
a rule that stopped matching passes every build while the import it was
written against comes back. So each case builds the graph or the source it is
about, and asks the rule what it makes of it.

Built by hand rather than read from the workspace, because the cases are about
imports the workspace must not have.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario, the_answer_was
from grimp import ImportGraph

from scripts.guard_layering import (
    the_admissions_made_outside_the_walk,
    the_chains_to_a_store_the_fence_cannot_reach,
    the_processes_reaching_past_their_extra,
    the_stale_allowances,
    the_vendors_named_outside_their_adapter,
    the_vendors_spoken_past_their_adapter,
    the_workspace_packages_named_by,
    what_each_process_installs,
)

# The packages that walk an incident, the worker's root among them: it builds
# what the walk is handed, the store it searches included.
THE_WALK = {"apps.worker", "orchestrator"}

# The packages that are somebody else's, which the rule is about reaching.
THIRD_PARTIES = {"qdrant_client", "slack_sdk"}


@pytest.mark.unit
def test_a_walk_module_importing_the_vector_store_is_refused() -> None:
    # The import the rule exists for: the walk writing to the store itself,
    # where a write for a run another claim holds is one nothing refuses.
    Scenario() \
        .given(a_graph := _a_graph_with(("apps.worker.assembling", "qdrant_client"))) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([("apps.worker.assembling", "qdrant_client")]))


@pytest.mark.unit
def test_a_walk_module_reaching_the_vector_store_through_the_writing_side_is_refused() -> None:
    # Indirectly is no better: a walk that builds the writing side of the
    # adapter writes to the store as surely as one that holds the client.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("apps.worker.assembling", "vector_store_qdrant.indexing"),
            ("vector_store_qdrant.indexing", "qdrant_client")
        )) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([
            ("apps.worker.assembling", "vector_store_qdrant.indexing", "qdrant_client")
        ]))


@pytest.mark.unit
def test_a_walk_module_recalling_through_the_reading_side_passes() -> None:
    # Recall is a read, and a read for a lost run changes nothing anybody else
    # holds - which is why the worker's root may build the adapter's reading side.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("apps.worker.assembling", "vector_store_qdrant.searching"),
            ("vector_store_qdrant.searching", "qdrant_client")
        )) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([]))


@pytest.mark.unit
def test_a_way_to_the_writing_side_through_the_reading_side_is_refused() -> None:
    # The exemption is recall's own read of the store, and nothing more. A
    # reading side that came to import the writer would hand the walk the
    # writer through the one door it is allowed - and a rule that waved through
    # every chain passing the reading side would never say so.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("apps.worker.assembling", "vector_store_qdrant.searching"),
            ("vector_store_qdrant.searching", "vector_store_qdrant.indexing"),
            ("vector_store_qdrant.indexing", "qdrant_client")
        )) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([
            ("apps.worker.assembling", "vector_store_qdrant.searching",
             "vector_store_qdrant.indexing", "qdrant_client")
        ]))


@pytest.mark.unit
def test_a_walk_module_importing_the_chat_platforms_sdk_is_refused() -> None:
    # A message posted is a change nothing can undo, and the walk tells
    # people through the event log the relay reads - never by posting itself.
    Scenario() \
        .given(a_graph := _a_graph_with(("orchestrator.walk.mitigating", "slack_sdk"))) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([("orchestrator.walk.mitigating", "slack_sdk")]))


@pytest.mark.unit
def test_a_module_that_walks_nothing_may_import_the_vector_store() -> None:
    # The deliverer is the store's writer by design: it writes outside any run,
    # from rows the fence has already let through.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("apps.deliverer", "vector_store_qdrant.indexing"),
            ("vector_store_qdrant.indexing", "qdrant_client")
        )) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([]))


@pytest.mark.unit
def test_a_module_importing_a_vendors_sdk_past_its_adapter_is_refused() -> None:
    # Typing a store by the vendor's client again, which is how the port came
    # to be missing in the first place.
    Scenario() \
        .given(a_graph := _a_graph_with(("repository_index.store", "qdrant_client"))) \
        .when(lambda: the_vendors_spoken_past_their_adapter(a_graph)) \
        .then(_these_are_refused([("repository_index.store", "qdrant_client")]))


@pytest.mark.unit
def test_the_vendors_adapter_importing_its_sdk_passes() -> None:
    # The adapter is the one place the vendor is spoken: both of its sides.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("vector_store_qdrant.searching", "qdrant_client"),
            ("vector_store_qdrant.indexing", "qdrant_client")
        )) \
        .when(lambda: the_vendors_spoken_past_their_adapter(a_graph)) \
        .then(_these_are_refused([]))


@pytest.mark.unit
def test_a_module_reaching_a_vendors_sdk_through_its_adapter_passes() -> None:
    # A process's root builds the adapter, and the adapter speaks the vendor:
    # that is the port working, not reached past.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("apps.deliverer", "vector_store_qdrant.indexing"),
            ("vector_store_qdrant.indexing", "qdrant_client")
        )) \
        .when(lambda: the_vendors_spoken_past_their_adapter(a_graph)) \
        .then(_these_are_refused([]))


@pytest.mark.unit
def test_a_package_named_like_the_adapter_is_not_the_adapter() -> None:
    # The allowance is the adapter's package and what is inside it, never a
    # package whose name merely begins the same way.
    Scenario() \
        .given(a_graph := _a_graph_with(("vector_store_qdrant_tools.export", "qdrant_client"))) \
        .when(lambda: the_vendors_spoken_past_their_adapter(a_graph)) \
        .then(_these_are_refused([("vector_store_qdrant_tools.export", "qdrant_client")]))


@pytest.mark.unit
def test_the_model_vendors_sdk_named_past_its_adapter_is_refused() -> None:
    # How the port came to be missing: the factory named the SDK's client in
    # its own signature, so every caller of it held Anthropic's type.
    Scenario() \
        .given(a_graph := _a_graph_with(("core.llm.building", "anthropic"))) \
        .when(lambda: the_vendors_spoken_past_their_adapter(a_graph)) \
        .then(_these_are_refused([("core.llm.building", "anthropic")]))


@pytest.mark.unit
def test_the_model_vendors_adapter_importing_its_sdk_passes() -> None:
    # One module rather than a package, and the one place Anthropic is spoken.
    Scenario() \
        .given(a_graph := _a_graph_with(("core.llm.adapters.anthropic_adapter", "anthropic"))) \
        .when(lambda: the_vendors_spoken_past_their_adapter(a_graph)) \
        .then(_these_are_refused([]))


# The Mitigator's write, which accepts an admission and must never make one.
THE_MITIGATOR_S_WRITE = "mitigation.trying"


@pytest.mark.unit
def test_the_mitigator_naming_the_admission_it_accepts_passes() -> None:
    # The import the policy's narrow door exists for: the write names the type
    # it accepts, which is what makes an action nobody admitted a type error.
    Scenario() \
        .given(sources := {THE_MITIGATOR_S_WRITE: _a_module_reading(
            "from core.autonomy import Admitted")}) \
        .when(lambda: the_admissions_made_outside_the_walk(sources)) \
        .then(_these_admissions_are_refused([]))


@pytest.mark.unit
@pytest.mark.parametrize("reaching", [
    pytest.param(["from core.autonomy import admit"], id="imported"),
    pytest.param(["from core.autonomy import Admitted, admit as allowed"], id="renamed"),
    pytest.param(["from core.autonomy import *"], id="everything"),
    pytest.param(["from core.autonomy import _ADMISSION"], id="the-key"),
    pytest.param(["def taking() -> None:", "    from core.autonomy import admit"],
                 id="deferred")
])
def test_the_mitigator_importing_what_makes_an_admission_is_refused(reaching: list[str]) -> None:
    # `admit` takes the reach it judges by from its caller, so a Mitigator that
    # could call it would admit any declared kind wherever its action was
    # aimed. Refused however it is spelled, and at the line that spells it.
    Scenario() \
        .given(sources := {THE_MITIGATOR_S_WRITE: _a_module_reading(*reaching)}) \
        .when(lambda: the_admissions_made_outside_the_walk(sources)) \
        .then(_these_admissions_are_refused([(THE_MITIGATOR_S_WRITE, len(reaching))]))


@pytest.mark.unit
@pytest.mark.parametrize("binding", [
    pytest.param(("import core.autonomy", "core.autonomy"), id="by-path"),
    pytest.param(("import core.autonomy as policy", "policy"), id="aliased"),
    pytest.param(("from core import autonomy", "autonomy"), id="from-the-kernel"),
    pytest.param(("import core", "core.autonomy"), id="through-the-kernel"),
    # Any `import core.<x>` binds `core` itself, and the policy is reachable
    # through it once anything has loaded it - which the worker always has.
    pytest.param(("import core.models", "core.autonomy"), id="through-another-door")
])
def test_the_mitigator_referring_to_admit_on_the_policy_module_is_refused(
    binding: tuple[str, str]
) -> None:
    # The import alone names no `admit`; a reference to it does, on the line
    # after it - called or not, since a reference is what a call is made with.
    imported, referred_to_as = binding
    lines = [imported, f"{referred_to_as}.admit"]

    Scenario() \
        .given(sources := {THE_MITIGATOR_S_WRITE: _a_module_reading(*lines)}) \
        .when(lambda: the_admissions_made_outside_the_walk(sources)) \
        .then(_these_admissions_are_refused([(THE_MITIGATOR_S_WRITE, len(lines))]))


@pytest.mark.unit
@pytest.mark.parametrize("module", ["orchestrator.walk.mitigating", "apps.worker.assembling",
                                    "core.autonomy"])
def test_the_walk_its_root_and_the_kernel_may_make_an_admission(module: str) -> None:
    # The walk asks the policy, at the gate and again as the action is taken;
    # the worker's root binds it into what the walk is handed; the kernel is
    # where `admit` is written.
    Scenario() \
        .given(sources := {module: _a_module_reading("from core.autonomy import admit")}) \
        .when(lambda: the_admissions_made_outside_the_walk(sources)) \
        .then(_these_admissions_are_refused([]))


@pytest.mark.unit
@pytest.mark.parametrize("module", ["apps.web", "apps.workers"])
def test_another_root_may_not_make_an_admission(module: str) -> None:
    # The worker's root, and nothing else of `apps`: the web process admitting
    # an action would be a change made outside any walk. A root named like the
    # worker's is not the worker's.
    Scenario() \
        .given(sources := {module: _a_module_reading("from core.autonomy import admit")}) \
        .when(lambda: the_admissions_made_outside_the_walk(sources)) \
        .then(_these_admissions_are_refused([(module, 1)]))


# The workspace's packages, as `root_packages` would name them for these cases.
THE_WORKSPACE = frozenset({"apps", "communication", "core", "orchestrator", "telemetry",
                           "web_app"})

# The roots' own configuration, cut down to what a case is about: two base
# dependencies every root takes, and two processes' extras.
ROOTS = {
    "project": {
        "dependencies": ["argus-core", "argus-telemetry"],
        "optional-dependencies": {
            "web": ["argus-web_app", "uvicorn[standard]>=0.30"],
            "worker": ["argus-core[llm,mcp]", "argus-orchestrator", "psycopg-pool>=3.2"]
        }
    }
}


@pytest.mark.unit
def test_a_process_installs_its_extra_the_base_and_the_roots() -> None:
    # Workspace packages by import name, and third parties left out: a
    # distribution's name is not its import name.
    Scenario() \
        .when(lambda: what_each_process_installs(ROOTS)) \
        .then(the_answer_was({"web": {"apps", "core", "telemetry", "web_app"},
                              "worker": {"apps", "core", "telemetry", "orchestrator"}}))


@pytest.mark.unit
@pytest.mark.parametrize("requirement", ["argus-core", "argus-core[llm,mcp]",
                                         "argus-core>=0.1", "argus-core ; python_version>'3'"])
def test_a_workspace_package_is_named_whatever_its_extras_and_version(requirement: str) -> None:
    Scenario() \
        .when(lambda: the_workspace_packages_named_by([requirement])) \
        .then(the_answer_was({"core"}))


@pytest.mark.unit
def test_a_root_importing_what_its_process_installs_passes() -> None:
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("apps.web", "web_app.app"),
            ("apps.web", "telemetry"),
            ("apps.worker.process", "apps.worker.assembling"),
            ("apps.worker.assembling", "orchestrator.sources")
        )) \
        .when(lambda: the_processes_reaching_past_their_extra(
            a_graph, what_each_process_installs(ROOTS), THE_WORKSPACE)) \
        .then(_these_are_refused([]))


@pytest.mark.unit
def test_a_root_importing_what_another_process_installs_is_refused() -> None:
    # The failure the extras exist to prevent: the web process installing an
    # agent because its root reached for the walk.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("apps.web", "web_app.app"),
            ("apps.web", "orchestrator.entrypoint")
        )) \
        .when(lambda: the_processes_reaching_past_their_extra(
            a_graph, what_each_process_installs(ROOTS), THE_WORKSPACE)) \
        .then(_these_are_refused([("apps.web", "orchestrator")]))


@pytest.mark.unit
def test_a_root_whose_process_has_no_extra_is_refused_everything() -> None:
    # A process nobody can install: whatever it imports, nothing says it is
    # there.
    Scenario() \
        .given(a_graph := _a_graph_with(("apps.relay", "core"))) \
        .when(lambda: the_processes_reaching_past_their_extra(
            a_graph, what_each_process_installs(ROOTS), THE_WORKSPACE)) \
        .then(_these_are_refused([("apps.relay", "core")]))


@pytest.mark.unit
def test_a_root_importing_a_third_party_is_not_held_to_its_extra() -> None:
    # A distribution's name is not its import name, so the rule holds the
    # workspace's packages alone - which `root_packages` names, not the graph.
    Scenario() \
        .given(a_graph := _a_graph_with(("apps.web", "web_app.app"), ("apps.web", "uvicorn"))) \
        .when(lambda: the_processes_reaching_past_their_extra(
            a_graph, what_each_process_installs(ROOTS), THE_WORKSPACE)) \
        .then(_these_are_refused([]))


# A port, which names what Argus needs and no vendor that answers it.
THE_CHAT_PORT = "chat_platform.platform"
# The chat platform's adapter, named for its vendor.
THE_CHAT_ADAPTER = "chat_platform.slack_posting"
# A process's root, which builds every adapter it hands out.
THE_WEB_WIRING = "apps.web"
# The alerting platform's adapter, whose own vendor's wire names another vendor.
THE_ALERTING_ADAPTER = "alerting_platform.grafana"
# A module with a debt to pay: it names a vendor until the item named for it lands.
A_DEBTOR = "core.config"
# Nobody allowed to name any vendor, for the cases about who is.
NOBODY: frozenset[str] = frozenset()
# No module allowed a vendor beside its own, for the cases about other allowances.
NO_ALLOWANCES: dict[str, frozenset[str]] = {}


@pytest.mark.unit
@pytest.mark.parametrize(("naming", "named"), [
    # A port declaring the vendor's settings: swapping the adapter would mean
    # editing the port.
    pytest.param("class ChatSettings:\n    slack_bot_token: str", "slack_bot_token",
                 id="a-field"),
    pytest.param("def post_to_slack() -> None: ...", "post_to_slack", id="a-function"),
    pytest.param("async def post_to_slack() -> None: ...", "post_to_slack",
                 id="an-async-function"),
    pytest.param("class SlackThread:\n    pass", "SlackThread", id="a-class"),
    pytest.param("def post(slack_channel: str) -> None: ...", "slack_channel",
                 id="an-argument"),
    pytest.param("from chat_platform.slack import ChatSettings", "chat_platform.slack",
                 id="an-import"),
    pytest.param("import chat_platform.slack_posting", "chat_platform.slack_posting",
                 id="a-module-imported"),
    pytest.param("from chat_platform import Line as SlackLine", "SlackLine",
                 id="an-import-renamed"),
    pytest.param("SIGNED_BY = b'x-slack-signature'", "x-slack-signature", id="bytes"),
    pytest.param("built = settings.slack_base_url", "slack_base_url", id="an-attribute"),
    pytest.param("build(slack_channel='C1')", "slack_channel", id="a-keyword"),
    # A kernel enum's member stored with every report: adding a vendor would
    # mean editing the kernel and migrating what was stored.
    pytest.param("SLACK = 'chat'", "SLACK", id="an-enum-member"),
    pytest.param("CHANNEL = 'slack'", "slack", id="a-stored-value")
])
def test_a_port_naming_a_vendor_in_code_is_refused(naming: str, named: str) -> None:
    Scenario() \
        .given(sources := {THE_CHAT_PORT: _a_module_reading(naming)}) \
        .when(lambda: the_vendors_named_outside_their_adapter(sources, NOBODY)) \
        .then(_these_vendor_names_are_refused([(THE_CHAT_PORT, "slack", named)]))


@pytest.mark.unit
@pytest.mark.parametrize("spelled", ["'Argo CD'", "'argo_cd'", "'ArgoCD'", "'argo-cd'"])
def test_a_vendor_is_known_by_every_spelling_it_is_given(spelled: str) -> None:
    # Words may stand apart, or be joined by an underscore, a hyphen or a
    # change of case: each is the same vendor.
    Scenario() \
        .given(sources := {THE_CHAT_PORT: _a_module_reading(f"WHO = {spelled}")}) \
        .when(lambda: the_vendors_named_outside_their_adapter(sources, NOBODY)) \
        .then(_these_vendor_names_are_refused([(THE_CHAT_PORT, "argocd", spelled.strip("'"))]))


@pytest.mark.unit
@pytest.mark.parametrize(("said", "vendor"), [
    pytest.param("claude-opus-5-5", "anthropic", id="a-model"),
    pytest.param("rate(x[5m]) as PromQL says it", "prometheus", id="a-query-language"),
    pytest.param("BambooHR", "bamboohr", id="a-vendor-spelled-in-two-words")
])
def test_a_vendor_is_known_by_what_it_sells_as_well_as_by_its_name(said: str,
                                                                   vendor: str) -> None:
    Scenario() \
        .given(sources := {THE_CHAT_PORT: _a_module_reading(f"WHAT = {said!r}")}) \
        .when(lambda: the_vendors_named_outside_their_adapter(sources, NOBODY)) \
        .then(_these_vendor_names_are_refused([(THE_CHAT_PORT, vendor, said)]))


@pytest.mark.unit
def test_a_long_string_is_refused_at_the_line_that_names_the_vendor() -> None:
    # A query or a schema is one string over many lines, and the line to go to
    # is the one naming the vendor, not the one the string opens on.
    the_line_naming_it = "-- told in Slack"

    Scenario() \
        .given(sources := {THE_CHAT_PORT: _a_module_reading(
            'SCHEMA = """', "CREATE TABLE thread (id TEXT);", the_line_naming_it, '"""')}) \
        .when(lambda: the_vendors_named_outside_their_adapter(sources, NOBODY)) \
        .then(_these_vendor_names_are_refused_at([(THE_CHAT_PORT, 3, "slack",
                                                   the_line_naming_it)]))


@pytest.mark.unit
@pytest.mark.parametrize("naming", [
    pytest.param("unleashed = 1", id="an-identifier"),
    pytest.param("PATTERN = 'striped'", id="a-string"),
    pytest.param("Slackline = 1", id="a-capitalised-word")
])
def test_a_vendor_s_name_inside_another_word_passes(naming: str) -> None:
    # A vendor is named by whole words: `unleashed` is not Unleash, `striped`
    # is not Stripe, and `Slackline` is one word, not Slack and a line.
    Scenario() \
        .given(sources := {THE_CHAT_PORT: _a_module_reading(naming)}) \
        .when(lambda: the_vendors_named_outside_their_adapter(sources, NOBODY)) \
        .then(_these_vendor_names_are_refused([]))


@pytest.mark.unit
def test_a_module_that_does_not_parse_is_left_to_the_tools_that_say_so() -> None:
    # Ruff and mypy each refuse it first, and in words about the syntax; this
    # guard saying so too would bury theirs under a traceback of its own.
    Scenario() \
        .given(sources := {THE_CHAT_PORT: _a_module_reading("def slack(:")}) \
        .when(lambda: the_vendors_named_outside_their_adapter(sources, NOBODY)) \
        .then(_these_vendor_names_are_refused([]))


@pytest.mark.unit
@pytest.mark.parametrize("prose", [
    pytest.param('"""Slack is one platform a deployment may talk in."""', id="a-docstring"),
    pytest.param("# Slack is one platform a deployment may talk in.", id="a-comment"),
    pytest.param('def f() -> None:\n    "Slack, said to a reader."', id="a-bare-string")
])
def test_prose_naming_a_vendor_passes(prose: str) -> None:
    # An explanation of what an adapter does is not a coupling to it: the module
    # still speaks Argus's words.
    Scenario() \
        .given(sources := {THE_CHAT_PORT: _a_module_reading(prose)}) \
        .when(lambda: the_vendors_named_outside_their_adapter(sources, NOBODY)) \
        .then(_these_vendor_names_are_refused([]))


@pytest.mark.unit
def test_an_adapter_naming_its_own_vendor_passes() -> None:
    # The one place the vendor is spoken: a module named for it.
    Scenario() \
        .given(sources := {THE_CHAT_ADAPTER: _a_module_reading(
            "SLACK = 'Slack'", "def as_slack_says_it() -> None: ...")}) \
        .when(lambda: the_vendors_named_outside_their_adapter(sources, NOBODY)) \
        .then(_these_vendor_names_are_refused([]))


@pytest.mark.unit
def test_an_adapter_naming_another_vendor_is_refused() -> None:
    # An adapter is named for one vendor, and is that vendor's alone.
    Scenario() \
        .given(sources := {THE_CHAT_ADAPTER: _a_module_reading("PAGED_BY = 'PagerDuty'")}) \
        .when(lambda: the_vendors_named_outside_their_adapter(sources, NOBODY)) \
        .then(_these_vendor_names_are_refused([(THE_CHAT_ADAPTER, "pagerduty", "PagerDuty")]))


@pytest.mark.unit
def test_a_module_under_an_allowed_package_may_name_any_vendor() -> None:
    # The roots are a package, and a root may be a package too: the worker's
    # binds the walk's vendors in a module of its own.
    Scenario() \
        .given(sources := {"apps.worker.assembling": _a_module_reading(
            "from revenue_source.stripe_adapter import charges_between")}) \
        .when(lambda: the_vendors_named_outside_their_adapter(sources, {"apps"})) \
        .then(_these_vendor_names_are_refused([]))


@pytest.mark.unit
def test_an_allowed_module_may_name_any_vendor() -> None:
    # A process's root builds each adapter by its name, which is its job.
    Scenario() \
        .given(sources := {THE_WEB_WIRING: _a_module_reading(
            "from chat_platform.slack import slack_from",
            "from oncall_source.pagerduty_adapter import pagerduty_from")}) \
        .when(lambda: the_vendors_named_outside_their_adapter(sources, {THE_WEB_WIRING})) \
        .then(_these_vendor_names_are_refused([]))


@pytest.mark.unit
def test_an_adapter_may_say_another_vendor_s_name_its_own_vendor_s_wire_says() -> None:
    # A route of the alerting platform's is named for the metrics API it
    # serves: the adapter speaks its own vendor's wire, which happens to name
    # another vendor - and that vendor alone.
    Scenario() \
        .given(sources := {THE_ALERTING_ADAPTER: _a_module_reading(
            "STATE = '/api/prometheus/grafana/api/v1/rules'",
            "PAGED_BY = 'PagerDuty'")}) \
        .when(lambda: the_vendors_named_outside_their_adapter(
            sources, NOBODY, {THE_ALERTING_ADAPTER: frozenset({"prometheus"})})) \
        .then(_these_vendor_names_are_refused([(THE_ALERTING_ADAPTER, "pagerduty",
                                                "PagerDuty")]))


@pytest.mark.unit
def test_a_debt_covers_the_vendors_it_lists_and_no_other() -> None:
    # A module allowed one vendor until its item lands has not been allowed
    # the next one it starts naming.
    Scenario() \
        .given(sources := {A_DEBTOR: _a_module_reading(
            "slack_bot_token = ''", "pagerduty_api_key = ''")}) \
        .when(lambda: the_vendors_named_outside_their_adapter(
            sources, NOBODY, {A_DEBTOR: frozenset({"slack"})})) \
        .then(_these_vendor_names_are_refused([(A_DEBTOR, "pagerduty", "pagerduty_api_key")]))


@pytest.mark.unit
def test_an_allowance_naming_no_vendor_is_stale() -> None:
    # An allowance outliving its reason lets the next vendor in with nobody
    # having decided it should.
    Scenario() \
        .given(sources := {THE_WEB_WIRING: _a_module_reading("from chat_platform import Line")}) \
        .when(lambda: the_stale_allowances(sources, {THE_WEB_WIRING}, NO_ALLOWANCES)) \
        .then(_these_allowances_are_stale([THE_WEB_WIRING]))


@pytest.mark.unit
def test_an_allowance_for_a_module_that_is_not_there_is_stale() -> None:
    # A module renamed or removed takes its reason with it.
    Scenario() \
        .given(sources := {THE_CHAT_PORT: _a_module_reading("WHO = 'Slack'")}) \
        .when(lambda: the_stale_allowances(sources, {THE_WEB_WIRING}, NO_ALLOWANCES)) \
        .then(_these_allowances_are_stale([THE_WEB_WIRING]))


@pytest.mark.unit
def test_an_allowance_still_naming_a_vendor_is_not_stale() -> None:
    Scenario() \
        .given(sources := {THE_WEB_WIRING: _a_module_reading(
            "from chat_platform.slack import slack_from")}) \
        .when(lambda: the_stale_allowances(sources, {THE_WEB_WIRING}, NO_ALLOWANCES)) \
        .then(_these_allowances_are_stale([]))


@pytest.mark.unit
def test_a_debt_s_vendor_no_longer_named_is_stale() -> None:
    # Paid off in part: the vendor the module stopped naming goes from its
    # list, or it could come back with nobody deciding it should.
    Scenario() \
        .given(sources := {A_DEBTOR: _a_module_reading("slack_bot_token = ''")}) \
        .when(lambda: the_stale_allowances(
            sources, NOBODY, {A_DEBTOR: frozenset({"pagerduty", "slack"})})) \
        .then(_these_allowances_are_stale([f"{A_DEBTOR}: pagerduty"]))


@pytest.mark.unit
def test_another_vendor_s_name_an_adapter_no_longer_says_is_stale() -> None:
    # Its vendor's wire stopped naming the other vendor; the allowance would
    # otherwise let that vendor back into the adapter unnoticed.
    Scenario() \
        .given(sources := {THE_ALERTING_ADAPTER: _a_module_reading(
            "STATE = '/api/v1/rules'")}) \
        .when(lambda: the_stale_allowances(
            sources, NOBODY, {THE_ALERTING_ADAPTER: frozenset({"prometheus"})})) \
        .then(_these_allowances_are_stale([f"{THE_ALERTING_ADAPTER}: prometheus"]))


def _these_vendor_names_are_refused(
    expected: list[tuple[str, str, str]]
) -> Assertion[list[tuple[str, int, str, str]]]:
    """Exactly these, as the module, the vendor and what named it - the line
    being whichever the one-line source put it on."""
    def assertion(refused: list[tuple[str, int, str, str]]) -> bool:
        named = [(module, vendor, said) for module, _, vendor, said in refused]

        if named != expected:
            raise AssertionError(f"Expected {expected} refused, got {named}.")

        return True

    return assertion


def _these_vendor_names_are_refused_at(
    expected: list[tuple[str, int, str, str]]
) -> Assertion[list[tuple[str, int, str, str]]]:
    """Exactly these, line included."""
    def assertion(refused: list[tuple[str, int, str, str]]) -> bool:
        if refused != expected:
            raise AssertionError(f"Expected {expected} refused, got {refused}.")

        return True

    return assertion


def _these_allowances_are_stale(expected: list[str]) -> Assertion[list[str]]:
    def assertion(stale: list[str]) -> bool:
        if stale != expected:
            raise AssertionError(f"Expected the allowances {expected} stale, got {stale}.")

        return True

    return assertion


def _a_module_reading(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _these_admissions_are_refused(expected: list[tuple[str, int]]
                                  ) -> Assertion[list[tuple[str, int]]]:
    def assertion(refused: list[tuple[str, int]]) -> bool:
        if refused != expected:
            raise AssertionError(
                f"Expected the admissions at {expected} refused, got {refused}."
            )

        return True

    return assertion


def _a_graph_with(*imports: tuple[str, str]) -> ImportGraph:
    """A graph holding these imports and the packages around them, with the
    third parties in it as grimp builds them with externals: one squashed
    module per package."""
    graph = ImportGraph()

    for importer, imported in imports:
        for module in (importer, imported):
            for package in _the_packages_down_to(module):
                if package not in graph.modules:
                    graph.add_module(package, is_squashed=package in THIRD_PARTIES)

        graph.add_import(importer=importer, imported=imported)

    return graph


def _the_packages_down_to(module: str) -> list[str]:
    """`a`, `a.b` and `a.b.c` for `a.b.c`: a module is in a graph with every
    package it sits in, which is what lets a rule ask about a package whole."""
    parts = module.split(".")

    return [".".join(parts[:depth]) for depth in range(1, len(parts) + 1)]


def _these_are_refused(expected: list[tuple[str, ...]]) -> Assertion[list[tuple[str, ...]]]:
    def assertion(refused: list[tuple[str, ...]]) -> bool:
        if refused != expected:
            raise AssertionError(f"Expected the chains {expected} refused, got {refused}.")

        return True

    return assertion
