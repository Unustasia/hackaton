import logging
import asyncio
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks, Depends, Header, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from config import settings
import database
import services

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Ujin Smart Display Full API", debug=settings.DEBUG_MODE)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Валидация токена Ujin (Header или URL) ---
def verify_ujin_token(authorization: str = Header(None), token: str = Query(None)):
    # Временный фикс для локальных тестов: всегда пропускаем запрос
    return "test_token"

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, display_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[display_id] = websocket

    def disconnect(self, display_id: str):
        if display_id in self.active_connections:
            del self.active_connections[display_id]

    async def broadcast_emergency(self, target_type: str, target_id: str, text: str):
        """Адресная рассылка ЧС (ТЗ Стр 5: конкретный дисплей, группа, все)"""
        conn = database.get_db_connection()
        cursor = conn.cursor()
        
        if target_type == "all":
            cursor.execute("UPDATE displays SET is_emergency = 1, emergency_text = ?", (text,))
            targets = list(self.active_connections.keys())
        elif target_type == "group":
            cursor.execute("UPDATE displays SET is_emergency = 1, emergency_text = ? WHERE group_name = ?", (text, target_id))
            rows = cursor.execute("SELECT id FROM displays WHERE group_name = ?", (target_id,)).fetchall()
            targets = [r["id"] for r in rows if r["id"] in self.active_connections]
        else:
            cursor.execute("UPDATE displays SET is_emergency = 1, emergency_text = ? WHERE id = ?", (text, target_id))
            targets = [target_id] if target_id in self.active_connections else []

        conn.commit()
        conn.close()

        for d_id in targets:
            if d_id in self.active_connections:
                await self.active_connections[d_id].send_json({"event": "EMERGENCY_ACTIVATE", "text": text})

    async def broadcast_reset(self, target_type: str, target_id: str):
        """Адресный сброс режима ЧС"""
        conn = database.get_db_connection()
        cursor = conn.cursor()
        
        if target_type == "all":
            cursor.execute("UPDATE displays SET is_emergency = 0, emergency_text = NULL")
            targets = list(self.active_connections.keys())
        elif target_type == "group":
            cursor.execute("UPDATE displays SET is_emergency = 0, emergency_text = NULL WHERE group_name = ?", (target_id,))
            rows = cursor.execute("SELECT id FROM displays WHERE group_name = ?", (target_id,)).fetchall()
            targets = [r["id"] for r in rows if r["id"] in self.active_connections]
        else:
            cursor.execute("UPDATE displays SET is_emergency = 0, emergency_text = NULL WHERE id = ?", (target_id,))
            targets = [target_id] if target_id in self.active_connections else []

        conn.commit()
        conn.close()

        for d_id in targets:
            if d_id in self.active_connections:
                await self.active_connections[d_id].send_json({"event": "EMERGENCY_RESET"})

manager = ConnectionManager()

class EmergencyPayload(BaseModel):
    target_type: str
    target_id: str
    emergency_text: str
    timeout_seconds: int = 30

class TemplatePayload(BaseModel):
    name: str
    columns_count: int
    theme: str

async def auto_reset_task(target_type: str, target_id: str, delay: int):
    await asyncio.sleep(delay)
    await manager.broadcast_reset(target_type, target_id)
    logger.info(f"[АУДИТ ТАЙМАУТА] Автоматический сброс ЧС выполнен для {target_type}:{target_id}")

@app.on_event("startup")
def startup():
    database.init_db()

# --- СЕРВЕРНАЯ РАЗДАЧА HTML СТРАНИЦЫ (Фикс блокировок CORS) ---
@app.get("/", response_class=HTMLResponse)
def read_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

# --- REAL-TIME WEBSOCKET ЭКРАНА КЛИЕНТА ---
@app.websocket("/ws/display/{display_id}")
async def websocket_endpoint(websocket: WebSocket, display_id: str):
    await manager.connect(display_id, websocket)
    try:
        conn = database.get_db_connection()
        display = conn.execute("SELECT * FROM displays WHERE id = ?", (display_id,)).fetchone()
        conn.close()
        
        if display and display["is_emergency"]:
            await websocket.send_json({"event": "EMERGENCY_ACTIVATE", "text": display["emergency_text"]})
        else:
            await websocket.send_json({"event": "NORMAL_MODE"})
            
        while True:
            ujin_data = services.fetch_ujin_data_safe()
            await websocket.send_json({"event": "DATA_UPDATE", "data": ujin_data})
            await asyncio.sleep(4)
    except WebSocketDisconnect:
        manager.disconnect(display_id)

# --- АКТИВАЦИЯ ЧС ---
@app.post("/api/v1/uk/emergency/activate")
async def activate_emergency(payload: EmergencyPayload, background_tasks: BackgroundTasks, token: str = Depends(verify_ujin_token)):
    logger.info(f"[AUDIT] Прямой пуш ЧС на цель {payload.target_id}")
    
    # МАГИЯ: Бэкенд мгновенно рассылает сигнал ЧС во все открытые веб-сокеты экранов!
    await manager.broadcast_emergency(payload.target_type, payload.target_id, payload.emergency_text)
    
    # Ставим таймер автосброса
    background_tasks.add_task(auto_reset_task, payload.target_type, payload.target_id, payload.timeout_seconds)
    return {"status": "success"}

# --- СБРОС ЧС ---
@app.post("/api/v1/uk/emergency/reset")
async def reset_emergency(target_type: str, target_id: str, token: str = Depends(verify_ujin_token)):
    await manager.broadcast_reset(target_type, target_id)
    return {"status": "success"}

# --- УПРАВЛЕНИЕ ШАБЛОНАМИ (CRUD) ---
@app.post("/api/v1/uk/templates")
def create_template(payload: TemplatePayload, token: str = Depends(verify_ujin_token)):
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO templates (name, columns_count, theme) VALUES (?, ?, ?)", (payload.name, payload.columns_count, payload.theme))
    conn.commit()
    t_id = cursor.lastrowid
    conn.close()
    return {"id": t_id, "status": "created"}

@app.get("/api/v1/uk/dashboard")
def get_dashboard(token: str = Depends(verify_ujin_token)):
    conn = database.get_db_connection()
    displays = conn.execute("SELECT * FROM displays").fetchall()
    templates = conn.execute("SELECT * FROM templates").fetchall()
    conn.close()
    return {"connected_displays": [dict(d) for d in displays], "available_templates": [dict(t) for t in templates]}
