import os
from flask import Flask, render_template_string, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'roblox_clone_secret_key'
# Настройка CORS, чтобы Render не блокировал соединения
socketio = SocketIO(app, cors_allowed_origins="*")

# Симуляция базы данных (замени на вызовы своей БД, если нужно)
# Структура плейса: { id: { name: str, objects: list } }
places = {
    "1": {"name": "Spawn World", "objects": [{"type": "box", "x": 0, "y": 1, "z": -5, "color": 0xff0000}]}
}

# Активные игроки в комнатах: { session_id: { place_id: str, x: f, y: f, z: f } }
active_players = {}

@app.route('/')
def index():
    # Читаем твой index.html
    with open('index.html', 'r', encoding='utf-8') as f:
        return render_template_string(f.read())

# API для работы с плейсами
@app.route('/api/places', methods=['GET', 'POST'])
def handle_places():
    if request.method == 'POST':
        data = request.json
        place_id = str(len(places) + 1)
        places[place_id] = {
            "name": data.get("name", f"Place #{place_id}"),
            "objects": data.get("objects", [])
        }
        return jsonify({"success": True, "place_id": place_id})
    return jsonify(places)

# --- WebSockets для Мультиплеера и Чата ---

@socketio.on('join_place')
def on_join(data):
    username = data.get('username', 'Guest')
    place_id = str(data.get('place_id', '1'))
    
    join_room(place_id)
    
    # Сохраняем состояние игрока
    active_players[request.sid] = {
        "username": username,
        "place_id": place_id,
        "x": 0, "y": 1, "z": 0
    }
    
    # Оповещаем остальных в этом плейсе
    emit('player_joined', {"id": request.sid, "username": username, "x": 0, "y": 1, "z": 0}, to=place_id, skip_sid=request.sid)
    
    # Отправляем новому игроку список всех, кто уже в плейсе
    current_players = {sid: p for sid, p in active_players.items() if p['place_id'] == place_id and sid != request.sid}
    emit('current_players', current_players)

@socketio.on('move')
def on_move(data):
    sid = request.sid
    if sid in active_players:
        active_players[sid]['x'] = data['x']
        active_players[sid]['y'] = data['y']
        active_players[sid]['z'] = data['z']
        place_id = active_players[sid]['place_id']
        
        # Транслируем движение другим игрокам в этой комнате
        emit('player_moved', {"id": sid, "x": data['x'], "y": data['y'], "z": data['z']}, to=place_id, skip_sid=sid)

@socketio.on('chat_message')
def on_chat_message(data):
    sid = request.sid
    if sid in active_players:
        place_id = active_players[sid]['place_id']
        msg = f"{active_players[sid]['username']}: {data['text']}"
        emit('new_chat_message', {"msg": msg}, to=place_id)

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    if sid in active_players:
        place_id = active_players[sid]['place_id']
        emit('player_left', {"id": sid}, to=place_id)
        del active_players[sid]

if __name__ == '__main__':
    # На Render порт задается переменной окружения
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
