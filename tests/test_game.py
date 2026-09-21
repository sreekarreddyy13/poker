import pytest

from poker.game import ActionType, Game, IllegalActionError, Stage


def find(game: Game, player_id: str):
    for p in game.players:
        if p.player_id == player_id:
            return p
    raise KeyError(player_id)


# ---------------------------------------------------------------------------
# Construction

def test_rejects_too_few_players():
    with pytest.raises(ValueError):
        Game(["A"], starting_stack=100, small_blind=5, big_blind=10)


def test_rejects_too_many_players():
    with pytest.raises(ValueError):
        Game([f"P{i}" for i in range(10)], starting_stack=100, small_blind=5, big_blind=10)


def test_rejects_duplicate_player_ids():
    with pytest.raises(ValueError):
        Game(["A", "A"], starting_stack=100, small_blind=5, big_blind=10)


def test_rejects_small_blind_not_less_than_big_blind():
    with pytest.raises(ValueError):
        Game(["A", "B"], starting_stack=100, small_blind=10, big_blind=10)


# ---------------------------------------------------------------------------
# start_hand

def test_start_hand_deals_and_posts_blinds():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()

    assert game.stage == Stage.PREFLOP
    assert game.community_cards == []
    for p in game.players:
        assert len(p.hole_cards) == 2
    assert game.pot == 15
    assert game.current_bet == 10
    assert find(game, "B").current_bet == 5  # sb
    assert find(game, "C").current_bet == 10  # bb


def test_dealer_button_rotates():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    assert game.button_index == 0
    game.start_hand()
    assert game.button_index == 1
    game.start_hand()
    assert game.button_index == 2
    game.start_hand()
    assert game.button_index == 0


def test_first_to_act_preflop_and_postflop_three_or_more_players():
    game = Game(["A", "B", "C", "D"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    # button=A(0), sb=B(1), bb=C(2), utg=D(3)
    assert game.current_actor == "D"

    game.apply_action("D", ActionType.CALL)
    game.apply_action("A", ActionType.CALL)
    game.apply_action("B", ActionType.CALL)
    game.apply_action("C", ActionType.CHECK)  # bb option, closes preflop

    assert game.stage == Stage.FLOP
    assert game.current_actor == "B"  # first active player left of the button


def test_first_to_act_heads_up():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    # heads-up: button==sb acts first preflop
    assert game.current_actor == "A"

    game.apply_action("A", ActionType.CALL)
    game.apply_action("B", ActionType.CHECK)

    assert game.stage == Stage.FLOP
    assert game.current_actor == "B"  # bb acts first postflop


# ---------------------------------------------------------------------------
# Actions: FOLD

def test_fold_down_to_one_player_ends_hand():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    # button=A(0)=utg preflop(3-handed), sb=B(1), bb=C(2)
    assert game.current_actor == "A"
    game.apply_action("A", ActionType.FOLD)
    assert game.current_actor == "B"
    game.apply_action("B", ActionType.FOLD)

    assert game.stage == Stage.SHOWDOWN
    assert game.current_actor is None
    remaining = [p for p in game.players if not p.folded]
    assert [p.player_id for p in remaining] == ["C"]


# ---------------------------------------------------------------------------
# Actions: CHECK

def test_check_illegal_when_facing_a_bet():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    with pytest.raises(IllegalActionError):
        game.apply_action("A", ActionType.CHECK)


def test_check_legal_with_nothing_to_call():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.CALL)
    game.apply_action("B", ActionType.CHECK)  # bb option
    assert game.stage == Stage.FLOP


# ---------------------------------------------------------------------------
# Actions: CALL

def test_call_matches_current_bet_and_moves_chips():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.CALL)
    a = find(game, "A")
    assert a.current_bet == 10
    assert a.stack == 990
    assert game.pot == 25


def test_call_illegal_with_nothing_to_call():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.CALL)
    game.apply_action("B", ActionType.CALL)
    with pytest.raises(IllegalActionError):
        game.apply_action("C", ActionType.CALL)  # bb already matches; must check


def test_call_leaving_chips_does_not_mark_all_in():
    game = Game(["A", "B", "C"], starting_stack=12, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.CALL)  # A has 12, calls 10, 2 left
    b = find(game, "B")
    assert b.stack == 7  # posted 5 of 12
    game.apply_action("B", ActionType.CALL)  # calls remaining 5 -> 2 left
    assert b.stack == 2
    assert not b.all_in


def test_call_that_exhausts_stack_marks_all_in():
    game = Game(["A", "B", "C"], starting_stack=10, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.CALL)  # A has 10, calls 10, 0 left
    a = find(game, "A")
    assert a.stack == 0
    assert a.all_in


