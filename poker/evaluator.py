from __future__ import annotations

from collections import Counter
from enum import IntEnum
from itertools import combinations
from typing import Sequence

from poker.cards import Card, Rank

HandRank = tuple[int, ...]


class HandCategory(IntEnum):
    HIGH_CARD = 0
    PAIR = 1
    TWO_PAIR = 2
    THREE_OF_A_KIND = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    FOUR_OF_A_KIND = 7
    STRAIGHT_FLUSH = 8


def _rank_name(value: int) -> str:
    return str(Rank(value))


def _plural(value: int) -> str:
    name = _rank_name(value)
    return name + "es" if name.endswith("x") else name + "s"


def describe_hand(rank: HandRank) -> str:
    """Human-readable description of an evaluated hand, e.g. "Two Pair,
    Kings and Fours" or "High Card, Ace" -- the same classification
    evaluate_hand() uses to compare hands, rendered for display."""
    category = HandCategory(rank[0])
    if category is HandCategory.HIGH_CARD:
        return f"High Card, {_rank_name(rank[1])}"
    if category is HandCategory.PAIR:
        return f"Pair of {_plural(rank[1])}"
    if category is HandCategory.TWO_PAIR:
        return f"Two Pair, {_plural(rank[1])} and {_plural(rank[2])}"
    if category is HandCategory.THREE_OF_A_KIND:
        return f"Three of a Kind, {_plural(rank[1])}"
    if category is HandCategory.STRAIGHT:
        return f"Straight, {_rank_name(rank[1])}-High"
    if category is HandCategory.FLUSH:
        return f"Flush, {_rank_name(rank[1])}-High"
    if category is HandCategory.FULL_HOUSE:
        return f"Full House, {_plural(rank[1])} full of {_plural(rank[2])}"
    if category is HandCategory.FOUR_OF_A_KIND:
        return f"Four of a Kind, {_plural(rank[1])}"
    if category is HandCategory.STRAIGHT_FLUSH:
        if rank[1] == Rank.ACE:
            return "Royal Flush"
        return f"Straight Flush, {_rank_name(rank[1])}-High"
    raise ValueError(f"unknown hand category {category!r}")


def evaluate_hand(cards: Sequence[Card]) -> HandRank:
    if not 5 <= len(cards) <= 7:
        raise ValueError("evaluate_hand requires between 5 and 7 cards")
    return max(_evaluate_5(combo) for combo in combinations(cards, 5))


def _check_straight(unique_ranks_desc: list[int]) -> tuple[bool, int]:
    if len(unique_ranks_desc) != 5:
        return False, 0
    if unique_ranks_desc[0] - unique_ranks_desc[4] == 4:
        return True, unique_ranks_desc[0]
    if unique_ranks_desc == [14, 5, 4, 3, 2]:
        return True, 5
    return False, 0


def _evaluate_5(cards: Sequence[Card]) -> HandRank:
    ranks = sorted((int(c.rank) for c in cards), reverse=True)
    is_flush = len({c.suit for c in cards}) == 1
    unique_ranks_desc = sorted(set(ranks), reverse=True)
    is_straight, straight_high = _check_straight(unique_ranks_desc)

    counts = Counter(ranks)
    groups = sorted(counts.items(), key=lambda item: (-item[1], -item[0]))
    group_ranks = [rank for rank, _count in groups]

    if is_straight and is_flush:
        return (HandCategory.STRAIGHT_FLUSH, straight_high)
    if groups[0][1] == 4:
        return (HandCategory.FOUR_OF_A_KIND, group_ranks[0], group_ranks[1])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (HandCategory.FULL_HOUSE, group_ranks[0], group_ranks[1])
    if is_flush:
        return (HandCategory.FLUSH, *ranks)
    if is_straight:
        return (HandCategory.STRAIGHT, straight_high)
    if groups[0][1] == 3:
        return (HandCategory.THREE_OF_A_KIND, group_ranks[0], *group_ranks[1:])
    if groups[0][1] == 2 and groups[1][1] == 2:
        pair_ranks = sorted(group_ranks[:2], reverse=True)
        kicker = group_ranks[2]
        return (HandCategory.TWO_PAIR, *pair_ranks, kicker)
    if groups[0][1] == 2:
        return (HandCategory.PAIR, group_ranks[0], *group_ranks[1:])
    return (HandCategory.HIGH_CARD, *ranks)
