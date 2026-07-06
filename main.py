import os
from flask import Flask, render_template_string, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'roblox_web_ultra_secret_key_2026'

# Инициализируем сокеты с поддержкой aiohttp (работает на чистом Python без компиляции)
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='aiohttp'
)

# =====================================================================
#  БАЗА ДАННЫХ (Симуляция)
# =====================================================================
places_db = {
    "1": {
        "name": "Начальный Baseplate", 
        "objects": [
            {"type": "box", "x": 0, "y": 0.75, "z": -5, "color": 16711680},
            {"type": "sphere", "x": 3, "y": 0.75, "z": -3, "color": 65280}
        ]
    }
}

online_players = {}

# =====================================================================
#  HTTP МАРШРУТЫ
# =====================================================================

@app.route('/')
def index():
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except FileNotFoundError:
        return "Ошибка: Файл index.html не найден!", 404

@app.route('/api/places', methods=['GET'])
def get_places():
    return jsonify(places_db)

@app.route('/api/places', methods=['POST'])
def save_place():
    data = request.json or {}
    place_id = data.get('place_id')
    name = data.get('name', 'Безымянный плейс')
    objects = data.get('objects', [])

    if not place_id or place_id not in places_db:
        place_id = str(len(places_db) + 1)

    places_db[place_id] = {"name": name, "objects": objects}
    return jsonify({"success": True, "place_id": place_id})

# =====================================================================
#  WEBSOCKETS (Мультиплеер и Чат)
# =====================================================================

@socketio.on('join_place')
def handle_join(data):
    sid = request.sid
    username = data.get('username', f'Guest_{sid[:4]}').strip()
    place_id = str(data.get('place_id', '1'))

    if sid in online_players:
        old_place = online_players[sid]['place_id']
        leave_room(old_place)
        emit('player_left', {"id": sid}, to=old_place, skip_sid=sid)

    join_room(place_id)
    online_players[sid] = {"username": username, "place_id": place_id, "x": 0, "y": 1, "z": 0}

    emit('player_joined', {"id": sid, "username": username, "x": 0, "y": 1, "z": 0}, to=place_id, skip_sid=sid)

    room_players = {
        other_sid: p_info 
        for other_sid, p_info in online_players.items() 
        if p_info['place_id'] == place_id and other_sid != sid
    }
    emit('current_players', room_players)

@socketio.on('move')
def handle_move(data):
    sid = request.sid
    if sid in online_players:
        player = online_players[sid]
        player['x'] = data.get('x', 0)
        player['y'] = data.get('y', 1)
        player['z'] = data.get('z', 0)
        emit('player_moved', {"id": sid, "x": player['x'], "y": player['y'], "z": player['z']}, to=player['place_id'], skip_sid=sid)

@socketio.on('chat_message')
def handle_chat(data):
    sid = request.sid
    if sid in online_players:
        player = online_players[sid]
        msg_text = data.get('text', '').strip()
        if msg_text:
            emit('new_chat_message', {"msg": f"[{player['username']}]: {msg_text}"}, to=player['place_id'])

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in online_players:
        place_id = online_players[sid]['place_id']
        emit('player_left', {"id": sid}, to=place_id)
        del online_players[sid]

# =====================================================================
#  ЗАПУСК
# =====================================================================
if __name__ == '__main__':
    server_port = int(os.environ.get('PORT', 5000))
    # aiohttp запустится автоматически благодаря async_mode='aiohttp'
    socketio.run(app, host='0.0.0.0', port=server_port, debug=False)
