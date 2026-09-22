"""Load test for real-time websocket gameplay.

Spins up the real server (`uvicorn server.main:app`, same command as the
Dockerfile) as a subprocess and drives it over real websocket connections
for N concurrent simulated rooms of 2-6 players each. Each simulated player
takes legal actions at a randomized "thinking" pace. Measures action-to-
broadcast latency: the time from a client sending an action to every
connected client in that room receiving the resulting state broadcast
(the sender's own reply distinguishes an error, sent only to the sender,
from a broadcast, sent to everyone).

Run with:
    python -m benchmarks.bench_ws_load
    python -m benchmarks.bench_ws_load --sweep 10,20,40,80,160

Every socket operation is wrapped in a timeout, a room is aborted (not left
hanging) after repeated stalls or illegal actions, and the whole run sits
under one hard deadline that always tears down the server subprocess.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import random
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

REPO_ROOT = Path(__file__).resolve().parent.parent

MSG_TIMEOUT = 10.0  # per websocket send/recv and per HTTP call
SERVER_START_TIMEOUT = 15.0
SERVER_STOP_TIMEOUT = 10.0
MAX_CONSECUTIVE_ERRORS = 5  # abort a room rather than retry-loop forever


@dataclass
class RoomStats:
    hands_started: int = 0
    actions: int = 0
    busted_out: int = 0
    aborted: int = 0
    abort_reasons: list[str] = field(default_factory=list)


def decide_action(state: dict, me: dict, rng: random.Random) -> dict:
    """Pick a legal action for `me` given the current public state. Biased
    toward check/call so hands last long enough to generate sustained load
    instead of everyone busting out in the first minute."""
    current_bet = state["current_bet"]
    min_raise = state["min_raise"]
    stack = me["stack"]
    my_bet = me["current_bet"]
    to_call = current_bet - my_bet
    max_total_bet = my_bet + stack

    if to_call <= 0:
        if stack > min_raise and rng.random() < 0.12:
            target = min(current_bet + min_raise, max_total_bet)
            if target > current_bet:
                return {"action": "raise", "amount": target}
        return {"action": "check"}

    if to_call >= stack:
        return {"action": "call"} if rng.random() < 0.3 else {"action": "fold"}

    if rng.random() < 0.10:
        return {"action": "fold"}
    if rng.random() < 0.08 and stack > to_call + min_raise:
        target = min(current_bet + min_raise, max_total_bet)
        return {"action": "raise", "amount": target}
    return {"action": "call"}


async def _get(queue: asyncio.Queue, timeout: float) -> tuple[float, dict]:
    return await asyncio.wait_for(queue.get(), timeout=timeout)


async def run_room(
    http: httpx.AsyncClient,
    base_url: str,
    ws_base: str,
    min_players: int,
    max_players: int,
    duration: float,
    think_min: float,
    think_max: float,
    samples: list[float],
    stats: RoomStats,
    rng: random.Random,
) -> None:
    resp = await http.post(f"{base_url}/rooms", timeout=MSG_TIMEOUT)
    code = resp.json()["code"]

    n = rng.randint(min_players, max_players)
    players = []
    for i in range(n):
        r = await http.post(f"{base_url}/rooms/{code}/join", json={"name": f"bot{i}"}, timeout=MSG_TIMEOUT)
        players.append(r.json())
    host_id = players[0]["player_id"]

    ws_map: dict[str, "websockets.WebSocketClientProtocol"] = {}
    queues: dict[str, asyncio.Queue] = {p["player_id"]: asyncio.Queue() for p in players}

    async def reader(pid: str, uri: str) -> None:
        try:
            async with websockets.connect(uri, open_timeout=MSG_TIMEOUT) as ws:
                ws_map[pid] = ws
                async for raw in ws:
                    queues[pid].put_nowait((time.monotonic(), json.loads(raw)))
        except (ConnectionClosed, OSError, asyncio.TimeoutError):
            pass

    reader_tasks = [
        asyncio.create_task(reader(p["player_id"], f"{ws_base}/ws/{code}?player_id={p['player_id']}"))
        for p in players
    ]

    try:
        deadline = time.monotonic() + MSG_TIMEOUT
        while len(ws_map) < n:
            if time.monotonic() > deadline:
                raise TimeoutError(f"room {code}: only {len(ws_map)}/{n} connections established")
            await asyncio.sleep(0.02)

        # Let the join-triggered lobby broadcasts settle, then drain them so
        # the timed loop below starts from a clean slate.
        await asyncio.sleep(0.2)
        for q in queues.values():
            while not q.empty():
                q.get_nowait()

        async def send_and_measure(sender_id: str, msg: dict) -> tuple[Optional[float], dict]:
            t0 = time.monotonic()
            await asyncio.wait_for(ws_map[sender_id].send(json.dumps(msg)), timeout=MSG_TIMEOUT)
            ts0, resp0 = await _get(queues[sender_id], MSG_TIMEOUT)
            if resp0.get("type") == "error":
                return None, resp0
            others = [pid for pid in ws_map if pid != sender_id]
            other = await asyncio.gather(*(_get(queues[pid], MSG_TIMEOUT) for pid in others))
            latest = max([ts0] + [ts for ts, _ in other])
            return latest - t0, resp0

        latency, state = await send_and_measure(host_id, {"action": "start_match"})
        if latency is None:
            stats.aborted += 1
            stats.abort_reasons.append("start_match rejected")
            return
        samples.append(latency)
        stats.hands_started += 1

        end_time = time.monotonic() + duration
        consecutive_errors = 0
        while time.monotonic() < end_time:
            if state.get("game_over"):
                stats.busted_out += 1
                break

            if state.get("stage") == "SHOWDOWN":
                sender_id = next(p["player_id"] for p in state["players"] if p.get("connected") and "stack" in p)
                msg = {"action": "next_hand"}
            else:
                actor_id = state["current_actor"]
                me = next(p for p in state["players"] if p["player_id"] == actor_id)
                msg = decide_action(state, me, rng)
                sender_id = actor_id

            await asyncio.sleep(rng.uniform(think_min, think_max))
            latency, resp = await send_and_measure(sender_id, msg)
            if latency is None:
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    stats.aborted += 1
                    stats.abort_reasons.append(f"{consecutive_errors} consecutive action errors")
                    break
                continue
            consecutive_errors = 0
            samples.append(latency)
            stats.actions += 1
            if msg["action"] == "next_hand":
                stats.hands_started += 1
            state = resp
    except (asyncio.TimeoutError, TimeoutError) as exc:
        stats.aborted += 1
        stats.abort_reasons.append(str(exc))
    finally:
        for ws in ws_map.values():
            with contextlib.suppress(Exception):
                await ws.close()
        for t in reader_tasks:
            t.cancel()
        await asyncio.gather(*reader_tasks, return_exceptions=True)


async def run_level(
    base_url: str,
    ws_base: str,
    rooms: int,
    min_players: int,
    max_players: int,
    duration: float,
    think_min: float,
    think_max: float,
    seed: int,
) -> tuple[list[float], RoomStats]:
    samples: list[float] = []
    stats = RoomStats()
    rng_master = random.Random(seed)

    async with httpx.AsyncClient() as http:
        tasks = [
            asyncio.create_task(
                run_room(
                    http,
                    base_url,
                    ws_base,
                    min_players,
                    max_players,
                    duration,
                    think_min,
                    think_max,
                    samples,
                    stats,
                    random.Random(rng_master.random()),
                )
            )
            for _ in range(rooms)
        ]
        # Hard cap well above `duration` so a stuck room can never hang the
        # whole level -- individual per-message timeouts should trip first,
        # but this is the backstop.
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=duration + MSG_TIMEOUT * (MAX_CONSECUTIVE_ERRORS + 4) + 30,
        )
    return samples, stats


def _percentile(sorted_samples: list[float], pct: float) -> float:
    if not sorted_samples:
        return float("nan")
    idx = min(len(sorted_samples) - 1, int(round(pct / 100 * (len(sorted_samples) - 1))))
    return sorted_samples[idx]


async def wait_for_server(base_url: str) -> None:
    deadline = time.monotonic() + SERVER_START_TIMEOUT
    async with httpx.AsyncClient() as http:
        while True:
            try:
                r = await http.get(base_url + "/", timeout=1.0)
                if r.status_code < 500:
                    return
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError(f"server did not become ready within {SERVER_START_TIMEOUT}s")
            await asyncio.sleep(0.2)


async def main_async(args: argparse.Namespace) -> None:
    base_url = f"http://{args.host}:{args.port}"
    ws_base = f"ws://{args.host}:{args.port}"

    server = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "server.main:app",
            "--host", args.host, "--port", str(args.port), "--log-level", "warning",
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        await wait_for_server(base_url)

        levels = args.sweep if args.sweep else [args.rooms]
        rows = []
        for rooms in levels:
            samples, stats = await run_level(
                base_url, ws_base, rooms, args.min_players, args.max_players,
                args.duration, args.think_min, args.think_max, args.seed,
            )
            sorted_samples = sorted(samples)
            p50 = _percentile(sorted_samples, 50) * 1000
            p95 = _percentile(sorted_samples, 95) * 1000
            connections_estimate = rooms * (args.min_players + args.max_players) // 2
            rows.append(
                {
                    "rooms": rooms,
                    "connections": connections_estimate,
                    "samples": len(samples),
                    "p50_ms": p50,
                    "p95_ms": p95,
                    "hands": stats.hands_started,
                    "aborted": stats.aborted,
                    "busted": stats.busted_out,
                }
            )
            print(
                f"[rooms={rooms:>4}] ~{connections_estimate:>4} conns | "
                f"{len(samples):>5} samples | p50={p50:7.1f}ms  p95={p95:7.1f}ms | "
                f"hands={stats.hands_started:>4} aborted={stats.aborted} busted={stats.busted_out}"
            )
            if stats.abort_reasons:
                for reason in stats.abort_reasons[:5]:
                    print(f"           abort: {reason}")

        if len(rows) > 1:
            baseline_p95 = rows[0]["p95_ms"]
            threshold = max(baseline_p95 * 3, 500.0)
            degraded = next((r for r in rows if r["p95_ms"] > threshold), None)
            if degraded:
                print(
                    f"\nLatency degrades meaningfully at rooms={degraded['rooms']} "
                    f"(p95={degraded['p95_ms']:.1f}ms vs baseline p95={baseline_p95:.1f}ms)"
                )
            else:
                print("\nNo meaningful degradation observed across the tested range.")
    finally:
        server.terminate()
        try:
            server.wait(timeout=SERVER_STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=SERVER_STOP_TIMEOUT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--rooms", type=int, default=20, help="concurrent rooms (ignored if --sweep is given)")
    parser.add_argument("--sweep", type=str, default=None, help="comma-separated room counts, e.g. 10,20,40,80")
    parser.add_argument("--min-players", type=int, default=2)
    parser.add_argument("--max-players", type=int, default=6)
    parser.add_argument("--duration", type=float, default=30.0, help="seconds of steady-state load per level")
    parser.add_argument("--think-min", type=float, default=0.15, help="min simulated thinking delay, seconds")
    parser.add_argument("--think-max", type=float, default=0.6, help="max simulated thinking delay, seconds")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.sweep:
        args.sweep = [int(x) for x in args.sweep.split(",")]
    return args


def main() -> None:
    args = parse_args()
    total_levels = len(args.sweep) if args.sweep else 1
    hard_cap = SERVER_START_TIMEOUT + total_levels * (args.duration + MSG_TIMEOUT * (MAX_CONSECUTIVE_ERRORS + 4) + 30) + 60
    try:
        asyncio.run(asyncio.wait_for(main_async(args), timeout=hard_cap))
    except asyncio.TimeoutError:
        print(f"\nERROR: load test exceeded its hard deadline ({hard_cap:.0f}s) and was aborted.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
