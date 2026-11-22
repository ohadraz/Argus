#!/usr/bin/env python3
"""
Fails if a module imports something its layer is not allowed to know about, or
if a test reaches into the kernel by module path.

Runs the import-linter contracts declared in the root `pyproject.toml` -
`core` depends on nothing in this workspace, `incident_record` knows only
the kernel, `web_app` serves HTML without installing an agent, and the kernel
is reached through its front doors. The contracts are the check on a claim
`CLAUDE.md` has made since before it was true.

First it checks the contracts can see every module. `root_packages` is the one
list import-linter takes no wildcard for, so a module missing from it is not
analyzed at all - and a package no contract can see is a package no contract can
be broken by. That is the failure this whole file exists to prevent, arriving
through the file that prevents it.

Then it checks the suites, which the contracts cannot. import-linter analyzes
the packages named in `root_packages`, and a test package is not one of them -
so the front-door rule would hold across every module in the workspace and be
silently unenforced in the 113 files that had to be converted by hand. The same
blindness let one agent's suite build a double out of another agent's code
while the independence contract held, so both rules are carried over the suites
here. Both read their membership from the contract that argues it rather than
restating it: two lists of one thing is one of them going stale.

And it holds the walk to the half of its own contract that import-linter cannot
see: no package that walks an incident reaches a vendor's SDK for a store the
fence cannot reach. And it holds every module to a vendor's SDK being imported
by that vendor's adapter alone. import-linter sees a third party only with
`include_external_packages`, which is global, and turns every `["*"]` contract
against the standard library - so the graph with third parties in it is built
here, for these two rules alone.

And it holds every vendor's *name* to its adapter, which is not an import at all:
a port declaring the vendor's settings, a kernel enum with a member per vendor,
a stored value spelled for one, an agent reading the vendor's setting. Nothing
shipped names a vendor in code - an identifier or a string, prose aside - but
the module named for it, each process's root (`apps`), and the debts listed
with what clears each.

And it holds who may make an admission, which import-linter cannot say either.
The Mitigator imports the autonomy policy (`core.autonomy`) because its write
accepts only an `Admitted`, and import-linter allows a module or forbids it -
it cannot allow the type and forbid `admit` beside it. A Mitigator that could
call `admit` could hand it any reach it liked, and admit any declared kind
anywhere; so outside the walk, the worker's root that binds the walk, and the
kernel, nothing names `admit`, imports everything from the policy, or reaches a
private name of it.

And it holds each process's root to what its process installs. The roots are
one package, `apps`, with one extra per process (`argus-apps[web]`, ...), so
that installing the web process installs no agent - and import-linter cannot
read an extra. So every module under `apps.<process>` imports only the
workspace packages that extra, or the package's own dependencies, name.

And it holds that only a process's root reads the environment, which is a name
rather than an import: the kernel's settings, a connection to the database they
name, `os.environ` and its kin, and any class built on `BaseSettings` - found by
following class bases across the workspace - used anywhere that ships outside
`apps`, with or without arguments, or handed on to be called. A library that
read for itself would read what the root that started its process cannot see,
and a test wanting another value would have to change the environment to say
so. Where each reader is defined is allowed, with its reason, and an allowance
that no longer reads anything is reported. And the kernel's settings declare no
field any adapter's settings declare - a model's name or a namespace as much as
a `SLACK_` token - since a field in both is a second place to configure the
vendor, and one every slice of the kernel's could reach.

A script rather than the `lint-imports` shim, for the reason every other tool
here is invoked as a module: going through the interpreter avoids the
locally-generated `.exe` stubs in `.venv/Scripts/`, which Windows Smart App
Control has blocked before. See the `smart-app-control-blocks` skill.
"""
import ast
import re
import sys
import tomllib
from collections.abc import Collection, Iterable, Iterator, Mapping
from io import TextIOWrapper
from pathlib import Path
from typing import Any

import grimp
from grimp import ImportGraph
from importlinter.cli import lint_imports_command

REPOSITORY = Path(__file__).resolve().parent.parent
MODULES = REPOSITORY / "modules"