# ---------------------------------------------------------------------------
# Actions: RAISE

def test_raise_below_min_raise_is_illegal():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    with pytest.raises(IllegalActionError):
        game.apply_action("A", ActionType.RAISE, amount=15)  # increase of 5 < min_raise 10


def test_raise_exceeding_stack_is_illegal():
    game = Game(["A", "B", "C"], starting_stack=15, small_blind=5, big_blind=10)
    game.start_hand()
    with pytest.raises(IllegalActionError):
        game.apply_action("A", ActionType.RAISE, amount=1000)


def test_raise_updates_bet_and_reopens_action_for_players_who_already_acted():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.CALL)
    game.apply_action("B", ActionType.CALL)
    assert find(game, "A").has_acted
    assert find(game, "B").has_acted

    game.apply_action("C", ActionType.RAISE, amount=30)

    assert game.current_bet == 30
    assert game.min_raise == 20
    assert not find(game, "A").has_acted
    assert not find(game, "B").has_acted
    assert game.current_actor == "A"


# ---------------------------------------------------------------------------
# Actions: ALL_IN

def test_all_in_pushes_entire_stack():
    game = Game(["A", "B"], starting_stack=20, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.ALL_IN)
    a = find(game, "A")
    assert a.stack == 0
    assert a.all_in
    assert a.current_bet == 20


def test_all_in_full_raise_reopens_action():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.players[2].stack = 25  # C (bb) has a short stack
    game.start_hand()
    game.apply_action("A", ActionType.CALL)
    game.apply_action("B", ActionType.CALL)
    assert find(game, "A").has_acted
    assert find(game, "B").has_acted

    game.apply_action("C", ActionType.ALL_IN)  # posted bb(10) + 15 more = 25, increase 15 >= min_raise 10

    assert not find(game, "A").has_acted
    assert not find(game, "B").has_acted


def test_all_in_short_raise_does_not_reopen_action():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.players[2].stack = 15  # C (bb) has a very short stack
    game.start_hand()
    game.apply_action("A", ActionType.CALL)
    game.apply_action("B", ActionType.CALL)
    assert find(game, "A").has_acted
    assert find(game, "B").has_acted

    game.apply_action("C", ActionType.ALL_IN)  # posted bb(10) + 5 more = 15, increase 5 < min_raise 10

    assert find(game, "A").has_acted
    assert find(game, "B").has_acted


def test_all_in_preflop_both_players_auto_runs_board_to_showdown():
    game = Game(["A", "B"], starting_stack=20, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.ALL_IN)
    game.apply_action("B", ActionType.ALL_IN)

    assert game.stage == Stage.SHOWDOWN
    assert len(game.community_cards) == 5


# ---------------------------------------------------------------------------
# Turn validation

def test_acting_out_of_turn_is_illegal():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    with pytest.raises(IllegalActionError):
        game.apply_action("B", ActionType.FOLD)


# ---------------------------------------------------------------------------
# Full stage progression

def test_full_stage_progression_with_checks():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()

    assert game.stage == Stage.PREFLOP
    assert len(game.community_cards) == 0

    game.apply_action("A", ActionType.CALL)
    game.apply_action("B", ActionType.CHECK)
    assert game.stage == Stage.FLOP
    assert len(game.community_cards) == 3

    game.apply_action("B", ActionType.CHECK)
    game.apply_action("A", ActionType.CHECK)
    assert game.stage == Stage.TURN
    assert len(game.community_cards) == 4

    game.apply_action("B", ActionType.CHECK)
    game.apply_action("A", ActionType.CHECK)
    assert game.stage == Stage.RIVER
    assert len(game.community_cards) == 5

    game.apply_action("B", ActionType.CHECK)
    game.apply_action("A", ActionType.CHECK)
    assert game.stage == Stage.SHOWDOWN
    assert len(game.community_cards) == 5


# ---------------------------------------------------------------------------
# Player count smoke test

@pytest.mark.parametrize("n_players", [2, 3, 6, 9])
def test_hand_runs_to_completion_for_various_table_sizes(n_players):
    ids = [f"P{i}" for i in range(n_players)]
    game = Game(ids, starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()

    assert game.stage == Stage.PREFLOP
    for p in game.players:
        assert len(p.hole_cards) == 2

    while game.stage != Stage.SHOWDOWN:
        game.apply_action(game.current_actor, ActionType.FOLD)

    remaining = [p for p in game.players if not p.folded]
    assert len(remaining) == 1
