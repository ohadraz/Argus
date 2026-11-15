from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from pydantic import BaseModel, model_validator

# Anthropic's own vocabulary for a tool offer, named here because this is the
# one module that writes it. Everything above holds a `ToolDefinition` and
# never assembles a schema by hand - which is the point: the strictness rules
# below are easy to half-apply, and a schema that half-applies them is quietly
# permissive rather than broken.
_NAME_KEY: Final = "name"
_DESCRIPTION_KEY: Final = "description"
_INPUT_SCHEMA_KEY: Final = "input_schema"
_STRICT_KEY: Final = "strict"

_TYPE_KEY: Final = "type"
_PROPERTIES_KEY: Final = "properties"
_REQUIRED_KEY: Final = "required"
_ADDITIONAL_PROPERTIES_KEY: Final = "additionalProperties"

_OBJECT_TYPE: Final = "object"

# A schema keyword a generator writes on every node - pydantic's, under
# FastMCP - which strict tool use lists no support for and no model needs.
_TITLE_KEY: Final = "title"
# Where a schema says a node is defined elsewhere in it.
_REF_KEY: Final = "$ref"


class ToolDefinition(BaseModel):
    """One tool Argus offers the model, in Argus's terms rather than the wire's.

    Holds what a caller actually decides - what the tool is called, when to
    reach for it, and what it may be asked for - and leaves the schema
    boilerplate to `to_wire`. A caller writing the JSON Schema itself would be
    restating `type: object` and `additionalProperties: false` at every tool,
    and the day one of them is omitted the tool silently stops being strict.

    `description` is not decoration. It is the only thing telling the model
    when this tool is the right one, so a tool offered without one leaves the
    model choosing between names.

    `properties` is a JSON Schema fragment rather than a typed structure,
    because what a tool takes is that tool's business and a type here would
    have to anticipate every one of them. What this class does enforce is that
    the fragment is coherent with `required`.
    """

    name: str
    description: str
    properties: dict[str, Any]
    required: list[str]

    @model_validator(mode="after")
    def _cannot_require_what_it_does_not_offer(self) -> ToolDefinition:
        """Refuses a schema that demands an argument it never declared.

        The API rejects the whole request over one malformed tool, not just
        that tool, so a typo in a required list takes the entire investigation
        down with it - and reports an HTTP status rather than the mistake.
        Caught here, where the tool is written and the name is in front of
        whoever wrote it.
        """
        undeclared = [name for name in self.required if name not in self.properties]
        if undeclared:
            raise ValueError(
                f"tool {self.name!r} requires {undeclared}, which it does not offer: "
                f"a schema demanding an undeclared property is rejected whole"
            )

        return self

    @classmethod
    def from_input_schema(cls,
                          name: str,
                          description: str | None,
                          input_schema: dict[str, Any]) -> ToolDefinition:
        """A tool as the server that serves it declares it (MCP, `tools/list`).

        The server owns a tool's definition, and what it declares is what a
        model is offered - less the titles its schema generator writes, which
        repeat the names they sit on. A server that wrote no description offers
        an empty one, which is the server's to fix rather than a guess's here.

        Refuses an argument the offer cannot carry, naming it, rather than
        offering something wrong: one defined elsewhere in the schema (a `$ref`
        into `$defs`, which properties alone leave pointing at nothing), and an
        object that does not name every key it takes - a map, one open to any
        key, one naming none - which strict tool use cannot say: stamped strict,
        it would take only the keys it named, and those may be none at all.
        """
        for argument, schema in input_schema.get(_PROPERTIES_KEY, {}).items():
            if _anywhere_in(schema, _refers_elsewhere):
                raise ValueError(f"tool {name!r} argument {argument!r} is defined "
                                 f"elsewhere in its schema, which an offer does not carry")

            if _anywhere_in(schema, _takes_keys_it_does_not_name):
                raise ValueError(f"tool {name!r} argument {argument!r} is an object taking "
                                 f"keys it does not name, which a strict offer cannot say")

        return cls(
            name=name,
            description=description or "",
            properties={argument: _untitled(schema)
                        for argument, schema in input_schema.get(_PROPERTIES_KEY, {}).items()},
            required=list(input_schema.get(_REQUIRED_KEY, []))
        )

    def without(self, *arguments: str) -> ToolDefinition:
        """The same tool, less arguments its caller fills in itself.

        Taken from `required` as well as `properties`: a schema demanding an
        argument it does not offer is refused whole. The model is then offered
        only what is its to choose, as LangChain's `InjectedToolArg` does.

        Refuses an argument the tool does not take: a server that renamed one
        would otherwise have it offered to the model again, under its new name.
        """
        unknown = [argument for argument in arguments if argument not in self.properties]

        if unknown:
            raise ValueError(f"tool {self.name!r} takes no {unknown} to leave out")

        return self.model_copy(update={
            "properties": {argument: schema for argument, schema in self.properties.items()
                           if argument not in arguments},
            "required": [argument for argument in self.required if argument not in arguments]
        })

    def to_wire(self) -> dict[str, Any]:
        """Renders this tool as the API expects a tool offer to look.

        Always strict, and not by a per-tool choice. The dispatcher looks a
        tool up by name and calls it with whatever arrived; an argument the
        schema never promised is one nothing is written to handle. Strict mode
        is what makes the arguments a dispatcher receives exactly the arguments
        it declared - and `additionalProperties: false` is the half of that
        which is easiest to leave out, which is why it is written here rather
        than asked of every caller.

        Strict at every depth, not only at the top. A tool taking a list of
        records - a patch of whole files, each a path and its contents -
        carries objects the caller wrote, and the API demands the same of those.
        It refuses the whole request over one of them, so a nested object left
        permissive takes every other tool in the call down with it.
        """
        return {
            _NAME_KEY: self.name,
            _DESCRIPTION_KEY: self.description,
            _STRICT_KEY: True,
            _INPUT_SCHEMA_KEY: _strictly(
                {
                    _TYPE_KEY: _OBJECT_TYPE,
                    _PROPERTIES_KEY: self.properties,
                    _REQUIRED_KEY: self.required
                }
            )
        }


