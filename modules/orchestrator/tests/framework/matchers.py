from collections.abc import Callable


class _Matcher:
    def __init__(self, predicate: Callable[[object], bool]) -> None:
        self._predicate = predicate

    def __eq__(self, other: object) -> bool:
        return self._predicate(other)


def matcher(predicate: Callable[[object], bool]) -> _Matcher:
    return _Matcher(predicate)
