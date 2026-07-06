import os
import eventlet
# Важно: eventlet требует "манки-патчинга", чтобы стандартные библиотеки Python 
# (например, функции времени или сетевые запросы к БД) работали асинхронно в сокетах.
eventlet.monkey_patch()

from flask import Flask, render_template_string, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'roblox_web_ultra_secret_key_2026'

# Инициализируем сокеты с поддержкой eventlet и CORS для Render
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='eventlet',
    ping_timeout=60, 
    ping_interval=25
)

# =====================================================================
#  БАЗА ДАННЫХ (Симуляция)
# =====================================================================
# TODO: Если у тебя подключена реальная БД, просто перепиши функции ниже, 
# чтобы они брали данные из твоих таблиц.
places_db = {
    "1": {
        "name": "Начальный Baseplate", 
        "objects": [
            {"type": "box", "x": 0, "y": 0.75, "z": -5, "color": 16711680},
            {"type": "sphere", "x": 3, "y": 0.75, "z": -3, "color": 65280}
        ]
    }
}

# Текущие игроки в онлайне: { session_id: { username, place_id, x, y, z } }
online_players = {}

# =====================================================================
#  HTTP МАРШРУТЫ (Рендеринг сайта и API)
# =====================================================================

@app.route('/')
def index():
    """Отдает главную страницу игры."""
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except FileNotFoundError:
        return "Ошибка: Файл index.html не найден в корневом каталоге!", 404

@app.route('/api/places', methods=['GET'])
def get_places():
    """Возвращает список всех существующих плейсов."""
    return jsonify(places_db)

@app.route('/api/places', methods=['POST'])
def save_place():
    """Создает новый или перезаписывает существующий плейс."""
    data = request.json or {}
    place_id = data.get('place_id')
    name = data.get('name', 'Безымянный плейс')
    objects = data.get('objects', [])

    # Если id не передан, генерируем новый (публикация нового мира)
    if not place_id or place_id not in places_db:
        place_id = str(len(places_db) + 1)

    places_db[place_id] = {
        "name": name,
        "objects": objects
    }
    return jsonify({"success": True, "place_id": place_id})

# =====================================================================
#  WEBSOCKETS (Мультиплеер, Чат, Студия в реальном времени)
# =====================================================================

@socketio.on('join_place')
def handle_join(data):
    """Вызывается, когда игрок заходит в определенный плейс."""
    sid = request.sid
    username = data.get('username', f'Guest_{sid[:4]}').strip()
    place_id = str(data.get('place_id', '1'))

    # Если игрок уже был в другой комнате, выходим из нее
    if sid in online_players:
        old_place = online_players[sid]['place_id']
        leave_room(old_place)
        emit('player_left', {"id": sid}, to=old_place, skip_sid=sid)

    # Заходим в новую комнату сокетов (комната = id плейса)
    join_room(place_id)
    
    # Регистрируем позицию игрока на спавне
    online_players[sid] = {
        "username": username,
        "place_id": place_id,
        "x": 0, "y": 1, "z": 0
    }

    # 1. Говорим всем в этой комнате, что зашел новый игрок
    emit('player_joined', {
        "id": sid, 
        "username": username, 
        "x": 0, "y": 1, "z": 0
    }, to=place_id, skip_sid=sid)

    # 2. Передаем новому игроку список ТЕХ, КТО УЖЕ ТУТ бегает
    room_players = {
        other_sid: player_info 
        for other_sid, player_info in online_players.items() 
        if player_info['place_id'] == place_id and other_sid != sid
    }
    emit('current_players', room_players)

@socketio.on('move')
def handle_move(data):
    """Синхронизация движения персонажа."""
    sid = request.sid
    if sid in online_players:
        player = online_players[sid]
        player['x'] = data.get('x', 0)
        player['y'] = data.get('y', 1)
        player['z'] = data.get('z', 0)
        
        # Пересылаем новые координаты всем остальным в этом же плейсе
        emit('player_moved', {
            "id": sid, 
            "x": player['x'], 
            "y": player['y'], 
            "z": player['z']
        }, to=player['place_id'], skip_sid=sid)

@socketio.on('chat_message')
def handle_chat(data):
    """Игровой чат внутри конкретного мира."""
    sid = request.sid
    if sid in online_players:
        player = online_players[sid]
        msg_text = data.get('text', '').strip()
        
        if msg_text:
            formatted_msg = f"[{player['username']}]: {msg_text}"
            # Отправляем сообщение абсолютно всем в комнате (включая автора)
            emit('new_chat_message', {"msg": formatted_msg}, to=player['place_id'])

@socketio.on('disconnect')
def handle_disconnect():
    """Вызывается автоматически, когда игрок закрывает вкладку или теряет сеть."""
    sid = request.sid
    if sid in online_players:
        place_id = online_players[sid]['place_id']
        # Оповещаем комнату, чтобы удалить 3D-модель игрока
        emit('player_left', {"id": sid}, to=place_id)
        del online_players[sid]

# =====================================================================
#  ЗАПУСК ПРИЛОЖЕНИЯ
# =====================================================================
if __name__ == '__main__':
    # Render передает порт динамически через переменную окружения PORT
    server_port = int(os.environ.get('PORT', 5000))
    # Запуск через socketio (использует eventlet под капотом при локальном запуске)
    socketio.run(app, host='0.0.0.0', port=server_port, debug=False)
