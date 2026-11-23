#!/usr/bin/env python3
"""
Fails if a module's prose sits below its imports instead of above them.

A string on its own line is a docstring only as the *first* statement in the
file. Written after the imports it is a no-op expression: `__doc__` is `None`,
and `help()`, pydoc, and every editor hover show a module that says nothing
about itself. The prose reads correctly in the file and is invisible everywhere
else, which is the worst way for documentation to be wrong.

Narrow on purpose. This asks only whether a file that *has* written its prose
put it where anything can read it - it never asks for prose that was not
written. Ruff's D100 is the other question, and the wrong one here: most
modules in this repo are a type or two whose own docstrings say everything,
and demanding a header on each would buy filler.
"""
import ast
import subprocess
import sys
from pathlib import Path


def stray_string_lines(source_file: Path) -> list[int]:
    """Returns the lines of `source_file` holding a string that says nothing.

    A free-standing string anywhere in the module body, except the docstring
    itself. A file that already has a docstring and a second string later is
    reported too: that second one is a section note, and a note belongs in a
    comment where it cannot be mistaken for the module's description.
    """
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    has_docstring = ast.get_docstring(tree) is not None

    return [
        node.lineno
        for index, node in enumerate(tree.body)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and not (has_docstring and index == 0)
    ]


def the_repositorys_python_files(repo_root: Path) -> list[Path]:
    """Every Python file the repository holds or is about to: tracked, or
    untracked and not ignored - as git sees them, so an ignored folder of
    someone's local copies (a virtualenv, a reviewer's captures of another
    repository) is never read as this repository's code. A tracked file
    deleted from the working tree is left out: there is nothing to read."""
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.py"],
        cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout

    return sorted(repo_root / name for name in set(listed.split("\0"))
                  if name and (repo_root / name).is_file())


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    violations = [
        f"{source_file.relative_to(repo_root).as_posix()}:{lineno}"
        for source_file in the_repositorys_python_files(repo_root)
        for lineno in stray_string_lines(source_file)
    ]

    if violations:
        print(
            "Module prose found below the imports, where nothing can read it.\n"
            "A string is a docstring only as the file's first statement; "
            "anywhere else `__doc__` stays None.\n"
            "Move it to the top of the file, or make it a # comment if it is a "
            "note rather than the module's description:\n"
            + "\n".join(f"  {violation}" for violation in violations),
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
