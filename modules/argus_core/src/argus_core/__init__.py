"""The shared kernel: what every module in this workspace is allowed to know.

Three surfaces, and the split is deliberate. `argus_core.models` holds the types
two modules both name - a contract kept inside one of the parties is one the
other installs an agent to read. `argus_core.llm` holds asking a model something.
What is exported here is the rest: how a process is configured, how it reaches
the database, how an id is minted and how a timestamp is spelled - the vocabulary
every module uses and none of them owns.

`events`, `replay`, `schema`, `anomaly` and `mcp_transport` are deliberately not
flattened into this namespace. Each is already a coherent surface under its own
name, and two of them export a `nobody` - one meaning "publish to no subscriber"
and the other "record no call". Flattening would force one of those to be
renamed to suit the packaging rather than the reading.
"""

from argus_core.config import Settings, get_settings
from argus_core.db import Connections, connect, open_pool
from argus_core.ids import UuidStr, new_id
from argus_core.timestamps import TIMESTAMP_FORMAT, parse_iso, to_iso, to_iso_minute

__all__ = [
    "TIMESTAMP_FORMAT",
    "Connections",
    "Settings",
    "UuidStr",
    "connect",
    "get_settings",
    "new_id",
    "open_pool",
    "parse_iso",
    "to_iso",
    "to_iso_minute"
]
