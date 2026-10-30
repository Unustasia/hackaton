import asyncio
import json
import re
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import database
import services
from config import BASE_DIR, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
STATIC = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="Ujin Smart Display", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- Авторизация: токен в заголовке и/или url (если оба — должны совпадать) ----------
def auth(authorization: str = Header(None), token: str = Query(None)) -> str:
    h = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else None
    if h and token and h != token:
        raise HTTPException(401, "Токены в заголовке и url различаются")
    t = h or token
    if settings.UK_TOKEN and t != settings.UK_TOKEN:
        raise HTTPException(401, "Неверный токен")
    return ("uk:..." + t[-4:]) if t else "uk:demo"


# ---------- Вспомогательное ----------
def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def resolve(conn, target_type: str, target_id: str) -> list[str]:
    rows = conn.execute("SELECT id, group_name FROM displays").fetchall()
    if target_type == "all":
        ids = [r["id"] for r in rows]
    elif target_type == "group":
        ids = [r["id"] for r in rows if r["group_name"] == target_id]
    else:  # single / list ("a,b,c")
        wanted = {x.strip() for x in target_id.split(",") if x.strip()}
        ids = [r["id"] for r in rows if r["id"] in wanted]
    if not ids:
        raise HTTPException(404, "Экраны не найдены")
    return ids


def audit(conn, actor: str, action: str, ids: list[str], text: str = ""):
    conn.execute("INSERT INTO audit_log (ts, actor, action, targets, text) VALUES (?,?,?,?,?)",
                 (now(), actor, action, ",".join(ids), text))
    logger.info("[AUDIT] %s %s -> %s %s", actor, action, ids, text)


class Manager:
    def __init__(self):
        self.conns: dict[str, list[WebSocket]] = {}
        self.timers: dict[str, asyncio.Task] = {}

    async def connect(self, did: str, ws: WebSocket):
        await ws.accept()
        self.conns.setdefault(did, []).append(ws)

    def disconnect(self, did: str, ws: WebSocket):
        if ws in self.conns.get(did, []):
            self.conns[did].remove(ws)

    def online(self, did: str) -> bool:
        return bool(self.conns.get(did))

    async def push(self, did: str):
        if not self.conns.get(did):
            return
        state = await build_state(did)
        for ws in list(self.conns[did]):
            try:
                await ws.send_json(state)
            except Exception:
                self.disconnect(did, ws)

    def cancel_timer(self, did: str):
        t = self.timers.pop(did, None)
        if t:
            t.cancel()

    def schedule_reset(self, did: str, minutes: int):
        self.cancel_timer(did)  # новое сообщение заменяет старое вместе с его таймером
        if minutes > 0:
            self.timers[did] = asyncio.create_task(self._auto_reset(did, minutes))

    async def _auto_reset(self, did: str, minutes: int):
        await asyncio.sleep(minutes * 60)
        conn = database.get_db_connection()
        conn.execute("UPDATE displays SET is_emergency=0, emergency_text=NULL, emergency_expires=NULL WHERE id=?", (did,))
        audit(conn, "system", "emergency_timeout_reset", [did])
        conn.commit()
        conn.close()
        self.timers.pop(did, None)
        await self.push(did)


manager = Manager()


