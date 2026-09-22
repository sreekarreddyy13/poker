from __future__ import annotations

import random
import time

from poker.cards import Card, Rank, Suit
from poker.evaluator import evaluate_hand, evaluate_hand_naive

NUM_HANDS = 100_000


def random_seven_card_hands(n: int) -> list[list[Card]]:
    deck = [Card(rank, suit) for suit in Suit for rank in Rank]
    rng = random.Random(0)
    return [rng.sample(deck, 7) for _ in range(n)]


def _bench(fn, hands: list[list[Card]]) -> float:
    start = time.perf_counter()
    for hand in hands:
        fn(hand)
    return time.perf_counter() - start


def main() -> None:
    hands = random_seven_card_hands(NUM_HANDS)

    naive_elapsed = _bench(evaluate_hand_naive, hands)
    fast_elapsed = _bench(evaluate_hand, hands)

    for label, elapsed in (("naive", naive_elapsed), ("fast", fast_elapsed)):
        hands_per_second = NUM_HANDS / elapsed
        print(f"[{label}] Evaluated {NUM_HANDS:,} 7-card hands in {elapsed:.3f}s")
        print(f"[{label}] {hands_per_second:,.0f} hands/second")

    print(f"Speedup: {naive_elapsed / fast_elapsed:.2f}x")


if __name__ == "__main__":
    main()