def _say_it_in_utf8() -> None:
    """Makes the output encodable wherever it is being sent.

    import-linter draws its progress through `rich`, whose spinner carries an
    emoji. On Windows `rich` takes a legacy-console path that encodes with the
    machine's codepage rather than UTF-8, and a codepage that cannot represent
    the emoji - cp1255 here - raises `UnicodeEncodeError` mid-render. The
    process then exits 1 having checked every contract and found nothing wrong.

    Which is the worst shape a guard can fail in: it depends on where the
    output is going, so it passes when a person runs it and fails when a script
    redirects it, and the failure names an encoding rather than a contract. A
    reader who believed it would go looking for an import that was never there.

    Asked whether each stream is a real one rather than cast to one. `stdout`
    is a `TextIOWrapper` when it is attached to a console or a file and
    something else entirely when it is captured - and a cast would trade a
    check that mypy can make for an `AttributeError` raised by the very line
    that exists to stop this guard failing on its output.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
CONFIGURATION = REPOSITORY / "pyproject.toml"

KERNEL = "core"
FRONT_DOOR_CONTRACT = "the kernel is reached through its front doors, not by module path"
INDEPENDENCE_CONTRACT = "an agent knows the kernel and its own sources, never another agent"
WALK_CONTRACT = "the walk writes to no store the fence cannot reach"

# The vendors' SDKs a walk may not reach: the vector store long-term memory is
# searched in, and the chat platform people are told in. Neither has a fence, so
# a write through either from a walk whose run was taken back is a write nothing
# refuses. Named here rather than in the contract, which would see a third party
# only with `include_external_packages` - a setting that is global.
STORES_THE_FENCE_CANNOT_REACH = ("qdrant_client", "slack_sdk")

# The one way a walk reaches one of them, and why it may: recall reads, and a
# read made for a run since taken back changes nothing anybody else holds. The
# reading side of the store's adapter is what the worker's root builds, and
# nothing beyond it - the writing side reaches the same SDK, and is the
# contract's to forbid.
THE_WAY_RECALL_READS = ("vector_store_qdrant.searching", "qdrant_client")

# Each vendor's SDK, by the one package allowed to import it: the adapter named
# for that vendor. Anything else importing the SDK is reaching past the port -
# typing a store by the vendor's client again, which is how the port came to be
# missing in the first place. Held here rather than by a contract for the reason
# the walk's SDK rule is: import-linter sees a third party only with
# `include_external_packages`, which is global (see the docstring above).
SPOKEN_ONLY_BY_ITS_ADAPTER = {
    "qdrant_client": "vector_store_qdrant",
    "anthropic": "llm_anthropic",
    "fastembed": "embedding_fastembed"
}

# The kernel's own suite, exempt for the reason the kernel itself is: it tests
# the modules behind the front doors, and a test that could only reach them
# through one could not test them at all.
THE_KERNELS_OWN_SUITE = "modules/core/tests"

# The autonomy policy, and the one name in it that makes an admission.
AUTONOMY = "core.autonomy"
ADMIT = "admit"

# Who may make one: the walk, whose gate and mitigation node ask the policy; the
# worker's root, which binds the policy into what the walk is handed; and the
# kernel, where it is written. Each is a package and everything under it.
# Everybody else may name `Admitted` - the Mitigator's write accepts nothing
# else - and never `admit`, since `admit` takes the reach it judges by from its
# caller: a Mitigator that called it with the address its own action names
# would admit that action wherever it was aimed.
WHO_MAY_ADMIT = frozenset({"orchestrator", "apps.worker", KERNEL})

# The package every process's root lives in, its configuration, and how a
# workspace package is named as a distribution.
APPS = "apps"
APPS_CONFIGURATION = MODULES / APPS / "pyproject.toml"
WORKSPACE_DISTRIBUTION = "argus-"

# Every vendor Argus speaks to, by each spelling code gives it, as the words it
# is made of. Code and strings alike are read as words - split at an underscore,
# a hyphen, a space or a change of case, so `ArgoCd`, `argo_cd`, `"argo-cd"` and
# `"Argo CD"` are each `argo cd` - and a spelling is found only as whole words in
# a row: `unleashed` and `striped` name nobody. PromQL is Prometheus's language
# and Claude is Anthropic's models, each named for its vendor. A vendor is
# spoken by its adapter, and an adapter is a module named for it - so a name or
# a string carrying one anywhere else is the vendor leaking past its port.
VENDORS = {
    "anthropic": ("anthropic", "claude"),
    "argocd": ("argocd", "argo cd"),
    "bamboohr": ("bamboohr", "bamboo hr"),
    "frankfurter": ("frankfurter",),
    "github": ("github", "git hub"),
    "grafana": ("grafana",),
    "langfuse": ("langfuse",),
    "pagerduty": ("pagerduty", "pager duty"),
    "prometheus": ("prometheus", "promql", "prom ql"),
    "qdrant": ("qdrant",),
    "slack": ("slack",),
    "stripe": ("stripe",),
    "unleash": ("unleash",)
}

# A word, as `VENDORS` reads one: a run of capitals not starting a capitalised
# word (`CD` in `ArgoCD`), a word with or without its capital, or a number.
WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")

# What reads the environment by name: the kernel's settings, a connection to the
# database the environment names, and the environment itself. A process's root
# reads them, once, and hands each library the part it reads; anywhere else one
# is a service locator, reached through a default argument as often as through
# a call.
READS_THE_ENVIRONMENT = frozenset({"get_settings", "connect_from_env",
                                   "environ", "environb", "getenv", "getenvb"})

# What every class that reads its fields from the environment is built on,
# directly or through another such class - the kernel's `Settings`, the base for
# an adapter's (`core.AdapterSettings`) and every adapter's own. Using one is
# reading the environment whatever it is handed: each field it is not handed
# comes from there. A slice is not one, and is built from what it is handed.
READS_ITS_FIELDS_FROM_THE_ENVIRONMENT = "BaseSettings"

# The kernel's own settings, by module and class, and the base every adapter's
# settings are declared on: no field of the one is a field of any class built
# on the other.
KERNEL_SETTINGS = ("core.config", "Settings")
ADAPTER_SETTINGS = "AdapterSettings"

# The one annotation whose arguments are not all types: the first is, and what
# follows it is metadata - often a call, which builds something.
ANNOTATED = "Annotated"

# Where the environment is read outside a root, and why each may. Each covers its
# whole module, so one that no longer reads anything is reported as stale.
READ_WHERE_DEFINED = {
    "core.__init__": "the kernel's export list, which names both readers",
    "core.config": "defines `get_settings` and the settings it reads",
    "core.db": "defines `connect_from_env`, the suites' and the scripts' connection - "
               "named by no shipped module but this one and the kernel's export list",
    "core.migrations.env": "Alembic's own entry script, which nothing hands a parameter: "
                           "`alembic revision` runs it with "
                           "no root at all, and under the schema job it reads the settings "
                           "`apps.schema` already read, `get_settings` being cached",
    "core.timestamps": "the clock the stack runs on, named once, before anything runs - "
                       "every module's timestamps read it at import"
}

# Each process's root, and everything beneath it: where adapters are built and
# handed out as their ports, which is the one job that has to name every vendor
# it builds. The same package the composition-root contract lets import every
# adapter.
WIRING = frozenset({APPS})

# What still names a vendor outside its adapter: which vendors, and what takes
# them away. An allowance is a debt with a name on it, and covers the vendors it
# lists and no other - a module allowed GitHub that starts naming Slack is
# refused - and each vendor the module stops naming is reported as stale and
# must go from the list. Empty: every debt is paid.
NOT_YET: dict[str, tuple[frozenset[str], str]] = {}

# Another vendor's name an adapter has to say because its own vendor's wire
# says it, by adapter: a route of Grafana's is named for the Prometheus-
# compatible API it serves. The adapter may say that vendor's name and no other;
# reported stale the day it no longer does.
SAID_ON_ITS_VENDOR_S_WIRE = {
    "alerting_platform.grafana": frozenset({"prometheus"})
}

# A vendor's name in an address somebody outside the repository configured, by
# the module that serves it: the web application's routes the Slack app and the
# repository's webhook post to. Renaming one breaks a live deployment until both
# are edited, and buys no decoupling - each route is one sender's door, as
# `/webhooks/alerts/{source}` is - so they stay, by decision rather than as a
# debt; reported stale the day the module no longer says them.
CONFIGURED_OUTSIDE = {
    "web_app.app": frozenset({"github", "slack"})
}

# Every vendor a module may name beside its own, by module: the debts, the words
# an adapter's wire says and the addresses configured outside, held to the same
# rule.
ALLOWED_BESIDE_ITS_OWN: dict[str, frozenset[str]] = {
    module: (NOT_YET[module][0] if module in NOT_YET else frozenset())
    | SAID_ON_ITS_VENDOR_S_WIRE.get(module, frozenset())
    | CONFIGURED_OUTSIDE.get(module, frozenset())
    for module in NOT_YET.keys() | SAID_ON_ITS_VENDOR_S_WIRE.keys() | CONFIGURED_OUTSIDE.keys()
}


def _the_modules_on_disk() -> set[str]:
    """Every package under `modules/` that a contract could have an opinion about.

    `modules/` alone: what lives in `test_support/` - the testkit and the doubles -
    is never imported by anything that ships, and a contract naming it would be a
    contract about the suites.
    """
    return {
        directory.name
        for directory in MODULES.iterdir()
        if directory.is_dir() and (directory / "pyproject.toml").exists()
    }


def _the_contracts() -> list[dict[str, object]]:
    """The contracts as `pyproject.toml` declares them."""
    with CONFIGURATION.open("rb") as configuration:
        contracts = tomllib.load(configuration)["tool"]["importlinter"]["contracts"]

        return list(contracts)


def _the_modules_the_contracts_see() -> set[str]:
    """What `root_packages` names - the whole of what import-linter will analyze."""
    with CONFIGURATION.open("rb") as configuration:
        return set(tomllib.load(configuration)["tool"]["importlinter"]["root_packages"])


def _the_front_doors() -> dict[str, set[str]]:
    """Every kernel module anything may name, by the module allowed to name it.

    Read from the contract rather than listed again here: a second list would be
    a second place to add a door to, and the failure it produces is a suite
    refused an import the source tree is allowed.

    Two shapes. `** -> core.models` is a door anything may use.
    `mitigation.** -> core.autonomy` is one only the modules it names may, and a
    suite is held to its own module's allowance as its source is: a door is
    narrowed for what reaching it would let a module do, and a test of that
    module can do it as well.

    Keyed by module name, with `""` holding the doors open to everything.
    """
    for contract in _the_contracts():
        if contract.get("name") != FRONT_DOOR_CONTRACT:
            continue

        allowances = contract.get("ignore_imports", [])

        if not isinstance(allowances, list):
            break

        doors: dict[str, set[str]] = {"": {KERNEL}}

        for allowance in allowances:
            importer, _, door = str(allowance).partition("->")
            importer, door = importer.strip(), door.strip()

            if not door.startswith(KERNEL):
                continue

            whose = "" if importer == "**" else importer.removesuffix(".**")
            doors.setdefault(whose, set()).add(door)

        return doors

    print(
        f"no contract named [{FRONT_DOOR_CONTRACT}] in pyproject.toml, so the "
        "front doors cannot be read and the suites cannot be checked against them.",
        file=sys.stderr,
    )
    sys.exit(1)


def _the_independent_modules() -> set[str]:
    """The packages the independence contract says know nothing of each other.

    Read from the contract for the reason the front doors are: the contract is
    where the membership is argued, and a second list here is the one that goes
    stale the day a sixth agent is written.
    """
    for contract in _the_contracts():
        if contract.get("name") != INDEPENDENCE_CONTRACT:
            continue

        modules = contract.get("modules", [])

        if isinstance(modules, list):
            return {str(module) for module in modules}

        break

    print(
        f"no contract named [{INDEPENDENCE_CONTRACT}] in pyproject.toml, so the "
        "agents cannot be read and their suites cannot be held apart.",
        file=sys.stderr,
    )
    sys.exit(1)


def _the_walk() -> set[str]:
    """The packages that walk an incident, as the walk's contract names them.

    Read from the contract for the reason the agents are: the contract is where
    the membership is argued, and the rule over the SDKs is the same rule's
    other half.
    """
    for contract in _the_contracts():
        if contract.get("name") != WALK_CONTRACT:
            continue

        modules = contract.get("source_modules", [])

        if isinstance(modules, list):
            return {str(module) for module in modules}

        break

    print(
        f"no contract named [{WALK_CONTRACT}] in pyproject.toml, so the packages "
        "that walk an incident cannot be read and held to it.",
        file=sys.stderr
    )
    sys.exit(1)


def the_chains_to_a_store_the_fence_cannot_reach(
    graph: ImportGraph, walk: Iterable[str]
) -> list[tuple[str, ...]]:
    """Every way a package that walks an incident reaches a store with no fence.

    Each chain begins in one of `walk` and ends at one of the SDKs, directly or
    through anything in between - a walk calling the store's writer writes as
    surely as one holding the client. Recall's one read is taken out of `graph`
    first, so a chain that ends in it is no chain; `graph` is changed by that,
    and is the caller's to have built for this.

    Empty where the walk holds to the rule, which is the whole of what passing
    means.
    """
    reader, read = THE_WAY_RECALL_READS

    if reader in graph.modules and graph.direct_import_exists(importer=reader, imported=read):
        graph.remove_import(importer=reader, imported=read)

    return sorted(
        chain
        for package in sorted(walk) if package in graph.modules
        for store in STORES_THE_FENCE_CANNOT_REACH if store in graph.modules
        for chain in graph.find_shortest_chains(importer=package, imported=store)
    )


def the_vendors_spoken_past_their_adapter(graph: ImportGraph) -> list[tuple[str, str]]:
    """Every module that imports a vendor's SDK without being its adapter, with
    the SDK it imports.

    Direct imports only: a module reaching the SDK through its adapter is using
    the port's other side, which is what the adapter is for. Empty where every
    SDK is spoken by its adapter alone.
    """
    return sorted(
        (importer, vendor)
        for vendor, adapter in SPOKEN_ONLY_BY_ITS_ADAPTER.items() if vendor in graph.modules
        for importer in graph.find_modules_that_directly_import(vendor)
        if importer != adapter and not importer.startswith(f"{adapter}.")
    )


def _the_whole_graph() -> ImportGraph:
    """The workspace's import graph with the third parties in it - built here
    and nowhere else, because import-linter's would then hold every one of its
    contracts against them too."""
    return grimp.build_graph(
        *sorted(_the_modules_the_contracts_see()),
        include_external_packages=True,
        cache_dir=None
    )


def _every_vendor_is_spoken_by_its_adapter_alone() -> None:
    """Refuses a module that reaches a vendor's SDK past the port."""
    spoken = the_vendors_spoken_past_their_adapter(_the_whole_graph())

    if spoken:
        print(
            "these import a vendor's SDK that only its adapter may:\n"
            + "\n".join(
                f"  {importer} -> {vendor}\n      only {SPOKEN_ONLY_BY_ITS_ADAPTER[vendor]} may"
                for importer, vendor in spoken
            )
            + "\nHold the port, and let the process's root build the adapter.",
            file=sys.stderr
        )
        sys.exit(1)


