"""The deployments the shop's scenarios name, staged into the repository double.

A scenario that ships a revision puts it in the deployment history, and the read
tier answers "what did that deployment change" by asking the repository to
compare it with the revision before. The double holds the fixture and nothing
else, so a pair nobody staged is a 404 - and the walk reads that as a repository
it could not reach, not as the diff that is the diagnosis.

Staged by the case rather than held by the double, for the reason the two
blind-spot cases give: these are the scenarios' facts, and a double that named
them would be keeping a copy of another repository's history. Kept here rather
than in each case because two of them are seeded by more than one file.

Each pair is a hand-written excerpt of the real one: the lines either side of
each change, as `Argus-Demo-Target-App` has them at the two commits. Not the
whole file - the double compares the two texts it was given, so an excerpt
answers with the real change and nothing else. Source files only: the tests a
commit carried beside its change are left out.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx2
from github_double.server import DEFAULT_BASE_URL as GITHUB_DOUBLE_BASE_URL

from tests.e2e.framework.argus import REQUEST_TIMEOUT_SECONDS


@dataclass(frozen=True)
class DeploymentPair:
    """A revision the shop's history names, the one before it, and what changed.

    `files` maps each path to its text at the earlier commit and at the later one.
    """

    before: str
    after: str
    files: dict[str, tuple[str, str]]


def the_deployment_was_staged(pair: DeploymentPair) -> Callable[[], bool]:
    """Puts both commits of a pair into the repository double.

    Raises rather than answering `False`, for the reason `a_scenario_was_seeded`
    does: `calling` discards what a step returns, so a commit the double refused
    would go unnoticed until the walk read a 404 as the deployment's diff.
    """
    def stage_them() -> bool:
        for sha, side in ((pair.before, 0), (pair.after, 1)):
            httpx2.post(
                f"{GITHUB_DOUBLE_BASE_URL}/double-control/stage-commit",
                json={
                    "sha": sha,
                    "files": {path: texts[side] for path, texts in pair.files.items()}
                },
                timeout=REQUEST_TIMEOUT_SECONDS
            ).raise_for_status()

        return True

    return stage_them


# `cache-misconfigured`: the cache's port moved in the values the shop ships.
THE_CACHE_PORT_MOVED = DeploymentPair(
    before="544cef36a8eaf45c5b030c3d5c21473d8176cef3",
    after="0d8e826225f0de73958a8a8dd3d867b2ae249e72",
    files={
        "deploy/values-production.yaml": (
            "cache:\n"
            "  host: cache.io-shop.svc.cluster.local\n"
            "  port: 6379\n",
            "cache:\n"
            "  host: cache.io-shop.svc.cluster.local\n"
            "  port: 6380\n"
        )
    }
)

# `bad-deployment`: the lifetime average derived from the purchases, once per
# purchase.
THE_AVERAGE_SLOWED = DeploymentPair(
    before="70dbcfde2b549d110a3817d92d60b6dd9786e78b",
    after="5e07d73148d0a704b8fefe5f379bc652bb773655",
    files={
        "src/io_shop/spend_summary.py": (
            '''\
    Live for years. Its divisor is empty only for an account that has never
    bought anything at all, which no real shopper is.
    """
    return account.total_cents // len(account.purchases)
''',
            '''\
    Live for years. Its divisor is empty only for an account that has never
    bought anything at all, which no real shopper is.

    Derives the total from the purchases rather than reading the one the account
    carries, taking each purchase in and recomputing what has been spent by
    then, so that the figure agrees with the list the shopper is looking at even
    where the totals the query returned have drifted from it.
    """
    spent_by_then = 0

    for index, _ in enumerate(account.purchases):
        spent_by_then = sum(
            earlier.price_cents for earlier in account.purchases[:index + 1]
        )

    return spent_by_then // len(account.purchases)
'''
        )
    }
)

# `control-plane-unreachable`: which purchases fall in this month, decided from
# when each was recorded rather than from the flag the writer set.
THE_MONTH_BOUNDARY_MOVED = DeploymentPair(
    before="f0bcdb929bc6e89981742d03b02f36a40cd19ca0",
    after="3398e10e131ea6c16f468f1bc1ac0fa6426d1b0c",
    files={
        "src/io_shop/spend_summary.py": (
            '''\
from __future__ import annotations

from io_shop.accounts import Account
from io_shop.typical_spend import typical_spend_per_item

    show what a shopper is spending now rather than what they averaged over
    three years.
    """
    bought_this_month = [
        purchase for purchase in account.purchases if purchase.in_current_month
    ]
    return account.total_this_month_cents // len(bought_this_month)
''',
            '''\
from __future__ import annotations

from datetime import UTC, datetime

