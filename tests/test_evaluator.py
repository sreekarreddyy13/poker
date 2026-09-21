import pytest

from poker.cards import Card, Rank, Suit
from poker.evaluator import HandCategory, evaluate_hand


def C(rank: Rank, suit: Suit) -> Card:
    return Card(rank, suit)


def category(cards):
    return evaluate_hand(cards)[0]


# --- category detection -----------------------------------------------------

def test_high_card():
    hand = [
        C(Rank.TWO, Suit.CLUBS),
        C(Rank.FIVE, Suit.DIAMONDS),
        C(Rank.SEVEN, Suit.HEARTS),
        C(Rank.NINE, Suit.SPADES),
        C(Rank.KING, Suit.CLUBS),
    ]
    assert category(hand) == HandCategory.HIGH_CARD


def test_pair():
    hand = [
        C(Rank.TWO, Suit.CLUBS),
        C(Rank.TWO, Suit.DIAMONDS),
        C(Rank.SEVEN, Suit.HEARTS),
        C(Rank.NINE, Suit.SPADES),
        C(Rank.KING, Suit.CLUBS),
    ]
    assert category(hand) == HandCategory.PAIR


def test_two_pair():
    hand = [
        C(Rank.TWO, Suit.CLUBS),
        C(Rank.TWO, Suit.DIAMONDS),
        C(Rank.NINE, Suit.HEARTS),
        C(Rank.NINE, Suit.SPADES),
        C(Rank.KING, Suit.CLUBS),
    ]
    assert category(hand) == HandCategory.TWO_PAIR


def test_three_of_a_kind():
    hand = [
        C(Rank.TWO, Suit.CLUBS),
        C(Rank.TWO, Suit.DIAMONDS),
        C(Rank.TWO, Suit.HEARTS),
        C(Rank.NINE, Suit.SPADES),
        C(Rank.KING, Suit.CLUBS),
    ]
    assert category(hand) == HandCategory.THREE_OF_A_KIND


def test_straight():
    hand = [
        C(Rank.FIVE, Suit.CLUBS),
        C(Rank.SIX, Suit.DIAMONDS),
        C(Rank.SEVEN, Suit.HEARTS),
        C(Rank.EIGHT, Suit.SPADES),
        C(Rank.NINE, Suit.CLUBS),
    ]
    rank = evaluate_hand(hand)
    assert rank[0] == HandCategory.STRAIGHT
    assert rank[1] == Rank.NINE


def test_wheel_straight_ace_low():
    hand = [
        C(Rank.ACE, Suit.CLUBS),
        C(Rank.TWO, Suit.DIAMONDS),
        C(Rank.THREE, Suit.HEARTS),
        C(Rank.FOUR, Suit.SPADES),
        C(Rank.FIVE, Suit.CLUBS),
    ]
    rank = evaluate_hand(hand)
    assert rank[0] == HandCategory.STRAIGHT
    assert rank[1] == Rank.FIVE  # wheel is the lowest straight, high card is the 5


def test_wheel_is_lower_than_six_high_straight():
    wheel = [
        C(Rank.ACE, Suit.CLUBS),
        C(Rank.TWO, Suit.DIAMONDS),
        C(Rank.THREE, Suit.HEARTS),
        C(Rank.FOUR, Suit.SPADES),
        C(Rank.FIVE, Suit.CLUBS),
    ]
    six_high = [
        C(Rank.TWO, Suit.CLUBS),
        C(Rank.THREE, Suit.DIAMONDS),
        C(Rank.FOUR, Suit.HEARTS),
        C(Rank.FIVE, Suit.SPADES),
        C(Rank.SIX, Suit.CLUBS),
    ]
    assert evaluate_hand(wheel) < evaluate_hand(six_high)


def test_flush():
    hand = [
        C(Rank.TWO, Suit.CLUBS),
        C(Rank.FIVE, Suit.CLUBS),
        C(Rank.SEVEN, Suit.CLUBS),
        C(Rank.NINE, Suit.CLUBS),
        C(Rank.KING, Suit.CLUBS),
    ]
    assert category(hand) == HandCategory.FLUSH


def test_full_house():
    hand = [
        C(Rank.TWO, Suit.CLUBS),
        C(Rank.TWO, Suit.DIAMONDS),
        C(Rank.TWO, Suit.HEARTS),
        C(Rank.NINE, Suit.SPADES),
        C(Rank.NINE, Suit.CLUBS),
    ]
    assert category(hand) == HandCategory.FULL_HOUSE


def test_four_of_a_kind():
    hand = [
        C(Rank.TWO, Suit.CLUBS),
        C(Rank.TWO, Suit.DIAMONDS),
        C(Rank.TWO, Suit.HEARTS),
        C(Rank.TWO, Suit.SPADES),
        C(Rank.NINE, Suit.CLUBS),
    ]
    assert category(hand) == HandCategory.FOUR_OF_A_KIND


