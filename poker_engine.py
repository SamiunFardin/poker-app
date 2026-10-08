import random
from treys import Card, Evaluator

evaluator = Evaluator()

class CardModel:
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit

    def to_dict(self):
        return {'rank': self.rank, 'suit': self.suit}

    def to_treys_str(self):
        r = self.rank if self.rank != '10' else 'T'
        s = self.suit.lower()
        return f"{r}{s}"

class Player:
    def __init__(self, sid, session_id, name, chips, avatar="😎", is_host=False):
        self.sid = sid
        self.session_id = session_id
        self.name = name
        self.avatar = avatar
        self.is_host = is_host
        self.initial_buy_in = float(chips)
        self.added_cash = 0.0
        self.chips = float(chips)
        self.current_bet = 0.0
        self.total_invested = 0.0
        self.folded = False
        self.acted_this_street = False
        self.hole_cards = []

    def get_net_pl(self):
        total_in = self.initial_buy_in + self.added_cash
        return self.chips - total_in

class GameRoom:
    def __init__(self, room_id, host_sid, host_session_id, sb=10, bb=20, host_is_playing=False, host_name="Host Admin", host_buyin=1000, host_avatar="👑"):
        self.room_id = room_id
        self.host_sid = host_sid
        self.host_session_id = host_session_id
        self.host_is_playing = host_is_playing
        self.sb = float(sb)
        self.bb = float(bb)
        
        self.players = {}             # sid -> Player
        self.player_order = []        # list of sids
        self.session_map = {}         # session_id -> Player
        self.pending_joins = []
        self.pending_add_cash = []
        self.left_players_history = []
        
        self.in_progress = False
        self.pot = 0.0
        self.highest_bet = 0.0
        self.street = 'PREFLOP'
        self.community_cards = []
        self.current_turn_idx = 0
        self.dealer_idx = 0
        self.dealer_sid = None
        self.sb_sid = None
        self.bb_sid = None
        self.winning_cards = []
        self.deck = []
        self.last_hand_summary = "No hands played yet."

        if self.host_is_playing:
            self.add_player(host_sid, host_session_id, host_name, host_buyin, host_avatar, is_host=True)

    def add_player(self, sid, session_id, name, chips, avatar="😎", is_host=False):
        player = Player(sid, session_id, name, chips, avatar, is_host=is_host)
        self.players[sid] = player
        self.session_map[session_id] = player
        if sid not in self.player_order:
            self.player_order.append(sid)

    def rebind_socket(self, old_sid, new_sid, session_id):
        if session_id in self.session_map:
            p = self.session_map[session_id]
            old_p_sid = p.sid
            if old_p_sid in self.players:
                del self.players[old_p_sid]
            p.sid = new_sid
            self.players[new_sid] = p
            
            if old_p_sid in self.player_order:
                idx = self.player_order.index(old_p_sid)
                self.player_order[idx] = new_sid
            elif new_sid not in self.player_order:
                self.player_order.append(new_sid)
            return True
        return False

    def remove_player(self, sid, reason="Left Game"):
        if sid in self.players:
            p = self.players[sid]
            self.left_players_history.append({
                'name': p.name,
                'initial_buy_in': p.initial_buy_in,
                'added_cash': p.added_cash,
                'final_chips': p.chips,
                'net_pl': p.get_net_pl(),
                'reason': reason
            })
            if p.session_id in self.session_map:
                del self.session_map[p.session_id]
            del self.players[sid]
            if sid in self.player_order:
                self.player_order.remove(sid)
            
            self.pending_joins = [j for j in self.pending_joins if j['sid'] != sid]
            self.pending_add_cash = [c for c in self.pending_add_cash if c['sid'] != sid]

            if len([p for p in self.players.values() if not p.folded]) < 2 and self.in_progress:
                self.discontinue_hand("Not enough players left in hand.")

    def get_ledger_summary(self):
        summary = []
        for p in self.players.values():
            summary.append({
                'name': p.name,
                'avatar': p.avatar,
                'initial_buy_in': p.initial_buy_in,
                'added_cash': p.added_cash,
                'total_in': p.initial_buy_in + p.added_cash,
                'chips': p.chips,
                'net_pl': p.get_net_pl(),
                'status': 'Active'
            })
        for item in self.left_players_history:
            summary.append({
                'name': item['name'],
                'avatar': '🚪',
                'initial_buy_in': item['initial_buy_in'],
                'added_cash': item['added_cash'],
                'total_in': item['initial_buy_in'] + item['added_cash'],
                'chips': item['final_chips'],
                'net_pl': item['net_pl'],
                'status': f"Left ({item['reason']})"
            })
        return summary

    def start_hand(self):
        active_players = [p for p in self.players.values() if p.chips > 0]
        if len(active_players) < 2:
            return False, "At least 2 players with chips are required to start."

        self.in_progress = True
        self.pot = 0.0
        self.highest_bet = 0.0
        self.street = 'PREFLOP'
        self.community_cards = []
        self.winning_cards = []

        for p in self.players.values():
            p.current_bet = 0.0
            p.total_invested = 0.0
            p.folded = False if p.chips > 0 else True
            p.acted_this_street = False
            p.hole_cards = []

        self.dealer_idx = (self.dealer_idx + 1) % len(self.player_order)
        self.dealer_sid = self.player_order[self.dealer_idx]

        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        suits = ['S', 'H', 'D', 'C']
        self.deck = [CardModel(r, s) for r in ranks for s in suits]
        random.shuffle(self.deck)

        for p_sid in self.player_order:
            if p_sid in self.players and not self.players[p_sid].folded:
                self.players[p_sid].hole_cards = [self.deck.pop(), self.deck.pop()]

        n = len(self.player_order)
        sb_idx = (self.dealer_idx + 1) % n
        bb_idx = (self.dealer_idx + 2) % n if n > 2 else sb_idx

        self.sb_sid = self.player_order[sb_idx]
        self.bb_sid = self.player_order[bb_idx]

        sb_player = self.players[self.sb_sid]
        bb_player = self.players[self.bb_sid]

        sb_amt = min(self.sb, sb_player.chips)
        bb_amt = min(self.bb, bb_player.chips)

        sb_player.chips -= sb_amt
        sb_player.current_bet = sb_amt
        sb_player.total_invested += sb_amt

        bb_player.chips -= bb_amt
        bb_player.current_bet = bb_amt
        bb_player.total_invested += bb_amt

        self.pot = sb_amt + bb_amt
        self.highest_bet = bb_amt

        self.current_turn_idx = (bb_idx + 1) % n
        self.ensure_active_turn()
        return True, "Hand started successfully."

    def ensure_active_turn(self):
        n = len(self.player_order)
        if n == 0:
            return
        attempts = 0
        while attempts < n:
            current_sid = self.player_order[self.current_turn_idx]
            p = self.players.get(current_sid)
            if p and not p.folded and p.chips > 0:
                break
            self.current_turn_idx = (self.current_turn_idx + 1) % n
            attempts += 1

    def discontinue_hand(self, reason="Hand discontinued by Host."):
        if not self.in_progress:
            return
        for p in self.players.values():
            p.chips += p.current_bet
            p.current_bet = 0.0
            p.folded = False
            p.hole_cards = []
        self.in_progress = False
        self.pot = 0.0
        self.street = 'PREFLOP'
        self.community_cards = []
        self.winning_cards = []
        self.last_hand_summary = f"Hand Discontinued: {reason}"

    def process_action(self, sid, action, amount=0.0):
        if not self.in_progress:
            return False, "No active hand.", None

        current_sid = self.player_order[self.current_turn_idx]
        if sid != current_sid:
            return False, "Not your turn.", None

        player = self.players[sid]
        player.acted_this_street = True

        if action == 'fold':
            player.folded = True
        elif action == 'check':
            if player.current_bet < self.highest_bet:
                return False, f"Cannot check. Call amount is ${self.highest_bet - player.current_bet:.2f}", None
        elif action == 'call':
            call_amt = self.highest_bet - player.current_bet
            actual_call = min(call_amt, player.chips)
            player.chips -= actual_call
            player.current_bet += actual_call
            player.total_invested += actual_call
            self.pot += actual_call
        elif action == 'raise':
            if amount <= self.highest_bet:
                return False, f"Raise target must exceed current bet of ${self.highest_bet:.2f}", None
            needed = amount - player.current_bet
            if needed > player.chips:
                return False, "Insufficient chips for raise.", None
            player.chips -= needed
            player.current_bet += needed
            player.total_invested += needed
            self.pot += needed
            self.highest_bet = amount
            for p_sid, p in self.players.items():
                if p_sid != sid and not p.folded:
                    p.acted_this_street = False

        active_unfolded = [p for p in self.players.values() if not p.folded]
        if len(active_unfolded) == 1:
            winner = active_unfolded[0]
            winner.chips += self.pot
            summary = f"🏆 Winner: {winner.name}\n💰 Amount Won: ${self.pot:.2f}\nReason: All other players folded."
            self.last_hand_summary = summary
            self.in_progress = False
            return True, "Hand ended by fold.", {'type': 'hand_ended', 'summary': summary}

        event_notice = self.advance_turn()
        return True, "Action processed.", event_notice

    def advance_turn(self):
        active_players = [p for p in self.players.values() if not p.folded and p.chips > 0]
        bets_equal = len(set(p.current_bet for p in active_players)) <= 1
        all_acted = all(p.acted_this_street for p in active_players)

        if bets_equal and all_acted:
            return self.next_street()
        else:
            n = len(self.player_order)
            self.current_turn_idx = (self.current_turn_idx + 1) % n
            self.ensure_active_turn()
            return None

    def next_street(self):
        for p in self.players.values():
            p.current_bet = 0.0
            p.acted_this_street = False
        self.highest_bet = 0.0

        event_notice = None

        if self.street == 'PREFLOP':
            self.street = 'FLOP'
            new_cards = [self.deck.pop(), self.deck.pop(), self.deck.pop()]
            self.community_cards.extend(new_cards)
            card_str = ", ".join([f"{c.rank}{c.suit}" for c in new_cards])
            event_notice = {'type': 'community_cards', 'title': 'Flop Revealed!', 'cards': card_str}
        elif self.street == 'FLOP':
            self.street = 'TURN'
            new_card = self.deck.pop()
            self.community_cards.append(new_card)
            card_str = f"{new_card.rank}{new_card.suit}"
            event_notice = {'type': 'community_cards', 'title': 'Turn Revealed!', 'cards': card_str}
        elif self.street == 'TURN':
            self.street = 'RIVER'
            new_card = self.deck.pop()
            self.community_cards.append(new_card)
            card_str = f"{new_card.rank}{new_card.suit}"
            event_notice = {'type': 'community_cards', 'title': 'River Revealed!', 'cards': card_str}
        elif self.street == 'RIVER':
            self.street = 'SHOWDOWN'
            summary = self.evaluate_showdown()
            return {'type': 'hand_ended', 'summary': summary}

        self.current_turn_idx = (self.dealer_idx + 1) % len(self.player_order)
        self.ensure_active_turn()
        return event_notice

    def evaluate_showdown(self):
        self.in_progress = False
        active_players = [p for p in self.players.values() if not p.folded]
        
        if not active_players:
            summary = "Hand ended with no active players."
            self.last_hand_summary = summary
            return summary

        board_treys = [Card.new(c.to_treys_str()) for c in self.community_cards]
        best_score = 99999
        winners = []
        summary_lines = []

        for p in active_players:
            hand_treys = [Card.new(c.to_treys_str()) for c in p.hole_cards]
            score = evaluator.evaluate(board_treys, hand_treys)
            rank_class = evaluator.get_rank_class(score)
            class_str = evaluator.class_to_string(rank_class)
            summary_lines.append(f"• {p.name}: {class_str}")

            if score < best_score:
                best_score = score
                winners = [p]
            elif score == best_score:
                winners.append(p)

        split_pot = self.pot / len(winners)
        winner_names = ", ".join(w.name for w in winners)
        for w in winners:
            w.chips += split_pot

        self.winning_cards = []
        for w in winners:
            for c in w.hole_cards:
                self.winning_cards.append(c.to_dict())

        final_summary = f"🏆 WINNER: {winner_names}\n💰 POT WON: ${self.pot:.2f}\n\nEVALUATION:\n" + "\n".join(summary_lines)
        self.last_hand_summary = final_summary
        return final_summary
