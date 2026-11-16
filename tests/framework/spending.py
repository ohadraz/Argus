"""What a paid eval's model calls cost, counted as they are made.

An eval's sample answers two questions, whether the model was right and what
the answer cost, and they are asked of the same run because a rate and its
price are read side by side. Counted here rather than asked of a budget: a
budget keeps one total to stop a run by, and a comparison needs the four counts
apart - with caching on, `input_tokens` is only the uncached remainder, and a
figure that read it alone would credit a configuration for tokens that merely
moved into the cache.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.llm import LLMClient
from core.models import ToolDefinition, Transcript, Turn


@dataclass(frozen=True)
class Spend:
    """What one sample was billed: how many turns it took, and the four token
    counts summed over them."""

    turns: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


class Tally:
    """A client that keeps every turn taken through it, so a run can say
    afterwards what it was billed.

    One per sample. A tally shared by concurrent runs would charge each one for
    whatever the others happened to spend before it finished.
    """

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self._turns: list[Turn] = []

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int | None = None) -> Turn:
        turn = self._client.converse(transcript, tools, max_tokens)
        self._turns.append(turn)

        return turn

    def spent(self) -> Spend:
        return Spend(
            turns=len(self._turns),
            input_tokens=sum(turn.input_tokens for turn in self._turns),
            output_tokens=sum(turn.output_tokens for turn in self._turns),
            cache_read_tokens=sum(turn.cache_read_tokens for turn in self._turns),
            cache_write_tokens=sum(turn.cache_write_tokens for turn in self._turns)
        )
