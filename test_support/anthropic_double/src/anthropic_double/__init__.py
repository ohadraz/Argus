"""A stand-in for Anthropic's Messages API, reached via the SDK's `base_url`.

The seam sits *below* the SDK on purpose: the real adapter, the real
`messages.parse`, the real schema transform and the real response parsing all
run against this server. Only Anthropic is replaced.

It replays recordings of real responses rather than inventing answers - see
`recordings` for the store and `server` for the two routes.

This package knows nothing about Argus. It speaks one wire protocol, and the
domain model it happens to carry is whatever the recorded response contained.
"""
