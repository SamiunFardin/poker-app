import os
import uuid
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from poker_engine import GameRoom

app = Flask(__name__)
app.config['SECRET_KEY'] = 'poker-secret-key-123'

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

rooms = {}

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('create_room')
def handle_create_room(data):
    room_id = data.get('room_id', '').strip().upper()
    host_name = data.get('host_name', 'Host Admin').strip()
    host_is_playing = bool(data.get('host_is_playing', False))
    host_buyin = float(data.get('host_buyin', 1000.0))
    sb = float(data.get('sb', 10))
    bb = float(data.get('bb', 20))
    session_id = data.get('session_id') or str(uuid.uuid4())

    if not room_id:
        emit('error', {'message': 'Room code required.'})
        return

    if room_id in rooms:
        emit('error', {'message': f'Room code "{room_id}" already exists.'})
        return

    room = GameRoom(room_id, request.sid, session_id, sb, bb, host_is_playing, host_name, host_buyin)
    rooms[room_id] = room

    join_room(room_id)
    emit('room_created', {'room_id': room_id, 'is_host': True, 'session_id': session_id, 'host_is_playing': host_is_playing})
    broadcast_room_state(room_id)

@socketio.on('reconnect_session')
def handle_reconnect(data):
    room_id = data.get('room_id', '').strip().upper()
    session_id = data.get('session_id')

    if room_id not in rooms or not session_id:
        emit('session_restored', {'success': False})
        return

    room = rooms[room_id]
    join_room(room_id)

    if session_id == room.host_session_id:
        room.host_sid = request.sid
        if room.host_is_playing:
            room.rebind_socket(None, request.sid, session_id)
        emit('session_restored', {'success': True, 'is_host': True, 'room_id': room_id, 'session_id': session_id})
    elif room.rebind_socket(None, request.sid, session_id):
        emit('session_restored', {'success': True, 'is_host': False, 'room_id': room_id, 'session_id': session_id})
    else:
        emit('session_restored', {'success': False})
        return

    broadcast_room_state(room_id)

@socketio.on('close_room_by_host')
def handle_close_room(data):
    room_id = data.get('room_id', '').strip().upper()
    if room_id not in rooms:
        return
    room = rooms[room_id]

    if request.sid == room.host_sid:
        ledger = room.get_ledger_summary()
        # Broadcast final ledger popup & force exit to all room members
        socketio.emit('room_closed', {
            'message': 'The Host has closed the table and ended the game.',
            'ledger': ledger
        }, to=room_id)
        del rooms[room_id]

@socketio.on('join_room_request')
def handle_join_request(data):
    room_id = data.get('room_id', '').strip().upper()
    player_name = data.get('player_name', 'Player').strip()
    buy_in = float(data.get('buy_in', 1000.0))
    session_id = data.get('session_id') or str(uuid.uuid4())

    if room_id not in rooms:
        emit('error', {'message': f'Room "{room_id}" not found.'})
        return

    room = rooms[room_id]

    already_pending = any(p['session_id'] == session_id for p in room.pending_joins)
    already_in_game = session_id in room.session_map

    if not already_pending and not already_in_game:
        room.pending_joins.append({
            'sid': request.sid,
            'session_id': session_id,
            'name': player_name,
            'buy_in': buy_in
        })

    emit('join_pending', {'message': 'Join request sent to Host for approval.', 'session_id': session_id})
    broadcast_room_state(room_id)

@socketio.on('approve_join')
def handle_approve_join(data):
    room_id = data.get('room_id', '').strip().upper()
    target_sid = data.get('sid')

    if room_id not in rooms:
        return
    room = rooms[room_id]

    if request.sid != room.host_sid:
        return

    pending = next((p for p in room.pending_joins if p['sid'] == target_sid), None)
    if pending:
        room.add_player(pending['sid'], pending['session_id'], pending['name'], pending['buy_in'])
        room.pending_joins.remove(pending)
        
        socketio.emit('join_approved', {'room_id': room_id}, to=target_sid)
        broadcast_room_state(room_id)

@socketio.on('leave_game')
def handle_leave_game(data):
    room_id = data.get('room_id', '').strip().upper()
    if room_id in rooms:
        room = rooms[room_id]
        if request.sid == room.host_sid:
            # If host leaves voluntarily, trigger room close flow
            handle_close_room(data)
        else:
            room.remove_player(request.sid, reason="Player Left Voluntarily")
            emit('game_left', {'message': 'You have left the game.'})
            broadcast_room_state(room_id)

@socketio.on('kick_player')
def handle_kick_player(data):
    room_id = data.get('room_id', '').strip().upper()
    target_sid = data.get('target_sid')

    if room_id not in rooms:
        return
    room = rooms[room_id]

    if request.sid == room.host_sid and target_sid in room.players:
        room.remove_player(target_sid, reason="Kicked by Host")
        socketio.emit('kicked', {'message': 'You were kicked by the host.'}, to=target_sid)
        broadcast_room_state(room_id)

