"""What a person meant by what they wrote about an incident (spec §7).

The Communicator's counterpart. The Communicator says what happened, where
people are; the Intent Agent understands what people say back. It follows the
event log as the relay does, and for every message a person wrote in an
incident's thread it asks the model to classify it - what did they mean - and
records the answer. Where the answer is that the incident is over, it offers
that person the chance to confirm it.

It never posts. What it decides reaches the thread as an event, through the
relay, like everything else Argus says.
"""
