import random
from treys import Card as TreysCard, Evaluator

SUITS = ['s', 'h', 'd', 'c']
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']

class Card:
    def __init__(self, rank, suit):
        self.rank = str(rank).upper()
        self.suit = str(suit).lower()

    def to_string(self):
        return f"{self.rank}{self.suit}"

    def to_dict(self):
        return {'rank': self.rank, 'suit': self.suit}

    def to_treys_int(self):
        """Converts Card object safely into Treys integer representation."""
        return TreysCard.new(self.to_string())

class Deck:
    def __init__(self):
        self.cards = [Card(r, s) for r in RANKS for s in SUITS]
        random.shuffle(self.cards)

    def deal(self, count=1):
        dealt = self.cards[:count]
        self.cards = self.cards[count:]
        return dealt

class Player:
    def __init__(self, sid, name, chips):
        self.sid = sid
        self.name = name
        self.chips = float(chips)
        self.current_bet = 0.0
        self.total_invested = 0.0
        self.hole_cards = []
        self.folded = False
        self.is_all_in = False
        self.seat_index = -1

    def to_dict(self, show_cards=False):
        return {
            'sid': self.sid,
            'name': self.name,
            'chips': self.chips,
            'current_bet': self.current_bet,
            'total_invested': self.total_invested,
            'folded': self.folded,
            'is_all_in': self.is_all_in,
            'seat_index': self.seat_index,
            'hole_cards': [c.to_dict() for c in self.hole_cards] if show_cards else []
        }

