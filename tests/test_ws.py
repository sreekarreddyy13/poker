import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from poker.cards import Card, Rank, Suit
from poker.game import Stage
from server.game_ws import build_state
from server.main import app, room_manager
from server.rooms import STARTING_STACK, RoomStatus

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


def test_first_player_waits_until_a_second_joins():
    code, (alice_id, _bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        state = alice_ws.receive_json()
        assert state["waiting"] is True


def test_room_starts_in_waiting_status():
    code, (alice_id, _bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        state = alice_ws.receive_json()
        assert state["room_status"] == "WAITING"
        assert state["host_id"] == alice_id


def test_room_stays_in_lobby_until_host_starts_match():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_state = bob_ws.receive_json()
            alice_state = alice_ws.receive_json()

    assert bob_state["room_status"] == "WAITING"
    assert alice_state["room_status"] == "WAITING"
    assert bob_state["waiting"] is True
    assert "stage" not in bob_state


def test_non_host_cannot_start_match():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            bob_ws.send_json({"action": "start_match"})
            error = bob_ws.receive_json()

    assert error["type"] == "error"

    room = room_manager.get_room(code)
    assert room.status == RoomStatus.WAITING
    assert room.game is None


def test_match_cannot_start_with_fewer_than_two_players():
    code, (alice_id,) = _create_room_with_players(["Alice"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        alice_ws.send_json({"action": "start_match"})
        error = alice_ws.receive_json()

    assert error["type"] == "error"

    room = room_manager.get_room(code)
    assert room.status == RoomStatus.WAITING


def test_hand_starts_after_host_starts_match():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            alice_state, bob_state = _start_match(alice_ws, bob_ws)

    assert alice_state["room_status"] == "IN_PROGRESS"
    assert bob_state["waiting"] is False
    assert alice_state["waiting"] is False
    assert bob_state["stage"] == "PREFLOP"
    assert bob_state["current_actor"] in (alice_id, bob_id)


def test_join_once_in_progress_queues_for_next_hand_instead_of_being_rejected():
    # Chosen policy for latecomers (see plan): joining stays open once the
    # match is IN_PROGRESS. New joiners take a seat immediately but aren't
    # dealt into the hand already underway -- they queue for the next hand,
    # same mechanism test_joining_mid_hand_is_queued_until_next_hand exercises
    # end-to-end. This test just pins the HTTP-level contract.
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            _start_match(alice_ws, bob_ws)

            response = client.post(f"/rooms/{code}/join", json={"name": "Carol"})
            assert response.status_code == 200


def test_player_never_receives_another_players_hole_cards():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            alice_state, bob_state = _start_match(alice_ws, bob_ws)

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
            other_final = other_ws.receive_json()

    assert actor_final["stage"] == "SHOWDOWN"
    assert other_final["stage"] == "SHOWDOWN"
    assert sum(actor_final["payouts"].values()) > 0


def test_showdown_reveals_hole_cards_and_hand_category_to_every_viewer():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            _start_match(alice_ws, bob_ws)

            room = room_manager.get_room(code)
            game = room.game
            game.community_cards = [
                Card(Rank.TWO, Suit.CLUBS), Card(Rank.FIVE, Suit.DIAMONDS),
                Card(Rank.NINE, Suit.HEARTS), Card(Rank.JACK, Suit.CLUBS),
                Card(Rank.KING, Suit.DIAMONDS),
            ]
            alice_player = next(p for p in game.players if p.player_id == alice_id)
            bob_player = next(p for p in game.players if p.player_id == bob_id)
            alice_player.hole_cards = [Card(Rank.KING, Suit.HEARTS), Card(Rank.SIX, Suit.HEARTS)]
            bob_player.hole_cards = [Card(Rank.JACK, Suit.HEARTS), Card(Rank.THREE, Suit.SPADES)]
            game.stage = Stage.SHOWDOWN
            game.current_actor_index = None

            connected = {alice_id, bob_id}
            bob_view_state = build_state(room, alice_id, connected)

    players = {p["player_id"]: p for p in bob_view_state["players"]}
    assert players[alice_id]["hand_category"] == "Pair of Kings"
    assert players[bob_id]["hand_category"] == "Pair of Jacks"
    # Alice (the viewer) sees Bob's hole cards too, since both hands were
    # shown at showdown -- not just her own.
    assert players[bob_id]["hole_cards"] == [
        {"rank": "JACK", "suit": "HEARTS"},
        {"rank": "THREE", "suit": "SPADES"},
    ]


def test_acting_out_of_turn_sends_error_only_to_sender():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            alice_state, bob_state = _start_match(alice_ws, bob_ws)

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


def test_next_hand_starts_a_new_hand_preserving_stacks():
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
            actor_showdown = actor_ws.receive_json()
            other_ws.receive_json()
            assert actor_showdown["stage"] == "SHOWDOWN"

            actor_ws.send_json({"action": "next_hand"})
            actor_next = actor_ws.receive_json()
            other_next = other_ws.receive_json()

    assert actor_next["stage"] == "PREFLOP"
    assert actor_next["game_over"] is False
    assert other_next["stage"] == "PREFLOP"
    stacks = {p["player_id"]: p["stack"] for p in actor_next["players"]}
    assert sum(stacks.values()) + actor_next["pot"] == 2 * STARTING_STACK


def test_next_hand_before_showdown_is_rejected():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            _start_match(alice_ws, bob_ws)

            alice_ws.send_json({"action": "next_hand"})
            error = alice_ws.receive_json()

    assert error["type"] == "error"


def test_joining_mid_hand_is_queued_until_next_hand():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            alice_state, bob_state = _start_match(alice_ws, bob_ws)

            carol_id = client.post(f"/rooms/{code}/join", json={"name": "Carol"}).json()["player_id"]

            with client.websocket_connect(f"/ws/{code}?player_id={carol_id}") as carol_ws:
                carol_state = carol_ws.receive_json()
                bob_ws.receive_json()
                alice_ws.receive_json()

                carol_view = next(p for p in carol_state["players"] if p["player_id"] == carol_id)
                assert "stack" not in carol_view  # not dealt into the hand in progress

                actor_id = alice_state["current_actor"]
                actor_ws = alice_ws if actor_id == alice_id else bob_ws
                other_ws = bob_ws if actor_ws is alice_ws else alice_ws

                actor_ws.send_json({"action": "fold"})
                actor_ws.receive_json()
                other_ws.receive_json()
                carol_ws.receive_json()

                actor_ws.send_json({"action": "next_hand"})
                actor_next = actor_ws.receive_json()
                other_ws.receive_json()
                carol_next = carol_ws.receive_json()

    assert actor_next["stage"] == "PREFLOP"
    assert len(actor_next["players"]) == 3
    carol_own_view = next(p for p in carol_next["players"] if p["player_id"] == carol_id)
    assert carol_own_view["stack"] > 0
    assert len(carol_own_view["hole_cards"]) == 2


def test_next_hand_ends_game_when_only_one_player_has_chips():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()  # lobby broadcast to bob
            alice_ws.receive_json()  # lobby broadcast to alice

            _start_match(alice_ws, bob_ws)

            room = room_manager.get_room(code)
            game = room.game
            next(p for p in game.players if p.player_id == alice_id).stack = 0
            next(p for p in game.players if p.player_id == bob_id).stack = 2000
            game.stage = Stage.SHOWDOWN
            game.current_actor_index = None
            room.last_payouts = {alice_id: 0, bob_id: 0}

            bob_ws.send_json({"action": "next_hand"})
            bob_final = bob_ws.receive_json()
            alice_final = alice_ws.receive_json()

    assert bob_final["game_over"] is True
    assert bob_final["winner_name"] == "Bob"
    assert alice_final["game_over"] is True


def test_disconnected_player_sits_out_next_hand():
    code, (alice_id, bob_id) = _create_room_with_players(["Alice", "Bob"])
    carol_id = client.post(f"/rooms/{code}/join", json={"name": "Carol"}).json()["player_id"]

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

            actor_ws.send_json({"action": "fold"})
            actor_ws.receive_json()
            other_ws.receive_json()

            # The player who just lost the hand goes offline; Carol connects
            # to take an open seat at the table before the next hand starts.
            other_ws.close()
            disconnect_state = actor_ws.receive_json()
            other_stack = next(p["stack"] for p in disconnect_state["players"] if p["player_id"] == other_id)

            with client.websocket_connect(f"/ws/{code}?player_id={carol_id}") as carol_ws:
                carol_ws.receive_json()
                actor_ws.receive_json()

                actor_ws.send_json({"action": "next_hand"})
                actor_next = actor_ws.receive_json()
                carol_next = carol_ws.receive_json()

    assert actor_next["stage"] == "PREFLOP"
    assert carol_next["stage"] == "PREFLOP"

    players_by_id = {p["player_id"]: p for p in actor_next["players"]}
    assert "stack" not in players_by_id[other_id]  # sat out, not dealt in
    assert players_by_id[other_id]["connected"] is False
    assert "stack" in players_by_id[carol_id]

    room = room_manager.get_room(code)
    assert {p.player_id for p in room.game.players} == {actor_id, carol_id}
    assert room.sitting_out[other_id] == other_stack  # stack preserved off the table


def test_eliminated_player_not_dealt_back_in_when_another_player_disconnects():
    # Regression test: an eliminated player's websocket can stay open (they
    # never explicitly disconnect), so they remain in connection_manager's
    # connected set even after being dropped from game.players. next_hand
    # must not mistake them for a new "pending" joiner when the room later
    # dips below two connected players with chips.
    code, (alice_id, bob_id, carol_id) = _create_room_with_players(["Alice", "Bob", "Carol"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()
            alice_ws.receive_json()

            with client.websocket_connect(f"/ws/{code}?player_id={carol_id}") as carol_ws:
                carol_ws.receive_json()
                bob_ws.receive_json()
                alice_ws.receive_json()

                _start_match(alice_ws, bob_ws, carol_ws)

                room = room_manager.get_room(code)
                game = room.game
                # Force Carol to bust out of this hand.
                next(p for p in game.players if p.player_id == carol_id).stack = 0
                game.stage = Stage.SHOWDOWN
                game.current_actor_index = None
                room.last_payouts = {alice_id: 0, bob_id: 0, carol_id: 0}

                alice_ws.send_json({"action": "next_hand"})
                alice_ws.receive_json()
                bob_ws.receive_json()
                carol_after_elim = carol_ws.receive_json()

                assert room.eliminated_ids == {carol_id}
                assert {p.player_id for p in room.game.players} == {alice_id, bob_id}
                carol_view = next(p for p in carol_after_elim["players"] if p["player_id"] == carol_id)
                assert carol_view.get("eliminated") is True
                assert "stack" not in carol_view

                # Force this new Alice/Bob hand to showdown too, then Bob
                # (one of the two remaining players) disconnects -- while
                # Carol's stale, eliminated-but-still-open connection lingers.
                game = room.game
                game.stage = Stage.SHOWDOWN
                game.current_actor_index = None
                room.last_payouts = {alice_id: 0, bob_id: 0}

                bob_ws.close()
                alice_ws.receive_json()  # disconnect broadcast
                carol_ws.receive_json()

                alice_ws.send_json({"action": "next_hand"})
                alice_after = alice_ws.receive_json()
                carol_ws.receive_json()

    assert alice_after["waiting_for_players"] is True
    assert alice_after["stage"] == "SHOWDOWN"

    room = room_manager.get_room(code)
    assert room.eliminated_ids == {carol_id}
    assert {p.player_id for p in room.game.players} == {alice_id, bob_id}

    stacks = {p["player_id"]: p["stack"] for p in alice_after["players"] if "stack" in p}
    assert carol_id not in stacks  # never re-dealt in, never handed a fresh stack


def test_eliminated_player_stays_eliminated_after_reconnecting():
    code, (alice_id, bob_id, carol_id) = _create_room_with_players(["Alice", "Bob", "Carol"])

    with client.websocket_connect(f"/ws/{code}?player_id={alice_id}") as alice_ws:
        alice_ws.receive_json()  # lobby: alice alone

        with client.websocket_connect(f"/ws/{code}?player_id={bob_id}") as bob_ws:
            bob_ws.receive_json()
            alice_ws.receive_json()

            with client.websocket_connect(f"/ws/{code}?player_id={carol_id}") as carol_ws:
                carol_ws.receive_json()
                bob_ws.receive_json()
                alice_ws.receive_json()

                _start_match(alice_ws, bob_ws, carol_ws)

                room = room_manager.get_room(code)
                game = room.game
                next(p for p in game.players if p.player_id == carol_id).stack = 0
                game.stage = Stage.SHOWDOWN
                game.current_actor_index = None
                room.last_payouts = {alice_id: 0, bob_id: 0, carol_id: 0}

                alice_ws.send_json({"action": "next_hand"})
                alice_ws.receive_json()
                bob_ws.receive_json()
                carol_ws.receive_json()

            # Carol's socket fully closes here, then she reconnects.
            with client.websocket_connect(f"/ws/{code}?player_id={carol_id}") as carol_ws:
                carol_reconnect_state = carol_ws.receive_json()
                bob_ws.receive_json()
                alice_ws.receive_json()

                carol_view = next(
                    p for p in carol_reconnect_state["players"] if p["player_id"] == carol_id
                )
                assert carol_view.get("eliminated") is True
                assert "stack" not in carol_view

                game = room.game
                game.stage = Stage.SHOWDOWN
                game.current_actor_index = None
                room.last_payouts = {alice_id: 0, bob_id: 0}

                alice_ws.send_json({"action": "next_hand"})
                alice_after = alice_ws.receive_json()
                bob_ws.receive_json()
                carol_after = carol_ws.receive_json()

    assert alice_after["stage"] == "PREFLOP"
    assert {p.player_id for p in room_manager.get_room(code).game.players} == {alice_id, bob_id}
    assert room_manager.get_room(code).eliminated_ids == {carol_id}
    carol_final_view = next(p for p in carol_after["players"] if p["player_id"] == carol_id)
    assert carol_final_view.get("eliminated") is True
    assert "stack" not in carol_final_view


def test_next_hand_waits_when_fewer_than_two_connected_remain():
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
            actor_ws.receive_json()
            other_ws.receive_json()

            other_ws.close()
            actor_ws.receive_json()  # disconnect broadcast

            actor_ws.send_json({"action": "next_hand"})
            actor_next = actor_ws.receive_json()

    assert actor_next["stage"] == "SHOWDOWN"
    assert actor_next["waiting_for_players"] is True
    assert actor_next["game_over"] is False

    room = room_manager.get_room(code)
    assert room.game.stage == Stage.SHOWDOWN
    assert room.waiting_for_players is True
