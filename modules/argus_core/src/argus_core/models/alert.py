from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, model_validator


class AlarmClaim(StrEnum):
    """What a rule looked at to decide it had something to say.

    Named for the rule's own subject rather than for what Argus does with the
    answer, because the rule is what knows it and a consumer is not. What the
    answer decides is whether a window holding no departure is evidence against
    this alarm or no evidence about it at all: a threshold on a series Argus also
    retrieves can be contradicted by that series, and a check comparing stored
    values against the records behind them cannot be contradicted by any series,
    because none of them was ever the subject.
    """

    # A condition the rule measured on a series the system also retrieves - an
    # error rate, a latency, a resource against its limit. Almost every rule in
    # any monitoring stack, and the reading a silent sender is taken to mean.
    A_SERIES_CONDITION = "series-condition"
    # Something the rule worked out for itself and no series carries: stored
    # totals that disagree with the records behind them, cached figures the
    # records have moved past, readings that stopped arriving at all.
    ITS_OWN_FINDING = "own-finding"


class Alert(BaseModel):
    """Argus's own normalized alert shape (spec §7.9, §25).

    Built by a vendor-specific adapter (e.g. argus_web's Grafana parser) at
    the system boundary - nothing past that boundary ever sees a vendor's
    raw payload shape.
    """

    service: str
    alert_name: str
    severity: str | None = None
    summary: str | None = None
    started_at: datetime | None = None
    # When the incident began, according to whatever raised the alert - and
    # unset for almost every alert there is, which is the normal case rather
    # than a gap. A rule watching a series reports a minute Argus measures for
    # itself from the buckets it retrieved, and a measured minute is evidence
    # where a stated one is testimony.
    #
    # An alert states one only where it knows something the series cannot say. A
    # check that reconciles stored values against the records behind them finds
    # what went wrong long after the writing did, and dates it from the oldest
    # record it found wrong; nothing in any series marks that minute, because
    # nothing failed and nothing slowed. Distinct from `started_at` for exactly
    # that reason - that is when somebody noticed, and here the two differ by a
    # week.
    stated_onset: datetime | None = None
    # What the rule that fired this looked at, which decides what a window with
    # no departure in it proves.
    #
    # The one field here whose omission means something rather than nothing, and
    # the only one carrying a default that is not `None`. A sender saying nothing
    # is read as a threshold rule, because that is what almost every rule is -
    # and the alternative is worse in the one direction that matters: a silence
    # read as a finding of the rule's own would make a well service
    # unfalsifiable, because nothing Argus retrieves could ever contradict it.
    #
    # Deliberately not derived from whether `stated_onset` is set. A check can
    # find a disagreement it cannot date - what would date it is sometimes the
    # very thing that went missing - and such an alert is indistinguishable from
    # a threshold rule that stated nothing. Nor read off `alert_name`: that is a
    # table every rule in the estate has to join, and it classifies a rule named
    # after its service by its spelling rather than by what it watched.
    claim: AlarmClaim = AlarmClaim.A_SERIES_CONDITION
    # The entries a reconciliation found holding a value the records behind them
    # have moved past, addressed as the store that holds them addresses them.
    #
    # The only thing in an alert that is an address rather than a description, and
    # the reason it is carried at all: a key's format belongs to whoever wrote the
    # cache, so a consumer that composed one would be holding another service's
    # internals, and nothing downstream could tell a derived key from a real one.
    # The check built these to read the cache it was comparing, which is why it
    # can hand them over and Argus cannot work them out.
    #
    # A tuple rather than a set, and order is kept: an action is sent one call
    # naming all of them, and a collection that collapsed duplicates or sorted
    # them would be a different set of entries wearing the same count.
    #
    # `None` rather than empty where the sender said nothing, as every other
    # optional field here is - an alert that mentions no cache is not an alert
    # claiming no entry is stale.
    stale_entry_keys: tuple[str, ...] | None = None
    # How many entries that reconciliation found, as it counted them.
    #
    # The same fact as the length of the list above, carried twice on purpose.
    # A list of addresses is the one payload whose truncation is invisible: cut
    # short, it is still a list of real keys, and it reads as a smaller incident
    # and is acted on as one. Two fields that say the same thing can be made to
    # disagree, which is the only way this is ever caught.
    stale_entries_found: int | None = None
    # Which rule fired, as whatever raised the alert addresses it - so that whether
    # it has stopped firing can be asked of that rule.
    #
    # A reference that names no vendor. The adapter that built this alert knows
    # where its sender keeps the rule's identity; everything past the boundary
    # only joins a re-firing to the incident the rule opened, or hands it back
    # to the port that reads rules. `None` where the sender
    # named none, and never guessed from `alert_name`, which is a title several
    # rules can share.
    rule: str | None = None

    @model_validator(mode="after")
    def _the_keys_account_for_the_count(self) -> Alert:
        """Refuse an alert whose key list does not match its own count.

        Refused rather than reconciled, because there is no way to tell which of
        the two is wrong: a count that is high may be a truncated list, and a
        list that is long may be a count written before somebody appended. Either
        way the entries Argus would act on are not the entries the check found,
        and acting on a subset is how an incident is closed over entries nobody
        looks at again.

        Only where both were stated. A sender that gave keys and no count, or a
        count and no keys, has said less rather than said something
        contradictory - and the first is still enough to act on.
        """
        if self.stale_entry_keys is None or self.stale_entries_found is None:
            return self

        if len(self.stale_entry_keys) != self.stale_entries_found:
            raise ValueError(
                f"The alert carries {len(self.stale_entry_keys)} stale entry "
                f"keys and reports {self.stale_entries_found} stale entries. "
                f"One of the two is wrong and nothing here can say which, so "
                f"the entries to act on are not the entries that were found."
            )

        return self
