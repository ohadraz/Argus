---
name: test-mocking-style
description: Use when writing or reviewing test doubles/mocks anywhere in this workspace, to keep injection seams, Protocol vs Callable choices, and create_autospec usage consistent with established conventions.
---

**Injection seam: default-argument parameter, not a class.** Match the
`agent_investigator.investigate()`/`fetch_logs` pattern - a dependency becomes a
parameter with a real default (`def some_node(state, collaborator: Collaborator =
_real_collaborator) -> ...`). Only reach for a class (`__init__` holding the
dependencies, `__call__` doing the work) when there are 2+ related collaborators
that get configured together once and reused across many calls. A class-based
LangGraph node design was tried in this codebase and reverted - LangGraph only
ever needs a plain `state -> dict` callable, and the class added ceremony with no
matching benefit once tests could inject function-shaped defaults directly.

**`unittest.mock` (`create_autospec`, `Mock(spec=...)`) is a fine test double.
`unittest.mock.patch` is not.** Two independent reasons, not just style:
- `patch()` targets a module-level import instead of the injection seam itself -
  fragile ("patch where it's used, not where it's defined").
- It doesn't even work correctly against a default-argument seam: default values
  are captured once, when the `def` statement runs - patching the underlying name
  afterward has zero effect on what the default already resolved to. Verified
  directly: patching a module attribute after a function using it as a default
  arg is defined does not change what that function calls.

**Use a `Protocol` instead of a `Callable[[...], ...]` alias when either:**
1. the collaborator is called with keyword arguments (a `Callable[...]` alias can
   only express positional parameter types), or
2. a test needs `create_autospec` to target it directly (a `Callable[...]` alias
   isn't introspectable at runtime - `create_autospec` needs a real class or
   function to inspect; a `Protocol`'s `__call__` method gives it one).

**Two `create_autospec` gotchas, both confirmed empirically in this workspace -
don't assume the obvious API works:**
- `create_autospec(some_function)` on a plain function returns a real function
  object with mock-tracking attributes bolted on (`.return_value`, `.call_args`,
  etc.) - not a `MagicMock` instance. It has no `.configure_mock`. Set
  `.return_value = ...` directly instead.
- `create_autospec(SomeProtocol, instance=True)` does not strip `self` from the
  Protocol's `__call__` signature when building its internal spec signature. This
  makes `.assert_called_with(...)`/`.assert_called_once_with(...)` fail even when
  the actual and expected calls print identically in the error message. Work
  around it by comparing `mock.call_args == call(*args, **kwargs)` directly
  instead of using the `assert_called_*_with` methods.

**Don't mock/autospec a private (`_`-prefixed) name.** Spec against the public
contract - the real public function, or a public `Protocol`/class - not an
internal default-implementation detail. If the thing worth specing against is
private, that's a sign it needs a public type (usually a `Protocol`) instead.
