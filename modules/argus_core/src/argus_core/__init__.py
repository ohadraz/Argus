"""The shared kernel: what every module in this workspace is allowed to know.

Three surfaces, and the split is deliberate. `argus_core.models` holds the types
two modules both name - a contract kept inside one of the parties is one the
other installs an agent to read. `argus_core.llm` holds asking a model something.
What is exported here is the rest: how a process is configured, how it reaches
the database, how an id is minted and how a timestamp is spelled - the vocabulary
every module uses and none of them owns.

Configuration is exported twice over, and the pair is the point. `Settings` is
the whole environment, which a process reads once where it starts; a
`SettingsSlice` is what that process hands onwards, carrying the fields one
consumer reads and no others. A slice belongs to whoever declares it - only the
four here are named by two parties, which is what makes them contracts rather
than somebody's own.

`events`, `replay`, `schema`, `anomaly` and `mcp_transport` are deliberately not
flattened into this namespace. Each is already a coherent surface under its own
name, and two of them export a `nobody` - one meaning "publish to no subscriber"
and the other "record no call". Flattening would force one of those to be
renamed to suit the packaging rather than the reading.
"""

from argus_core.config import (
    DatabaseSettings,
    LLMSettings,
    ReadMcpEndpoint,
    Settings,
    SettingsSlice,
    WriteMcpEndpoint,
    get_settings,
)
from argus_core.db import Connections, connect, connect_from_env, open_pool
from argus_core.ids import UuidStr, new_id
from argus_core.timestamps import (
    TIMESTAMP_FORMAT,
    parse_iso,
    to_iso,
    to_iso_minute,
    utc_now,
)

__all__ = [
    "TIMESTAMP_FORMAT",
    "Connections",
    "DatabaseSettings",
    "LLMSettings",
    "ReadMcpEndpoint",
    "Settings",
    "SettingsSlice",
    "UuidStr",
    "WriteMcpEndpoint",
    "connect",
    "connect_from_env",
    "get_settings",
    "new_id",
    "open_pool",
    "parse_iso",
    "to_iso",
    "to_iso_minute",
    "utc_now"
]
