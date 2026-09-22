# Benchmarks

## evaluate_hand (poker/evaluator.py)

Run with: `python -m benchmarks.bench_evaluator`

Measures `evaluate_hand` over 100,000 random 7-card hands. `evaluate_hand_naive`
is the original combinations-based evaluator (scores all 21 five-card subsets
via itertools.combinations + Counter); `evaluate_hand` is a bit-manipulation
evaluator that builds rank/suit bitmasks in a single pass over the 7 cards
instead. Both are covered by a test asserting identical results over 100,000
random hands (tests/test_evaluator.py::test_fast_evaluator_matches_naive_on_random_hands).

- Date: 2026-09-22
- Machine: Intel Core i5-1335U, 16 GB RAM, Windows 11 Home 10.0.26200

| Version | Result |
| --- | --- |
| naive (baseline) | 100,000 hands in 8.451s -> ~11,832 hands/second |
| fast (bit-manipulation) | 100,000 hands in 0.467s -> ~214,349 hands/second |

Speedup: ~18x
