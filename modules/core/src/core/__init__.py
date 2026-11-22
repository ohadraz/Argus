"""The shared kernel: what every module in this workspace is allowed to know.

Three surfaces, and the split is deliberate. `core.models` holds the types
two modules both name - a contract kept inside one of the parties is one the
other installs an agent to read. `core.llm` holds asking a model something.
What is exported here is the rest: how a process is configured, how it reaches
the database, how an id is minted and how a timestamp is spelled - the vocabulary
every module uses and none of them owns. How a day, a level, a span, an amount
of money or a revision is said in words is narration's.

Configuration is exported three times over. `Settings` is Argus's own
configuration, which a process reads once where it starts; `AdapterSettings` is
the base each vendor's adapter declares what it needs on - its address, its
credential, the names in its catalogue - read by the root of each process that
builds that adapter; and a `SettingsSlice` is what a root hands onwards, carrying
the fields one consumer reads and no others. A slice belongs to whoever declares
it - only the four here are named by two parties, which is what makes them
contracts rather than somebody's own. None of it names a vendor.

`events`, `replay`, `schema`, `anomaly` and `mcp_transport` are deliberately not
flattened into this namespace. Each is already a coherent surface under its own
name, and two of them export a `nobody` - one meaning "publish to no subscriber"
and the other "record no call". Flattening would force one of those to be
renamed to suit the packaging rather than the reading.
"""

from core.clock import Clock, the_clock_named_by
from core.config import (
    AdapterSettings,
    DatabaseSettings,
    ReadMcpEndpoint,
    Settings,
    SettingsSlice,
    TelemetrySettings,
    WriteMcpEndpoint,
    get_settings,
)
from core.db import Connections, connect, connect_from_env, open_pool, unit_of_work
from core.fencing import Fence, Holding, RunLost, fence, was_lost
from core.ids import UuidStr, new_id
from core.pytest_naming import is_a_test_file
from core.timestamps import (
    in_real_time,
    parse_iso,
    sleep_on_the_clock,
    to_iso,
    to_iso_minute,
    utc_now,
)

__all__ = [
    "AdapterSettings",
    "Clock",
    "Connections",
    "DatabaseSettings",
    "Fence",
    "Holding",
    "ReadMcpEndpoint",
    "RunLost",
    "Settings",
    "SettingsSlice",
    "TelemetrySettings",
    "UuidStr",
    "WriteMcpEndpoint",
    "connect",
    "connect_from_env",
    "fence",
    "get_settings",
    "in_real_time",
    "is_a_test_file",
    "new_id",
    "open_pool",
    "parse_iso",
    "sleep_on_the_clock",
    "the_clock_named_by",
    "to_iso",
    "to_iso_minute",
    "unit_of_work",
    "utc_now",
    "was_lost"
]
