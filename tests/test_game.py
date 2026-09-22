import pytest

from poker.cards import Card, Rank, Suit
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


def test_call_with_fewer_chips_than_owed_is_a_legal_short_all_in():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()  # A=button/sb (posted 5), B=bb (posted 10)

    game.apply_action("A", ActionType.RAISE, amount=100)  # A owes B a call of 90

    b = find(game, "B")
    b.stack = 40  # far less than the 90 owed
    game.apply_action("B", ActionType.CALL)  # must not raise IllegalActionError

    assert b.stack == 0
    assert b.all_in
    assert b.total_contributed == 50  # 10 already in + 40 remaining stack
    # only A can still act, so the board auto-runs straight to showdown
    assert game.stage == Stage.SHOWDOWN


def test_short_stacked_call_creates_a_side_pot():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()  # A=button, B=sb(5), C=bb(10); A acts first

    game.apply_action("A", ActionType.RAISE, amount=200)

    b = find(game, "B")
    b.stack = 45  # short of the 195 owed
    game.apply_action("B", ActionType.CALL)
    assert b.stack == 0
    assert b.all_in
    assert b.total_contributed == 50  # 5 posted + 45 remaining stack

    game.apply_action("C", ActionType.CALL)  # C has plenty and calls the full 200

    pots = game.compute_side_pots()
    assert [p.amount for p in pots] == [150, 300]
    assert set(pots[0].eligible_player_ids) == {"A", "B", "C"}
    assert set(pots[1].eligible_player_ids) == {"A", "C"}  # B can't contest chips beyond their all-in


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


# ---------------------------------------------------------------------------
# Side pots / showdown payout

BOARD = [
    Card(Rank.TWO, Suit.CLUBS),
    Card(Rank.FIVE, Suit.DIAMONDS),
    Card(Rank.NINE, Suit.HEARTS),
    Card(Rank.JACK, Suit.CLUBS),
    Card(Rank.KING, Suit.DIAMONDS),
]


def test_fold_out_winner_takes_entire_pot_without_showdown_cards():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    # button=A(0)=utg, sb=B(1) posts 5, bb=C(2) posts 10
    game.apply_action("A", ActionType.FOLD)
    game.apply_action("B", ActionType.FOLD)
    assert game.stage == Stage.SHOWDOWN
    assert game.community_cards == []

    payouts = game.settle_showdown()

    assert payouts == {"A": 0, "B": 0, "C": 15}
    assert find(game, "C").stack == 1005  # 1000 - 10 (bb) + 15 (pot)


def test_showdown_hands_empty_when_pot_won_uncontested_by_fold():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.FOLD)
    game.apply_action("B", ActionType.FOLD)
    assert game.stage == Stage.SHOWDOWN

    assert game.showdown_hands() == {}


def test_showdown_hands_empty_before_showdown():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    assert game.showdown_hands() == {}


def test_showdown_hands_reports_category_for_each_active_player():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.CALL)
    game.apply_action("B", ActionType.CHECK)
    game.apply_action("B", ActionType.CHECK)
    game.apply_action("A", ActionType.CHECK)
    game.apply_action("B", ActionType.CHECK)
    game.apply_action("A", ActionType.CHECK)
    game.apply_action("B", ActionType.CHECK)
    game.apply_action("A", ActionType.CHECK)
    assert game.stage == Stage.SHOWDOWN

    game.community_cards = BOARD  # TWOc, FIVEd, NINEh, JACKc, KINGd
    find(game, "A").hole_cards = [Card(Rank.KING, Suit.HEARTS), Card(Rank.SIX, Suit.HEARTS)]
    find(game, "B").hole_cards = [Card(Rank.JACK, Suit.HEARTS), Card(Rank.THREE, Suit.SPADES)]

    assert game.showdown_hands() == {
        "A": "Pair of Kings",
        "B": "Pair of Jacks",
    }


def test_settle_showdown_before_showdown_stage_is_illegal():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    with pytest.raises(IllegalActionError):
        game.settle_showdown()