@socketio.on('discontinue_hand')
def handle_discontinue_hand(data):
    room_id = data.get('room_id', '').strip().upper()
    if room_id not in rooms:
        return
    room = rooms[room_id]

    if request.sid == room.host_sid:
        room.discontinue_hand("Host manually discontinued the hand.")
        socketio.emit('notification', {'title': 'Hand Stopped', 'message': 'Host discontinued current hand.'}, to=room_id)
        broadcast_room_state(room_id)

@socketio.on('request_add_cash')
def handle_request_add_cash(data):
    room_id = data.get('room_id', '').strip().upper()
    amount = float(data.get('amount', 0.0))

    if room_id not in rooms or amount <= 0:
        return

    room = rooms[room_id]
    if request.sid in room.players:
        player_name = room.players[request.sid].name
        room.pending_add_cash.append({
            'sid': request.sid,
            'name': player_name,
            'amount': amount
        })
        emit('notification', {'title': 'Request Sent', 'message': f'Requested ${amount} cash top-up.'})
        broadcast_room_state(room_id)

@socketio.on('approve_add_cash')
def handle_approve_add_cash(data):
    room_id = data.get('room_id', '').strip().upper()
    target_sid = data.get('sid')
    amount = float(data.get('amount', 0.0))

    if room_id not in rooms:
        return
    room = rooms[room_id]

    if request.sid != room.host_sid:
        return

    req = next((c for c in room.pending_add_cash if c['sid'] == target_sid and c['amount'] == amount), None)
    if req:
        if target_sid in room.players:
            p = room.players[target_sid]
            p.chips += amount
            p.added_cash += amount
        room.pending_add_cash.remove(req)
        socketio.emit('notification', {'title': 'Chips Added', 'message': f'Host approved ${amount} chips!'}, to=target_sid)
        broadcast_room_state(room_id)

@socketio.on('start_hand')
def handle_start_hand(data):
    room_id = data.get('room_id', '').strip().upper()
    if room_id not in rooms:
        return
    room = rooms[room_id]

    if request.sid != room.host_sid:
        return

    success, msg = room.start_hand()
    if not success:
        emit('error', {'message': msg})
        return

    socketio.emit('notification', {'title': 'New Hand', 'message': 'Hand started! Cards dealt.'}, to=room_id)
    broadcast_room_state(room_id)

@socketio.on('player_action')
def handle_player_action(data):
    room_id = data.get('room_id', '').strip().upper()
    action = data.get('action')
    amount = float(data.get('amount', 0.0))

    if room_id not in rooms:
        return
    room = rooms[room_id]

    success, msg, event_notice = room.process_action(request.sid, action, amount)
    if not success:
        emit('error', {'message': msg})
        return

    broadcast_room_state(room_id)

    if event_notice:
        if event_notice['type'] == 'community_cards':
            socketio.emit('notification', {'title': event_notice['title'], 'message': f"Community Cards Revealed: {event_notice['cards']}"}, to=room_id)
        elif event_notice['type'] == 'hand_ended':
            socketio.emit('notification', {'title': 'Hand Completed', 'message': event_notice['summary']}, to=room_id)

def broadcast_room_state(room_id):
    if room_id not in rooms:
        return
    room = rooms[room_id]

    active_turn_sid = None
    if room.in_progress and 0 <= room.current_turn_idx < len(room.player_order):
        active_turn_sid = room.player_order[room.current_turn_idx]

    recipients = set(list(room.players.keys()) + [room.host_sid] + [p['sid'] for p in room.pending_joins])

    ledger_summary = room.get_ledger_summary()

    for sid in recipients:
        is_host = (sid == room.host_sid)
        players_data = []
        
        for p_sid in room.player_order:
            if p_sid in room.players:
                p = room.players[p_sid]
                show_cards = (p.sid == sid or room.street == 'SHOWDOWN')
                players_data.append({
                    'sid': p.sid,
                    'name': p.name,
                    'chips': p.chips,
                    'current_bet': p.current_bet,
                    'folded': getattr(p, 'folded', False),
                    'is_dealer': (p_sid == getattr(room, 'dealer_sid', None)),
                    'hole_cards': [c.to_dict() for c in p.hole_cards] if show_cards and hasattr(p, 'hole_cards') else []
                })

        state = {
            'room_id': room.room_id,
            'is_host': is_host,
            'in_progress': room.in_progress,
            'street': room.street,
            'pot': room.pot,
            'highest_bet': room.highest_bet,
            'community_cards': [c.to_dict() for c in room.community_cards] if hasattr(room, 'community_cards') else [],
            'current_turn_sid': active_turn_sid,
            'players': players_data,
            'last_hand_summary': room.last_hand_summary,
            'pending_joins': getattr(room, 'pending_joins', []),
            'pending_add_cash': getattr(room, 'pending_add_cash', []),
            'ledger_summary': ledger_summary
        }
        socketio.emit('game_state', state, to=sid)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
