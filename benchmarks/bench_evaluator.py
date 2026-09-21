from __future__ import annotations

import random
import time

from poker.cards import Card, Rank, Suit
from poker.evaluator import evaluate_hand

NUM_HANDS = 100_000


def random_seven_card_hands(n: int) -> list[list[Card]]:
    deck = [Card(rank, suit) for suit in Suit for rank in Rank]
    rng = random.Random(0)
    return [rng.sample(deck, 7) for _ in range(n)]


def main() -> None:
    hands = random_seven_card_hands(NUM_HANDS)

    start = time.perf_counter()
    for hand in hands:
        evaluate_hand(hand)
    elapsed = time.perf_counter() - start

    hands_per_second = NUM_HANDS / elapsed
    print(f"Evaluated {NUM_HANDS:,} 7-card hands in {elapsed:.3f}s")
    print(f"{hands_per_second:,.0f} hands/second")


if __name__ == "__main__":
    main()
