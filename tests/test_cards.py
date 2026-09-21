from poker.cards import Card, Deck, Rank, Suit


def test_deck_has_52_unique_cards():
    deck = Deck()
    cards = deck.deal(52)
    assert len(cards) == 52
    assert len(set(cards)) == 52
    assert set(cards) == {Card(rank, suit) for suit in Suit for rank in Rank}


def test_dealing_removes_cards_from_deck():
    deck = Deck()
    assert len(deck) == 52
    deck.deal(5)
    assert len(deck) == 47


def test_deal_returns_no_duplicates_across_multiple_deals():
    deck = Deck()
    deck.shuffle()
    first = deck.deal(5)
    second = deck.deal(5)
    assert len(set(first) | set(second)) == 10


def test_deal_too_many_raises():
    deck = Deck()
    deck.deal(52)
    try:
        deck.deal(1)
    except ValueError:
        pass
    else:
        assert False, "expected ValueError when deck is empty"
