#!/usr/bin/env python3
"""
Fails if a module imports something its layer is not allowed to know about.

Runs the import-linter contracts declared in the root `pyproject.toml` -
`argus_core` depends on nothing in this workspace, `argus_incidents` knows only
the kernel, `argus_web` serves HTML without installing an agent. The contracts
are the check on a claim `CLAUDE.md` has made since before it was true.

First it checks the contracts can see every module. `root_packages` is the one
list import-linter takes no wildcard for, so a module missing from it is not
analyzed at all - and a package no contract can see is a package no contract can
be broken by. That is the failure this whole file exists to prevent, arriving
through the file that prevents it.

A script rather than the `lint-imports` shim, for the reason every other tool
here is invoked as a module: Windows Smart App Control blocks the unsigned
`.exe` stubs in `.venv/Scripts/`, and the block comes back after every
`uv sync`. See the `smart-app-control-blocks` skill.
"""
import sys
import tomllib
from pathlib import Path

from importlinter.cli import lint_imports_command

REPOSITORY = Path(__file__).resolve().parent.parent
MODULES = REPOSITORY / "modules"
CONFIGURATION = REPOSITORY / "pyproject.toml"

# Test support and the doubles, which no contract has anything to say about:
# they are installed as dev dependencies, never imported by anything that ships,
# and a contract naming them would be a contract about the suites. Stated here
# rather than read from `noxfile.py`, because that list is about test discovery
# and the two happening to agree today is not a reason to couple them.
NOT_LAYERED = frozenset({"argus_testkit", "anthropic_double", "slack_double"})


def _the_modules_on_disk() -> set[str]:
    """Every package under `modules/` that a contract could have an opinion about."""
    return {
        directory.name
        for directory in MODULES.iterdir()
        if directory.is_dir() and (directory / "pyproject.toml").exists()
    } - NOT_LAYERED


def _the_modules_the_contracts_see() -> set[str]:
    """What `root_packages` names - the whole of what import-linter will analyze."""
    with CONFIGURATION.open("rb") as configuration:
        return set(tomllib.load(configuration)["tool"]["importlinter"]["root_packages"])


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


def main() -> None:
    """Checks the graph is whole, then runs every contract against it.

    import-linter's report goes to stdout as it writes it - the whole value of a
    broken contract is the chain of imports it prints, and a wrapper that
    summarised that would be a wrapper hiding the answer.
    """
    _every_module_is_analyzed()
    sys.exit(lint_imports_command())


if __name__ == "__main__":
    main()