def test_straight_flush():
    hand = [
        C(Rank.FIVE, Suit.CLUBS),
        C(Rank.SIX, Suit.CLUBS),
        C(Rank.SEVEN, Suit.CLUBS),
        C(Rank.EIGHT, Suit.CLUBS),
        C(Rank.NINE, Suit.CLUBS),
    ]
    assert category(hand) == HandCategory.STRAIGHT_FLUSH


def test_wheel_straight_flush():
    hand = [
        C(Rank.ACE, Suit.CLUBS),
        C(Rank.TWO, Suit.CLUBS),
        C(Rank.THREE, Suit.CLUBS),
        C(Rank.FOUR, Suit.CLUBS),
        C(Rank.FIVE, Suit.CLUBS),
    ]
    rank = evaluate_hand(hand)
    assert rank[0] == HandCategory.STRAIGHT_FLUSH
    assert rank[1] == Rank.FIVE


def test_royal_flush_is_a_straight_flush():
    hand = [
        C(Rank.TEN, Suit.SPADES),
        C(Rank.JACK, Suit.SPADES),
        C(Rank.QUEEN, Suit.SPADES),
        C(Rank.KING, Suit.SPADES),
        C(Rank.ACE, Suit.SPADES),
    ]
    rank = evaluate_hand(hand)
    assert rank[0] == HandCategory.STRAIGHT_FLUSH
    assert rank[1] == Rank.ACE


# --- category ordering --------------------------------------------------

def test_category_ordering_high_to_low():
    straight_flush = [
        C(Rank.FIVE, Suit.CLUBS), C(Rank.SIX, Suit.CLUBS), C(Rank.SEVEN, Suit.CLUBS),
        C(Rank.EIGHT, Suit.CLUBS), C(Rank.NINE, Suit.CLUBS),
    ]
    four_kind = [
        C(Rank.TWO, Suit.CLUBS), C(Rank.TWO, Suit.DIAMONDS), C(Rank.TWO, Suit.HEARTS),
        C(Rank.TWO, Suit.SPADES), C(Rank.NINE, Suit.CLUBS),
    ]
    full_house = [
        C(Rank.THREE, Suit.CLUBS), C(Rank.THREE, Suit.DIAMONDS), C(Rank.THREE, Suit.HEARTS),
        C(Rank.NINE, Suit.SPADES), C(Rank.NINE, Suit.CLUBS),
    ]
    flush = [
        C(Rank.TWO, Suit.CLUBS), C(Rank.FIVE, Suit.CLUBS), C(Rank.SEVEN, Suit.CLUBS),
        C(Rank.NINE, Suit.CLUBS), C(Rank.KING, Suit.CLUBS),
    ]
    straight = [
        C(Rank.FIVE, Suit.CLUBS), C(Rank.SIX, Suit.DIAMONDS), C(Rank.SEVEN, Suit.HEARTS),
        C(Rank.EIGHT, Suit.SPADES), C(Rank.NINE, Suit.CLUBS),
    ]
    trips = [
        C(Rank.TWO, Suit.CLUBS), C(Rank.TWO, Suit.DIAMONDS), C(Rank.TWO, Suit.HEARTS),
        C(Rank.NINE, Suit.SPADES), C(Rank.KING, Suit.CLUBS),
    ]
    two_pair = [
        C(Rank.TWO, Suit.CLUBS), C(Rank.TWO, Suit.DIAMONDS), C(Rank.NINE, Suit.HEARTS),
        C(Rank.NINE, Suit.SPADES), C(Rank.KING, Suit.CLUBS),
    ]
    pair = [
        C(Rank.TWO, Suit.CLUBS), C(Rank.TWO, Suit.DIAMONDS), C(Rank.SEVEN, Suit.HEARTS),
        C(Rank.NINE, Suit.SPADES), C(Rank.KING, Suit.CLUBS),
    ]
    high_card = [
        C(Rank.TWO, Suit.CLUBS), C(Rank.FIVE, Suit.DIAMONDS), C(Rank.SEVEN, Suit.HEARTS),
        C(Rank.NINE, Suit.SPADES), C(Rank.KING, Suit.CLUBS),
    ]

    ordered = [
        straight_flush, four_kind, full_house, flush, straight,
        trips, two_pair, pair, high_card,
    ]
    ranks = [evaluate_hand(hand) for hand in ordered]
    assert ranks == sorted(ranks, reverse=True)


# --- kickers and ties -----------------------------------------------------

def test_pair_kickers_break_ties():
    lower_kicker = [
        C(Rank.TWO, Suit.CLUBS), C(Rank.TWO, Suit.DIAMONDS), C(Rank.THREE, Suit.HEARTS),
        C(Rank.FOUR, Suit.SPADES), C(Rank.FIVE, Suit.CLUBS),
    ]
    higher_kicker = [
        C(Rank.TWO, Suit.HEARTS), C(Rank.TWO, Suit.SPADES), C(Rank.THREE, Suit.DIAMONDS),
        C(Rank.FOUR, Suit.CLUBS), C(Rank.SIX, Suit.HEARTS),
    ]
    assert evaluate_hand(higher_kicker) > evaluate_hand(lower_kicker)


