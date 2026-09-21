from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from server.rooms import RoomFullError, RoomManager, RoomNotFoundError

app = FastAPI(title="Poker App")
room_manager = RoomManager()


class CreateRoomResponse(BaseModel):
    code: str


class JoinRoomRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32)


class JoinRoomResponse(BaseModel):
    player_id: str
    name: str
    code: str


class PlayerPublic(BaseModel):
    player_id: str
    name: str


class RoomStateResponse(BaseModel):
    code: str
    players: list[PlayerPublic]


@app.post("/rooms", response_model=CreateRoomResponse)
def create_room() -> CreateRoomResponse:
    room = room_manager.create_room()
    return CreateRoomResponse(code=room.code)


@app.post("/rooms/{code}/join", response_model=JoinRoomResponse)
def join_room(code: str, body: JoinRoomRequest) -> JoinRoomResponse:
    try:
        player = room_manager.join_room(code, body.name)
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RoomFullError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JoinRoomResponse(player_id=player.player_id, name=player.name, code=code)


@app.get("/rooms/{code}", response_model=RoomStateResponse)
def get_room(code: str) -> RoomStateResponse:
    try:
        room = room_manager.get_room(code)
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RoomStateResponse(
        code=room.code,
        players=[PlayerPublic(player_id=p.player_id, name=p.name) for p in room.players],
    )
