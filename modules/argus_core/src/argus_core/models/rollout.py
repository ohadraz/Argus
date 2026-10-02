"""How far a deployment's rollout has got (spec §16)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RolloutProgress(BaseModel):
    """How many of a deployment's replicas have reached the revision being
    rolled out, and whether that is all of them.

    A contract rather than one module's value, because three parties name it: the
    read tier counts the replicas off the live Deployment, the read client carries
    the counts across the wire, and Mitigation waits on them to learn that the
    change it made has actually arrived. A type kept inside any one of those is a
    type the other two install a dependency to read.

    Two arrivals, because two actions arrive differently. A rollback has arrived
    when every replica is on the revision it returned to; a scale-out has arrived
    when every replica it asked for is running. One answer would be wrong for one
    of them: a fleet wholly on the new revision and still short of the count it
    was told to run is finished for the rollback and half done for the scale-out.
    Both targets are on the live resource - the count asked for is `spec.replicas`,
    which is the field a scale-out writes - so neither has to be remembered from
    the moment the action was taken.

    Counts rather than a verdict, and the one conclusion drawn is arithmetic.
    §16 places the counting with the channel and the judging with whoever weighs
    causes: a rollout part way through is the ordinary condition of every
    deployment for a minute or two, so a model that called one *stuck* would be
    deciding, on a timing it cannot know, something that is not its to decide.
    Whether every replica has arrived is a count reaching its target, which is a
    different question and the only one answered here.

    What the distinction buys is the thing a verdict would have cost. Mitigation
    needs to know when the minutes it is judging are minutes the change was
    actually in, so that a recovery is not read off a service still running the
    code being rolled back - and it needs that without acquiring an opinion about
    how long a platform may take, which is the opinion §16 keeps out of the write
    tier.
    """

    # Non-negative because nothing a platform reports should be otherwise, and
    # the answer that must never be arrived at by arithmetic on nonsense is that
    # the rollout converged. Refused here so a malformed count is an error the
    # caller handles rather than a confirmation it acts on.
    replicas_wanted: int = Field(ge=0)
    replicas_serving: int = Field(ge=0)
    replicas_updated: int = Field(ge=0)
    # Whether the platform has stopped converging this deployment, which is what
    # gives a caller's wait an end that nobody had to name. A rollout stopped part
    # way satisfies neither count above and never will, so a caller holding only
    # those would poll until its lease expired and leave its change applied for
    # another worker to find. It says nothing about a rollout stopped after it
    # finished, where the counts are already met and the change is in force.
    #
    # A state rather than a duration, and that is why it is readable here at all.
    # "How long is too long for a rollout" is the judgement §16 keeps out of this
    # tier, because it cannot be made from a replica count and a timestamp; "the
    # platform has stopped" is something the platform says, and reading it is the
    # same move as reading the count instead of guessing at convergence.
    #
    # Defaulted, because the read tier answers it off `spec.paused` and that field
    # is absent from a manifest nobody has interrupted. "Not stated" and "running"
    # have to be one answer, or every untouched deployment in the estate would read
    # as stopped.
    is_paused: bool = False

    @property
    def has_converged(self) -> bool:
        """Whether every replica is on the revision being rolled out.

        Reached rather than matched, and the difference is not pedantry: a
        platform scaling a deployment up reports the new replicas as updated
        before it reports them as serving, so an equality would read a fleet
        wholly on the new revision as still arriving - for as long as the
        scale-up took, which is exactly when a scale-out mitigation is waiting to
        be judged.

        Here rather than at each caller because two spellings of one comparison
        drift apart, and the two callers are a tier that reports and an agent
        that waits - the pair least likely to notice they had come to disagree.
        """
        return self.replicas_updated >= self.replicas_serving

    @property
    def has_every_replica_it_asked_for(self) -> bool:
        """Whether the deployment is running the number of replicas it was told
        to run.

        What a scale-out waits on, and a different comparison from
        `has_converged`: that one asks whether the replicas that exist are on the
        right revision, this one whether they exist at all. Doubling a fleet is
        accepted the moment the count is written and the new replicas take as long
        as they take to start, so a caller measuring in between is measuring the
        shortage the action was meant to end.

        More than asked for counts, for the reason more updated than serving
        counts: a controller that overshot while settling has still given the
        service its capacity, and an equality would wait out a surge that had
        already answered the question.
        """
        return self.replicas_serving >= self.replicas_wanted

    @property
    def replicas_outstanding(self) -> int:
        """How many replicas have not arrived yet, never below zero.

        Said as well as `has_converged` because the two answer different
        questions at different moments - whether to keep waiting, and what to say
        while waiting - and a caller holding only the boolean has nothing to tell
        a reader about a wait that is still going.
        """
        return max(0, self.replicas_serving - self.replicas_updated)
