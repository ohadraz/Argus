"""How the code outside a patch uses what the patch changes, said by the syntax
tree rather than by a model.

Code-Fix said of code it did not change that every reader of a stored figure
trusts it, and one of those readers compares the figure with the purchases to
catch it being wrong. Each piece was read right on its own; the sentence about
them together was not. What each line outside the patch does with what the
patch changes is a fact the tree holds, so the tree says it, and the model is
not asked to.

What the patch changes is read off the patch against the file it replaces: a
function whose definition differs, and a field a changed function now writes -
by keyword or by assignment - where it wrote nothing or something else before. A
field it writes as it did is not a change, however much else the function's
text moved. A function the patch adds is not a change either: nothing outside
the patch was written against it, and a test the patch adds builds its fixtures
by keyword - read as fields the patch writes, those buried the rows that
mattered. Python only: a file the tree cannot parse says nothing it could be
wrong about, so it is passed over rather than guessed at.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from typing import Final, NamedTuple

from argus_core.models import CodeOutsideThePatch, CodeUse

PYTHON_SUFFIX: Final = ".py"

# What an arithmetic line does with a value, said as the operation. An operator
# not here is said as the line it sits in.
_VERBS: Final[dict[type[ast.operator], str]] = {
    ast.FloorDiv: "divides",
    ast.Div: "divides",
    ast.Add: "adds",
    ast.Sub: "subtracts",
    ast.Mult: "multiplies"
}

# The calls that build a copy of an object, whose keywords are its fields as a
# class's are.
_BUILDS_A_COPY: Final = frozenset({"replace", "_replace"})

_A_FUNCTION: Final = (ast.FunctionDef, ast.AsyncFunctionDef)
_A_DEFINITION: Final = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

Parents = dict[ast.AST, ast.AST]


class _Changes(NamedTuple):
    """What a patch changes that code outside it can use: the fields its
    changed code now writes differently, each module-level function whose
    definition it changes with the module defining it, and each method."""

    fields: set[str]
    functions: dict[str, str]
    methods: set[str]


def code_outside_the_patch(source: Mapping[str, str],
                           patch: Mapping[str, str]) -> CodeOutsideThePatch:
    """Every use, in the files `patch` does not touch, of what it changes in
    the files of `source` it replaces - and every function and class those
    untouched files define, with each file defining it."""
    outside = {path: (text, tree) for path, text in sorted(source.items())
               if path not in patch and (tree := _parsed(path, text)) is not None}
    classes = {node.name
               for tree in [*(tree for _, tree in outside.values()),
                            *filter(None, (_parsed(path, text) for path, text in patch.items()))]
               for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    changes = _what_it_changes(source, patch, classes)

    uses = [use for path, (text, tree) in outside.items()
            for use in _uses_in(path, text, tree, changes)]
    defined: dict[str, list[str]] = {}

    for path, (_, tree) in outside.items():
        for name in dict.fromkeys(node.name for node in ast.walk(tree)
                                  if isinstance(node, _A_DEFINITION)):
            defined.setdefault(name, []).append(path)

    return CodeOutsideThePatch(uses=sorted(uses, key=lambda use: (use.path, use.line)),
                               defined=defined)


def _what_it_changes(source: Mapping[str, str],
                     patch: Mapping[str, str],
                     classes: set[str]) -> _Changes:
    """The fields the patch's changed functions now write differently, and the
    functions and methods whose definitions it changes."""
    changes = _Changes(fields=set(), functions={}, methods=set())

    for path, text in patch.items():
        after = _parsed(path, text)

        if after is None:
            continue

        before = _parsed(path, source.get(path, ""))
        module = path.rsplit("/", 1)[-1].removesuffix(PYTHON_SUFFIX)

        for are_methods, defined_now, defined_before in (
            (False, _module_functions(after), _module_functions(before)),
            (True, _methods(after), _methods(before))
        ):
            for name, function in defined_now.items():
                was = defined_before.get(name)

                if was is None or ast.dump(was) == ast.dump(function):
                    continue

                if are_methods:
                    changes.methods.add(name)
                else:
                    changes.functions[name] = module

                wrote = _fields_written_by(was, _module_functions(before), classes)
                changes.fields.update(
                    field for field, value
                    in _fields_written_by(function, _module_functions(after), classes).items()
                    if wrote.get(field) != value
                )

    return changes


def _module_functions(tree: ast.Module | None) -> dict[str, ast.AST]:
    """Each function a module defines at its top level, by name."""
    if tree is None:
        return {}

    return {node.name: node for node in tree.body if isinstance(node, _A_FUNCTION)}


def _methods(tree: ast.Module | None) -> dict[str, ast.AST]:
    """Each method a module's classes define, by name."""
    if tree is None:
        return {}

    return {node.name: node
            for cls in ast.walk(tree) if isinstance(cls, ast.ClassDef)
            for node in cls.body if isinstance(node, _A_FUNCTION)}