def _anywhere_in(schema: Any, found: Callable[[dict[str, Any]], bool]) -> bool:
    """Whether any node of `schema` is one `found` picks out."""
    if isinstance(schema, dict):
        return found(schema) or any(_anywhere_in(value, found) for value in schema.values())

    if isinstance(schema, list):
        return any(_anywhere_in(item, found) for item in schema)

    return False


def _refers_elsewhere(node: dict[str, Any]) -> bool:
    """A node defined by a reference rather than in place."""
    return _REF_KEY in node


def _takes_keys_it_does_not_name(node: dict[str, Any]) -> bool:
    """An object open to keys beyond those it names - a map among them, whose
    keys are anybody's - or one naming no keys at all."""
    if node.get(_ADDITIONAL_PROPERTIES_KEY, False) is not False:
        return True

    return node.get(_TYPE_KEY) == _OBJECT_TYPE and _PROPERTIES_KEY not in node


def _untitled(schema: Any) -> Any:
    """The same schema, with no node carrying a `title`.

    The keyword only: an argument called `title` is a key of `properties`, and
    a properties map is walked by its values, never stripped of its keys.
    """
    if isinstance(schema, dict):
        return {
            key: ({argument: _untitled(value) for argument, value in inner.items()}
                  if key == _PROPERTIES_KEY and isinstance(inner, dict)
                  else _untitled(inner))
            for key, inner in schema.items()
            if key != _TITLE_KEY
        }

    if isinstance(schema, list):
        return [_untitled(item) for item in schema]

    return schema


def _strictly(schema: Any) -> Any:
    """The same schema, with every object in it forbidding what it did not name.

    A copy rather than an edit in place: `properties` is the caller's own
    fragment, usually a module-level constant, and stamping it where it lies
    would rewrite the definition somebody wrote rather than the offer being
    sent.

    Set rather than defaulted, so a fragment that said `true` is corrected
    rather than honoured. There is no tool here for which permissive is the
    right answer, and one arriving that way is a mistake rather than a choice.
    """
    if isinstance(schema, dict):
        stamped = {key: _strictly(value) for key, value in schema.items()}

        if stamped.get(_TYPE_KEY) == _OBJECT_TYPE:
            stamped[_ADDITIONAL_PROPERTIES_KEY] = False

        return stamped

    if isinstance(schema, list):
        return [_strictly(item) for item in schema]

    return schema
