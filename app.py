import os
import uuid
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
from poker_engine import GameRoom as PokerRoom
from callbridge_engine import CallBridgeRoom
from twenty_nine_engine import TwentyNineRoom

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'casino-lounge-secret-456')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

rooms = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/game/<game_type>')
def render_game_room(game_type):
    if game_type == 'texas_holdem':
        return render_template('poker.html')
    elif game_type == 'call_bridge':
        return render_template('callbridge.html')
    elif game_type == 'twenty_nine':
        return render_template('twentynine.html')
    return render_template('index.html')

@socketio.on('create_room')
def handle_create_room(data):
    room_id = data.get('room_id', '').strip().upper()
    game_type = data.get('game_type', 'texas_holdem')
    host_name = data.get('host_name', 'Host Admin').strip()
    host_avatar = data.get('avatar', '👑')
    session_id = data.get('session_id') or str(uuid.uuid4())

    if not room_id or room_id in rooms:
        emit('error', {'message': 'Invalid or existing room code.'})
        return

    if game_type == 'call_bridge':
        room = CallBridgeRoom(room_id, request.sid, session_id, host_name, host_avatar)
    elif game_type == 'twenty_nine':
        room = TwentyNineRoom(room_id, request.sid, session_id, host_name, host_avatar)
    else:
        room = PokerRoom(room_id, request.sid, session_id, host_is_playing=True, host_name=host_name, host_avatar=host_avatar)

    rooms[room_id] = room
    join_room(room_id)
    emit('room_created', {'room_id': room_id, 'game_type': game_type, 'session_id': session_id})

@socketio.on('join_room_request')
def handle_join_request(data):
    room_id = data.get('room_id', '').strip().upper()
    name = data.get('player_name', 'Player').strip()
    avatar = data.get('avatar', '😎')
    session_id = data.get('session_id') or str(uuid.uuid4())

    if room_id not in rooms:
        emit('error', {'message': 'Room not found.'})
        return

    room = rooms[room_id]
    if isinstance(room, PokerRoom):
        room.pending_joins.append({'sid': request.sid, 'session_id': session_id, 'name': name, 'avatar': avatar, 'buy_in': 1000.0})
        emit('join_pending', {'message': 'Request sent to host.'})
    else:
        success, msg = room.add_player(request.sid, session_id, name, avatar)
        if not success:
            emit('error', {'message': msg})
            return
        join_room(room_id)
        emit('join_approved', {'room_id': room_id, 'game_type': room.game_type})
    broadcast_room_state(room_id)

@socketio.on('reject_join')
def handle_reject_join(data):
    room_id = data.get('room_id', '').strip().upper()
    target_sid = data.get('sid')
    if room_id in rooms and isinstance(rooms[room_id], PokerRoom):
        room = rooms[room_id]
        if request.sid == room.host_sid:
            room.pending_joins = [p for p in room.pending_joins if p['sid'] != target_sid]
            socketio.emit('kicked', {'message': 'Host rejected your join request.'}, to=target_sid)
            broadcast_room_state(room_id)

@socketio.on('reject_add_cash')
def handle_reject_add_cash(data):
    room_id = data.get('room_id', '').strip().upper()
    target_sid = data.get('sid')
    if room_id in rooms and isinstance(rooms[room_id], PokerRoom):
        room = rooms[room_id]
        if request.sid == room.host_sid:
            room.pending_add_cash = [c for c in room.pending_add_cash if c['sid'] != target_sid]
            socketio.emit('notification', {'title': 'Rejected', 'message': 'Host rejected your cash top-up.'}, to=target_sid)
            broadcast_room_state(room_id)

@socketio.on('player_action')
def handle_player_action(data):
    room_id = data.get('room_id', '').strip().upper()
    if room_id in rooms and isinstance(rooms[room_id], PokerRoom):
        room = rooms[room_id]
        success, msg, _ = room.process_action(request.sid, data.get('action'), float(data.get('amount', 0)))
        if not success: emit('error', {'message': msg})
        broadcast_room_state(room_id)

def broadcast_room_state(room_id):
    if room_id not in rooms: return
    room = rooms[room_id]
    for sid in list(room.players.keys()) + [getattr(room, 'host_sid', None)]:
        if sid:
            state = room.get_room_state(sid) if hasattr(room, 'get_room_state') else {'room_id': room.room_id}
            socketio.emit('game_state', state, to=sid)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