async def build_state(did: str, template_id: int | None = None, with_emergency: bool = True) -> dict:
    conn = database.get_db_connection()
    d = conn.execute("SELECT * FROM displays WHERE id=?", (did,)).fetchone()
    tid = template_id or (d["template_id"] if d else None)
    t = conn.execute("SELECT * FROM templates WHERE id=?", (tid,)).fetchone()
    static = {r["key"]: {"title": r["title"], "body": r["body"]} for r in conn.execute("SELECT * FROM static_content")}
    cfg = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}
    conn.close()
    em = None
    if with_emergency and d and d["is_emergency"]:
        em = d["emergency_text"]
        if d["emergency_expires"] and d["emergency_expires"] < now():
            em = None  # таймаут истёк (даже если сервер перезапускался)
    data = dict(await asyncio.to_thread(services.fetch_ujin_data_safe))
    data.update(await asyncio.to_thread(services.fetch_extras, cfg))
    if cfg.get("camera_url"):
        data["camera_url"] = cfg["camera_url"]
    template = {"name": t["name"], "columns_count": t["columns_count"], "theme": t["theme"],
                "widgets": json.loads(t["widgets"])} if t else \
        {"name": "—", "columns_count": 1, "theme": "dark", "widgets": ["clock", "news"]}
    return {"event": "STATE", "display_id": did, "template": template, "emergency": em, "static": static, "data": data}


# ---------- Страницы ----------
@app.get("/")
def panel():
    return FileResponse(STATIC / "index.html")


@app.get("/display/{display_id}")
def display_page(display_id: str):
    return FileResponse(STATIC / "display.html")


@app.get("/preview")
def preview_page():
    return FileResponse(STATIC / "preview.html")


@app.get("/api/v1/public/preview/{template_id}")
async def preview_state(template_id: int):
    return await build_state("preview", template_id=template_id, with_emergency=False)


# ---------- WebSocket дисплея ----------
@app.websocket("/ws/display/{display_id}")
async def ws_display(ws: WebSocket, display_id: str):
    if not re.fullmatch(r"[\w\-]{1,64}", display_id):
        await ws.close(code=1008)
        return
    conn = database.get_db_connection()
    # экран, которого нет в базе, регистрируется автоматически при первом подключении
    conn.execute("INSERT OR IGNORE INTO displays (id, location, group_name, template_id) "
                 "VALUES (?,?,?,(SELECT MIN(id) FROM templates))", (display_id, display_id, "unassigned"))
    conn.commit()
    conn.close()
    await manager.connect(display_id, ws)
    try:
        await ws.send_json(await build_state(display_id))
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                await ws.send_json(await build_state(display_id))  # периодическое обновление данных
    except (WebSocketDisconnect, RuntimeError):
        manager.disconnect(display_id, ws)


# ---------- API панели УК ----------
class Target(BaseModel):
    target_type: str = "single"   # single | list | group | all
    target_id: str = ""


class EmergencyPayload(Target):
    emergency_text: str = Field(min_length=1, max_length=300)
    timeout_minutes: int = settings.EMERGENCY_DEFAULT_TIMEOUT_MIN  # 0 = без таймаута
    priority: int = 1


class AssignPayload(Target):
    template_id: int


class TemplatePayload(BaseModel):
    name: str
    columns_count: int = Field(1, ge=1, le=3)
    theme: str = "dark"
    widgets: list[str] = []


class StaticPayload(BaseModel):
    body: str


@app.get("/api/v1/uk/dashboard")
def dashboard(actor: str = Depends(auth)):
    conn = database.get_db_connection()
    displays = [dict(d) | {"online": manager.online(d["id"])} for d in conn.execute("SELECT * FROM displays")]
    templates = []
    for t in conn.execute("SELECT * FROM templates"):
        templates.append(dict(t) | {"widgets": json.loads(t["widgets"])})
    static = [dict(r) for r in conn.execute("SELECT * FROM static_content")]
    audit_rows = [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 15")]
    cfg = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}
    conn.close()
    return {"displays": displays, "templates": templates, "static": static, "audit": audit_rows, "settings": cfg}


