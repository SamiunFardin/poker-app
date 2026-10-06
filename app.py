import time

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from poker_engine import GameRoom

app = Flask(__name__)
app.config['SECRET_KEY'] = 'poker-secret-key-render'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

rooms = {}  # room_id -> GameRoom

def start_turn_timer(room_id):
    room = rooms.get(room_id)
    if not room or not room.in_progress or room.current_turn_idx == -1:
        return

    room.timer_end_time = time.time() + 120  # 2 minute timer
    
    def timer_task():
        time.sleep(120)
        current_room = rooms.get(room_id)
        if current_room and current_room.in_progress:
            # Auto Fold if turn hasn't changed
            p_keys = list(current_room.players.keys())
            if current_room.current_turn_idx < len(p_keys):
                acting_sid = p_keys[current_room.current_turn_idx]
                current_room.process_action(acting_sid, 'fold')
                broadcast_game_state(room_id, "Player timed out and automatically folded.")

    socketio.start_background_task(timer_task)

def broadcast_game_state(room_id, notification=""):
    room = rooms.get(room_id)
    if not room:
        return

    # Broadcast specialized payload to each client (safeguards hole cards)
    for sid, p in room.players.items():
        state = {
            'room_id': room.room_id,
            'is_host': (sid == room.host_sid),
            'in_progress': room.in_progress,
            'street': room.street,
            'pot': room.pot,
            'community_cards': [c.to_dict() for c in room.community_cards],
            'highest_bet': room.highest_bet,
            'current_turn_sid': list(room.players.keys())[room.current_turn_idx] if room.in_progress and room.current_turn_idx != -1 else None,
            'players': [pl.to_dict(show_cards=(pl.sid == sid or not room.in_progress)) for pl in room.players.values()],
            'pending_joins': room.pending_joins if sid == room.host_sid else [],
            'pending_add_cash': room.pending_add_cash if sid == room.host_sid else [],
            'history_log': room.history_log,
            'notification': notification
        }
        socketio.emit('game_state_update', state, room=sid)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('create_room')
def on_create_room(data):
    room_id = str(data.get('room_id')).upper().strip()
    sb = float(data.get('sb', 10))
    bb = float(data.get('bb', 20))
    
    rooms[room_id] = GameRoom(room_id, request.sid, sb, bb)
    join_room(room_id)
    emit('room_created', {'room_id': room_id})

@socketio.on('request_join')
def on_request_join(data):
    room_id = str(data.get('room_id')).upper().strip()
    name = data.get('name')
    buyin = float(data.get('buyin'))

    room = rooms.get(room_id)
    if not room:
        emit('error_msg', {'message': 'Room not found.'})
        return

    join_req = {'sid': request.sid, 'name': name, 'buyin': buyin}
    room.pending_joins.append(join_req)
    join_room(room_id)
    
    emit('join_requested', {'message': 'Join request submitted to host.'})
    broadcast_game_state(room_id, f"New join request from {name}")

@socketio.on('host_respond_join')
def on_host_respond_join(data):
    room_id = data.get('room_id')
    target_sid = data.get('target_sid')
    approve = data.get('approve')

    room = rooms.get(room_id)
    if room and request.sid == room.host_sid:
        req = next((r for r in room.pending_joins if r['sid'] == target_sid), None)
        if req:
            room.pending_joins.remove(req)
            if approve:
                room.add_player(req['sid'], req['name'], req['buyin'])
                broadcast_game_state(room_id, f"{req['name']} joined the table.")
            else:
                broadcast_game_state(room_id, f"Join request for {req['name']} rejected.")

@socketio.on('start_hand')
def on_start_hand(data):
    room_id = data.get('room_id')
    room = rooms.get(room_id)
    if room and request.sid == room.host_sid:
        success, msg = room.start_hand()
        if success:
            start_turn_timer(room_id)
            broadcast_game_state(room_id, "New Hand Started!")
        else:
            emit('error_msg', {'message': msg})

@socketio.on('discontinue_hand')
def on_discontinue_hand(data):
    room_id = data.get('room_id')
    room = rooms.get(room_id)
    if room and request.sid == room.host_sid:
        room.discontinue_hand()
        broadcast_game_state(room_id, "Hand Discontinued by Host. Bets refunded.")

@socketio.on('player_action')
def on_player_action(data):
    room_id = data.get('room_id')
    action_type = data.get('action')
    amount = float(data.get('amount', 0.0))

    room = rooms.get(room_id)
    if room:
        prev_street = room.street
        success, msg = room.process_action(request.sid, action_type, amount)
        if success:
            if room.street != prev_street and room.in_progress:
                broadcast_game_state(room_id, f"Community cards revealed! Current street: {room.street}")
            else:
                broadcast_game_state(room_id)
            
            if room.in_progress:
                start_turn_timer(room_id)
            else:
                # Hand concluded
                res = room.evaluate_showdown() if len([p for p in room.players.values() if not p.folded]) > 1 else None
                summary = "Hand Complete!"
                if res:
                    summary = " ".join([f"{w['name']} won ${w['amount']} ({w['desc']})" for w in res['winners']])
                broadcast_game_state(room_id, summary)
        else:
            emit('error_msg', {'message': msg})

@socketio.on('kick_player')
def on_kick_player(data):
    room_id = data.get('room_id')
    target_sid = data.get('target_sid')
    room = rooms.get(room_id)
    if room and request.sid == room.host_sid:
        kicked = room.remove_player(target_sid, reason="kicked by host")
        if kicked:
            broadcast_game_state(room_id, f"{kicked.name} was kicked from the game.")

@socketio.on('end_game')
def on_end_game(data):
    room_id = data.get('room_id')
    room = rooms.get(room_id)
    if room and request.sid == room.host_sid:
        socketio.emit('game_ended_summary', {
            'players': [p.to_dict(show_cards=False) for p in room.players.values()],
            'history': room.history_log
        }, room=room_id)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)