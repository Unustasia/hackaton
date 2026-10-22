import json
import sqlite3
from config import settings


def get_db_connection():
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS displays (
            id TEXT PRIMARY KEY,
            location TEXT NOT NULL,
            group_name TEXT NOT NULL,
            emergency_text TEXT,
            is_emergency INTEGER DEFAULT 0,
            emergency_expires TEXT,
            template_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            columns_count INTEGER DEFAULT 1,
            theme TEXT DEFAULT 'dark',
            widgets TEXT DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS static_content (
            key TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            actor TEXT,
            action TEXT,
            targets TEXT,
            text TEXT
        );
    """)
    # ИСПРАВЛЕНО: раньше было fetchone() == 0 (Row никогда не равен 0) -> seed не выполнялся
    if conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0] == 0:
        conn.executemany("INSERT INTO templates (name, columns_count, theme, widgets) VALUES (?,?,?,?)", [
            ("Стандартный тёмный", 1, "dark", json.dumps(["clock", "news", "parking", "rules", "trash", "contacts"])),
            ("Контрастный светлый", 2, "light", json.dumps(["clock", "news", "parking", "camera"])),
        ])
    if conn.execute("SELECT COUNT(*) FROM displays").fetchone()[0] == 0:
        conn.executemany("INSERT INTO displays (id, location, group_name, template_id) VALUES (?,?,?,?)", [
            ("main_hall_01", "Холл, подъезд 1", "entrance_1", 1),
            ("lift_box_02", "Лифт 1, подъезд 1", "entrance_1", 1),
            ("reception_01", "Главный ресепшн", "management", 2),
            ("main_hall_03", "Холл, подъезд 3", "entrance_3", 1),
        ])
    if conn.execute("SELECT COUNT(*) FROM static_content").fetchone()[0] == 0:
        conn.executemany("INSERT INTO static_content VALUES (?,?,?)", [
            ("rules", "Правила ЖК", "Тишина с 23:00 до 07:00\nОставляйте лифт чистым\nПарковка только на своём месте"),
            ("trash", "График вывоза мусора", "Пн, Ср, Пт — 08:00\nКрупногабаритный — 1-я суббота месяца"),
            ("contacts", "Аварийные службы", "Диспетчер УК: +7 (000) 000-00-01\nЛифты: +7 (000) 000-00-02\nЕДДС: 112"),
        ])
    conn.commit()
    conn.close()
