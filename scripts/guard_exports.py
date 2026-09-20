#!/usr/bin/env python3
"""
Fails if a package's `__all__` offers a name nothing outside that package uses.

A module's front door says what the rest of the workspace may reach for, and a
door wider than anyone walks through is a door nobody can read. Every extra
name is a promise somebody may be keeping - so a helper that was exported once
and never imported still has to be treated as public the next time it is
touched, and the actual public surface of a module becomes unfindable inside
its own export list.

What counts as *used* is deliberately generous: any import of the name, from
anywhere in `modules/`, `tests/` or `scripts/` that is not the package
declaring it. Production code, a test, a script - each is a caller that would
break, and none of them is more of a reason to keep the name than another.

What this does **not** ask is whether the name is called. A type alias, a
Protocol, an exception or the parameter type of an exported function is part of
the surface by being nameable: `relay_once` takes a `Place`, and a caller that
cannot name `Place` cannot call it. So a name written in any annotation inside
its own package counts as used, whoever imports it. An earlier sweep that
looked for calls reported nine names of which five were correct as they were,
which is the mistake this checks against instead of repeating.
"""
import ast
import sys
from pathlib import Path

SKIPPED_DIRECTORIES = ("__pycache__", ".venv", ".nox", ".git")

# Where a caller might live. Everything this repo writes, so a name kept only
# for a script or a test suite is kept rather than reported.
SEARCHED = ("modules", "tests", "scripts")

# Names offered on purpose to a caller who has not arrived yet, each with the
# reason somebody kept it. The same shape `guard_layering`'s ignored imports
# have, and for the same reason: an exception nobody has to write down is an
# exception nobody can argue with.
KEPT_DELIBERATELY = {
    # The one-shot alternative to `open_pool`, for a caller whose whole life is
    # shorter than a pool would be worth - a migration, a suite arranging a
    # row, a command. Everything in the workspace happens to want
    # `connect_from_env` instead, which is a fact about this deployment rather
    # than about the kernel's surface.
    ("argus_core", "connect"),
    # A typed function per tool is what a client package *is*: the read tier
    # offers this one, so the client offers it, and a tool nobody has needed
    # yet is not a tool the client may quietly stop exposing.
    ("read_mcp_client", "get_enabled_flags")
}


def exported_names(package_init: Path) -> list[str]:
    """The names `package_init` lists in `__all__`, in the order it lists them.

    Read from the literal rather than by importing the package: a guard that
    imported every front door in the workspace would need every dependency
    installed to answer a question about text.
    """
    tree = ast.parse(package_init.read_text(encoding="utf-8"), filename=str(package_init))

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue

        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            continue

        if not isinstance(node.value, ast.List):
            continue

        return [
            element.value
            for element in node.value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]

    return []


def names_imported_by(source_file: Path) -> set[str]:
    """Every name `source_file` imports, under whatever spelling it imports it.

    The imported name rather than the alias: `from x import y as z` is a use of
    `y`, and the local spelling is the importer's business.
    """
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))

    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def names_annotated_in(package: Path) -> set[str]:
    """Every identifier this package writes into an annotation.

    A parameter's type, a return type, an attribute's type - each names a thing
    a caller has to be able to name too, so an exported alias appearing in one
    is part of the surface however few callers spell it today. Subscripts and
    unions are walked rather than matched, because `Mapping[str, PayBand]` and
    `Place | None` name their members as surely as a bare annotation does.
    """
    annotated: set[str] = set()

    for source_file in package.rglob("*.py"):
        if any(part in SKIPPED_DIRECTORIES for part in source_file.parts):
            continue

        tree = ast.parse(source_file.read_text(encoding="utf-8"),
                         filename=str(source_file))

        for node in ast.walk(tree):
            annotation = getattr(node, "annotation", None) or getattr(
                node, "returns", None
            )

            if annotation is None:
                continue

            annotated |= {
                named.id
                for named in ast.walk(annotation)
                if isinstance(named, ast.Name)
            }

    return annotated


def unused_exports(repo_root: Path) -> list[str]:
    """Every exported name no file outside its own package imports.

    A package is its `src/<name>/` directory, and a name imported anywhere
    below that directory does not count - the question is whether anything
    *else* reaches for it. The exception is an annotation: a type the package
    writes into one of its own signatures is a type a caller has to be able to
    name, and nothing outside has to import it to make that true.
    """
    violations: list[str] = []

    for package_init in sorted(repo_root.glob("modules/*/src/*/__init__.py")):
        package = package_init.parent
        exported = exported_names(package_init)

        if not exported:
            continue

        imported_elsewhere: set[str] = set()

        for directory in SEARCHED:
            for source_file in (repo_root / directory).rglob("*.py"):
                if any(part in SKIPPED_DIRECTORIES for part in source_file.parts):
                    continue

                if package in source_file.parents:
                    continue

                imported_elsewhere |= names_imported_by(source_file)

        nameable = imported_elsewhere | names_annotated_in(package)

        violations.extend(
            f"{package_init.relative_to(repo_root).as_posix()}: {name}"
            for name in exported
            if name not in nameable
            and (package.name, name) not in KEPT_DELIBERATELY
        )

    return violations


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    violations = unused_exports(repo_root)

    if violations:
        print(
            "Exported names nothing outside their own package imports.\n"
            "An export list wider than anyone asked for makes the public "
            "surface unreadable, and a name nothing references is a name "
            "nobody can be sure is safe to change.\n"
            "Drop each from its package's `__init__.py` - the import line and "
            "`__all__` both - or, if it is genuinely the surface a caller "
            "needs, make something import it:\n"
            + "\n".join(f"  {violation}" for violation in violations),
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
