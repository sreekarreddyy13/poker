from __future__ import annotations

import asyncio
import secrets
import string
import threading
from dataclasses import dataclass, field
from typing import Collection, Optional

from poker.game import Game

CODE_ALPHABET = string.ascii_uppercase + string.digits
CODE_LENGTH = 6
MAX_PLAYERS = 9

STARTING_STACK = 1000
SMALL_BLIND = 5
BIG_BLIND = 10

TURN_TIMEOUT_SECONDS = 30
DISCONNECT_GRACE_SECONDS = 10


class RoomError(ValueError):
    pass


class RoomNotFoundError(RoomError):
    pass


class RoomFullError(RoomError):
    pass


class NameTakenError(RoomError):
    pass


class InvalidNameError(RoomError):
    pass


@dataclass
class RoomPlayer:
    player_id: str
    name: str


@dataclass
class Room:
    code: str
    players: list[RoomPlayer] = field(default_factory=list)
    game: Optional[Game] = None
    last_payouts: Optional[dict[str, int]] = None
    game_over: bool = False
    winner_id: Optional[str] = None
    eliminated_ids: set[str] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    turn_deadline: Optional[float] = None
    turn_timer_task: Optional[asyncio.Task] = None


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

    def join_room(
        self,
        code: str,
        name: str,
        player_id: Optional[str] = None,
        connected_ids: Collection[str] = (),
    ) -> RoomPlayer:
        name = name.strip()
        if not name:
            raise InvalidNameError("name must not be blank")
        with self._lock:
            room = self._rooms.get(code)
            if room is None:
                raise RoomNotFoundError(f"no room with code {code!r}")

            if player_id is not None:
                existing = next((p for p in room.players if p.player_id == player_id), None)
                if existing is not None:
                    return existing  # same seat, reconnecting

            if any(
                p.name.lower() == name.lower() and p.player_id in connected_ids
                for p in room.players
            ):
                raise NameTakenError(f"name {name!r} is already taken in this room")

            if len(room.players) >= MAX_PLAYERS:
                raise RoomFullError(f"room {code!r} is full")

            # A client-supplied player_id only ever resolves an existing seat
            # (above); new seats always get a fresh server-issued id.
            player = RoomPlayer(player_id=secrets.token_hex(8), name=name)
            room.players.append(player)
            return player

    def _generate_unique_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self._rooms:
                return code
