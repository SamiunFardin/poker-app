import random

class CardModel:
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit

    def to_dict(self):
        return {'rank': self.rank, 'suit': self.suit}

    def get_rank_value(self):
        order = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        return order.index(self.rank)

class Player:
    def __init__(self, sid, session_id, name, avatar="😎", is_host=False):
        self.sid = sid
        self.session_id = session_id
        self.name = name
        self.avatar = avatar
        self.is_host = is_host
        self.hand = []
        self.call = 0
        self.tricks_won = 0
        self.total_score = 0.0

class CallBridgeRoom:
    def __init__(self, room_id, host_sid, host_session_id, host_name="Host Admin", host_avatar="👑"):
        self.room_id = room_id
        self.game_type = "call_bridge"
        self.host_sid = host_sid
        self.host_session_id = host_session_id
        
        self.players = {}
        self.player_order = []
        self.session_map = {}
        
        self.in_progress = False
        self.round_number = 1
        self.phase = 'BIDDING'  # 'BIDDING', 'PLAYING', 'ROUND_ENDED'
        self.current_turn_idx = 0
        self.lead_suit = None
        self.current_trick = []
        self.last_hand_summary = "Waiting for Call Bridge table to fill (4 players)..."

        self.add_player(host_sid, host_session_id, host_name, host_avatar, is_host=True)

    def add_player(self, sid, session_id, name, avatar="😎", is_host=False):
        if len(self.player_order) >= 4:
            return False, "Call Bridge room is full."
        player = Player(sid, session_id, name, avatar, is_host)
        self.players[sid] = player
        self.session_map[session_id] = player
        if sid not in self.player_order:
            self.player_order.append(sid)
        return True, "Joined successfully."

    def start_game(self):
        if len(self.player_order) != 4:
            return False, "Exactly 4 players are required to start Call Bridge."
        self.in_progress = True
        self.start_round()
        return True, "Call Bridge started."

    def start_round(self):
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        suits = ['S', 'H', 'D', 'C']
        deck = [CardModel(r, s) for r in ranks for s in suits]
        random.shuffle(deck)

        for p in self.players.values():
            p.hand = [deck.pop() for _ in range(13)]
            p.call = 0
            p.tricks_won = 0

        self.phase = 'BIDDING'
        self.current_turn_idx = (self.round_number - 1) % 4
        self.current_trick = []
        self.lead_suit = None

    def place_bid(self, sid, call_amount):
        if self.phase != 'BIDDING' or self.player_order[self.current_turn_idx] != sid:
            return False, "Not your turn or wrong phase."
        if not (1 <= call_amount <= 13):
            return False, "Call must be between 1 and 13."

        self.players[sid].call = call_amount
        self.current_turn_idx = (self.current_turn_idx + 1) % 4

        if all(p.call > 0 for p in self.players.values()):
            self.phase = 'PLAYING'
            self.current_turn_idx = (self.round_number - 1) % 4

        return True, "Call recorded."

    def play_card(self, sid, card_dict):
        if self.phase != 'PLAYING' or self.player_order[self.current_turn_idx] != sid:
            return False, "Not your turn."

        player = self.players[sid]
        card = next((c for c in player.hand if c.rank == card_dict['rank'] and c.suit == card_dict['suit']), None)
        if not card: return False, "Card not in hand."

        if self.lead_suit and any(c.suit == self.lead_suit for c in player.hand) and card.suit != self.lead_suit:
            return False, f"Must follow lead suit ({self.lead_suit})."

        if not self.current_trick: self.lead_suit = card.suit
        player.hand.remove(card)
        self.current_trick.append({'sid': sid, 'card': card})

        if len(self.current_trick) < 4:
            self.current_turn_idx = (self.current_turn_idx + 1) % 4
            return True, "Played."

        # Evaluate Trick
        best = self.current_trick[0]
        for t in self.current_trick[1:]:
            if t['card'].suit == 'S' and best['card'].suit != 'S': best = t
            elif t['card'].suit == best['card'].suit and t['card'].get_rank_value() > best['card'].get_rank_value(): best = t

        winner_sid = best['sid']
        self.players[winner_sid].tricks_won += 1
        self.lead_suit = None
        self.current_trick = []

        if all(len(p.hand) == 0 for p in self.players.values()):
            self.calculate_round_scores()
            self.round_number += 1
            self.start_round()
        else:
            self.current_turn_idx = self.player_order.index(winner_sid)

        return True, "Trick resolved."

    def calculate_round_scores(self):
        total_calls = sum(p.call for p in self.players.values())
        for p in self.players.values():
            if total_calls < 13:
                if p.tricks_won >= p.call + 1 or p.tricks_won < p.call: p.total_score -= p.call
                else: p.total_score += p.call
            else:
                if p.tricks_won >= p.call + 2 or p.tricks_won < p.call: p.total_score -= p.call
                else: p.total_score += p.call + (max(0, p.tricks_won - p.call) * 0.1)

    def get_room_state(self, for_sid):
        return {
            'room_id': self.room_id,
            'game_type': self.game_type,
            'in_progress': self.in_progress,
            'phase': self.phase,
            'round_number': self.round_number,
            'current_turn_sid': self.player_order[self.current_turn_idx] if self.in_progress else None,
            'players': [{'name': p.name, 'avatar': p.avatar, 'call': p.call, 'tricks': p.tricks_won, 'score': p.total_score, 'hand': [c.to_dict() for c in p.hand] if p.sid == for_sid else []} for p in self.players.values()],
            'last_hand_summary': self.last_hand_summary
        }
