import os
import json
import hmac
import hashlib
import secrets
import base64
from datetime import datetime, timedelta
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import psycopg2

SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-render-env-vars").encode()
TOKEN_TTL_SECONDS = 60 * 60 * 24  # 24 часа

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id SERIAL PRIMARY KEY,
            owner_username TEXT NOT NULL,
            title TEXT NOT NULL,
            scene_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_state (
            username TEXT NOT NULL,
            game_id INTEGER NOT NULL,
            x REAL, y REAL, z REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (username, game_id)
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


if DATABASE_URL:
    init_db()


# ---------- Пароли (без bcrypt, чистый stdlib) ----------
def hash_password(password: str, salt: str = None):
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return dk.hex(), salt


def verify_password(password: str, salt: str, expected_hash: str):
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return hmac.compare_digest(dk.hex(), expected_hash)


# ---------- Токены (без jose/jwt, самодельный HMAC-токен) ----------
def create_token(username: str):
    expire = int((datetime.utcnow() + timedelta(seconds=TOKEN_TTL_SECONDS)).timestamp())
    payload = f"{username}:{expire}".encode()
    sig = hmac.new(SECRET_KEY, payload, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(payload + b"." + sig).decode()
    return token


def verify_token(token: str):
    try:
        raw = base64.urlsafe_b64decode(token.encode())
        payload, sig = raw.rsplit(b".", 1)
        expected_sig = hmac.new(SECRET_KEY, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        username, expire = payload.decode().rsplit(":", 1)
        if int(expire) < int(datetime.utcnow().timestamp()):
            return None
        return username
    except Exception:
        return None


def get_user(username: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username, password_hash, salt FROM users WHERE username=%s", (username,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


@app.post("/api/register")
async def register(payload: dict):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        raise HTTPException(400, "username and password are required")
    if get_user(username):
        raise HTTPException(400, "Username already taken")

    password_hash, salt = hash_password(password)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, password_hash, salt) VALUES (%s, %s, %s)",
        (username, password_hash, salt),
    )
    conn.commit()
    cur.close()
    conn.close()

    token = create_token(username)
    return {"token": token, "username": username}


@app.post("/api/login")
async def login(payload: dict):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    row = get_user(username)
    if not row or not verify_password(password, row[3], row[2]):
        raise HTTPException(401, "Invalid username or password")
    token = create_token(username)
    return {"token": token, "username": username}


# ---------- WebSocket (чат + позиции игроков) ----------
class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, WebSocket] = {}

    async def connect(self, username: str, ws: WebSocket):
        await ws.accept()
        self.active[username] = ws

    def disconnect(self, username: str):
        self.active.pop(username, None)

    async def broadcast(self, message: dict, exclude: str = None):
        dead = []
        for user, ws in self.active.items():
            if user == exclude:
                continue
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(user)
        for user in dead:
            self.disconnect(user)


manager = ConnectionManager()


@app.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    username = verify_token(token)
    if not username:
        await websocket.close(code=4001)
        return

    await manager.connect(username, websocket)
    await manager.broadcast({"type": "join", "user": username}, exclude=username)

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            payload["user"] = username
            await manager.broadcast(payload, exclude=None)
    except WebSocketDisconnect:
        manager.disconnect(username)
        await manager.broadcast({"type": "leave", "user": username})


# ---------- Статика ----------
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")
