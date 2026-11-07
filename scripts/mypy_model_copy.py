"""A mypy plugin: the keys and values of `model_copy(update={...})`, checked.

Pydantic's `model_copy` takes its update as a `dict[str, Any]`, and applies it
without validating anything - so a key naming a field that does not exist is
dropped without a word, and a value of the wrong type is stored as given. A
field renamed in a model then leaves every `model_copy` that set it doing
nothing, and the test or the code built on it goes on running against the
default. That is how a renamed flag once left two tests asserting against a
state they never built.

So this checks what mypy otherwise cannot see: where the update is a dict
literal, each string key must name a field of the model being copied, and each
value must be of that field's type. An update built some other way - a dict
assembled elsewhere and passed in - is beyond a static check, and is left alone.

Enabled from `[tool.mypy] plugins` in the root `pyproject.toml`, so it runs
wherever `nox -s typecheck` does.
"""

from __future__ import annotations

from collections.abc import Callable

from mypy.nodes import DictExpr, StrExpr, Var
from mypy.plugin import MethodContext, Plugin
from mypy.subtypes import is_subtype
from mypy.types import Instance, Type, get_proper_type

_BASE_MODEL = "pydantic.main.BaseModel"
_MODEL_COPY = ".model_copy"
_UPDATE = "update"


class ModelCopyPlugin(Plugin):
    """Asks every `model_copy` call on a pydantic model to be checked.

    mypy names the hook after the class the method was looked up on, not the
    one that defines it, so the suffix is matched and the receiver is checked to
    be a model inside the hook.
    """

    def get_method_hook(self, fullname: str) -> Callable[[MethodContext], Type] | None:
        return _check_the_update if fullname.endswith(_MODEL_COPY) else None


def _the_field(receiver: Instance, name: str) -> Var | None:
    """The field `name` on the model, from wherever in its bases it is declared.

    `None` for a name the model does not have, and for one that is not a field
    - a method, or a class variable.
    """
    for base in receiver.type.mro:
        symbol = base.names.get(name)

        if symbol is not None:
            node = symbol.node
            return node if isinstance(node, Var) and not node.is_classvar else None

    return None


def _check_the_update(ctx: MethodContext) -> Type:
    """Fails each literal key the model has no field for, and each value of the
    wrong type for the field it names.

    The value is typed against the field rather than on its own, so a literal
    that only fits in context - `[DEPLOYMENT_PLATFORM]` for a list of a
    `Literal` - is read the way the field would read it.
    """
    receiver = get_proper_type(ctx.type)

    if not isinstance(receiver, Instance) or not receiver.type.has_base(_BASE_MODEL):
        return ctx.default_return_type

    for names, arguments in zip(ctx.arg_names, ctx.args, strict=True):
        for name, argument in zip(names, arguments, strict=True):
            if name != _UPDATE or not isinstance(argument, DictExpr):
                continue

            for key, value in argument.items:
                if not isinstance(key, StrExpr):
                    continue

                field = _the_field(receiver, key.value)

                if field is None:
                    ctx.api.fail(f'"{receiver.type.name}" has no field "{key.value}"', key)
                    continue

                given = ctx.api.get_expression_type(value, type_context=field.type)

                if field.type is not None and not is_subtype(given, field.type):
                    ctx.api.fail(f'Field "{key.value}" of "{receiver.type.name}" is '
                                 f'"{field.type}", got "{given}"', value)

    return ctx.default_return_type


def plugin(version: str) -> type[Plugin]:
    """The entry point mypy calls, by this name, for the plugin class."""
    return ModelCopyPlugin
