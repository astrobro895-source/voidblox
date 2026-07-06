import os
import eventlet
# Обязательный патч для работы сокетов внутри контейнеров Render
eventlet.monkey_patch()

from flask import Flask, render_template_string, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'roblox_pro_secret_2026'

# Автоматический режим сокетов под Gunicorn + Eventlet
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60)

# Профессиональная симуляция базы данных (Подключи сюда свою БД)
db = {
    "users": {
        "admin": "12345" # Простой пример для тестов авторизации
    },
    "places": {
        "1": {
            "name": "🛝 Начальный Спавн (Baseplate)", 
            "creator": "Система",
            "objects": [
                {"type": "box", "x": 0, "y": 0.75, "z": -5, "color": 16711680},
                {"type": "sphere", "x": 3, "y": 0.75, "z": -3, "color": 65280}
            ]
        }
    }
}

# Онлайн игроки на серверах: { session_id: { username, place_id, x, y, z } }
online_players = {}

@app.route('/')
def index():
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except FileNotFoundError:
        return "Критическая ошибка: Файл index.html не найден!", 404

# --- API Авторизации и Регистрации ---
@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if username in db['users'] and db['users'][username] == password:
        return jsonify({"success": True, "username": username})
    return jsonify({"success": False, "message": "Неверный никнейм или перевод пароля!"})

@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or len(password) < 4:
        return jsonify({"success": False, "message": "Имя пустое или пароль слишком короткий!"})
    if username in db['users']:
        return jsonify({"success": False, "message": "Этот никнейм уже занят!"})
        
    db['users'][username] = password
    return jsonify({"success": True, "username": username})

# --- API Управления Плейсами ---
@app.route('/api/places', methods=['GET'])
def get_places():
    return jsonify(db['places'])

@app.route('/api/places/save', methods=['POST'])
def save_place():
    data = request.json or {}
    place_id = str(data.get('place_id', ''))
    name = data.get('name', 'Новый мир')
    creator = data.get('creator', 'Система')
    objects = data.get('objects', [])

    if not place_id or place_id not in db['places']:
        place_id = str(len(db['places']) + 1)

    db['places'][place_id] = {
        "name": name,
        "creator": creator,
        "objects": objects
    }
    return jsonify({"success": True, "place_id": place_id})

# --- WebSockets Синхронизация ---
@socketio.on('join_place')
def handle_join(data):
    sid = request.sid
    username = data.get('username', 'Guest')
    place_id = str(data.get('place_id', '1'))

    join_room(place_id)
    online_players[sid] = {"username": username, "place_id": place_id, "x": 0, "y": 1, "z": 0}

    # Оповещаем мир о входе
    emit('player_joined', {"id": sid, "username": username, "x": 0, "y": 1, "z": 0}, to=place_id, skip_sid=sid)
    
    # Отправляем вошедшему список тех, кто уже на карте
    current_room_players = {
        other_sid: info for other_sid, info in online_players.items() 
        if info['place_id'] == place_id and other_sid != sid
    }
    emit('current_players', current_room_players)

@socketio.on('move')
def handle_move(data):
    sid = request.sid
    if sid in online_players:
        player = online_players[sid]
        player['x'], player['y'], player['z'] = data.get('x', 0), data.get('y', 1), data.get('z', 0)
        emit('player_moved', {"id": sid, "x": player['x'], "y": player['y'], "z": player['z']}, to=player['place_id'], skip_sid=sid)

@socketio.on('chat_message')
def handle_chat(data):
    sid = request.sid
    if sid in online_players:
        place_id = online_players[sid]['place_id']
        msg = f"[{online_players[sid]['username']}]: {data.get('text', '')}"
        emit('new_chat_message', {"msg": msg}, to=place_id)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in online_players:
        place_id = online_players[sid]['place_id']
        emit('player_left', {"id": sid}, to=place_id)
        del online_players[sid]

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
