"""Notes on testing approach: Starlette's TestClient only flushes a
server-pushed websocket message to the synchronous client once some
client-driven call pumps that connection again. A message pushed purely by
an independent background task (like our turn timer, with no client action
following it) can sit unseen forever, even though it was sent successfully
(this does not happen against a real browser/uvicorn, which streams pushes
immediately). So timer-only transitions are asserted by inspecting the
Room/Game objects directly after a real sleep past the (shortened) timeout;
receive_json() is reserved for broadcasts genuinely triggered by a client
action, which are delivered immediately and are exercised elsewhere too."""
import time

import pytest
from fastapi.testclient import TestClient

from poker.game import Stage
from server import game_ws
from server.main import app, room_manager
from server.rooms import STARTING_STACK

client = TestClient(app)


def setup_function() -> None:
    room_manager._rooms.clear()


def _create_room_with_players(names: list[str]) -> tuple[str, list[str]]:
    code = client.post("/rooms").json()["code"]
    player_ids = [client.post(f"/rooms/{code}/join", json={"name": n}).json()["player_id"] for n in names]
    return code, player_ids


def _start_match(host_ws, *other_ws):
    """Host starts the match; returns the resulting state for host_ws
    followed by each of other_ws, in the order given."""
    host_ws.send_json({"action": "start_match"})
    return [host_ws.receive_json()] + [ws.receive_json() for ws in other_ws]


