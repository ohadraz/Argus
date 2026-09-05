"""What a job title is worth, as an HR system's pay bands report it.

The adapter behind the postmortem's rate port. It answers one question - what
one job title's time costs - as a band: a minimum, a midpoint and a maximum in
a stated currency.

Bands rather than salaries, and the distinction is the point. A band belongs to
a compensation *level*, and job titles are assigned to levels, so a title can be
priced without any person's pay being read - and the credential this module
holds never needs to be able to read one.

The source is reached by configuration at whichever host is to answer: the
arrangement the on-call and revenue adapters have with their stand-ins, and for
the same reason - an adapter exercised only against a fake written by the same
hand proves the fake.
"""

from responder_rate_source.bamboohr_adapter import pay_bands
from responder_rate_source.bands import (
    PayBand,
    PayBandsByTitle,
    PayBandsUnavailable,
    ReadPayBands,
)

__all__ = [
    "PayBand",
    "PayBandsByTitle",
    "PayBandsUnavailable",
    "ReadPayBands",
    "pay_bands",
]