def test_settle_showdown_twice_is_illegal():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.FOLD)
    game.apply_action("B", ActionType.FOLD)

    game.settle_showdown()
    with pytest.raises(IllegalActionError):
        game.settle_showdown()


def test_single_pot_split_evenly_on_exact_tie():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.CALL)
    game.apply_action("B", ActionType.CHECK)
    game.apply_action("B", ActionType.CHECK)
    game.apply_action("A", ActionType.CHECK)
    game.apply_action("B", ActionType.CHECK)
    game.apply_action("A", ActionType.CHECK)
    game.apply_action("B", ActionType.CHECK)
    game.apply_action("A", ActionType.CHECK)
    assert game.stage == Stage.SHOWDOWN

    game.community_cards = BOARD
    find(game, "A").hole_cards = [Card(Rank.THREE, Suit.CLUBS), Card(Rank.FOUR, Suit.HEARTS)]
    find(game, "B").hole_cards = [Card(Rank.THREE, Suit.SPADES), Card(Rank.FOUR, Suit.SPADES)]

    payouts = game.settle_showdown()

    assert payouts == {"A": 10, "B": 10}  # pot of 20 splits evenly, no remainder


def test_split_pot_tie_with_odd_chip_to_first_winner_left_of_button():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()  # button=A(0); first seat left of button is B(1)

    find(game, "A").total_contributed = 101
    find(game, "B").total_contributed = 101
    find(game, "C").total_contributed = 101
    find(game, "C").folded = True
    game.pot = 303
    game.stage = Stage.SHOWDOWN
    game.community_cards = BOARD
    find(game, "A").hole_cards = [Card(Rank.THREE, Suit.CLUBS), Card(Rank.FOUR, Suit.DIAMONDS)]
    find(game, "B").hole_cards = [Card(Rank.THREE, Suit.HEARTS), Card(Rank.FOUR, Suit.CLUBS)]

    pots = game.compute_side_pots()
    assert len(pots) == 1
    assert pots[0].amount == 303
    assert set(pots[0].eligible_player_ids) == {"A", "B"}  # C folded, excluded despite contributing

    payouts = game.settle_showdown()

    assert payouts == {"A": 151, "B": 152, "C": 0}  # A,B tie 151 each + 1 odd chip to B (left of button)
    assert find(game, "B").stack == 995 + 152  # B posted the 5 sb before this hand-state was rigged
    assert find(game, "A").stack == 1000 + 151  # A (button) posted no blind


def test_uncalled_all_in_excess_forms_its_own_pot():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()  # A=button/sb (posted 5), B=bb (posted 10)

    find(game, "A").stack = 30
    game.apply_action("A", ActionType.ALL_IN)  # total_contributed A = 5 + 30 = 35

    find(game, "B").stack = 500
    game.apply_action("B", ActionType.ALL_IN)  # total_contributed B = 10 + 500 = 510

    assert game.stage == Stage.SHOWDOWN

    pots = game.compute_side_pots()
    assert [p.amount for p in pots] == [70, 475]
    assert set(pots[0].eligible_player_ids) == {"A", "B"}
    assert pots[1].eligible_player_ids == ("B",)  # A's smaller all-in can't contest the excess

    game.community_cards = BOARD
    find(game, "A").hole_cards = [Card(Rank.THREE, Suit.CLUBS), Card(Rank.FOUR, Suit.DIAMONDS)]
    find(game, "B").hole_cards = [Card(Rank.KING, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)]

    payouts = game.settle_showdown()

    assert payouts == {"A": 0, "B": 545}
    assert find(game, "B").stack == 545


# ---------------------------------------------------------------------------
# start_next_hand

def test_start_next_hand_rotates_button_and_preserves_stacks():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    assert game.button_index == 0
    game.apply_action("A", ActionType.FOLD)
    game.apply_action("B", ActionType.FOLD)
    game.settle_showdown()
    assert find(game, "C").stack == 1005
    total_chips = sum(p.stack for p in game.players)

    removed = game.start_next_hand()

    assert removed == []
    assert game.button_index == 1
    assert game.stage == Stage.PREFLOP
    assert sum(p.stack for p in game.players) + game.pot == total_chips


