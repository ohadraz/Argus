# The module's tests, as one package named for the module they cover.
#
# A package so that a test can import the builders beside it by name, and so
# that two modules may each have a `test_logs.py` - without one, pytest refuses
# duplicate test-file basenames across the workspace.
#
# Named `<module>_test` rather than `tests` or `<module>`, and the name is the
# whole point. mypy typechecks every module in one process, so whatever sits at
# the top of this chain is a workspace-wide name: `tests` or `framework` would
# collide with the next module to do the same, and `agent_investigator` would
# shadow the package under test - `import agent_investigator.tools` would find
# this directory instead of the real one.
#
# `modules/<module>/tests/` itself stays package-free, which is what keeps
# `modules/<module>/` the directory that lands on `sys.path`.
