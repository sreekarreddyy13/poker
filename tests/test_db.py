from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.db import Database
from server.main import app, room_manager
from server.rooms import STARTING_STACK

client = TestClient(app)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def _create_room_with_players(names: list[str]) -> tuple[str, list[str]]:
    code = client.post("/rooms").json()["code"]
    player_ids = [client.post(f"/rooms/{code}/join", json={"name": n}).json()["player_id"] for n in names]
    return code, player_ids


def test_record_hand_stores_payouts_and_stacks(database: Database):
    hand_id = database.record_hand(
        "ABC123",
        payouts={"p1": 20, "p2": 0},
        stacks_after={"p1": 1020, "p2": 980},
    )
    assert hand_id == 1

    history = database.get_hand_history("ABC123")
    assert len(history) == 1
    assert history[0]["hand_number"] == 1
    assert history[0]["payouts"] == {"p1": 20, "p2": 0}
    assert history[0]["stacks_after"] == {"p1": 1020, "p2": 980}
    assert history[0]["created_at"]


def test_hand_numbers_increment_per_room(database: Database):
    database.record_hand("ABC123", {"p1": 10}, {"p1": 1010})
    database.record_hand("ABC123", {"p1": 10}, {"p1": 1020})
    database.record_hand("OTHER1", {"p2": 5}, {"p2": 1005})

    history = database.get_hand_history("ABC123")
    assert [h["hand_number"] for h in history] == [1, 2]

    other_history = database.get_hand_history("OTHER1")
    assert [h["hand_number"] for h in other_history] == [1]


def test_get_hand_history_empty_for_unknown_room(database: Database):
    assert database.get_hand_history("NOPE99") == []


def test_update_and_get_chip_balance(database: Database):
    assert database.get_chip_balance("p1") is None

    database.update_chip_balance("p1", "Alice", 1000)
    assert database.get_chip_balance("p1") == 1000

    database.update_chip_balance("p1", "Alice", 850)
    assert database.get_chip_balance("p1") == 850


def test_chip_balances_are_independent_per_player(database: Database):
    database.update_chip_balance("p1", "Alice", 1000)
    database.update_chip_balance("p2", "Bob", 500)

    assert database.get_chip_balance("p1") == 1000
    assert database.get_chip_balance("p2") == 500


def test_data_persists_across_database_instances(tmp_path: Path):
    path = tmp_path / "persist.db"
    Database(path).update_chip_balance("p1", "Alice", 750)

    reopened = Database(path)
    assert reopened.get_chip_balance("p1") == 750


def test_settling_a_hand_over_websocket_persists_history_and_balances(isolated_game_db: Database):
    room_manager._rooms.clear()
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            alice_ws.send_json({"action": "start_match"})
            alice_state = alice_ws.receive_json()
            bob_state = bob_ws.receive_json()

            actor_id = alice_state["current_actor"]
            actor_ws = alice_ws if actor_id == alice_id else bob_ws
            other_ws = bob_ws if actor_ws is alice_ws else alice_ws

            actor_ws.send_json({"action": "fold"})
            actor_ws.receive_json()
            other_ws.receive_json()

    history = isolated_game_db.get_hand_history(code)
    assert len(history) == 1
    assert history[0]["hand_number"] == 1
    assert set(history[0]["payouts"]) == {alice_id, bob_id}
    assert sum(history[0]["payouts"].values()) > 0

    assert isolated_game_db.get_chip_balance(alice_id) is not None
    assert isolated_game_db.get_chip_balance(bob_id) is not None
    balances = {alice_id: isolated_game_db.get_chip_balance(alice_id), bob_id: isolated_game_db.get_chip_balance(bob_id)}
    assert sum(balances.values()) == 2 * STARTING_STACK
