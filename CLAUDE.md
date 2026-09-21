# Poker App
Real-time multiplayer Texas Hold'em (play chips only, no real money).

## Stack
Python 3.11+, FastAPI, WebSockets, Pydantic, pytest, SQLite (later), vanilla HTML/CSS/JS frontend.

## Layout
- poker/      pure game engine (no web imports, no I/O)
- server/     FastAPI app, rooms, websocket handling
- static/     frontend files
- tests/      pytest tests
- benchmarks/ benchmark scripts; results go in BENCHMARKS.md

## Rules
- Type hints everywhere. Keep functions small.
- Engine must stay independent of FastAPI.
- Server is authoritative: clients send intents; validate everything.
- Never send other players' hole cards to a client.
- Use secrets/SystemRandom for shuffling.
- Every feature needs pytest tests. Run tests before saying done.
- Work only on the task asked. Don't refactor unrelated files.
- Be concise: short summaries, no long explanations unless asked.

## Commands
- Run tests: pytest -q
- Run server: uvicorn server.main:app --reload