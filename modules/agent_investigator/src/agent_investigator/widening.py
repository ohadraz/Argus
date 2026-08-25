from __future__ import annotations


def widening_schedule(
    initial_minutes: int, maximum_minutes: int, iterations: int
) -> list[int]:
    """The log lookback each investigation iteration uses, derived once from
    the three numbers that constrain it (spec §9).

    A geometric progression from the initial lookback to the maximum span:
    small steps first, the long reach last, because causes cluster near the
    onset. Deriving the whole schedule up front is what makes the last entry
    land *exactly* on the maximum - which is what makes "the onset predates
    everything retrievable" a reachable conclusion rather than a branch no
    run ever takes. Stepping the lookback iteration by iteration (doubling,
    say) silently leaves the ceiling unreached whenever the budget or the
    ceiling is reconfigured.

    With a range too narrow to give every iteration its own whole minute
    (30 to 31 over five iterations), entries repeat rather than raise; the
    schedule still spans what it was asked to span.
    """
    if iterations < 2:
        return [maximum_minutes] * iterations

    steps = iterations - 1
    growth_per_step = (maximum_minutes / initial_minutes) ** (1 / steps)

    schedule = [round(initial_minutes * growth_per_step**step) for step in range(steps)]

    # The endpoints are the two the caller actually specified, so they are set
    # rather than computed - rounding must never be the reason a lookback
    # misses the ceiling it was told to reach.
    schedule[0] = initial_minutes

    return [*schedule, maximum_minutes]
