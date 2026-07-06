import os
import json
from datetime import datetime, timedelta
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import jwt, JWTError
import sqlite3

SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-render-env-vars")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "users.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


init_db()


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_user(username: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT id, username, password_hash FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return row


@app.post("/api/register")
def register(req: RegisterRequest):
    if get_user(req.username):
        raise HTTPException(400, "Username already taken")
    password_hash = pwd_context.hash(req.password)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (req.username, password_hash))
    conn.commit()
    conn.close()
    token = create_access_token({"sub": req.username})
    return {"token": token, "username": req.username}


@app.post("/api/login")
def login(req: LoginRequest):
    row = get_user(req.username)
    if not row or not pwd_context.verify(req.password, row[2]):
        raise HTTPException(401, "Invalid username or password")
    token = create_access_token({"sub": req.username})
    return {"token": token, "username": req.username}


def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


# --- WebSocket chat + позиции игроков ---
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


# --- Статика (наш "клиент" на Three.js) ---
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")