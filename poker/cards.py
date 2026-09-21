from __future__ import annotations

import secrets
from dataclasses import dataclass
from enum import IntEnum


class Suit(IntEnum):
    CLUBS = 0
    DIAMONDS = 1
    HEARTS = 2
    SPADES = 3

    def __str__(self) -> str:
        return self.name.capitalize()


class Rank(IntEnum):
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10
    JACK = 11
    QUEEN = 12
    KING = 13
    ACE = 14

    def __str__(self) -> str:
        return self.name.capitalize()


@dataclass(frozen=True)
class Card:
    rank: Rank
    suit: Suit

    def __str__(self) -> str:
        return f"{self.rank} of {self.suit}"


class Deck:
    def __init__(self) -> None:
        self._cards: list[Card] = [Card(rank, suit) for suit in Suit for rank in Rank]
        self._rng = secrets.SystemRandom()

    def __len__(self) -> int:
        return len(self._cards)

    def shuffle(self) -> None:
        self._rng.shuffle(self._cards)

    def deal(self, n: int = 1) -> list[Card]:
        if n < 0:
            raise ValueError("n must be non-negative")
        if n > len(self._cards):
            raise ValueError("not enough cards left in the deck")
        dealt, self._cards = self._cards[:n], self._cards[n:]
        return dealt
