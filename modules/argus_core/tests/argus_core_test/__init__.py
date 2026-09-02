# The module's tests, as one package named for the module they cover.
#
# A package so that a test can import the builders beside it by name, and so
# that two modules may each have a `test_config.py` - without one, pytest
# refuses duplicate test-file basenames across the workspace.
#
# Named `<module>_test` rather than `tests` or `<module>`, and the name is the
# whole point. mypy typechecks every module in one process, so whatever sits at
# the top of this chain is a workspace-wide name: `tests` or `framework` would
# collide with the next module to do the same, and `argus_core` would shadow
# the package under test.
#
# `modules/argus_core/tests/` itself stays package-free, which is what keeps
# `modules/argus_core/` the directory that lands on `sys.path`.