def test_two_pair_uses_higher_pair_first_then_kicker():
    aces_and_twos = [
        C(Rank.ACE, Suit.CLUBS), C(Rank.ACE, Suit.DIAMONDS), C(Rank.TWO, Suit.HEARTS),
        C(Rank.TWO, Suit.SPADES), C(Rank.THREE, Suit.CLUBS),
    ]
    kings_and_queens = [
        C(Rank.KING, Suit.CLUBS), C(Rank.KING, Suit.DIAMONDS), C(Rank.QUEEN, Suit.HEARTS),
        C(Rank.QUEEN, Suit.SPADES), C(Rank.ACE, Suit.CLUBS),
    ]
    assert evaluate_hand(aces_and_twos) > evaluate_hand(kings_and_queens)


def test_identical_hands_tie():
    hand_a = [
        C(Rank.TEN, Suit.CLUBS), C(Rank.TEN, Suit.DIAMONDS), C(Rank.KING, Suit.HEARTS),
        C(Rank.FOUR, Suit.SPADES), C(Rank.TWO, Suit.CLUBS),
    ]
    hand_b = [
        C(Rank.TEN, Suit.HEARTS), C(Rank.TEN, Suit.SPADES), C(Rank.KING, Suit.CLUBS),
        C(Rank.FOUR, Suit.DIAMONDS), C(Rank.TWO, Suit.HEARTS),
    ]
    assert evaluate_hand(hand_a) == evaluate_hand(hand_b)


def test_full_house_trips_rank_breaks_tie_over_pair_rank():
    threes_full_of_kings = [
        C(Rank.THREE, Suit.CLUBS), C(Rank.THREE, Suit.DIAMONDS), C(Rank.THREE, Suit.HEARTS),
        C(Rank.KING, Suit.SPADES), C(Rank.KING, Suit.CLUBS),
    ]
    fours_full_of_twos = [
        C(Rank.FOUR, Suit.CLUBS), C(Rank.FOUR, Suit.DIAMONDS), C(Rank.FOUR, Suit.HEARTS),
        C(Rank.TWO, Suit.SPADES), C(Rank.TWO, Suit.CLUBS),
    ]
    assert evaluate_hand(fours_full_of_twos) > evaluate_hand(threes_full_of_kings)


# --- 6/7 card inputs pick the best 5-card subset -----------------------------

def test_seven_cards_picks_best_five_card_hand():
    hole = [C(Rank.ACE, Suit.CLUBS), C(Rank.ACE, Suit.DIAMONDS)]
    board = [
        C(Rank.ACE, Suit.HEARTS),
        C(Rank.ACE, Suit.SPADES),
        C(Rank.KING, Suit.CLUBS),
        C(Rank.TWO, Suit.DIAMONDS),
        C(Rank.SEVEN, Suit.HEARTS),
    ]
    rank = evaluate_hand(hole + board)
    assert rank[0] == HandCategory.FOUR_OF_A_KIND
    assert rank[1] == Rank.ACE
    assert rank[2] == Rank.KING  # best kicker among the remaining cards


def test_six_cards_finds_flush_over_weaker_five_card_subsets():
    hand = [
        C(Rank.TWO, Suit.CLUBS),
        C(Rank.FIVE, Suit.CLUBS),
        C(Rank.SEVEN, Suit.CLUBS),
        C(Rank.NINE, Suit.CLUBS),
        C(Rank.KING, Suit.CLUBS),
        C(Rank.KING, Suit.HEARTS),
    ]
    assert category(hand) == HandCategory.FLUSH


def test_seven_card_straight_uses_best_run():
    hand = [
        C(Rank.TWO, Suit.CLUBS),
        C(Rank.THREE, Suit.DIAMONDS),
        C(Rank.FOUR, Suit.HEARTS),
        C(Rank.FIVE, Suit.SPADES),
        C(Rank.SIX, Suit.CLUBS),
        C(Rank.SEVEN, Suit.DIAMONDS),
        C(Rank.EIGHT, Suit.HEARTS),
    ]
    rank = evaluate_hand(hand)
    assert rank[0] == HandCategory.STRAIGHT
    assert rank[1] == Rank.EIGHT


# --- input validation -----------------------------------------------------

def test_rejects_too_few_cards():
    with pytest.raises(ValueError):
        evaluate_hand([C(Rank.TWO, Suit.CLUBS)] * 4)


def test_rejects_too_many_cards():
    with pytest.raises(ValueError):
        evaluate_hand([C(r, Suit.CLUBS) for r in list(Rank)[:8]])