def _the_walk_reaches_no_store_the_fence_cannot_reach(walk: set[str]) -> None:
    """Refuses a walk that can write somewhere the fence cannot stop it, over the
    graph of the whole workspace with the third parties in it."""
    reached = the_chains_to_a_store_the_fence_cannot_reach(_the_whole_graph(), walk)

    if reached:
        print(
            "these reach a store the fence cannot reach, from a package that walks "
            "an incident:\n"
            + "\n".join(f"  {' -> '.join(chain)}" for chain in reached)
            + "\nThe walk files what it means to keep as a row, and tells people "
              "through the event log.",
            file=sys.stderr
        )
        sys.exit(1)


def _the_packages_named_by(path: Path) -> list[tuple[int, str]]:
    """The top-level package of everything this file imports, however it does it.

    Both spellings, because both reach: `import investigation_agent` and
    `from investigation_agent.reasoning import ...` are the same edge, and the
    one that actually appeared in this workspace was the second.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []  # not this guard's complaint; ruff and mypy both say so first

    named: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None and not node.level:
            named.append((node.lineno, node.module.partition(".")[0]))
        elif isinstance(node, ast.Import):
            named.extend((node.lineno, alias.name.partition(".")[0])
                         for alias in node.names)

    return named


def _the_suites_keep_the_agents_apart(independent: set[str]) -> None:
    """Refuses a suite that borrows from an agent its module does not know.

    The other half of the independence contract, applied where the contract
    cannot see. import-linter analyzes `root_packages`, and a test package is
    not one - so an agent's suite could build its doubles out of a sibling
    agent's code and the contract would hold while the double modelled a shape
    the real collaborator does not have. That is not hypothetical: it is how
    this rule came to be written.

    Only the suites of the independent modules are walked, so `orchestrator`'s
    - which imports four agents legitimately, because delegating to them is
    what it does - is outside this by construction rather than by exemption.
    """
    borrowed = [
        (path, lineno, named, whose)
        for whose in sorted(independent)
        for path in sorted((MODULES / whose / "tests").rglob("*.py"))
        for lineno, named in _the_packages_named_by(path)
        if named in independent - {whose}
    ]

    if borrowed:
        print(
            "these suites reach into an agent their own module does not know:\n"
            + "\n".join(
                f"  {path.relative_to(REPOSITORY).as_posix()}:{lineno} -> {named}"
                f"\n      {whose} is independent of it"
                for path, lineno, named, whose in borrowed
            )
            + "\nWhat two agents both need belongs in `core`.",
            file=sys.stderr,
        )
        sys.exit(1)


def _the_doors_open_to(path: Path, doors: dict[str, set[str]]) -> set[str]:
    """Which doors this file may go through.

    A file under `modules/<module>/tests/` or `test_support/<module>/tests/` is
    that module's, and gets the doors its module took plus the ones open to
    everything. Everything else - the root `tests/` tree, `scripts/` - runs
    against the workspace environment, where every extra is installed, so it
    gets all of them.
    """
    parts = path.relative_to(REPOSITORY).parts

    if len(parts) > 2 and parts[0] in ("modules", "test_support") and parts[2] == "tests":
        return doors[""] | doors.get(parts[1], set())

    return set().union(*doors.values())


def _every_module_is_analyzed() -> None:
    """Refuses to report on a graph that does not contain the whole workspace.

    Reported as a failure rather than added silently, because which layer a new
    module belongs to is a decision somebody has to make: adding it here would
    mean guessing, and guessing it into the analysis is how a module ends up
    quietly allowed to import anything.
    """
    unseen = _the_modules_on_disk() - _the_modules_the_contracts_see()

    if unseen:
        print(
            "these modules are not named in `root_packages`, so no contract can "
            "see them:\n"
            + "\n".join(f"  {module}" for module in sorted(unseen))
            + "\nAdd them to `[tool.importlinter] root_packages` in pyproject.toml.",
            file=sys.stderr,
        )
        sys.exit(1)


def _every_suite_file() -> list[Path]:
    """Every test file the front-door rule applies to.

    `scripts/` is here too. It is not a suite, but it is the other tree
    import-linter never sees, and a rule that held everywhere except the one
    directory nothing checks is the rule already described in `CLAUDE.md` and
    not enforced.
    """
    return [
        path
        for path in [
            *sorted((REPOSITORY / "tests").rglob("*.py")),
            *sorted((REPOSITORY / "scripts").rglob("*.py")),
            *sorted(REPOSITORY.glob("modules/*/tests/**/*.py")),
            *sorted(REPOSITORY.glob("test_support/*/tests/**/*.py"))
        ]
        if THE_KERNELS_OWN_SUITE not in path.as_posix()
    ]


def _the_paths_reached_into(path: Path, doors: set[str]) -> list[tuple[int, str]]:
    """Every kernel module this file names that is not a front door.

    Every import is walked rather than the top-level ones alone: a deferred
    import inside a function reaches exactly as far as one at the top, and is
    where the last of them hid when the source tree was converted.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []  # not this guard's complaint; ruff and mypy both say so first

    return [
        (node.lineno, node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and (node.module == KERNEL or node.module.startswith(f"{KERNEL}."))
        and node.module not in doors
    ]


def _the_suites_use_the_front_doors(doors: dict[str, set[str]]) -> None:
    """Refuses a suite that reaches past a front door into the kernel's insides.

    The same rule the contract holds the source tree to, applied where the
    contract cannot see. Reported with the file, the line and the doors that
    file may actually use, because a door narrowed to certain modules makes
    "which doors" a different answer per suite.
    """
    reached = [
        (path, lineno, module, open_to)
        for path in _every_suite_file()
        for open_to in [_the_doors_open_to(path, doors)]
        for lineno, module in _the_paths_reached_into(path, open_to)
    ]

    if reached:
        print(
            "these reach into the kernel by module path rather than through a "
            "front door:\n"
            + "\n".join(
                f"  {path.relative_to(REPOSITORY).as_posix()}:{lineno} -> {module}"
                f"\n      open to it: {', '.join(sorted(open_to))}"
                for path, lineno, module, open_to in reached
            ),
            file=sys.stderr,
        )
        sys.exit(1)


def _the_commits_in(path: Path) -> list[int]:
    """The line of every `.commit(` call in this file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []  # not this guard's complaint; ruff and mypy both say so first

    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "commit"
    ]


def _no_repository_commits() -> None:
    """Refuses a repository function that commits.

    A transaction belongs to whoever opened it (`core.unit_of_work`). A
    repository that commits ends its caller's unit part-way through, so a
    failure after it undoes only the half that came later - and inside a
    transaction block the commit is refused outright, so the function can
    never be part of a larger operation at all.
    """
    commits = [
        (path, lineno)
        for path in sorted(MODULES.glob("*/src/**/repository/**/*.py"))
        for lineno in _the_commits_in(path)
    ]

    if commits:
        print(
            "these repository functions commit, which is their caller's to do:\n"
            + "\n".join(
                f"  {path.relative_to(REPOSITORY).as_posix()}:{lineno}"
                for path, lineno in commits
            ),
            file=sys.stderr
        )
        sys.exit(1)


def the_admissions_made_outside_the_walk(sources: Mapping[str, str]) -> list[tuple[str, int]]:
    """Every place a module outside the walk, the worker's root and the kernel
    reaches `admit`, as the module and the line.

    `sources` is each module's source, keyed by its dotted name - which is what
    says whose it is. Reaching is any spelling that gets `admit` called: importing
    it from the policy under any name, importing everything from it, or naming it
    as an attribute of the policy however the policy was bound - `import
    core.autonomy`, `import core.autonomy as x`, `from core import autonomy`. A
    private name of the policy counts too, since the key is how an admission is
    built without `admit`. Every import is walked, deferred ones included, as
    the front-door rule walks them.

    Empty where only the walk admits, which is the whole of what passing means.
    """
    return sorted(
        (module, lineno)
        for module, source in sources.items()
        if not _is_within(module, WHO_MAY_ADMIT)
        for lineno in _the_admissions_in(source)
    )


def _is_within(module: str, packages: Iterable[str]) -> bool:
    """Whether `module` is one of `packages` or anything beneath one."""
    return any(module == package or module.startswith(f"{package}.") for package in packages)


def _makes_an_admission(name: str) -> bool:
    """Whether naming `name` of the policy reaches what makes an admission."""
    return name in (ADMIT, "*") or name.startswith("_")


def _the_dotted_name_of(node: ast.expr) -> str | None:
    """`a.b.c` for the expression `a.b.c`, and `None` for anything that is not a
    plain chain of names."""
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        within = _the_dotted_name_of(node.value)

        return f"{within}.{node.attr}" if within is not None else None

    return None


def _the_admissions_in(source: str) -> list[int]:
    """The line of every place this source reaches `admit`."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []  # not this guard's complaint; ruff and mypy both say so first

    kernel, _, policy = AUTONOMY.rpartition(".")
    # The names the policy module itself is bound to here.
    bound: set[str] = set()
    lines: list[int] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and not node.level:
            if node.module == AUTONOMY:
                lines.extend(node.lineno for alias in node.names
                             if _makes_an_admission(alias.name))
            elif node.module == kernel:
                bound.update(alias.asname or alias.name for alias in node.names
                             if alias.name == policy)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is not None:
                    # `import core.autonomy as x` binds the policy to `x`, and
                    # `import core as x` the kernel; `import core.models as x`
                    # binds neither.
                    if alias.name == AUTONOMY:
                        bound.add(alias.asname)
                    elif alias.name == kernel:
                        bound.add(f"{alias.asname}.{policy}")
                elif alias.name == kernel or alias.name.startswith(f"{kernel}."):
                    # Any `import core...` without `as` binds `core` itself, so
                    # `core.autonomy` is reachable through it - `import
                    # core.models` included, once anything has loaded the policy.
                    bound.add(AUTONOMY)

    lines.extend(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and _makes_an_admission(node.attr)
        and _the_dotted_name_of(node.value) in bound
    )

    return sorted(lines)


def _the_shipped_modules() -> dict[str, Path]:
    """Every module that ships, by its dotted name: the source trees under
    `modules/`, and not their suites - a suite builds admissions to hand the
    code it tests, and ships nothing."""
    return {
        ".".join(path.relative_to(MODULES / path.relative_to(MODULES).parts[0] / "src")
                 .with_suffix("").parts): path
        for path in sorted(MODULES.glob("*/src/**/*.py"))
    }


def _only_the_walk_admits() -> None:
    """Refuses a module outside the walk, the worker's root and the kernel that
    can make an admission."""
    modules = _the_shipped_modules()
    reached = the_admissions_made_outside_the_walk(
        {module: path.read_text(encoding="utf-8") for module, path in modules.items()}
    )

    if reached:
        print(
            "these make an admission outside the walk:\n"
            + "\n".join(
                f"  {modules[module].relative_to(REPOSITORY).as_posix()}:{lineno}"
                for module, lineno in reached
            )
            + f"\nOnly {', '.join(sorted(WHO_MAY_ADMIT))} name `{AUTONOMY}.{ADMIT}`; "
              f"everybody else may name `Admitted` and nothing more of it.",
            file=sys.stderr
        )
        sys.exit(1)


def _the_vendors_in(text: str) -> set[str]:
    """Every vendor `text` names: a spelling of it found as whole words in a
    row among the words `text` is made of."""
    words = [word.lower() for word in WORD.findall(text)]

    return {
        vendor
        for vendor, spellings in VENDORS.items()
        for spelling in spellings
        if _in_a_row(spelling.split(), words)
    }


def _in_a_row(spelling: list[str], words: list[str]) -> bool:
    """Whether `spelling`'s words appear in `words` one after another."""
    return any(words[start:start + len(spelling)] == spelling
               for start in range(len(words) - len(spelling) + 1))


def _the_prose_in(tree: ast.AST) -> set[int]:
    """The string constants that are prose rather than code: a docstring, or
    any string standing alone as a statement - said to a reader, and passed to
    nothing."""
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def _the_names_in(node: ast.AST) -> list[str]:
    """What `node` names, where it names anything: a definition, an argument,
    a name or an attribute read or bound, a keyword passed, a module imported
    and what is imported from it."""
    match node:
        case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
            return [name]
        case ast.Name(id=name) | ast.Attribute(attr=name) | ast.arg(arg=name):
            return [name]
        case ast.keyword(arg=str(name)):
            return [name]
        case ast.alias(name=name, asname=asname):
            return [name] if asname is None else [name, asname]
        case ast.ImportFrom(module=str(module)):
            return [module]

    return []


def _what_names_a_vendor(source: str) -> list[tuple[int, str, str]]:
    """Each line of `source` that names a vendor in code, with the vendor and
    what named it - once per line, vendor and name."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []  # not this guard's complaint; ruff and mypy both say so first

    prose = _the_prose_in(tree)
    named: set[tuple[int, str, str]] = set()

    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)

        for name in _the_names_in(node):
            named.update((line, vendor, name) for vendor in _the_vendors_in(name))

        if isinstance(node, ast.Constant) and id(node) not in prose:
            # A header or a signature is as often bytes as it is text.
            text = (node.value.decode("utf-8", "replace") if isinstance(node.value, bytes)
                    else node.value if isinstance(node.value, str) else "")
            # Line by line, so a long string - a query, a schema - is reported at
            # the line that names the vendor, quoting that line.
            named.update(
                (line + offset, vendor, said.strip())
                for offset, said in enumerate(text.splitlines() or [text])
                for vendor in _the_vendors_in(said)
            )

    return sorted(named)


def _whose_adapter(module: str) -> set[str]:
    """The vendors a module is the adapter of: those a part of its dotted name
    is named for - `chat_platform.slack_posting`, `vector_store_qdrant.indexing`."""
    return _the_vendors_in(module)


def the_vendors_named_outside_their_adapter(
    sources: Mapping[str, str],
    wiring: Collection[str] = WIRING,
    allowed: Mapping[str, frozenset[str]] = ALLOWED_BESIDE_ITS_OWN
) -> list[tuple[str, int, str, str]]:
    """Every place a shipped module names a vendor it is not the adapter of, as
    the module, the line, the vendor and what named it.

    `sources` is each module's source by its dotted name, which is what says
    whose adapter it is. Named in code - an identifier, an import, a keyword, a
    string a function is handed - and not in prose: a docstring saying what Argo
    CD does is an explanation, and the module it is in still speaks Argus's
    words. `wiring` is the modules that may name any vendor, and `allowed` the
    vendors each other module may name beside its own - the debts `NOT_YET`
    lists, and the vendors an adapter's own vendor's wire names.

    Empty where every vendor is named by its adapter alone.
    """
    return [
        (module, line, vendor, said)
        for module, source in sorted(sources.items())
        if not _is_within(module, wiring)
        for line, vendor, said in _what_names_a_vendor(source)
        if vendor not in _whose_adapter(module) | allowed.get(module, frozenset())
    ]


def the_stale_allowances(sources: Mapping[str, str],
                         wiring: Collection[str] = WIRING,
                         allowed: Mapping[str, frozenset[str]] = ALLOWED_BESIDE_ITS_OWN
                         ) -> list[str]:
    """Every wiring package nothing under which names a vendor, or that is not
    there at all, and every vendor a module is allowed that it no longer names -
    an allowance outliving its reason, which would let that vendor back in
    without anybody deciding it should."""
    return sorted(
        [package for package in wiring
         if not any(_is_within(module, {package}) and _what_names_a_vendor(source)
                    for module, source in sources.items())]
        + [f"{module}: {vendor}" for module, vendors in allowed.items()
           for vendor in sorted(vendors)
           if module not in sources
           or vendor not in {named for _, named, _ in _what_names_a_vendor(sources[module])}]
    )


def _every_vendor_is_named_by_its_adapter_alone() -> None:
    """Refuses a shipped module naming a vendor past its port, and an allowance
    nothing uses any more."""
    modules = _the_shipped_modules()
    sources = {module: path.read_text(encoding="utf-8") for module, path in modules.items()}
    named = the_vendors_named_outside_their_adapter(sources)
    stale = the_stale_allowances(sources)

    if named:
        print(
            "these name a vendor outside its adapter:\n"
            + "\n".join(
                f"  {modules[module].relative_to(REPOSITORY).as_posix()}:{line} -> "
                f"{said!r} names {vendor}"
                for module, line, vendor, said in named
            )
            + "\nSay it in Argus's words, and let the adapter - a module named for the "
              "vendor - be the one place the vendor is named.",
            file=sys.stderr
        )
        sys.exit(1)

    if stale:
        print(
            "these allowances outlive their reason - wiring naming no vendor, a vendor "
            "the module no longer names, or a module that is not there:\n"
            + "\n".join(f"  {module}" for module in stale)
            + "\nTake them out of `WIRING`, `NOT_YET`, `SAID_ON_ITS_VENDOR_S_WIRE` or "
              "`CONFIGURED_OUTSIDE` in scripts/guard_layering.py.",
            file=sys.stderr
        )
        sys.exit(1)


def the_workspace_packages_named_by(requirements: Iterable[str]) -> set[str]:
    """The workspace packages these requirements install, by import name.

    A workspace package is distributed as `argus-<package>`, so the name is the
    distribution's without the prefix and without its extras or version. Third
    parties are left out: a distribution's name is not its import name.
    """
    named: set[str] = set()

    for requirement in requirements:
        distribution = re.split(r"[\[<>=!~;\s]", requirement.strip(), maxsplit=1)[0]

        if distribution.startswith(WORKSPACE_DISTRIBUTION):
            named.add(distribution.removeprefix(WORKSPACE_DISTRIBUTION))

    return named


def what_each_process_installs(configuration: Mapping[str, Any]) -> dict[str, set[str]]:
    """The workspace packages each process's root may import, by process: its
    own extra's, the base dependencies every root takes, and the roots' own
    package - read from the roots' `pyproject.toml`, as `configuration`."""
    project = configuration.get("project", {})
    base = the_workspace_packages_named_by(project.get("dependencies", []))

    return {
        process: base | the_workspace_packages_named_by(requirements) | {APPS}
        for process, requirements in project.get("optional-dependencies", {}).items()
    }


def the_processes_reaching_past_their_extra(
    graph: ImportGraph,
    installs: Mapping[str, set[str]],
    workspace: Collection[str]
) -> list[tuple[str, str]]:
    """Every workspace package a root imports that its process does not install,
    as the importing module and the package.

    A module's process is the name under `apps` it sits in: `apps.web`, or
    `apps.worker.assembling`. A root whose process has no extra is a process
    nobody can install, and everything it imports is refused. Direct imports
    only: what a package imports in turn is that package's own dependencies'
    to install. Only `workspace`'s packages are held to it - the packages
    `root_packages` names; a third party's distribution name is not its import
    name. Empty where every root imports what its process installs.
    """
    roots = graph.find_descendants(APPS) if APPS in graph.modules else set()

    return sorted(
        (module, package)
        for module in roots
        for package in {imported.partition(".")[0]
                        for imported in graph.find_modules_directly_imported_by(module)}
        if package in workspace
        and package not in installs.get(module.split(".")[1], {APPS})
    )


def _every_root_imports_what_its_process_installs() -> None:
    """Refuses a root that imports a workspace package its extra does not name."""
    with APPS_CONFIGURATION.open("rb") as configuration:
        installs = what_each_process_installs(tomllib.load(configuration))

    graph = grimp.build_graph(*sorted(_the_modules_the_contracts_see()), cache_dir=None)
    reaching = the_processes_reaching_past_their_extra(
        graph, installs, _the_modules_the_contracts_see()
    )

    if reaching:
        declared_in = APPS_CONFIGURATION.relative_to(REPOSITORY).as_posix()

        print(
            "these roots import a workspace package their process does not install:\n"
            + "\n".join(
                f"  {module} -> {package}\n"
                f"      add {WORKSPACE_DISTRIBUTION}{package} to the "
                f"[{module.split('.')[1]}] extra in {declared_in}"
                for module, package in reaching
            ),
            file=sys.stderr
        )
        sys.exit(1)


def the_settings_classes_in(trees: Iterable[ast.AST]) -> set[str]:
    """Every class these modules declare on `BaseSettings`, by name - directly,
    or on another such class, however many classes down, whether the base is
    named bare, through its module or under another name it was imported as."""
    return _the_classes_built_on(trees, READS_ITS_FIELDS_FROM_THE_ENVIRONMENT)


def the_kernel_settings_an_adapter_declares_too(
    sources: Mapping[str, str]
) -> list[tuple[str, int, str]]:
    """Every field a class built on `AdapterSettings` declares that the
    kernel's `Settings` declares too, as the adapter's module, the line and
    the class's field. Empty where no vendor's setting is also the kernel's.

    Raises `LookupError` where the kernel's settings are not where
    `KERNEL_SETTINGS` says - a rule that found no kernel would pass on
    anything.
    """
    trees = _the_trees_of(sources)
    module, name = KERNEL_SETTINGS
    kernel = [node for node in ast.walk(trees.get(module, ast.Module(body=[], type_ignores=[])))
              if isinstance(node, ast.ClassDef) and node.name == name]

    if not kernel:
        raise LookupError(f"no class [{name}] in [{module}]")

    the_kernel_s = {field for cls in kernel for field, _ in _the_fields_of(cls)}
    adapters = _the_classes_built_on(trees.values(), ADAPTER_SETTINGS)

    return sorted(
        (owner, line, f"{node.name}.{field}")
        for owner, tree in trees.items()
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name in adapters
        for field, line in _the_fields_of(node)
        if field in the_kernel_s
    )


def _the_fields_of(cls: ast.ClassDef) -> list[tuple[str, int]]:
    """Each field a class declares in its own body, and the line it is on."""
    return [(node.target.id, node.lineno) for node in cls.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)]


