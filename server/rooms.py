from __future__ import annotations

import secrets
import string
import threading
from dataclasses import dataclass, field

CODE_ALPHABET = string.ascii_uppercase + string.digits
CODE_LENGTH = 6
MAX_PLAYERS = 9


class RoomError(ValueError):
    pass


class RoomNotFoundError(RoomError):
    pass


class RoomFullError(RoomError):
    pass


@dataclass
class RoomPlayer:
    player_id: str
    name: str


@dataclass
class Room:
    code: str
    players: list[RoomPlayer] = field(default_factory=list)


class RoomManager:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._lock = threading.Lock()

    def create_room(self) -> Room:
        with self._lock:
            code = self._generate_unique_code()
            room = Room(code=code)
            self._rooms[code] = room
            return room

    def get_room(self, code: str) -> Room:
        with self._lock:
            room = self._rooms.get(code)
            if room is None:
                raise RoomNotFoundError(f"no room with code {code!r}")
            return room

    def join_room(self, code: str, name: str) -> RoomPlayer:
        with self._lock:
            room = self._rooms.get(code)
            if room is None:
                raise RoomNotFoundError(f"no room with code {code!r}")
            if len(room.players) >= MAX_PLAYERS:
                raise RoomFullError(f"room {code!r} is full")
            player = RoomPlayer(player_id=secrets.token_hex(8), name=name)
            room.players.append(player)
            return player

    def _generate_unique_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self._rooms:
                return code
