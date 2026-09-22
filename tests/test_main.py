from fastapi.testclient import TestClient

from server.main import app, room_manager

client = TestClient(app)


def setup_function() -> None:
    room_manager._rooms.clear()


def create_room() -> str:
    response = client.post("/rooms")
    assert response.status_code == 200
    return response.json()["code"]


def test_create_room_returns_join_code():
    response = client.post("/rooms")
    assert response.status_code == 200
    body = response.json()
    assert len(body["code"]) == 6
    assert body["code"].isalnum()


def test_create_room_codes_are_unique():
    codes = {client.post("/rooms").json()["code"] for _ in range(20)}
    assert len(codes) == 20


def test_join_room_returns_player_id():
    code = create_room()
    response = client.post(f"/rooms/{code}/join", json={"name": "Alice"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Alice"
    assert body["code"] == code
    assert body["player_id"]


def test_join_room_unknown_code_returns_404():
    response = client.post("/rooms/NOPE99/join", json={"name": "Alice"})
    assert response.status_code == 404


def test_join_room_rejects_empty_name():
    code = create_room()
    response = client.post(f"/rooms/{code}/join", json={"name": ""})
    assert response.status_code == 422


def test_join_room_rejects_whitespace_only_name():
    code = create_room()
    response = client.post(f"/rooms/{code}/join", json={"name": "   "})
    assert response.status_code == 422


def test_join_room_same_player_id_reconnects_instead_of_duplicating():
    code = create_room()
    first = client.post(f"/rooms/{code}/join", json={"name": "Alice"}).json()

    second = client.post(
        f"/rooms/{code}/join", json={"name": "Alice", "player_id": first["player_id"]}
    ).json()
    assert second["player_id"] == first["player_id"]

    players = client.get(f"/rooms/{code}").json()["players"]
    assert len(players) == 1


def test_join_room_rejects_duplicate_name_from_connected_player():
    code = create_room()
    alice = client.post(f"/rooms/{code}/join", json={"name": "Alice"}).json()

    with client.websocket_connect(f"/ws/{code}?player_id={alice['player_id']}") as ws:
        ws.receive_json()  # waiting
        response = client.post(f"/rooms/{code}/join", json={"name": "alice"})

    assert response.status_code == 409


def test_join_room_full_returns_409():
    code = create_room()
    for i in range(6):
        response = client.post(f"/rooms/{code}/join", json={"name": f"P{i}"})
        assert response.status_code == 200
    response = client.post(f"/rooms/{code}/join", json={"name": "Overflow"})
    assert response.status_code == 409


def test_get_room_returns_players():
    code = create_room()
    client.post(f"/rooms/{code}/join", json={"name": "Alice"})
    client.post(f"/rooms/{code}/join", json={"name": "Bob"})

    response = client.get(f"/rooms/{code}")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == code
    names = {p["name"] for p in body["players"]}
    assert names == {"Alice", "Bob"}


def test_get_room_unknown_code_returns_404():
    response = client.get("/rooms/NOPE99")
    assert response.status_code == 404
