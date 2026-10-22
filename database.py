import sqlite3
from config import settings

def get_db_connection():
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS displays (
            id TEXT PRIMARY KEY,
            location TEXT NOT NULL,
            emergency_text TEXT,
            is_emergency INTEGER DEFAULT 0
        )
    """)
    
    cursor.execute("SELECT COUNT(*) FROM displays")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO displays VALUES (?, ?, ?, ?)", [
            ("main_hall_01", "Подъезд 1, Холл", None, 0),
            ("lift_box_02", "Подъезд 1, Лифт 1", None, 0)
        ])
    conn.commit()
    conn.close()
