import random
from treys import Card, Evaluator

class CardModel:
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit

    def to_dict(self):
        return {'rank': self.rank, 'suit': self.suit}

class Player:
    def __init__(self, sid, name, chips):
        self.sid = sid
        self.name = name
        self.chips = float(chips)
        self.current_bet = 0.0
        self.folded = False
        self.hole_cards = []

class GameRoom:
    def __init__(self, room_id, host_sid, sb=10, bb=20):
        self.room_id = room_id
        self.host_sid = host_sid
        self.sb = sb
        self.bb = bb
        self.players = {}
        self.player_order = []
        self.pending_joins = []
        self.pending_add_cash = []
        self.in_progress = False
        self.pot = 0.0
        self.highest_bet = 0.0
        self.street = 'PREFLOP'
        self.community_cards = []
        self.current_turn_idx = 0
        self.dealer_idx = 0
        self.dealer_sid = None
        self.deck = []
        self.last_hand_summary = "No hands played yet."

    def add_player(self, sid, name, chips):
        if sid not in self.players:
            player = Player(sid, name, chips)
            self.players[sid] = player
            self.player_order.append(sid)

    def start_hand(self):
        active_players = [p for p in self.players.values() if p.chips > 0]
        if len(active_players) < 2:
            return False, "At least 2 active players with chips required to start."

        self.in_progress = True
        self.pot = 0.0
        self.highest_bet = 0.0
        self.street = 'PREFLOP'
        self.community_cards = []
        
        # Reset players
        for p in self.players.values():
            p.current_bet = 0.0
            p.folded = False
            p.hole_cards = []

        # Advance dealer
        self.dealer_idx = (self.dealer_idx + 1) % len(self.player_order)
        self.dealer_sid = self.player_order[self.dealer_idx]

        # Build & Shuffle Deck
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        suits = ['S', 'H', 'D', 'C']
        self.deck = [CardModel(r, s) for r in ranks for s in suits]
        random.shuffle(self.deck)

        # Deal 2 cards to each player
        for p_sid in self.player_order:
            if p_sid in self.players and self.players[p_sid].chips > 0:
                self.players[p_sid].hole_cards = [self.deck.pop(), self.deck.pop()]

        # Post Blinds
        sb_idx = (self.dealer_idx + 1) % len(self.player_order)
        bb_idx = (self.dealer_idx + 2) % len(self.player_order)
        
        sb_player = self.players[self.player_order[sb_idx]]
        bb_player = self.players[self.player_order[bb_idx]]

        sb_amt = min(self.sb, sb_player.chips)
        bb_amt = min(self.bb, bb_player.chips)

        sb_player.chips -= sb_amt
        sb_player.current_bet = sb_amt
        bb_player.chips -= bb_amt
        bb_player.current_bet = bb_amt

        self.pot = sb_amt + bb_amt
        self.highest_bet = bb_amt

        # Action starts after BB
        self.current_turn_idx = (bb_idx + 1) % len(self.player_order)
        return True, "Hand started"

    def process_action(self, sid, action, amount=0.0):
        if not self.in_progress:
            return False, "No active hand in progress."

        current_sid = self.player_order[self.current_turn_idx]
        if sid != current_sid:
            return False, "Not your turn."

        player = self.players[sid]

        if action == 'fold':
            player.folded = True
        elif action == 'check':
            if player.current_bet < self.highest_bet:
                return False, f"Cannot check. High bet is ${self.highest_bet}"
        elif action == 'call':
            call_amt = self.highest_bet - player.current_bet
            actual_call = min(call_amt, player.chips)
            player.chips -= actual_call
            player.current_bet += actual_call
            self.pot += actual_call
        elif action == 'raise':
            total_bet = amount
            if total_bet <= self.highest_bet:
                return False, f"Raise must exceed current high bet of ${self.highest_bet}"
            added_chips = total_bet - player.current_bet
            if added_chips > player.chips:
                return False, "Insufficient chips."
            player.chips -= added_chips
            player.current_bet += added_chips
            self.pot += added_chips
            self.highest_bet = total_bet

        self.advance_turn()
        return True, "Action processed"

    def advance_turn(self):
        # Move to next un-folded player
        attempts = 0
        n = len(self.player_order)
        while attempts < n:
            self.current_turn_idx = (self.current_turn_idx + 1) % n
            next_player = self.players[self.player_order[self.current_turn_idx]]
            if not next_player.folded and next_player.chips >= 0:
                break
            attempts += 1