def _the_classes_built_on(trees: Iterable[ast.AST], base: str) -> set[str]:
    """Every class these modules declare on `base`, by name - directly, or on
    another such class, however many classes down, whether a base is named
    bare, through its module or under another name it was imported as."""
    bases_of: dict[str, set[str]] = {}

    for tree in trees:
        imported_as = _the_names_imported_as(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases_of.setdefault(node.name, set()).update(
                    imported_as.get(name, name) for base in node.bases
                    if (name := _the_name_referred_to(base)) is not None
                )

    found = {base}
    grown = True

    while grown:
        grown = False

        for name, bases in bases_of.items():
            if name not in found and bases & found:
                found.add(name)
                grown = True

    return found - {base}


def the_environment_read_outside_a_root(
    sources: Mapping[str, str],
    allowed: Collection[str] = frozenset(READ_WHERE_DEFINED)
) -> list[tuple[str, int, str]]:
    """Every place a shipped module outside a process's root reads the
    environment, as the module, the line and what read it.

    Read means one of `READS_THE_ENVIRONMENT` named - called, passed as a
    default, imported, an attribute of `os` - or a settings class used at all:
    called with or without arguments, or passed on to be called, as a
    `default_factory` or FastAPI's `Depends` is - inside an annotation too.
    Only a type position says what something is and reads nothing: an
    annotation's types, a class's bases, an import. Which classes those are is
    read from `sources` themselves, so a class declared on another settings
    class is found however far down it sits, and under whatever name a module
    imported it as. `allowed` is where the readers are defined. Empty where only
    roots read it.
    """
    trees = _the_trees_of(sources)
    settings_classes = the_settings_classes_in(trees.values())
    found: set[tuple[str, int, str]] = set()

    for module, tree in sorted(trees.items()):
        if _is_within(module, {APPS}) or module in allowed:
            continue

        known_here = settings_classes | {
            asname for asname, name in _the_names_imported_as(tree).items()
            if name in settings_classes
        }
        saying_what_it_is = _the_type_positions_in(tree)

        for node in ast.walk(tree):
            line = getattr(node, "lineno", 0)
            found.update((module, line, name) for name in _the_names_in(node)
                         if name in READS_THE_ENVIRONMENT)

            if (isinstance(node, ast.Name | ast.Attribute)
                    and isinstance(node.ctx, ast.Load)
                    and id(node) not in saying_what_it_is
                    and (used := _the_name_referred_to(node)) in known_here):
                found.add((module, line, used))

    return sorted(found)


def the_stale_readers(sources: Mapping[str, str],
                      allowed: Collection[str] = frozenset(READ_WHERE_DEFINED)) -> list[str]:
    """Every module allowed to read the environment that is not there, or that
    the rule, allowing nothing, finds reading nothing - an allowance covering a
    whole module outliving its reason, which would let a read back in there
    without anybody deciding it should."""
    reading = {module for module, _, _ in the_environment_read_outside_a_root(sources, ())}

    return sorted(module for module in allowed if module not in reading)


def _the_trees_of(sources: Mapping[str, str]) -> dict[str, ast.AST]:
    """Each module's syntax tree, by its dotted name - but a module that does
    not parse, which is not this guard's complaint: ruff and mypy both say so
    first."""
    trees: dict[str, ast.AST] = {}

    for module, source in sources.items():
        try:
            trees[module] = ast.parse(source)
        except SyntaxError:
            continue

    return trees


def _the_names_imported_as(tree: ast.AST) -> dict[str, str]:
    """Each name a module imported something under another name as, and what
    it imported: `Chat` for `from chat_platform.slack import SlackSettings as
    Chat`."""
    return {
        alias.asname: alias.name.rpartition(".")[2]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
        if alias.asname is not None
    }


def _the_type_positions_in(tree: ast.AST) -> set[int]:
    """Every node standing where a type is named - an annotation's types and a
    class's bases - which says what something is and reads nothing. A call is
    never a type position, wherever it sits: `Field(default_factory=...)` or
    `Depends(...)` inside an `Annotated` builds, and the metadata `Annotated`
    carries after its type is not a type either."""
    saying: list[ast.expr] = []

    for node in ast.walk(tree):
        match node:
            case ast.arg(annotation=ast.expr() as annotation):
                saying.append(annotation)
            case ast.FunctionDef(returns=ast.expr() as returns) | ast.AsyncFunctionDef(
                    returns=ast.expr() as returns):
                saying.append(returns)
            case ast.AnnAssign(annotation=annotation):
                saying.append(annotation)
            case ast.ClassDef(bases=bases):
                saying.extend(bases)

    return {id(inner) for outer in saying for inner in _the_types_in(outer)}


def _the_types_in(annotation: ast.expr) -> Iterator[ast.expr]:
    """The nodes of `annotation` that name a type, stopping at a call, and
    reading only the first argument of an `Annotated`."""
    match annotation:
        case ast.Call():
            return
        case ast.Subscript(value=value, slice=ast.Tuple(elts=[first, *_])) if (
                _the_name_referred_to(value) == ANNOTATED):
            yield annotation
            yield from _the_types_in(value)
            yield from _the_types_in(first)
            return

    yield annotation

    for child in ast.iter_child_nodes(annotation):
        if isinstance(child, ast.expr):
            yield from _the_types_in(child)


def _the_name_referred_to(node: ast.expr) -> str | None:
    """The name an expression refers to something by - `Settings` in `Settings`
    and in `config.Settings` - or `None` where it is not a name."""
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name

    return None


def _only_a_root_reads_the_environment() -> None:
    """Refuses a shipped module outside `apps` that reads the environment, a
    vendor's setting the kernel's settings declare too, and an allowance to
    read the environment that nothing uses any more."""
    modules = _the_shipped_modules()
    sources = {module: path.read_text(encoding="utf-8") for module, path in modules.items()}
    read = the_environment_read_outside_a_root(sources)
    stale = the_stale_readers(sources)

    if read:
        print(
            "these read the environment outside a process's root:\n"
            + "\n".join(
                f"  {modules[module].relative_to(REPOSITORY).as_posix()}:{line} -> {said}"
                for module, line, said in read
            )
            + f"\nOnly a root, in `{APPS}`, reads the environment; take what it read as "
              "a parameter, and let the root hand it over.",
            file=sys.stderr
        )
        sys.exit(1)

    declared_twice = the_kernel_settings_an_adapter_declares_too(sources)

    if declared_twice:
        print(
            "these vendors' settings declare a field the kernel's settings declare too:\n"
            + "\n".join(
                f"  {modules[module].relative_to(REPOSITORY).as_posix()}:{line} -> {field}"
                for module, line, field in declared_twice
            )
            + "\nA vendor's setting is its adapter's alone; take it out of `Settings`.",
            file=sys.stderr
        )
        sys.exit(1)

    if stale:
        print(
            "these may read the environment and no longer do, or are not there:\n"
            + "\n".join(f"  {module}" for module in stale)
            + "\nTake them out of `READ_WHERE_DEFINED` in scripts/guard_layering.py.",
            file=sys.stderr
        )
        sys.exit(1)


def main() -> None:
    """Checks the graph is whole, the suites behave, no repository commits, every
    vendor's SDK is spoken by its adapter alone and its name named by it alone,
    the walk reaches no unfenced store, only the walk admits, every root
    imports what its process installs and only a root reads the environment,
    then runs every contract.

    Those are checked before import-linter rather than after, because
    import-linter exits the process with its own status and anything after it
    would never run.

    import-linter's report goes to stdout as it writes it - the whole value of a
    broken contract is the chain of imports it prints, and a wrapper that
    summarised that would be a wrapper hiding the answer.
    """
    _say_it_in_utf8()
    _every_module_is_analyzed()
    _the_suites_use_the_front_doors(_the_front_doors())
    _the_suites_keep_the_agents_apart(_the_independent_modules())
    _no_repository_commits()
    _every_vendor_is_spoken_by_its_adapter_alone()
    _every_vendor_is_named_by_its_adapter_alone()
    _the_walk_reaches_no_store_the_fence_cannot_reach(_the_walk())
    _only_the_walk_admits()
    _every_root_imports_what_its_process_installs()
    _only_a_root_reads_the_environment()
    sys.exit(lint_imports_command())


if __name__ == "__main__":
    main()
