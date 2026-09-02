from __future__ import annotations

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

    def to_wire(self) -> dict[str, Any]:
        """Renders this tool as the API expects a tool offer to look.

        Always strict, and not by a per-tool choice. The dispatcher looks a
        tool up by name and calls it with whatever arrived; an argument the
        schema never promised is one nothing is written to handle. Strict mode
        is what makes the arguments a dispatcher receives exactly the arguments
        it declared - and `additionalProperties: false` is the half of that
        which is easiest to leave out, which is why it is written here rather
        than asked of every caller.
        """
        return {
            _NAME_KEY: self.name,
            _DESCRIPTION_KEY: self.description,
            _STRICT_KEY: True,
            _INPUT_SCHEMA_KEY: {
                _TYPE_KEY: _OBJECT_TYPE,
                _PROPERTIES_KEY: self.properties,
                _REQUIRED_KEY: self.required,
                _ADDITIONAL_PROPERTIES_KEY: False
            }
        }
