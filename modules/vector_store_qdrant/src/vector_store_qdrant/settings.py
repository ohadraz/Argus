"""Where Qdrant answers, and nothing else."""

from __future__ import annotations

from core import AdapterSettings


class QdrantSettings(AdapterSettings):
    """Where the vector store is: one Qdrant, holding every corpus Argus keeps.

    The repository index and long-term memory are two collections in it, each
    named in the kernel's settings for what it holds; which store holds them is
    this adapter's. Read by the root of each process that opens one.

    Localhost by default, which is the developer's compose file; the deployment
    names the service. Qdrant's HTTP port, not its gRPC one - nothing here asks
    for gRPC.
    """

    qdrant_url: str = "http://localhost:6333"
