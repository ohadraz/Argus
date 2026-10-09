"""What another tool calls an incident.

Here rather than beside the parser that first records one, for the reason
`Report` is here: the intake adapter builds one, the incident record keeps it,
and the on-call platform's adapter matches against it. A shape kept inside one
of those parties is one the others read by comparing spellings.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel

# The kind of name a monitor stamps on every notification it also sends a
# paging tool, which is what the paging tool hands back about its incident.
#
# A kind the two sides of a match have to spell alike - the monitor's adapter
# writes it and the paging tool's adapter looks it up - and neither knows the
# other, so it is said once, here. Any monitor's, whatever its source: the
# paging tool cannot tell which monitor stamped the key it holds.
NOTIFICATION_KEY: Final = "notification-key"

# The kind of name an on-call platform's own incident is: the id the platform
# gave it, recorded once a person's resolution there was matched to an Argus
# incident, so that the next question about it goes straight to it. The source
# is the platform's report channel, so two platforms' ids never meet.
ON_CALL_INCIDENT: Final = "on-call-incident"


class Reference(BaseModel):
    """One name an external tool knows an incident by.

    Three parts, because a value alone says nothing about whose it is: two tools
    can each hand out a key that happens to be the same string, and one tool can
    name an incident several ways - a key it stamps on what it sends, an id it
    assigns itself. `source` is the tool, `kind` is which of its names this is,
    and `value` is the name as that tool spells it, never normalised, because it
    is matched against what the tool says later.

    Rows rather than fields on the incident: a new tool is one more `source`,
    not one more column.
    """

    source: str
    kind: str
    value: str
