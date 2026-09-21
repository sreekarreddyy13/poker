# Benchmarks

## evaluate_hand (poker/evaluator.py)

Run with: `python -m benchmarks.bench_evaluator`

Measures `evaluate_hand` over 100,000 random 7-card hands (the combinations-based
5-of-7 evaluator).

### Baseline

- Date: 2026-09-22
- Machine: TODO (fill in CPU model, RAM, OS)
- Result: 100,000 hands in 7.064s -> ~14,157 hands/second
