"""The tables this module owns, and the only SQL in it.

Two of them, and neither belongs to the incident record: where the relay got to
in the event log, and which Slack thread an incident is being told in. Nothing
outside this module reads either, which is what makes them its own - an
incident knows nothing about Slack, and a second destination adds a row here
rather than a column there.
"""