@app.post("/api/v1/uk/emergency/activate")
async def emergency_activate(p: EmergencyPayload, actor: str = Depends(auth)):
    conn = database.get_db_connection()
    ids = resolve(conn, p.target_type, p.target_id)
    expires = (datetime.now() + timedelta(minutes=p.timeout_minutes)).isoformat(timespec="seconds") \
        if p.timeout_minutes > 0 else None
    # новое сообщение ЗАМЕНЯЕТ предыдущее (одно сообщение на экран)
    conn.execute(f"UPDATE displays SET is_emergency=1, emergency_text=?, emergency_expires=? "
                 f"WHERE id IN ({','.join('?' * len(ids))})", (p.emergency_text, expires, *ids))
    audit(conn, actor, "emergency_activate", ids, p.emergency_text)
    conn.commit()
    conn.close()
    for did in ids:
        manager.schedule_reset(did, p.timeout_minutes)
        await manager.push(did)
    return {"status": "success", "targets": ids}


@app.post("/api/v1/uk/emergency/reset")
async def emergency_reset(p: Target, actor: str = Depends(auth)):
    conn = database.get_db_connection()
    ids = resolve(conn, p.target_type, p.target_id)
    conn.execute(f"UPDATE displays SET is_emergency=0, emergency_text=NULL, emergency_expires=NULL "
                 f"WHERE id IN ({','.join('?' * len(ids))})", ids)
    audit(conn, actor, "emergency_reset", ids)
    conn.commit()
    conn.close()
    for did in ids:
        manager.cancel_timer(did)
        await manager.push(did)
    return {"status": "success", "targets": ids}


@app.post("/api/v1/uk/screens/assign")
async def assign_template(p: AssignPayload, actor: str = Depends(auth)):
    conn = database.get_db_connection()
    if not conn.execute("SELECT 1 FROM templates WHERE id=?", (p.template_id,)).fetchone():
        raise HTTPException(404, "Шаблон не найден")
    ids = resolve(conn, p.target_type, p.target_id)
    conn.execute(f"UPDATE displays SET template_id=? WHERE id IN ({','.join('?' * len(ids))})", (p.template_id, *ids))
    audit(conn, actor, f"assign_template:{p.template_id}", ids)
    conn.commit()
    conn.close()
    for did in ids:
        await manager.push(did)
    return {"status": "success", "targets": ids}


@app.post("/api/v1/uk/templates")
def create_template(p: TemplatePayload, actor: str = Depends(auth)):
    conn = database.get_db_connection()
    cur = conn.execute("INSERT INTO templates (name, columns_count, theme, widgets) VALUES (?,?,?,?)",
                       (p.name, p.columns_count, p.theme, json.dumps(p.widgets)))
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return {"id": tid}


@app.put("/api/v1/uk/templates/{tid}")
async def update_template(tid: int, p: TemplatePayload, actor: str = Depends(auth)):
    conn = database.get_db_connection()
    conn.execute("UPDATE templates SET name=?, columns_count=?, theme=?, widgets=? WHERE id=?",
                 (p.name, p.columns_count, p.theme, json.dumps(p.widgets), tid))
    users = [r["id"] for r in conn.execute("SELECT id FROM displays WHERE template_id=?", (tid,))]
    conn.commit()
    conn.close()
    for did in users:  # экраны с этим шаблоном обновляются сразу
        await manager.push(did)
    return {"status": "updated"}


