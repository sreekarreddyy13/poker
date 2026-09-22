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

## Websocket gameplay load test (benchmarks/bench_ws_load.py)

Run with: `python -m benchmarks.bench_ws_load --sweep 20,80,160,320 --duration 25`

Spins up the real server (`uvicorn server.main:app`, single worker, same as
the Dockerfile) and drives it over real websocket connections for N
concurrent simulated rooms of 2-6 players each. Each simulated player takes
legal actions (mostly check/call, occasional raise/fold, `next_hand` at
showdown) at a randomized 0.15-0.6s thinking delay. Latency is measured from
a client sending an action to every connected client in that room receiving
the resulting state broadcast. Every socket op has a timeout, a room aborts
after repeated stalls/illegal actions instead of hanging, and the whole run
sits under a hard deadline that always tears down the server subprocess.

- Date: 2026-09-22
- Machine: Intel Core i5-1335U, 16 GB RAM, Windows 11 Home 10.0.26200
- Single uvicorn worker (default, matches Dockerfile CMD)

| Rooms | Connections | Samples | p50 | p95 | Hands played |
| --- | --- | --- | --- | --- | --- |
| 20 | ~80 | 1,299 | 2.5ms | 64.2ms | 95 |
| 80 | ~320 | 4,965 | 9.5ms | 122.9ms | 384 |
| 160 | ~640 | 8,321 | 79.4ms | 249.6ms | 636 |
| 320 | ~1,280 | 10,771 | 345.9ms | 852.9ms | 875 |

No actions were rejected as illegal and no rooms were aborted at any level.
Latency stays low (p95 well under 150ms) up to 80 concurrent rooms (~320
connections). Between 80 and 160 rooms p50 jumps ~8x (9.5ms -> 79.4ms),
and by 320 rooms both p50 and p95 have degraded by roughly two orders of
magnitude from baseline -- the single-process event loop is visibly
saturated. Treat ~150-300 concurrent rooms (600-1200 connections) as the
practical ceiling for one uvicorn worker on hardware like this; scale out
with more workers/processes (behind a shared room store) well before that.
