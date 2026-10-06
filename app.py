import os
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from poker_engine import GameRoom

app = Flask(__name__)
app.config['SECRET_KEY'] = 'poker-secret-key-123'

# Standard threading mode avoids C-extension dependencies on Render
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

rooms = {}  # room_id -> GameRoom instance

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('create_room')
def handle_create_room(data):
    room_id = data.get('room_id', '').strip().upper()
    host_name = data.get('host_name', 'Host').strip()
    sb = float(data.get('sb', 10))
    bb = float(data.get('bb', 20))

    if not room_id:
        emit('error', {'message': 'Room code cannot be empty.'})
        return

    if room_id in rooms:
        emit('error', {'message': 'Room already exists.'})
        return

    room = GameRoom(room_id, request.sid, sb, bb)
    room.add_player(request.sid, host_name, 1000.0)  # Default starting chips
    rooms[room_id] = room

    join_room(room_id)
    emit('room_created', {'room_id': room_id, 'is_host': True})
    broadcast_room_state(room_id)

@socketio.on('join_room_request')
def handle_join_request(data):
    room_id = data.get('room_id', '').strip().upper()
    player_name = data.get('player_name', 'Player').strip()
    buy_in = float(data.get('buy_in', 1000.0))

    if room_id not in rooms:
        emit('error', {'message': 'Room not found.'})
        return

    room = rooms[room_id]
    join_room(room_id)

    # Add player to pending joins for host approval
    room.pending_joins.append({
        'sid': request.sid,
        'name': player_name,
        'buy_in': buy_in
    })

    socketio.emit('pending_requests_update', {
        'pending_joins': room.pending_joins,
        'pending_add_cash': room.pending_add_cash
    }, to=room.host_sid)

    emit('join_pending', {'message': 'Waiting for host approval...'})

@socketio.on('approve_join')
def handle_approve_join(data):
    room_id = data.get('room_id')
    target_sid = data.get('sid')

    if room_id not in rooms:
        return
    room = rooms[room_id]

    if request.sid != room.host_sid:
        return

    pending = next((p for p in room.pending_joins if p['sid'] == target_sid), None)
    if pending:
        room.add_player(pending['sid'], pending['name'], pending['buy_in'])
        room.pending_joins.remove(pending)

        socketio.emit('join_approved', {'room_id': room_id}, to=target_sid)
        broadcast_room_state(room_id)

@socketio.on('start_hand')
def handle_start_hand(data):
    room_id = data.get('room_id')
    if room_id not in rooms:
        return
    room = rooms[room_id]

    if request.sid != room.host_sid:
        return

    success, msg = room.start_hand()
    if not success:
        emit('error', {'message': msg})
        return

    broadcast_room_state(room_id)

@socketio.on('player_action')
def handle_player_action(data):
    room_id = data.get('room_id')
    action = data.get('action')
    amount = float(data.get('amount', 0.0))

    if room_id not in rooms:
        return
    room = rooms[room_id]

    success, msg = room.process_action(request.sid, action, amount)
    if not success:
        emit('error', {'message': msg})
        return

    broadcast_room_state(room_id)

def broadcast_room_state(room_id):
    if room_id not in rooms:
        return
    room = rooms[room_id]

    # Send tailored state to each connected client in the room
    for sid, player in room.players.items():
        state = {
            'room_id': room.room_id,
            'is_host': (sid == room.host_sid),
            'in_progress': room.in_progress,
            'street': room.street,
            'pot': room.pot,
            'highest_bet': room.highest_bet,
            'community_cards': [c.to_dict() for c in room.community_cards],
            'current_turn_sid': list(room.players.keys())[room.current_turn_idx] if room.in_progress and room.current_turn_idx >= 0 else None,
            'players': [p.to_dict(show_cards=(p.sid == sid or room.street == 'SHOWDOWN')) for p in room.players.values()]
        }
        socketio.emit('game_state', state, to=sid)

@socketio.on('disconnect')
def handle_disconnect():
    for room_id, room in list(rooms.items()):
        if request.sid in room.players:
            room.remove_player(request.sid, reason="disconnected")
            broadcast_room_state(room_id)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
