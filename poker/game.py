from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Collection, Optional, Sequence

from poker.cards import Card, Deck
from poker.evaluator import describe_hand, evaluate_hand


class Stage(Enum):
    PREFLOP = auto()
    FLOP = auto()
    TURN = auto()
    RIVER = auto()
    SHOWDOWN = auto()


class ActionType(Enum):
    FOLD = auto()
    CHECK = auto()
    CALL = auto()
    RAISE = auto()
    ALL_IN = auto()


class IllegalActionError(ValueError):
    pass


@dataclass
class Player:
    player_id: str
    stack: int
    hole_cards: list[Card] = field(default_factory=list)
    folded: bool = False
    all_in: bool = False
    current_bet: int = 0
    has_acted: bool = False
    total_contributed: int = 0  # chips put in this hand, across all streets


@dataclass(frozen=True)
class Pot:
    amount: int
    eligible_player_ids: tuple[str, ...]


class Game:
    def __init__(
        self,
        player_ids: Sequence[str],
        starting_stack: int,
        small_blind: int,
        big_blind: int,
    ) -> None:
        if not 2 <= len(player_ids) <= 9:
            raise ValueError("Game supports between 2 and 9 players")
        if len(set(player_ids)) != len(player_ids):
            raise ValueError("player_ids must be unique")
        if starting_stack <= 0 or small_blind <= 0 or big_blind <= 0:
            raise ValueError("stacks and blinds must be positive")
        if small_blind >= big_blind:
            raise ValueError("small_blind must be less than big_blind")

        self.players: list[Player] = [Player(pid, starting_stack) for pid in player_ids]
        self.small_blind = small_blind
        self.big_blind = big_blind

        self.button_index = -1
        self.stage: Optional[Stage] = None
        self.community_cards: list[Card] = []
        self.pot = 0
        self.current_bet = 0
        self.min_raise = big_blind
        self.current_actor_index: Optional[int] = None
        self._deck: Optional[Deck] = None
        self._settled = False

    @property
    def current_actor(self) -> Optional[str]:
        if self.current_actor_index is None:
            return None
        return self.players[self.current_actor_index].player_id

    # ------------------------------------------------------------------
    # Hand setup

    def start_hand(self) -> None:
        if any(p.stack <= 0 for p in self.players):
            raise IllegalActionError("all players must have chips to start a new hand")

        self.button_index = (self.button_index + 1) % len(self.players)
        for p in self.players:
            p.hole_cards = []
            p.folded = False
            p.all_in = False
            p.current_bet = 0
            p.has_acted = False
            p.total_contributed = 0

        self.community_cards = []
        self.pot = 0
        self.current_bet = 0
        self.min_raise = self.big_blind
        self.stage = Stage.PREFLOP
        self._settled = False

        self._deck = Deck()
        self._deck.shuffle()
        self._deal_hole_cards()
        self._post_blinds()

        self.current_actor_index = self._seat_after(self._bb_index())
        self._sync_actor_state()

    def add_player(self, player_id: str, stack: int) -> None:
        """Seat a new player between hands; they'll be dealt in from the next
        start_hand() onward. Cannot be used while a hand is in progress."""
        if self.stage is not None and self.stage != Stage.SHOWDOWN:
            raise IllegalActionError("cannot add a player while a hand is in progress")
        if any(p.player_id == player_id for p in self.players):
            raise IllegalActionError(f"player {player_id} is already seated")
        if len(self.players) >= 9:
            raise IllegalActionError("table is full")
        self.players.append(Player(player_id, stack))

    def start_next_hand(self) -> list[str]:
        """Drop busted players, rotate the button, and start a new hand,
        keeping remaining players' stacks. Returns removed player ids."""
        if self.stage != Stage.SHOWDOWN:
            raise IllegalActionError("cannot start a new hand before showdown")
        busted = {p.player_id for p in self.players if p.stack <= 0}
        removed = self._remove_players(busted)
        if len(self.players) < 2:
            raise IllegalActionError("not enough players with chips to continue")
        self.start_hand()
        return removed

    def remove_players(self, player_ids: Collection[str]) -> list[str]:
        """Remove seated players between hands (e.g. they disconnected and
        are sitting out this hand). Cannot be used while a hand is in
        progress. Returns the ids actually removed."""
        if self.stage is not None and self.stage != Stage.SHOWDOWN:
            raise IllegalActionError("cannot remove a player while a hand is in progress")
        ids = set(player_ids)
        unknown = ids - {p.player_id for p in self.players}
        if unknown:
            raise IllegalActionError(f"unknown player(s) {sorted(unknown)}")
        return self._remove_players(ids)

    def _remove_players(self, ids: set[str]) -> list[str]:
        survivors = [p for p in self.players if p.player_id not in ids]
        removed = [p.player_id for p in self.players if p.player_id in ids]
        if not removed:
            return []

        old_order = [p.player_id for p in self.players]
        old_button_id = self.players[self.button_index].player_id
        self.players = survivors
        if not survivors:
            self.button_index = -1
            return removed

        survivor_ids = {p.player_id for p in survivors}
        n = len(old_order)
        start = old_order.index(old_button_id)
        for offset in range(1, n + 1):
            candidate = old_order[(start + offset) % n]
            if candidate in survivor_ids:
                target_index = next(i for i, p in enumerate(self.players) if p.player_id == candidate)
                self.button_index = (target_index - 1) % len(self.players)
                break
        return removed

    def _deal_hole_cards(self) -> None:
        assert self._deck is not None
        n = len(self.players)
        order = [(self._sb_index() + i) % n for i in range(n)]
        for _ in range(2):
            for i in order:
                self.players[i].hole_cards.extend(self._deck.deal(1))

    def _post_blinds(self) -> None:
        self._post_blind(self.players[self._sb_index()], self.small_blind)
        self._post_blind(self.players[self._bb_index()], self.big_blind)
        self.current_bet = self.big_blind

    def _post_blind(self, player: Player, amount: int) -> None:
        cost = min(amount, player.stack)
        player.stack -= cost
        player.current_bet += cost
        player.total_contributed += cost
        self.pot += cost
        if player.stack == 0:
            player.all_in = True

    # ------------------------------------------------------------------
    # Seat helpers

    def _seat_after(self, index: int) -> int:
        return (index + 1) % len(self.players)

    def _sb_index(self) -> int:
        if len(self.players) == 2:
            return self.button_index
        return self._seat_after(self.button_index)

    def _bb_index(self) -> int:
        return self._seat_after(self._sb_index())

    # ------------------------------------------------------------------
    # Actions

    def apply_action(self, player_id: str, action: ActionType, amount: Optional[int] = None) -> None:
        if self.stage is None or self.stage == Stage.SHOWDOWN:
            raise IllegalActionError("no betting action can be taken right now")
        if self.current_actor != player_id:
            raise IllegalActionError(f"it is not {player_id}'s turn")

        player = self._get_player(player_id)
        if player.folded or player.all_in:
            raise IllegalActionError(f"{player_id} cannot act (folded or all-in)")

        if action == ActionType.FOLD:
            self._fold(player)
        elif action == ActionType.CHECK:
            self._check(player)
        elif action == ActionType.CALL:
            self._call(player)
        elif action == ActionType.RAISE:
            if amount is None:
                raise IllegalActionError("raise requires an amount")
            self._raise(player, amount)
        elif action == ActionType.ALL_IN:
            self._all_in(player)
        else:
            raise IllegalActionError(f"unknown action {action}")

        self._after_action()

    def _get_player(self, player_id: str) -> Player:
        for p in self.players:
            if p.player_id == player_id:
                return p
        raise IllegalActionError(f"unknown player {player_id}")

    def _fold(self, player: Player) -> None:
        player.folded = True
        player.has_acted = True

    def _check(self, player: Player) -> None:
        if player.current_bet != self.current_bet:
            raise IllegalActionError("cannot check when facing a bet; call or fold instead")
        player.has_acted = True

    def _call(self, player: Player) -> None:
        to_call = self.current_bet - player.current_bet
        if to_call <= 0:
            raise IllegalActionError("nothing to call; check instead")
        # A short-stacked call is legal: it's capped at the player's stack
        # and just goes all-in for less than the full amount owed.
        cost = min(to_call, player.stack)
        player.stack -= cost
        player.current_bet += cost
        player.total_contributed += cost
        self.pot += cost
        player.has_acted = True
        if player.stack == 0:
            player.all_in = True

    def _raise(self, player: Player, amount: int) -> None:
        if amount <= self.current_bet:
            raise IllegalActionError("raise must be greater than the current bet")
        increase = amount - self.current_bet
        if increase < self.min_raise:
            raise IllegalActionError(f"raise must increase the bet by at least {self.min_raise}")
        cost = amount - player.current_bet
        if cost > player.stack:
            raise IllegalActionError("not enough chips for this raise; go all-in instead")

        player.stack -= cost
        player.current_bet = amount
        player.total_contributed += cost
        self.pot += cost
        self.current_bet = amount
        self.min_raise = increase
        player.has_acted = True
        if player.stack == 0:
            player.all_in = True
        self._reopen_action(except_player=player)

    def _all_in(self, player: Player) -> None:
        if player.stack <= 0:
            raise IllegalActionError("no chips left to go all-in")

        cost = player.stack
        new_total = player.current_bet + cost
        player.stack = 0
        player.current_bet = new_total
        player.all_in = True
        player.total_contributed += cost
        self.pot += cost
        player.has_acted = True

        if new_total > self.current_bet:
            increase = new_total - self.current_bet
            self.current_bet = new_total
            if increase >= self.min_raise:
                self.min_raise = increase
                self._reopen_action(except_player=player)

    def _reopen_action(self, except_player: Player) -> None:
        for p in self.players:
            if p is not except_player and not p.folded and not p.all_in:
                p.has_acted = False

    # ------------------------------------------------------------------
    # Round / stage progression

    def _after_action(self) -> None:
        if self._only_one_active_player():
            self.stage = Stage.SHOWDOWN
            self.current_actor_index = None
            return
        if self._round_complete():
            self._advance_round()
            return
        assert self.current_actor_index is not None
        self.current_actor_index = self._seat_after(self.current_actor_index)
        self._skip_unactable()

    def _only_one_active_player(self) -> bool:
        return sum(1 for p in self.players if not p.folded) == 1

    def _round_complete(self) -> bool:
        for p in self.players:
            if p.folded or p.all_in:
                continue
            if not p.has_acted or p.current_bet != self.current_bet:
                return False
        return True

    def _skip_unactable(self) -> None:
        assert self.current_actor_index is not None
        start = self.current_actor_index
        while self.players[self.current_actor_index].folded or self.players[self.current_actor_index].all_in:
            self.current_actor_index = self._seat_after(self.current_actor_index)
            if self.current_actor_index == start:
                break

    def _sync_actor_state(self) -> None:
        if self._only_one_active_player():
            self.stage = Stage.SHOWDOWN
            self.current_actor_index = None
            return
        if self._round_complete():
            self._advance_round()
            return
        self._skip_unactable()

    def _advance_round(self) -> None:
        self._deal_next_street()
        if self.stage == Stage.SHOWDOWN:
            self.current_actor_index = None
            return

        self._reset_round_state()
        can_act = [p for p in self.players if not p.folded and not p.all_in]
        if len(can_act) <= 1:
            self._advance_round()
            return
        self.current_actor_index = self._seat_after(self.button_index)
        self._skip_unactable()

    def _deal_next_street(self) -> None:
        assert self._deck is not None
        if self.stage == Stage.PREFLOP:
            self._deck.deal(1)
            self.community_cards.extend(self._deck.deal(3))
            self.stage = Stage.FLOP
        elif self.stage == Stage.FLOP:
            self._deck.deal(1)
            self.community_cards.extend(self._deck.deal(1))
            self.stage = Stage.TURN
        elif self.stage == Stage.TURN:
            self._deck.deal(1)
            self.community_cards.extend(self._deck.deal(1))
            self.stage = Stage.RIVER
        elif self.stage == Stage.RIVER:
            self.stage = Stage.SHOWDOWN

    def _reset_round_state(self) -> None:
        self.current_bet = 0
        self.min_raise = self.big_blind
        for p in self.players:
            p.current_bet = 0
            p.has_acted = False

    # ------------------------------------------------------------------
    # Side pots / showdown

    def compute_side_pots(self) -> list[Pot]:
        """Split total contributions into a main pot plus a side pot per
        distinct all-in level. A layer's chips are only won by players who
        haven't folded, but folded players' chips still count toward it."""
        remaining = [[p, p.total_contributed] for p in self.players if p.total_contributed > 0]
        pots: list[Pot] = []
        while remaining:
            level = min(amount for _, amount in remaining)
            eligible = tuple(p.player_id for p, _ in remaining if not p.folded)
            pots.append(Pot(amount=level * len(remaining), eligible_player_ids=eligible))
            for entry in remaining:
                entry[1] -= level
            remaining = [entry for entry in remaining if entry[1] > 0]
        return pots

    def settle_showdown(self) -> dict[str, int]:
        if self.stage != Stage.SHOWDOWN:
            raise IllegalActionError("cannot settle a hand before showdown")
        if self._settled:
            raise IllegalActionError("hand has already been settled")
        self._settled = True

        payouts = {p.player_id: 0 for p in self.players}
        for pot in self.compute_side_pots():
            winners = self._payout_order(self._pot_winners(pot))
            share, remainder = divmod(pot.amount, len(winners))
            for i, player_id in enumerate(winners):
                payouts[player_id] += share + (1 if i < remainder else 0)

        for p in self.players:
            p.stack += payouts[p.player_id]
        return payouts

    def showdown_hands(self) -> dict[str, str]:
        """Hand category description for each player whose cards were
        actually compared at showdown. Empty before showdown, and empty if
        the pot was won uncontested (everyone else folded) since no hand is
        shown in that case."""
        if self.stage != Stage.SHOWDOWN:
            return {}
        active = [p for p in self.players if not p.folded]
        if len(active) < 2:
            return {}
        return {
            p.player_id: describe_hand(evaluate_hand(p.hole_cards + self.community_cards))
            for p in active
            if len(p.hole_cards) + len(self.community_cards) >= 5
        }

    def _pot_winners(self, pot: Pot) -> list[str]:
        eligible = [self._get_player(pid) for pid in pot.eligible_player_ids]
        if len(eligible) == 1:
            return [eligible[0].player_id]
        ranks = {p.player_id: evaluate_hand(p.hole_cards + self.community_cards) for p in eligible}
        best = max(ranks.values())
        return [pid for pid, rank in ranks.items() if rank == best]

    def _payout_order(self, player_ids: list[str]) -> list[str]:
        """Odd chips go to the first winner left of the button."""
        start = self._seat_after(self.button_index)
        seat_of = {p.player_id: i for i, p in enumerate(self.players)}
        n = len(self.players)
        return sorted(player_ids, key=lambda pid: (seat_of[pid] - start) % n)