def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.02) -> None:
    """Poll instead of sleeping a fixed amount, so we react as soon as a
    timeout-driven transition happens rather than risking a second timeout
    cascading past the state we meant to observe."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition was not met within the timeout")


def test_timeout_auto_checks_when_legal_and_advances_stage(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(game_ws, "TURN_TIMEOUT_SECONDS", 0.15)
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            alice_state, bob_state = _start_match(alice_ws, bob_ws)

            actor_id = alice_state["current_actor"]
            actor_ws = alice_ws if actor_id == alice_id else bob_ws
            other_ws = bob_ws if actor_ws is alice_ws else alice_ws
            other_id = bob_id if actor_ws is alice_ws else alice_id

            actor_ws.send_json({"action": "call"})
            actor_ws.receive_json()
            other_ws.receive_json()

            # other_id now faces nothing to call; let the turn clock expire
            # instead of acting. Poll for the fully-settled condition (not
            # just the stage flip) since stage and current_actor are updated
            # by separate statements under the lock; polling raw attributes
            # from this thread without synchronization could otherwise catch
            # a half-updated snapshot.
            room = room_manager.get_room(code)
            _wait_until(lambda: room.game.stage == Stage.FLOP and room.game.current_actor == other_id)

            # drain the auto-check broadcast the timer pushed while nothing was
            # pumping the connection (see module docstring) before sending more.
            actor_ws.receive_json()
            other_ws.receive_json()

            # end the hand with a real action, confirming broadcasts resume normally.
            other_ws.send_json({"action": "fold"})
            other_final = other_ws.receive_json()
            actor_final = actor_ws.receive_json()

    assert other_final["stage"] == "SHOWDOWN"
    assert actor_final["stage"] == "SHOWDOWN"
    assert sum(actor_final["payouts"].values()) > 0


def test_timeout_auto_folds_when_facing_a_bet_ends_heads_up_hand(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(game_ws, "TURN_TIMEOUT_SECONDS", 0.15)
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            _start_match(alice_ws, bob_ws)

            # the first actor faces the big blind (to_call > 0) and never acts.
            # Poll for the fully-settled condition, since stage, last_payouts
            # and turn_deadline are cleared by separate statements under the
            # lock; a fixed sleep after just the stage flip is inherently racy.
            room = room_manager.get_room(code)
            _wait_until(
                lambda: room.game.stage == Stage.SHOWDOWN
                and room.turn_deadline is None
                and room.turn_timer_task is None
            )
            assert room.last_payouts is not None
            assert sum(room.last_payouts.values()) > 0


def test_disconnected_actor_auto_folds_after_grace_period_not_full_timeout(monkeypatch: pytest.MonkeyPatch):
    # A full timeout would take far longer than this test should ever wait;
    # only the short grace period should be able to resolve this in time.
    monkeypatch.setattr(game_ws, "TURN_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(game_ws, "DISCONNECT_GRACE_SECONDS", 0.15)
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            alice_state, bob_state = _start_match(alice_ws, bob_ws)

            actor_id = alice_state["current_actor"]
            actor_ws = alice_ws if actor_id == alice_id else bob_ws
            watcher_ws = bob_ws if actor_ws is alice_ws else alice_ws

            actor_ws.close()

            # the disconnect itself is a real connection-lifecycle event, so
            # its broadcast is delivered immediately (unlike a pure timer fire).
            disconnect_broadcast = watcher_ws.receive_json()
            players_by_id = {p["player_id"]: p for p in disconnect_broadcast["players"]}
            assert players_by_id[actor_id]["connected"] is False

            started = time.perf_counter()
            room = room_manager.get_room(code)
            _wait_until(lambda: room.game.stage == Stage.SHOWDOWN)
            elapsed = time.perf_counter() - started

    assert room.game.stage == Stage.SHOWDOWN
    assert elapsed < 2.0  # comfortably under the 5s full timeout: the grace period fired instead


def test_no_timer_left_armed_after_hand_ends_via_manual_action():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            alice_state, bob_state = _start_match(alice_ws, bob_ws)

            actor_id = alice_state["current_actor"]
            actor_ws = alice_ws if actor_id == alice_id else bob_ws
            other_ws = bob_ws if actor_ws is alice_ws else alice_ws

            actor_ws.send_json({"action": "fold"})
            actor_final = actor_ws.receive_json()
            other_ws.receive_json()

            room = room_manager.get_room(code)
            assert room.turn_deadline is None
            assert room.turn_timer_task is None

    assert actor_final["stage"] == "SHOWDOWN"


def test_chip_conservation_holds_through_timeout_driven_actions(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(game_ws, "TURN_TIMEOUT_SECONDS", 0.15)
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            alice_state, bob_state = _start_match(alice_ws, bob_ws)

            actor_id = alice_state["current_actor"]
            actor_ws = alice_ws if actor_id == alice_id else bob_ws
            other_ws = bob_ws if actor_ws is alice_ws else alice_ws

            # manual call, then a timeout-driven auto-check, then a manual fold.
            actor_ws.send_json({"action": "call"})
            actor_ws.receive_json()
            other_ws.receive_json()

            room = room_manager.get_room(code)
            _wait_until(lambda: room.game.stage == Stage.FLOP)

            # drain the auto-check broadcast the timer pushed while nothing was
            # pumping the connection (see module docstring) before sending more.
            actor_ws.receive_json()
            other_ws.receive_json()

            other_ws.send_json({"action": "fold"})
            other_final = other_ws.receive_json()
            actor_ws.receive_json()

    assert other_final["stage"] == "SHOWDOWN"
    assert sum(p.stack for p in room.game.players) == 2 * STARTING_STACK


def test_turn_deadline_is_stable_across_broadcasts_within_same_turn():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])
    carol_id = client.post(f"/rooms/{code}/join", json={"name": "Carol"}).json()["player_id"]

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            alice_state, bob_state = _start_match(alice_ws, bob_ws)

            first_deadline = alice_state["turn_deadline"]
            assert isinstance(first_deadline, float)
            assert bob_state["turn_deadline"] == first_deadline

            # Carol connecting mid-turn broadcasts a fresh state to everyone,
            # but it isn't a new turn, so the deadline must not move.
            with client.websocket_connect(f"/ws/{code}?player_id={carol_id}") as carol_ws:
                carol_state = carol_ws.receive_json()
                bob_state2 = bob_ws.receive_json()
                alice_state2 = alice_ws.receive_json()

    assert carol_state["turn_deadline"] == first_deadline
    assert bob_state2["turn_deadline"] == first_deadline
    assert alice_state2["turn_deadline"] == first_deadline


def test_rejoining_mid_turn_does_not_reset_the_deadline():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            alice_state, bob_state = _start_match(alice_ws, bob_ws)
            first_deadline = alice_state["turn_deadline"]

            actor_id = alice_state["current_actor"]
            actor_ws = alice_ws if actor_id == alice_id else bob_ws
            other_ws = bob_ws if actor_ws is alice_ws else alice_ws

            # The current actor "clicks Join again": a second websocket for
            # the same player_id connects, replacing the first, exactly like
            # an existing player rejoining rather than a fresh disconnect.
            with client.websocket_connect(f"/ws/{code}?player_id={actor_id}") as rejoin_ws:
                rejoin_state = rejoin_ws.receive_json()
                other_state = other_ws.receive_json()

                # The old connection's own disconnect handling (triggered by
                # being replaced) runs as an independent background task and
                # could still rearm the timer slightly later. Force it to
                # run now and confirm the deadline is untouched, checking the
                # room's actual state directly rather than trusting
                # message-pump timing (see module docstring).
                actor_ws.close()
                time.sleep(0.2)
                room = room_manager.get_room(code)
                assert room.turn_deadline == first_deadline

    assert rejoin_state["turn_deadline"] == first_deadline
    assert other_state["turn_deadline"] == first_deadline
    assert rejoin_state["current_actor"] == actor_id
