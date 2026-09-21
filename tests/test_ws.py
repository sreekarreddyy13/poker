import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from server.main import app, room_manager

client = TestClient(app)


def setup_function() -> None:
    room_manager._rooms.clear()


def _create_room_with_players(names: list[str]) -> tuple[str, list[str]]:
    code = client.post("/rooms").json()["code"]
    player_ids = [client.post(f"/rooms/{code}/join", json={"name": n}).json()["player_id"] for n in names]
    return code, player_ids


def test_first_player_waits_until_a_second_joins():
    code, (alice_id, _bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        state = alice_ws.receive_json()
        assert state["waiting"] is True


def test_hand_starts_once_two_players_connect():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # waiting

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_state = bob_ws.receive_json()
            alice_state = alice_ws.receive_json()

    assert bob_state["waiting"] is False
    assert alice_state["waiting"] is False
    assert bob_state["stage"] == "PREFLOP"
    assert bob_state["current_actor"] in (alice_id, bob_id)


def test_player_never_receives_another_players_hole_cards():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # waiting

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_state = bob_ws.receive_json()
            alice_state = alice_ws.receive_json()

    for state, own_id, other_id in (
        (alice_state, alice_id, bob_id),
        (bob_state, bob_id, alice_id),
    ):
        players = {p["player_id"]: p for p in state["players"]}
        assert len(players[own_id]["hole_cards"]) == 2
        assert "hole_cards" not in players[other_id]


def test_fold_ends_hand_and_broadcasts_payouts():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # waiting

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_state = bob_ws.receive_json()
            alice_state = alice_ws.receive_json()

            actor_id = alice_state["current_actor"]
            actor_ws = alice_ws if actor_id == alice_id else bob_ws
            other_ws = bob_ws if actor_ws is alice_ws else alice_ws

            actor_ws.send_json({"action": "fold"})

            actor_final = actor_ws.receive_json()
            other_final = other_ws.receive_json()

    assert actor_final["stage"] == "SHOWDOWN"
    assert other_final["stage"] == "SHOWDOWN"
    assert sum(actor_final["payouts"].values()) > 0


def test_acting_out_of_turn_sends_error_only_to_sender():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # waiting

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_state = bob_ws.receive_json()
            alice_state = alice_ws.receive_json()

            actor_id = alice_state["current_actor"]
            non_actor_ws = bob_ws if actor_id == alice_id else alice_ws

            non_actor_ws.send_json({"action": "check"})
            error = non_actor_ws.receive_json()

    assert error["type"] == "error"


def test_reconnecting_replaces_previous_connection():
    code, (alice_id, _bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as first_ws:
        first_ws.receive_json()  # waiting

        with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as second_ws:
            second_ws.receive_json()  # waiting, delivered to the new connection

            with pytest.raises(WebSocketDisconnect):
                first_ws.receive_json()


def test_missing_player_id_closes_connection():
    code = client.post("/rooms").json()["code"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/{code}") as ws:
            ws.receive_json()


def test_unknown_room_closes_connection():
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/NOPE99?player_id=abc") as ws:
            ws.receive_json()


def test_unknown_player_id_closes_connection():
    code, _ = _create_room_with_players(["Alice"])
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/{code}?player_id=doesnotexist") as ws:
            ws.receive_json()