def _fields_written_by(function: ast.AST,
                       its_file: Mapping[str, ast.AST],
                       classes: set[str],
                       seen: frozenset[str] = frozenset()) -> dict[str, str]:
    """Each field a function writes - as a keyword to a call building an
    object, or an attribute it assigns - with what it writes there, as the tree
    spells it, and what every function of its own file it calls writes.

    A keyword is a field only where the call builds something: a class the
    source defines, or a copy of an object (`replace`). `key=` to `sorted` is
    no field of anything. And a function of its own file it hands the work to
    writes for it: a fix that made the changed function delegate wrote the
    field all the same, one call down.

    A local the function assigns once is written as the value it was given: a
    fix that moves a value into a local to use it twice writes the same thing
    it wrote before."""
    locals_once = _locals_assigned_once(function)
    written: dict[str, str] = {}

    for node in ast.walk(function):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in its_file and node.func.id not in seen):
            written |= _fields_written_by(its_file[node.func.id], its_file, classes,
                                          seen | {node.func.id})

    for node in ast.walk(function):
        if isinstance(node, ast.Call) and _called(node) in classes | _BUILDS_A_COPY:
            written |= {keyword.arg: ast.dump(_resolved(keyword.value, locals_once))
                        for keyword in node.keywords if keyword.arg is not None}
        elif isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign) and node.value:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]

            for target in targets:
                if isinstance(target, ast.Attribute):
                    written[target.attr] = ast.dump(node)

    return written


def _locals_assigned_once(function: ast.AST) -> dict[str, ast.expr]:
    """Each plain name a function assigns exactly once, with its value."""
    assigned: dict[str, list[ast.expr]] = {}

    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, []).append(node.value)

    return {name: values[0] for name, values in assigned.items() if len(values) == 1}


def _resolved(value: ast.expr, locals_once: Mapping[str, ast.expr]) -> ast.expr:
    """A value as the local it names was given, where it names one."""
    if isinstance(value, ast.Name) and value.id in locals_once:
        return locals_once[value.id]

    return value


def _uses_in(path: str,
             text: str,
             tree: ast.Module,
             changes: _Changes) -> Iterator[CodeUse]:
    """Each line of one untouched file that reads a changed field or calls a
    changed function."""
    parents: Parents = {child: node for node in ast.walk(tree)
                        for child in ast.iter_child_nodes(node)}
    lines = text.splitlines()
    modules = _modules_imported_by(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in changes.fields:
            yield CodeUse(name=node.attr, path=path, line=node.lineno,
                          function=_the_function_around(node, parents),
                          does=_what_it_does(node, parents, text, lines))
        elif isinstance(node, ast.Call) and (called := _a_changed_call(node, changes, modules)):
            yield CodeUse(name=called, path=path, line=node.lineno,
                          function=_the_function_around(node, parents),
                          does=f"calls it: {lines[node.lineno - 1].strip()}")


def _a_changed_call(call: ast.Call, changes: _Changes, modules: Mapping[str, str]) -> str | None:
    """The changed function or method a call calls - `None` where it calls none.

    A module's function is called by its name, or through its module by
    whatever name the file imported that module as; a method, through an
    object. `cache.average(...)` calls whatever the cache's `average` is, and
    is not the changed function of a module that defines one."""
    if isinstance(call.func, ast.Name) and call.func.id in changes.functions:
        return call.func.id

    if not isinstance(call.func, ast.Attribute):
        return None

    name = call.func.attr

    if name in changes.methods:
        return name

    through = call.func.value
    if (name in changes.functions and isinstance(through, ast.Name)
            and modules.get(through.id) == changes.functions[name]):
        return name

    return None


def _modules_imported_by(tree: ast.Module) -> dict[str, str]:
    """Each name a module imports another module as, with the module it is."""
    imported: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported |= {alias.asname or alias.name: alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            imported |= {alias.asname or alias.name: alias.name.rsplit(".", 1)[-1]
                         for alias in node.names}

    return imported


def _called(call: ast.Call) -> str | None:
    """The name a call calls, by itself or as an attribute."""
    if isinstance(call.func, ast.Name):
        return call.func.id

    if isinstance(call.func, ast.Attribute):
        return call.func.attr

    return None


def _what_it_does(node: ast.Attribute, parents: Parents, text: str, lines: list[str]) -> str:
    """What the expression a field sits in does with it.

    A comparison is said as one, whichever side the field is on: a line that
    reads a figure to check it is the line a model counted among the ones that
    trust it."""
    parent = parents.get(node)
    line = lines[node.lineno - 1].strip()

    if isinstance(node.ctx, ast.Store):
        return f"sets it: {line}"

    if isinstance(parent, ast.Compare):
        other = parent.comparators[0] if parent.left is node else parent.left

        return f"compares it with {ast.get_source_segment(text, other)}"

    if isinstance(parent, ast.BinOp) and type(parent.op) in _VERBS:
        return f"{_VERBS[type(parent.op)]} with it: {ast.get_source_segment(text, parent)}"

    if isinstance(parent, ast.Return):
        return "returns it"

    if isinstance(parent, ast.keyword) and isinstance(call := parents.get(parent), ast.Call):
        return f"passes it to {ast.get_source_segment(text, call.func)} as {parent.arg}"

    if isinstance(parent, ast.Call) and node in parent.args:
        return f"passes it to {ast.get_source_segment(text, parent.func)}"

    return f"reads it: {line}"


def _the_function_around(node: ast.AST, parents: Parents) -> str | None:
    """The innermost function a node sits in - `None` at a module's top level."""
    while (node := parents.get(node)) is not None:  # type: ignore[assignment]
        if isinstance(node, _A_FUNCTION):
            return node.name

    return None


def _parsed(path: str, text: str) -> ast.Module | None:
    """A Python file's tree - `None` for a file that is not Python, or that does
    not parse."""
    if not path.endswith(PYTHON_SUFFIX):
        return None

    try:
        return ast.parse(text)
    except SyntaxError:
        return None
