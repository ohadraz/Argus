---
name: wire-vocabulary-constants
description: Use when reading or building an external protocol's payloads - Anthropic SDK responses, MCP messages, an HTTP API's JSON - to decide how its literal strings ("tool_use", "end_turn", "text") should be named, typed, and whether a test may share the constant with the code it tests.
---

An external protocol's literal strings are not arbitrary values and not domain
values. They are a third party's vocabulary, and they need three decisions made
deliberately: named or inline, typed how, and shared or restated.

## Name them, for the field they belong to

A bare `"tool_use"` in a call tells a reader nothing about which of the several
fields spelled that way it is. Name the constant after the *field*, not the
spelling:

    TOOL_USE_TYPE: Final = "tool_use"          # a content block's `type`
    TOOL_USE_STOP_REASON: Final = "tool_use"   # the whole turn's `stop_reason`

    TEXT_TYPE: Final = "text"
    THINKING_TYPE: Final = "thinking"
    END_TURN_STOP_REASON: Final = "end_turn"

Two constants holding the same string is correct here, not duplication. They
are different fields with different value sets, and collapsing them into one
name claims they are the same thing.

## Type them `Final` - this is load-bearing, not cosmetic

SDKs type these fields as `Literal`s. Two things follow, and both are mypy
errors that look like nonsense until you know the cause:

1. **Passing one in.** `Message(role=ASSISTANT_ROLE)` fails with *expected
   `Literal['assistant']`, got `str`* unless the constant is `Final`, because a
   plain assignment widens to `str`.
2. **Comparing one out.** A response's `content` is a discriminated union, and
   mypy narrows it only against a literal. Compared to a bare `str` variable,
   every block stays every kind - so `block.text` is an error on all of them,
   and one `if` produces dozens of errors.

`Final` makes the inferred type the literal itself, and both problems vanish.

    _TEXT_TYPE: Final = "text"   # inferred as Literal["text"], not str

## Prefer the SDK's own type where one exists

Where the SDK exports a type for the union or the payload, use it rather than
restating it. `anthropic.types` has `ContentBlock`, `StopReason`, `Message`.
Handwriting `list[TextBlock | ThinkingBlock | ToolUseBlock]` fails against a
parameter expecting the full union, because `list` is invariant - and it will
fail again the next time the vendor adds a block type.

There is no constant to import, though: `StopReason` is a `Literal` *type*, not
an enum, so there is no member to reference. The type checks the string; you
still have to write it.

## Declared once, imported everywhere - tests included

A protocol's vocabulary means the same thing in every file that reads it, so it
is declared once and imported. A test that restates `TOOL_USE_TYPE` is not
pinning anything: it is a second copy of a fact, and the two drift apart
silently the moment one is corrected.

What guards against Argus and the vendor disagreeing is a test that talks to the
vendor - `tests/contract/`, where a real request is made and a real response is
parsed. A restated string cannot catch that and never could: both copies say
what Argus believes, neither says what the API does.

So a shared constant lives in one public module and everything imports it,
including tests. Only a value whose meaning is local to one test file is
declared in it.

A constant that has to be imported must therefore be public. If a test needs a
module's `_NAME`, that is the design saying the vocabulary belongs somewhere
public rather than the test saying it may reach - see the private means private
rule in `AGENTS.md`.

## Same string, different field - still two constants

Sharing is per *meaning*, never per spelling. `TOOL_USE_TYPE` and
`TOOL_USE_STOP_REASON` stay two names however identical their values, because
they are different fields with different value sets, and one name for both
claims a block's `type` and a turn's `stop_reason` are the same thing. Collapse
them and the day the API adds a stop reason spelled like a block type, every
reader has to work out which was meant.

## Keep the vocabulary in one module

Only the module that translates the protocol into Argus's own shapes should
know these strings. Everything above it holds the domain type - a `Turn`, not a
`Message` - and never compares a `stop_reason`. If a second module starts
needing the constants, the translation is in the wrong place or is not
translating enough.
