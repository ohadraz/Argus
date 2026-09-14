#!/usr/bin/env python3
"""
Fails if a module imports something its layer is not allowed to know about, or
if a test reaches into the kernel by module path.

Runs the import-linter contracts declared in the root `pyproject.toml` -
`argus_core` depends on nothing in this workspace, `argus_incidents` knows only
the kernel, `argus_web` serves HTML without installing an agent, and the kernel
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
silently unenforced in the 113 files that had to be converted by hand. The
allowed doors are read from the contract rather than restated here: two lists of
one thing is one of them going stale.

A script rather than the `lint-imports` shim, for the reason every other tool
here is invoked as a module: going through the interpreter avoids the
locally-generated `.exe` stubs in `.venv/Scripts/`, which Windows Smart App
Control has blocked before. See the `smart-app-control-blocks` skill.
"""
import ast
import sys
import tomllib
from pathlib import Path

from importlinter.cli import lint_imports_command

REPOSITORY = Path(__file__).resolve().parent.parent
MODULES = REPOSITORY / "modules"
CONFIGURATION = REPOSITORY / "pyproject.toml"

KERNEL = "argus_core"
FRONT_DOOR_CONTRACT = "the kernel is reached through its front doors, not by module path"

# Test support and the doubles, which no contract has anything to say about:
# they are installed as dev dependencies, never imported by anything that ships,
# and a contract naming them would be a contract about the suites. Stated here
# rather than read from `noxfile.py`, because that list is about test discovery
# and the two happening to agree today is not a reason to couple them.
NOT_LAYERED = frozenset({"argus_testkit", "anthropic_double", "slack_double"})

# The kernel's own suite, exempt for the reason the kernel itself is: it tests
# the modules behind the front doors, and a test that could only reach them
# through one could not test them at all.
THE_KERNELS_OWN_SUITE = "modules/argus_core/tests"

# What a suite may still name by path, and why. A module deliberately left off a
# front door is not thereby untestable: the Anthropic adapter is absent from
# `argus_core.llm` so that no caller can reach for a vendor, and the two suites
# whose whole subject is that adapter name it directly - as the kernel's own
# suite does. An entry here is a claim that the importer exists to exercise the
# thing rather than to use it.
BEHIND_THE_DOOR = frozenset({"argus_core.llm.adapters.anthropic_adapter"})


def _the_modules_on_disk() -> set[str]:
    """Every package under `modules/` that a contract could have an opinion about."""
    return {
        directory.name
        for directory in MODULES.iterdir()
        if directory.is_dir() and (directory / "pyproject.toml").exists()
    } - NOT_LAYERED


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

    Two shapes, and the difference is `argus_core`'s extras. `** -> argus_core.models`
    is a door anything may use. `agent_investigator.** -> argus_core.llm` is one
    only that module may, because `anthropic` is an optional dependency and only
    the modules that declared the extra have it. A suite is held to its own
    module's allowance for the same reason the source is: `test_module` resolves
    each module against its own dependencies alone, so a suite reaching a door
    its module did not take fails on CI and nowhere else.

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


def _the_doors_open_to(path: Path, doors: dict[str, set[str]]) -> set[str]:
    """Which doors this file may go through.

    A file under `modules/<module>/tests/` is that module's, and gets the doors
    its module took plus the ones open to everything. Everything else - the root
    `tests/` tree, `scripts/` - runs against the workspace environment, where
    every extra is installed, so it gets all of them.
    """
    parts = path.relative_to(REPOSITORY).parts

    if len(parts) > 2 and parts[0] == "modules" and parts[2] == "tests":
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
        and node.module not in BEHIND_THE_DOOR
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


def main() -> None:
    """Checks the graph is whole and the suites behave, then runs every contract.

    The suites are checked before import-linter rather than after, because
    import-linter exits the process with its own status and anything after it
    would never run.

    import-linter's report goes to stdout as it writes it - the whole value of a
    broken contract is the chain of imports it prints, and a wrapper that
    summarised that would be a wrapper hiding the answer.
    """
    _every_module_is_analyzed()
    _the_suites_use_the_front_doors(_the_front_doors())
    sys.exit(lint_imports_command())


if __name__ == "__main__":
    main()