def test_start_next_hand_button_skips_busted_seat():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.FOLD)
    game.apply_action("B", ActionType.FOLD)
    game.settle_showdown()

    find(game, "A").stack = 0  # A had the button and is now eliminated

    game.start_next_hand()

    assert game.players[game.button_index].player_id == "B"


def test_start_next_hand_removes_busted_players():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.FOLD)
    game.apply_action("B", ActionType.FOLD)
    game.settle_showdown()

    find(game, "A").stack = 0

    removed = game.start_next_hand()

    assert removed == ["A"]
    assert {p.player_id for p in game.players} == {"B", "C"}


def test_start_next_hand_before_showdown_is_illegal():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    with pytest.raises(IllegalActionError):
        game.start_next_hand()


def test_start_next_hand_ends_when_fewer_than_two_have_chips():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.FOLD)
    game.settle_showdown()

    find(game, "A").stack = 0

    with pytest.raises(IllegalActionError):
        game.start_next_hand()


# ---------------------------------------------------------------------------
# remove_players

def test_remove_players_drops_seat_and_keeps_stack_off_the_table():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.FOLD)
    game.apply_action("B", ActionType.FOLD)
    game.settle_showdown()

    removed = game.remove_players({"B"})

    assert removed == ["B"]
    assert {p.player_id for p in game.players} == {"A", "C"}


def test_remove_players_rejects_mid_hand():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    with pytest.raises(IllegalActionError):
        game.remove_players({"A"})


def test_remove_players_rejects_unknown_id():
    game = Game(["A", "B"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    game.apply_action("A", ActionType.FOLD)
    game.settle_showdown()
    with pytest.raises(IllegalActionError):
        game.remove_players({"nope"})


# ---------------------------------------------------------------------------
# Side pots / showdown payout (continued)


def test_three_way_all_in_with_different_stacks_forms_two_side_pots():
    game = Game(["A", "B", "C"], starting_stack=1000, small_blind=5, big_blind=10)
    game.start_hand()
    # button=A(0)=utg, sb=B(1) posts 5, bb=C(2) posts 10
    assert game.current_actor == "A"

    find(game, "A").stack = 30
    game.apply_action("A", ActionType.ALL_IN)  # total_contributed A = 0 + 30 = 30

    find(game, "B").stack = 65
    game.apply_action("B", ActionType.ALL_IN)  # total_contributed B = 5 + 65 = 70

    find(game, "C").stack = 200
    game.apply_action("C", ActionType.CALL)  # total_contributed C = 10 + 60 = 70

    assert game.stage == Stage.SHOWDOWN
    assert len(game.community_cards) == 5  # board auto-dealt out, everyone is all-in or capped

    pots = game.compute_side_pots()
    assert [p.amount for p in pots] == [90, 80]
    assert set(pots[0].eligible_player_ids) == {"A", "B", "C"}
    assert set(pots[1].eligible_player_ids) == {"B", "C"}
    assert sum(p.amount for p in pots) == game.pot == 170

    # Rig the board/hole cards: A has the best hand overall (wins the main
    # pot), but B beats C head-to-head and takes the side pot A isn't
    # eligible for despite not having the best hand at the table.
    game.community_cards = BOARD  # 2c 5d 9h Jc Kd
    find(game, "A").hole_cards = [Card(Rank.KING, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)]  # trip kings
    find(game, "B").hole_cards = [Card(Rank.JACK, Suit.SPADES), Card(Rank.JACK, Suit.HEARTS)]  # trip jacks
    find(game, "C").hole_cards = [Card(Rank.NINE, Suit.SPADES), Card(Rank.NINE, Suit.DIAMONDS)]  # trip nines

    payouts = game.settle_showdown()

    assert payouts == {"A": 90, "B": 80, "C": 0}
    assert find(game, "A").stack == 90
    assert find(game, "B").stack == 80
    assert find(game, "C").stack == 140
