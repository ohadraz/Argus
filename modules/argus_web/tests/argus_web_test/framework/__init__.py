"""Test support shared across `argus_web`'s own suites.

Split by what a helper is rather than by which suite first needed it. `reading`
drives the app and picks the document apart, `assertions` says what a page or a
response had to contain, and `builders` makes the payloads an endpoint is sent.
"""
