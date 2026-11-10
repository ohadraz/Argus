"""The pay bands the Target Service's HR endpoint publishes, as far as the cases
that price a response need them: two titles on two different levels, and those
levels' midpoints.

TAKEN FROM THE DEMO APP (`target_app/people.py`) - DO NOT CHANGE THESE UNLESS
THE DEMO APP CHANGES THEM. They are not arbitrary: a title the endpoint does not
publish is priced by nobody, and a case that moves with the fixture fails
saying the cost left the band it was priced from, which is the failure worth
having.
"""

from __future__ import annotations

from decimal import Decimal

# Taken from the demo app - do not change unless the demo app changes them.
THE_CHEAPER_TITLE = "Site Reliability Engineer"
THE_DEARER_TITLE = "Senior Software Engineer"
THE_CHEAPEST_MIDPOINT = Decimal(175_000)
THE_DEAREST_MIDPOINT = Decimal(220_000)