from io_shop.accounts import Account
from io_shop.typical_spend import typical_spend_per_item

    show what a shopper is spending now rather than what they averaged over
    three years.

    This month is decided from when the purchase was recorded rather than from
    the flag the writer set, so that a record which sat in a queue over a month
    boundary counts against the month it happened in.
    """
    now = datetime.now(UTC)
    bought_this_month = [
        purchase
        for purchase in account.purchases
        if purchase.recorded_at is not None
        and purchase.recorded_at.month == now.month
        and purchase.recorded_at.year == now.year
    ]
    return account.total_this_month_cents // len(bought_this_month)
'''
        )
    }
)

# `half-finished-rollout`: what the summary cache stores changed shape, with no
# read path kept for the old one.
THE_CACHE_ENTRY_RESHAPED = DeploymentPair(
    before="5470c1a64205bb28f9f2e8a96dc6ffa5eb2e611e",
    after="696c33a68b36aed6456cdc5b3806f33038488515",
    files={
        "src/io_shop/account_page.py": (
            '''\
    if found is not None:
        return found, True, cache_failure
''',
            '''\
    if found is not None:
        return found.amount_cents, True, cache_failure
'''
        ),
        "src/io_shop/summary_cache.py": (
            '''\
_ENDPOINT_FORMAT = "redis://{host}:{port}"


@dataclass(frozen=True)
class CacheAnswer:
    reached: bool
    summary_cents: int | None = None


def cached_summary(shopper_id: str,
                   look_up: LookUpSummary,
                   endpoint: CacheEndpoint) -> int | None:
    """The figure the cache holds for this shopper, or `None` where it holds
    none.

        raise CacheUnreachable(f"connection refused to {endpoint}")

    return answer.summary_cents
''',
            '''\
_ENDPOINT_FORMAT = "redis://{host}:{port}"

# How an entry is written down, and what separates the two things it holds.
_ENTRY_FORMAT = "{amount_cents}/{items_counted}"
_ENTRY_SEPARATOR = "/"


@dataclass(frozen=True)
class SummaryEntry:
    """What the cache holds for one shopper: the figure, and what it covers."""

    amount_cents: int
    items_counted: int

    def __str__(self) -> str:
        return _ENTRY_FORMAT.format(
            amount_cents=self.amount_cents, items_counted=self.items_counted
        )


def summary_entry_in(written: str) -> SummaryEntry | None:
    """The entry this text holds, or `None` where it holds none.

    The shape above and no other. Text that does not carry the two fields an
    entry has is text this revision has nothing to do with, and passing over it
    is what the shop's fallback is for.
    """
    amount, separator, items = written.partition(_ENTRY_SEPARATOR)

    if not separator:
        return None

    try:
        return SummaryEntry(amount_cents=int(amount), items_counted=int(items))
    except ValueError:
        return None


@dataclass(frozen=True)
class CacheAnswer:
    reached: bool
    entry: str | None = None


def cached_summary(shopper_id: str,
                   look_up: LookUpSummary,
                   endpoint: CacheEndpoint) -> SummaryEntry | None:
    """The entry the cache holds for this shopper, or `None` where it holds
    none.

        raise CacheUnreachable(f"connection refused to {endpoint}")

    if answer.entry is None:
        return None

    return summary_entry_in(answer.entry)
'''
        )
    }
)

# `monthly-totals-falling-behind`: a purchase no longer moves its shopper's
# monthly total.
THE_MONTH_STOPPED_BEING_CARRIED = DeploymentPair(
    before="4c810f22894e612ced87f5ee3f3062dfeb785050",
    after="26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2",
    files={
        "src/io_shop/purchase_ledger.py": (
            '''\
def record_purchase(account: Account, purchase: Purchase) -> Account:
    """The account with this purchase written into it, and both totals moved.

    How a purchase has always been recorded. Each total is added to rather than
    worked out again: the account already carries what has been spent, and a sale
    changes it by exactly the price of the thing sold.

    The month is the part worth reading twice. A purchase counts towards the
    month's total only if it falls in the month being counted, so that addition is
    conditional where the lifetime one is not - and a shopper backfilling an older
    order leaves this month's figure exactly where it was.
    """
    return replace(
        account,
        purchases=(*account.purchases, purchase),
        total_cents=account.total_cents + purchase.price_cents,
        total_this_month_cents=(
            account.total_this_month_cents + purchase.price_cents
            if purchase.in_current_month
            else account.total_this_month_cents
        )
    )
''',
            '''\
def record_purchase(account: Account, purchase: Purchase) -> Account:
    """The account with this purchase written into it, and its total moved.

    How a purchase is recorded. The lifetime total is added to rather than worked
    out again: the account already carries what has been spent, and a sale changes
    it by exactly the price of the thing sold.

    The month is no longer carried. Every purchase says whether it falls in the
    current month, so what a shopper has spent this month adds up from the history
    whenever anybody wants it - exactly as the lifetime average is derived from the
    purchases rather than read off the account. A second copy of a figure the
    purchases already hold is a copy that has to be kept in step, and the cheapest
    way to keep it in step is not to keep it.
    """
    return replace(
        account,
        purchases=(*account.purchases, purchase),
        total_cents=account.total_cents + purchase.price_cents
    )
'''
        )
    }
)

# `categoriser-model-upgraded`: the categoriser moved from model v1 to v2.
THE_CATEGORISER_UPGRADED = DeploymentPair(
    before="d268103129978816ce705c50c14cd42c7c5fe46e",
    after="7c3ca00c7528df68d533f6e87acd4f23a55ab342",
    files={
        "deploy/values-production.yaml": (
            "categoriser:\n"
            "  model: v1\n",
            "categoriser:\n"
            "  model: v2\n"
        )
    }
)