class GameRoom:
    def __init__(self, room_id, host_sid, sb=10.0, bb=20.0):
        self.room_id = room_id
        self.host_sid = host_sid
        self.sb = float(sb)
        self.bb = float(bb)
        self.players = {}  # sid -> Player
        self.pending_joins = []
        self.pending_add_cash = []
        self.history_log = []

        # Hand State
        self.in_progress = False
        self.deck = None
        self.community_cards = []
        self.pot = 0.0
        self.dealer_idx = 0
        self.current_turn_idx = -1
        self.street = 'PREFLOP'  # PREFLOP, FLOP, TURN, RIVER, SHOWDOWN
        self.highest_bet = 0.0
        self.min_raise = 0.0

    def add_player(self, sid, name, chips):
        p = Player(sid, name, chips)
        p.seat_index = len(self.players)
        self.players[sid] = p

    def remove_player(self, sid, reason="left"):
        if sid in self.players:
            p = self.players.pop(sid)
            self.history_log.append({'name': p.name, 'reason': reason, 'chips': p.chips})
            for i, pl in enumerate(self.players.values()):
                pl.seat_index = i
            return p
        return None

    def start_hand(self):
        active_players = [p for p in self.players.values() if p.chips > 0]
        if len(active_players) < 2:
            return False, "At least 2 players with chips are required."

        self.in_progress = True
        self.deck = Deck()
        self.community_cards = []
        self.pot = 0.0
        self.street = 'PREFLOP'

        for p in self.players.values():
            p.hole_cards = self.deck.deal(2) if p.chips > 0 else []
            p.current_bet = 0.0
            p.total_invested = 0.0
            p.folded = (p.chips == 0)
            p.is_all_in = False

        p_keys = list(self.players.keys())
        self.dealer_idx = (self.dealer_idx + 1) % len(p_keys)

        sb_idx = (self.dealer_idx + 1) % len(p_keys)
        bb_idx = (self.dealer_idx + 2) % len(p_keys)

        sb_player = p_keys[sb_idx]
        bb_player = p_keys[bb_idx]

        self._post_bet(self.players[sb_player], min(self.players[sb_player].chips, self.sb))
        self._post_bet(self.players[bb_player], min(self.players[bb_player].chips, self.bb))

        self.highest_bet = max(self.players[sb_player].current_bet, self.players[bb_player].current_bet)
        self.min_raise = self.bb

        first_act_idx = (bb_idx + 1) % len(p_keys)
        self.current_turn_idx = first_act_idx

        return True, "Hand Started"

    def _post_bet(self, player, amount):
        player.chips -= amount
        player.current_bet += amount
        player.total_invested += amount
        self.pot += amount
        if player.chips == 0:
            player.is_all_in = True

    def process_action(self, sid, action_type, raise_amount=0.0):
        p_keys = list(self.players.keys())
        current_sid = p_keys[self.current_turn_idx]

        if sid != current_sid:
            return False, "Not your turn."

        p = self.players[sid]

        if action_type == 'fold':
            p.folded = True
        elif action_type == 'check':
            if p.current_bet < self.highest_bet:
                return False, "Cannot check when facing a bet."
        elif action_type == 'call':
            call_amount = self.highest_bet - p.current_bet
            actual_call = min(p.chips, call_amount)
            self._post_bet(p, actual_call)
        elif action_type == 'raise':
            total_bet_target = p.current_bet + raise_amount
            if total_bet_target < self.highest_bet + self.min_raise and raise_amount < p.chips:
                return False, f"Raise must be at least {self.min_raise} above current highest bet."

            actual_add = min(p.chips, raise_amount)
            self.min_raise = max(self.bb, actual_add - (self.highest_bet - p.current_bet))
            self._post_bet(p, actual_add)
            self.highest_bet = p.current_bet

        self.advance_turn()
        return True, "Action processed"

    def advance_turn(self):
        p_list = list(self.players.values())
        non_folded = [p for p in p_list if not p.folded]

        if len(non_folded) == 1:
            self.finish_hand_single_winner(non_folded[0])
            return

        street_complete = all(p.current_bet == self.highest_bet or p.is_all_in or p.folded for p in p_list)

        if street_complete:
            self._next_street()
        else:
            next_idx = (self.current_turn_idx + 1) % len(p_list)
            while p_list[next_idx].folded or p_list[next_idx].is_all_in:
                next_idx = (next_idx + 1) % len(p_list)
            self.current_turn_idx = next_idx

    def _next_street(self):
        for p in self.players.values():
            p.current_bet = 0.0
        self.highest_bet = 0.0
        self.min_raise = self.bb

        p_list = list(self.players.values())

        if self.street == 'PREFLOP':
            self.street = 'FLOP'
            self.community_cards.extend(self.deck.deal(3))
        elif self.street == 'FLOP':
            self.street = 'TURN'
            self.community_cards.extend(self.deck.deal(1))
        elif self.street == 'TURN':
            self.street = 'RIVER'
            self.community_cards.extend(self.deck.deal(1))
        elif self.street == 'RIVER':
            self.street = 'SHOWDOWN'
            self.evaluate_showdown()
            return

        non_folded_unallin = [p for p in p_list if not p.folded and not p.is_all_in]

        if len(non_folded_unallin) <= 1:
            while len(self.community_cards) < 5:
                cards_needed = 3 if len(self.community_cards) == 0 else 1
                self.community_cards.extend(self.deck.deal(cards_needed))
            self.street = 'SHOWDOWN'
            self.evaluate_showdown()
            return

        next_idx = (self.dealer_idx + 1) % len(p_list)
        while p_list[next_idx].folded or p_list[next_idx].is_all_in:
            next_idx = (next_idx + 1) % len(p_list)
        self.current_turn_idx = next_idx

    def discontinue_hand(self):
        for p in self.players.values():
            p.chips += p.total_invested
            p.total_invested = 0.0
            p.current_bet = 0.0
            p.hole_cards = []
            p.folded = False
        self.in_progress = False
        self.community_cards = []
        self.pot = 0.0

    def finish_hand_single_winner(self, winner):
        winner.chips += self.pot
        self.in_progress = False
        return {
            'winners': [{'name': winner.name, 'amount': self.pot, 'desc': 'Uncontested Pot (All Folded)'}],
            'pot': self.pot
        }

    def evaluate_showdown(self):
        evaluator = Evaluator()
        
        # Safely convert community cards into treys integer representation
        board_treys = [c.to_treys_int() for c in self.community_cards]

        investments = {p: p.total_invested for p in self.players.values()}
        pots = []

        # Pot & Side-Pot Calculation
        while any(v > 0 for v in investments.values()):
            min_invest = min(v for v in investments.values() if v > 0)
            pot_amount = 0.0
            eligible = []
            for p, inv in investments.items():
                if inv > 0:
                    contribution = min(inv, min_invest)
                    pot_amount += contribution
                    investments[p] -= contribution
                    if not p.folded:
                        eligible.append(p)
            if pot_amount > 0 and eligible:
                pots.append({'amount': pot_amount, 'eligible': eligible})

        winner_summary = []

        # Evaluate hands per pot
        for pot_info in pots:
            p_amount = pot_info['amount']
            p_eligible = pot_info['eligible']

            scores = {}
            for p in p_eligible:
                hand_treys = [c.to_treys_int() for c in p.hole_cards]
                # Lower score in treys indicates a stronger hand (1 = Royal Flush)
                score = evaluator.evaluate(board_treys, hand_treys)
                scores[p] = score

            min_score = min(scores.values())
            best_players = [p for p, s in scores.items() if s == min_score]
            split_share = p_amount / len(best_players)

            rank_class = evaluator.get_rank_class(min_score)
            class_string = evaluator.class_to_string(rank_class)

            for p in best_players:
                p.chips += split_share
                winner_summary.append({
                    'name': p.name,
                    'amount': split_share,
                    'desc': f"{class_string}"
                })

        self.in_progress = False
        return {'winners': winner_summary, 'pot': self.pot}