r"""What a model wrote, where it escaped a character instead of writing it.

The model's own artefact, not the API's. A response is decoded exactly once on
the way in - the SDK hands over a `tool_use` block's arguments already parsed -
so an escape sequence still standing in a decoded value is one the model typed a
backslash into. It happens rarely, and always around typography it could have
written directly: an arrow between two flag states, a dash between two times.

Resolved here, where the answer is accepted, rather than in whichever view
happens to show it. One summary reaches a web page, a postmortem and a message
to a human, and a repair living in one of those is missing from the other two.

Only `\uXXXX`. Every other backslash sequence is left as written, because this
runs over every tool argument of every agent - Code-Fix's arguments are source
code, and a `\n` inside a proposed string literal is two characters the model
meant.
"""

from __future__ import annotations

import re
from typing import Final

# A character the model escaped rather than wrote, with however many backslashes
# it put in front of it - it occasionally escapes the backslash of its own
# escape. Four hex digits exactly, so a sequence that opens like an escape and
# names no character - a Windows path, a regex, `\uZZZZ` - never matches, and is
# therefore never guessed at.
_AN_ESCAPED_CHARACTER: Final = re.compile(r"\\+u([0-9a-fA-F]{4})")

# The half-characters. A code point outside the basic plane is escaped as two of
# these, and one on its own names no character: Python will hold a lone half
# happily and then refuse to encode it, which surfaces as a page that will not
# render rather than as a sentence that reads oddly.
_LOWEST_HALF_CHARACTER: Final = 0xD800
_HIGHEST_HALF_CHARACTER: Final = 0xDFFF

_HEXADECIMAL: Final = 16


def with_escapes_resolved(said: str) -> str:
    r"""A model's sentence, with any character it escaped written out.

    Left exactly as written wherever the sequence names no character: the point
    is to show what the model meant, and guessing at something that is not an
    escape would be inventing it.
    """
    if "\\u" not in said:
        return said

    return _AN_ESCAPED_CHARACTER.sub(_the_character_named, said)


def _the_character_named(found: re.Match[str]) -> str:
    """One escape as the character it names, or as it stands if that is nothing."""
    code_point = int(found.group(1), _HEXADECIMAL)

    if _LOWEST_HALF_CHARACTER <= code_point <= _HIGHEST_HALF_CHARACTER:
        return found.group(0)

    return chr(code_point)
