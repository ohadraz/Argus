"""Argus's own database: where a connection comes from, saying on one which run
it writes for, and the schema - applied by one job, and required by the
processes that refuse to start without it.

A package of its own so the kernel installs no database driver. The kernel says
what a run's claim is (`core.Fence`) and how a lost one is known
(`core.was_lost`); this is everything that needs the driver to say it.
"""

from postgres.db import (
    Connections,
    connect,
    connect_from_env,
    open_pool,
    require_schema_at,
    unit_of_work,
)
from postgres.fencing import fence
from postgres.schema import (
    SchemaNotApplied,
    SchemaPresent,
    require_schema,
    reset_schema,
)

__all__ = [
    "Connections",
    "SchemaNotApplied",
    "SchemaPresent",
    "connect",
    "connect_from_env",
    "fence",
    "open_pool",
    "require_schema",
    "require_schema_at",
    "reset_schema",
    "unit_of_work"
]
