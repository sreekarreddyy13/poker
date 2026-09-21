from __future__ import annotations

from collections import Counter
from enum import IntEnum
from itertools import combinations
from typing import Sequence

from poker.cards import Card

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
