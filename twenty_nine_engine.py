import random

class Card29:
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit

    def to_dict(self):
        return {'rank': self.rank, 'suit': self.suit}

    def get_points(self):
        return {'J': 3, '9': 2, 'A': 1, '10': 1}.get(self.rank, 0)

    def get_rank_value(self):
        return ['7', '8', 'Q', 'K', '10', 'A', '9', 'J'].index(self.rank)

class Player29:
    def __init__(self, sid, session_id, name, avatar="😎", is_host=False, team=1):
        self.sid = sid
        self.session_id = session_id
        self.name = name
        self.avatar = avatar
        self.is_host = is_host
        self.team = team
        self.hand = []

class TwentyNineRoom:
    def __init__(self, room_id, host_sid, host_session_id, host_name="Host Admin", host_avatar="👑"):
        self.room_id = room_id
        self.game_type = "twenty_nine"
        self.host_sid = host_sid
        self.host_session_id = host_session_id
        
        self.players = {}
        self.player_order = []
        self.session_map = {}
        
        self.in_progress = False
        self.phase = 'BIDDING'
        self.highest_bid = 16
        self.bidder_sid = None
        self.bidding_team = None
        self.trump_suit = None
        self.trump_revealed = False
        self.is_7th_card_trump = False
        self.team_scores = {1: 0, 2: 0}
        self.round_card_points = {1: 0, 2: 0}
        self.current_turn_idx = 0
        self.current_trick = []
        self.last_hand_summary = "Waiting for 29 Card Game players (4 required)..."

        self.add_player(host_sid, host_session_id, host_name, host_avatar, is_host=True)

    def add_player(self, sid, session_id, name, avatar="😎", is_host=False):
        if len(self.player_order) >= 4: return False, "Table full."
        team = 1 if len(self.player_order) % 2 == 0 else 2
        p = Player29(sid, session_id, name, avatar, is_host, team)
        self.players[sid] = p
        self.player_order.append(sid)
        return True, "Joined."

    def start_game(self):
        if len(self.player_order) != 4: return False, "4 players required."
        self.in_progress = True
        self.start_round()
        return True, "Started."

    def start_round(self):
        deck = [Card29(r, s) for r in ['J', '9', 'A', '10', 'K', 'Q', '8', '7'] for s in ['S', 'H', 'D', 'C']]
        random.shuffle(deck)
        for p in self.players.values(): p.hand = [deck.pop() for _ in range(8)]
        self.phase = 'BIDDING'
        self.highest_bid = 16
        self.bidder_sid = None
        self.trump_suit = None
        self.trump_revealed = False

    def reveal_trump(self, setter_sid, suit, is_7th=False):
        self.trump_suit = suit
        self.trump_revealed = True
        if is_7th:
            setter = self.players[setter_sid]
            if not any(c.suit == suit and c.rank in ['J', '9', 'A', '10'] for c in setter.hand):
                self.start_round() # Void hand and redeal
                return False

    def get_room_state(self, for_sid):
        return {
            'room_id': self.room_id, 'game_type': self.game_type, 'in_progress': self.in_progress, 'phase': self.phase,
            'highest_bid': self.highest_bid, 'team_scores': self.team_scores,
            'players': [{'name': p.name, 'team': p.team, 'hand': [c.to_dict() for c in p.hand] if p.sid == for_sid else []} for p in self.players.values()],
            'last_hand_summary': self.last_hand_summary
        }
