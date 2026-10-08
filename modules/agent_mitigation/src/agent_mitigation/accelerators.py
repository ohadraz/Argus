"""Which card to hold a deployment to, decided from where its pods were placed.

A replica the platform moved onto another card, with nothing deployed, answers
differently from the rest, and what undoes it is to hold the deployment to the
card the fleet ran on before the incident. Which card that is comes from the
placement the Investigator recorded against the onset - never from a read made
when acting, which would be made after whatever the walk did first had moved the
pods.

A function of its own rather than a branch inside the strategy, because the
decision is the whole of what is worth testing about the pin and has nothing to
do with how a strategy is registered.
"""

from __future__ import annotations

from argus_core.models import RecordedPlacement


def the_accelerator_to_pin_to(placement: RecordedPlacement | None) -> str | None:
    """The one card every pod serving before the onset ran on, where a pod
    started at the onset ran on another - or `None` wherever that is not what the
    placement says.

    Pinned only where all four hold:
    - every pod has a card the platform reported, because a card nobody
      reported may be a second card the fleet ran on, or the fleet's own;
    - the pods serving before the onset ran on exactly one card, because
      holding a fleet that ran on two to either moves pods that were well;
    - at least one pod was started at the onset, because a pin answers a moved
      replica and there is none to answer;
    - no pod started at the onset is on that card, because a reschedule onto the
      fleet's own card at the same moment is evidence the card is not what
      changed.

    `None` is not a refusal made here. It reaches the gate as no mitigation
    proposed, the walk moves on to its next candidate, and in the end to a
    person - which is how an ambiguous placement is escalated without a route
    of its own.

    Which pods were started at the onset is `RecordedPlacement`'s rule, so this
    marks the pods the opening message and the timeline mark.
    """
    if placement is None:
        return None

    if any(pod.accelerator is None for pod in placement.pods):
        return None

    serving_before = {pod.accelerator for pod in placement.started_before_the_onset()}
    started_at_the_onset = {pod.accelerator for pod in placement.started_at_the_onset()}

    if len(serving_before) != 1 or not started_at_the_onset:
        return None

    if started_at_the_onset & serving_before:
        return None

    return next(iter(serving_before))
