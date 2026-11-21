"""The write tier, as a typed class rather than tool names and dictionaries.

`write_mcp` builds the `WriteTier` a process holds to `argus-write-mcp`. Two
classes rather than one, as there are two servers - and holding this one
authorizes nothing: what makes the write tier the write tier is the credential
that server holds and the tools it has (spec §12.1, §13).
"""

from write_mcp_client.client import WriteTier, write_mcp

__all__ = [
    "WriteTier",
    "write_mcp"
]
