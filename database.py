import sqlite3
from config import settings

def get_db_connection():
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Таблица экранов с поддержкой группировки (например, по подъездам)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS displays (
            id TEXT PRIMARY KEY,
            location TEXT NOT NULL,
            group_name TEXT NOT NULL,
            emergency_text TEXT,
            is_emergency INTEGER DEFAULT 0,
            current_template_id INTEGER
        )
    """)
    
    # Таблица конструктора шаблонов УК
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            columns_count INTEGER DEFAULT 4,
            theme TEXT DEFAULT 'dark'
        )
    """)
    
    # Мок-данные по ТЗ (экраны в разных локациях и группах)
    cursor.execute("SELECT COUNT(*) FROM displays")
    if cursor.fetchone() == 0:
        cursor.executemany("INSERT INTO displays VALUES (?, ?, ?, ?, ?, ?)", [
            ("main_hall_01", "Холл, Подъезд 1", "entrance_1", None, 0, 1),
            ("lift_box_02", "Лифт 1, Подъезд 1", "entrance_1", None, 0, 1),
            ("reception_01", "Главный ресепшн", "management", None, 0, 2)
        ])
        cursor.executemany("INSERT INTO templates (name, columns_count, theme) VALUES (?, ?, ?)", [
            ("Стандартный зимний", 4, "dark"),
            ("Контрастный светлый", 3, "light")
        ])
    conn.commit()
    conn.close()
