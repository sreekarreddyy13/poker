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


def evaluate_hand_naive(cards: Sequence[Card]) -> HandRank:
    """Original combinations-based evaluator, kept for correctness comparison
    against evaluate_hand()."""
    if not 5 <= len(cards) <= 7:
        raise ValueError("evaluate_hand requires between 5 and 7 cards")
    return max(_evaluate_5(combo) for combo in combinations(cards, 5))


_RANKS_DESC: tuple[int, ...] = tuple(range(14, 1, -1))

# (high_card, bitmask) for every straight, highest first; wheel (A-2-3-4-5) last.
_STRAIGHT_MASKS: tuple[tuple[int, int], ...] = tuple(
    (high, sum(1 << r for r in range(high - 4, high + 1))) for high in range(14, 5, -1)
) + ((5, (1 << 14) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5)),)


def _best_straight(rank_bits: int) -> int:
    """Highest straight present in a rank bitmask (bit N set = rank N present), or 0."""
    for high, mask in _STRAIGHT_MASKS:
        if rank_bits & mask == mask:
            return high
    return 0


def evaluate_hand(cards: Sequence[Card]) -> HandRank:
    """Bit-manipulation evaluator: builds rank/suit bitmasks in one pass over
    the cards instead of scoring all 21 five-card combinations."""
    if not 5 <= len(cards) <= 7:
        raise ValueError("evaluate_hand requires between 5 and 7 cards")

    rank_counts = [0] * 15
    suit_bits = [0, 0, 0, 0]
    suit_counts = [0, 0, 0, 0]
    all_bits = 0

    for c in cards:
        r = int(c.rank)
        s = int(c.suit)
        bit = 1 << r
        rank_counts[r] += 1
        suit_bits[s] |= bit
        suit_counts[s] += 1
        all_bits |= bit

    flush_suit = next((s for s in range(4) if suit_counts[s] >= 5), None)
    if flush_suit is not None:
        straight_high = _best_straight(suit_bits[flush_suit])
        if straight_high:
            return (HandCategory.STRAIGHT_FLUSH, straight_high)

    quad_rank = next((r for r in _RANKS_DESC if rank_counts[r] == 4), None)
    if quad_rank is not None:
        kicker = next(r for r in _RANKS_DESC if rank_counts[r] and r != quad_rank)
        return (HandCategory.FOUR_OF_A_KIND, quad_rank, kicker)

    trip_ranks = [r for r in _RANKS_DESC if rank_counts[r] == 3]
    pair_plus_ranks = [r for r in _RANKS_DESC if rank_counts[r] >= 2]

    if trip_ranks:
        best_trip = trip_ranks[0]
        pair_candidates = [r for r in pair_plus_ranks if r != best_trip]
        if pair_candidates:
            return (HandCategory.FULL_HOUSE, best_trip, pair_candidates[0])

    if flush_suit is not None:
        flush_ranks = [r for r in _RANKS_DESC if suit_bits[flush_suit] & (1 << r)][:5]
        return (HandCategory.FLUSH, *flush_ranks)

    straight_high = _best_straight(all_bits)
    if straight_high:
        return (HandCategory.STRAIGHT, straight_high)

    if trip_ranks:
        best_trip = trip_ranks[0]
        kickers = [r for r in _RANKS_DESC if rank_counts[r] and r != best_trip][:2]
        return (HandCategory.THREE_OF_A_KIND, best_trip, *kickers)

    if len(pair_plus_ranks) >= 2:
        top_pairs = pair_plus_ranks[:2]
        kicker = next(r for r in _RANKS_DESC if rank_counts[r] and r not in top_pairs)
        return (HandCategory.TWO_PAIR, top_pairs[0], top_pairs[1], kicker)

    if len(pair_plus_ranks) == 1:
        pair_rank = pair_plus_ranks[0]
        kickers = [r for r in _RANKS_DESC if rank_counts[r] and r != pair_rank][:3]
        return (HandCategory.PAIR, pair_rank, *kickers)

    top5 = [r for r in _RANKS_DESC if rank_counts[r]][:5]
    return (HandCategory.HIGH_CARD, *top5)


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