@app.delete("/api/v1/uk/templates/{tid}")
def delete_template(tid: int, actor: str = Depends(auth)):
    conn = database.get_db_connection()
    if conn.execute("SELECT 1 FROM displays WHERE template_id=?", (tid,)).fetchone():
        raise HTTPException(409, "Шаблон назначен экранам — сначала замените его")
    conn.execute("DELETE FROM templates WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


@app.put("/api/v1/uk/static/{key}")
async def update_static(key: str, p: StaticPayload, actor: str = Depends(auth)):
    conn = database.get_db_connection()
    conn.execute("UPDATE static_content SET body=? WHERE key=?", (p.body, key))
    ids = [r["id"] for r in conn.execute("SELECT id FROM displays")]
    conn.commit()
    conn.close()
    for did in ids:
        await manager.push(did)
    return {"status": "updated"}


# ---------- Управление экранами ----------
class DisplayCreate(BaseModel):
    id: str = Field(pattern=r"^[\w\-]{1,64}$")
    location: str = ""
    group_name: str = "unassigned"


class DisplayUpdate(BaseModel):
    location: str
    group_name: str


@app.post("/api/v1/uk/displays")
def create_display(p: DisplayCreate, actor: str = Depends(auth)):
    conn = database.get_db_connection()
    try:
        conn.execute("INSERT INTO displays (id, location, group_name, template_id) "
                     "VALUES (?,?,?,(SELECT MIN(id) FROM templates))", (p.id, p.location or p.id, p.group_name or "unassigned"))
    except Exception:
        conn.close()
        raise HTTPException(409, "Экран с таким ID уже есть")
    audit(conn, actor, "display_create", [p.id])
    conn.commit()
    conn.close()
    return {"status": "created"}


@app.put("/api/v1/uk/displays/{did}")
async def update_display(did: str, p: DisplayUpdate, actor: str = Depends(auth)):
    conn = database.get_db_connection()
    conn.execute("UPDATE displays SET location=?, group_name=? WHERE id=?", (p.location, p.group_name, did))
    audit(conn, actor, "display_update", [did], f"{p.location} / {p.group_name}")
    conn.commit()
    conn.close()
    return {"status": "updated"}


@app.delete("/api/v1/uk/displays/{did}")
async def delete_display(did: str, actor: str = Depends(auth)):
    conn = database.get_db_connection()
    conn.execute("DELETE FROM displays WHERE id=?", (did,))
    audit(conn, actor, "display_delete", [did])
    conn.commit()
    conn.close()
    manager.cancel_timer(did)
    for ws in manager.conns.pop(did, []):
        try:
            await ws.close(code=4000)  # код 4000: дисплей не переподключается
        except Exception:
            pass
    return {"status": "deleted"}


# ---------- Источники контента (RSS, погода, камера) ----------
ALLOWED_SETTINGS = set(database.DEFAULT_SETTINGS)


@app.put("/api/v1/uk/settings")
async def update_settings(p: dict[str, str], actor: str = Depends(auth)):
    conn = database.get_db_connection()
    for k, v in p.items():
        if k in ALLOWED_SETTINGS:
            conn.execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v.strip()))
    audit(conn, actor, "settings_update", [], ",".join(k for k in p if k in ALLOWED_SETTINGS))
    ids = [r["id"] for r in conn.execute("SELECT id FROM displays")]
    conn.commit()
    conn.close()
    for did in ids:
        await manager.push(did)
    return {"status": "updated"}


# ---------- Внешний API ЧС в формате из задания ----------
# tablo_id: "main_hall_01" | "a,b,c" | "group:entrance_1" | "all"
class ExternalEmergency(BaseModel):
    tablo_id: str
    emergency_text: str = Field(min_length=1, max_length=300)
    priority: int = 1
    timeout_minutes: int = settings.EMERGENCY_DEFAULT_TIMEOUT_MIN


class ExternalReset(BaseModel):
    tablo_id: str


def parse_tablo(t: str) -> Target:
    if t == "all":
        return Target(target_type="all")
    if t.startswith("group:"):
        return Target(target_type="group", target_id=t[6:])
    return Target(target_type="list", target_id=t)


@app.post("/api/v1/emergency")
async def external_emergency(p: ExternalEmergency, actor: str = Depends(auth)):
    tg = parse_tablo(p.tablo_id)
    return await emergency_activate(EmergencyPayload(target_type=tg.target_type, target_id=tg.target_id,
                                                     emergency_text=p.emergency_text, priority=p.priority,
                                                     timeout_minutes=p.timeout_minutes), actor)


@app.post("/api/v1/emergency_reset")
async def external_reset(p: ExternalReset, actor: str = Depends(auth)):
    return await emergency_reset(parse_tablo(p.tablo_id), actor)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT)
