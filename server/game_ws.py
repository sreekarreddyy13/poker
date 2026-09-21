from __future__ import annotations

from typing import Callable, Optional

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from poker.cards import Card
from poker.game import ActionType, Game, IllegalActionError, Stage
from server.rooms import (
    BIG_BLIND,
    STARTING_STACK,
    SMALL_BLIND,
    Room,
    RoomManager,
    RoomNotFoundError,
)

ACTION_MAP: dict[str, ActionType] = {
    "fold": ActionType.FOLD,
    "check": ActionType.CHECK,
    "call": ActionType.CALL,
    "raise": ActionType.RAISE,
}


class ActionRequest(BaseModel):
    action: str
    amount: Optional[int] = None


class ConnectionManager:
    """Tracks the live websocket per (room code, player_id), one room lock's
    worth of connections at a time so state can be broadcast per-player."""

    def __init__(self) -> None:
        self._connections: dict[str, dict[str, WebSocket]] = {}

    def connected_ids(self, code: str) -> set[str]:
        return set(self._connections.get(code, {}))

    async def connect(self, code: str, player_id: str, websocket: WebSocket) -> None:
        conns = self._connections.setdefault(code, {})
        previous = conns.get(player_id)
        conns[player_id] = websocket
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=4000, reason="replaced by a new connection")
            except Exception:
                pass

    def disconnect(self, code: str, player_id: str, websocket: WebSocket) -> None:
        conns = self._connections.get(code)
        if conns is not None and conns.get(player_id) is websocket:
            del conns[player_id]
            if not conns:
                self._connections.pop(code, None)

    async def broadcast(self, code: str, message_for: Callable[[str], dict]) -> None:
        for player_id, websocket in list(self._connections.get(code, {}).items()):
            try:
                await websocket.send_json(message_for(player_id))
            except Exception:
                pass


connection_manager = ConnectionManager()


def _card_json(card: Card) -> dict[str, str]:
    return {"rank": card.rank.name, "suit": card.suit.name}


def _player_view(room: Room, player_id: str, viewer_id: str, connected: set[str]) -> dict:
    room_player = next(p for p in room.players if p.player_id == player_id)
    view: dict = {
        "player_id": player_id,
        "name": room_player.name,
        "connected": player_id in connected,
    }
    game = room.game
    if game is not None:
        game_player = next((p for p in game.players if p.player_id == player_id), None)
        if game_player is not None:
            view["stack"] = game_player.stack
            view["current_bet"] = game_player.current_bet
            view["folded"] = game_player.folded
            view["all_in"] = game_player.all_in
            if player_id == viewer_id:
                view["hole_cards"] = [_card_json(c) for c in game_player.hole_cards]
        elif player_id in room.eliminated_ids:
            view["eliminated"] = True
    return view


def build_state(room: Room, viewer_id: str, connected: set[str]) -> dict:
    game = room.game
    if game is None or game.stage is None:
        return {
            "type": "state",
            "code": room.code,
            "waiting": True,
            "players": [_player_view(room, p.player_id, viewer_id, connected) for p in room.players],
        }
    state = {
        "type": "state",
        "code": room.code,
        "waiting": False,
        "stage": game.stage.name,
        "community_cards": [_card_json(c) for c in game.community_cards],
        "pot": game.pot,
        "current_bet": game.current_bet,
        "min_raise": game.min_raise,
        "current_actor": game.current_actor,
        "players": [_player_view(room, p.player_id, viewer_id, connected) for p in room.players],
    }
    if game.stage == Stage.SHOWDOWN and room.last_payouts is not None:
        state["payouts"] = room.last_payouts
    state["game_over"] = room.game_over
    if room.game_over:
        winner = next((p for p in room.players if p.player_id == room.winner_id), None)
        state["winner_name"] = winner.name if winner is not None else None
    return state


def _maybe_start_hand(room: Room) -> None:
    if room.game is not None:
        return
    eligible_ids = [p.player_id for p in room.players if p.player_id in connection_manager.connected_ids(room.code)]
    if len(eligible_ids) < 2:
        return
    room.game = Game(eligible_ids, STARTING_STACK, SMALL_BLIND, BIG_BLIND)
    room.game.start_hand()


def _maybe_settle(room: Room) -> None:
    game = room.game
    if game is None or game.stage != Stage.SHOWDOWN or room.last_payouts is not None:
        return
    room.last_payouts = game.settle_showdown()


def _apply_next_hand(room: Room, player_id: str) -> Optional[str]:
    game = room.game
    if game is None or game.stage != Stage.SHOWDOWN:
        return "no hand is ready to start"
    if room.last_payouts is None:
        return "the current hand has not been settled yet"
    if room.game_over:
        return "the game has already ended"
    if not any(p.player_id == player_id for p in game.players):
        return "you are not part of this game"

    survivors = [p.player_id for p in game.players if p.stack > 0]
    if len(survivors) < 2:
        room.game_over = True
        room.winner_id = survivors[0] if survivors else None
        return None

    removed = game.start_next_hand()
    room.eliminated_ids.update(removed)
    room.last_payouts = None
    return None


def _apply_message(room: Room, player_id: str, raw: dict) -> Optional[str]:
    """Validate and apply an incoming action. Returns an error string, or
    None on success."""
    try:
        request = ActionRequest.model_validate(raw)
    except ValidationError as exc:
        return str(exc)

    if request.action.lower() == "next_hand":
        return _apply_next_hand(room, player_id)

    action_type = ACTION_MAP.get(request.action.lower())
    if action_type is None:
        return f"unknown action {request.action!r}"

    if room.game is None:
        return "no hand in progress"

    try:
        room.game.apply_action(player_id, action_type, request.amount)
    except IllegalActionError as exc:
        return str(exc)
    return None


async def _broadcast_state(room: Room) -> None:
    connected = connection_manager.connected_ids(room.code)
    await connection_manager.broadcast(room.code, lambda viewer_id: build_state(room, viewer_id, connected))


async def handle_connection(websocket: WebSocket, code: str, room_manager: RoomManager) -> None:
    player_id = websocket.query_params.get("player_id")
    if not player_id:
        await websocket.close(code=4400, reason="player_id query parameter is required")
        return

    try:
        room = room_manager.get_room(code)
    except RoomNotFoundError:
        await websocket.close(code=4404, reason="room not found")
        return

    if not any(p.player_id == player_id for p in room.players):
        await websocket.close(code=4403, reason="player is not in this room")
        return

    await websocket.accept()
    await connection_manager.connect(code, player_id, websocket)

    try:
        async with room.lock:
            _maybe_start_hand(room)
        await _broadcast_state(room)

        while True:
            try:
                raw = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except ValueError:
                await websocket.send_json({"type": "error", "message": "invalid JSON"})
                continue

            if not isinstance(raw, dict):
                await websocket.send_json({"type": "error", "message": "expected a JSON object"})
                continue

            async with room.lock:
                error = _apply_message(room, player_id, raw)
                if error is None:
                    _maybe_settle(room)

            if error is not None:
                await websocket.send_json({"type": "error", "message": error})
            else:
                await _broadcast_state(room)
    finally:
        connection_manager.disconnect(code, player_id, websocket)
        await _broadcast_state(room)
