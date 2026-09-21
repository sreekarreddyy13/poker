"""Randomized simulation: play many full hands with random legal actions
and check that chips are conserved, stacks/pots never go negative, and
every hand terminates."""
from __future__ import annotations

import random
import time
from typing import Optional

from poker.game import ActionType, Game, Player, Stage

NUM_HANDS = 10_000
MAX_ACTIONS_PER_HAND = 5_000  # safety net in case of an engine infinite loop


def _find_player(game: Game, player_id: str) -> Player:
    for p in game.players:
        if p.player_id == player_id:
            return p
    raise KeyError(player_id)


def _legal_actions(game: Game, player: Player) -> list[tuple[ActionType, Optional[tuple[int, int]]]]:
    to_call = game.current_bet - player.current_bet
    actions: list[tuple[ActionType, Optional[tuple[int, int]]]] = [(ActionType.FOLD, None)]

    if to_call == 0:
        actions.append((ActionType.CHECK, None))
    elif to_call <= player.stack:
        actions.append((ActionType.CALL, None))

    min_raise_amount = game.current_bet + game.min_raise
    min_raise_cost = min_raise_amount - player.current_bet
    if min_raise_cost <= player.stack:
        max_raise_amount = player.current_bet + player.stack
        actions.append((ActionType.RAISE, (min_raise_amount, max_raise_amount)))

    actions.append((ActionType.ALL_IN, None))  # current actor always has stack > 0
    return actions


def _apply_random_action(game: Game, rng: random.Random) -> None:
    player = _find_player(game, game.current_actor)
    action, extra = rng.choice(_legal_actions(game, player))

    if action == ActionType.RAISE:
        low, high = extra
        game.apply_action(player.player_id, ActionType.RAISE, amount=rng.randint(low, high))
    else:
        game.apply_action(player.player_id, action)


def _assert_no_negative_chips(game: Game) -> None:
    assert game.pot >= 0
    for p in game.players:
        assert p.stack >= 0


def _play_one_hand(rng: random.Random) -> None:
    n_players = rng.randint(2, 9)
    starting_stack = rng.randint(20, 2000)
    big_blind = rng.randint(2, 50)
    small_blind = max(1, big_blind // 2)
    if small_blind >= big_blind:
        big_blind = small_blind + 1

    game = Game(
        [f"P{i}" for i in range(n_players)],
        starting_stack=starting_stack,
        small_blind=small_blind,
        big_blind=big_blind,
    )
    game.start_hand()
    total_chips = sum(p.stack for p in game.players) + game.pot
    _assert_no_negative_chips(game)

    actions_taken = 0
    while game.stage != Stage.SHOWDOWN:
        _apply_random_action(game, rng)
        _assert_no_negative_chips(game)
        assert sum(p.stack for p in game.players) + game.pot == total_chips

        actions_taken += 1
        assert actions_taken <= MAX_ACTIONS_PER_HAND, "hand failed to terminate"

    game.settle_showdown()
    _assert_no_negative_chips(game)
    assert sum(p.stack for p in game.players) == total_chips


def test_simulate_10000_random_hands_conserve_chips_and_terminate():
    rng = random.Random(1234567)  # fixed seed: reproducible failures

    start = time.perf_counter()
    for _ in range(NUM_HANDS):
        _play_one_hand(rng)
    elapsed = time.perf_counter() - start

    print(f"\nSimulated {NUM_HANDS} hands in {elapsed:.2f}s ({NUM_HANDS / elapsed:.0f} hands/sec)")
