"""The read tier, as a typed class rather than tool names and dictionaries.

`read_mcp` builds the `ReadTier` a process holds to `argus-read-mcp`, and every
tool the tier serves is a method on it. Where that server is reached is read
once, by whoever builds it; nothing below this door learns an address.

`offered` is the filtering behind `ReadTier.offered`, on a listing rather than
a session, for a suite that offers the tier's tools with no tier running.
"""

from read_mcp_client.client import ReadTier, read_mcp
from read_mcp_client.offering import NotServed, offered

__all__ = [
    "NotServed",
    "ReadTier",
    "offered",
    "read_mcp"
]
