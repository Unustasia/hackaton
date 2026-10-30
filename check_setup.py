"""Проверка окружения проекта. Работает на Windows и Linux: python check_setup.py"""
import importlib.util
import os
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
problems = []


def ok(msg, hint=""):
    print(f"[ OK ] {msg}")


def bad(msg, hint=""):
    print(f"[ !! ] {msg}")
    if hint:
        print(f"        -> {hint}")
    problems.append(msg)


def warn(msg, hint=""):
    print(f"[ ?? ] {msg}")
    if hint:
        print(f"        -> {hint}")


print(f"Папка проекта: {BASE}\n")

# 1. Python
v = sys.version_info
(ok if v >= (3, 10) else bad)(f"Python {v.major}.{v.minor}.{v.micro}",
    "" if v >= (3, 10) else "нужен Python 3.10 или новее: python.org/downloads (галочка Add Python to PATH)")

# 2. pip и venv
for mod, name in (("pip", "pip"), ("venv", "venv (виртуальное окружение)")):
    if importlib.util.find_spec(mod):
        ok(name)
    else:
        bad(f"{name} не найден", "Linux: sudo apt install python3-venv python3-pip; Windows: переустановите Python")

# 3. Файлы проекта
need = ["main.py", "config.py", "database.py", "services.py", "fallback.json", "requirements.txt",
        "static/index.html", "static/display.html", "static/preview.html"]
for f in need:
    (ok if (BASE / f).is_file() else bad)(f"файл {f}" if (BASE / f).is_file() else f"нет файла {f}",
        "" if (BASE / f).is_file() else "положите его на это место (см. схему папок)")
for stale in BASE.glob("*_1.*"):
    warn(f"лишний файл {stale.name}", "это копия со старым именем; удалите или переименуйте её в нормальное имя")
for stale in ("index.html",):
    if (BASE / stale).is_file():
        warn("index.html лежит в корне проекта", "он должен быть только в папке static; из корня удалите")

# 4. .env
if (BASE / ".env").is_file():
    ok("файл .env")
elif (BASE / ".env.txt").is_file():
    bad("файл называется .env.txt", "переименуйте в .env (включите показ расширений файлов в проводнике)")
else:
    warn(".env не найден", "не обязательно: без него проект работает на тестовых данных. Скопируйте .env.example в .env")

# 5. Пакеты (проверяем в .venv, если он есть)
venv_py = BASE / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
exe = str(venv_py) if venv_py.is_file() else sys.executable
print(f"\nПакеты проверяются в: {exe}")
if not venv_py.is_file():
    warn("папки .venv нет", "создайте: py -m venv .venv (Windows) или python3 -m venv .venv (Linux)")
for pkg in ("fastapi", "uvicorn", "pydantic_settings", "websockets"):
    r = subprocess.run([exe, "-c", f"import {pkg}"], capture_output=True)
    (ok if r.returncode == 0 else bad)(f"пакет {pkg}" if r.returncode == 0 else f"пакет {pkg} не установлен",
        "" if r.returncode == 0 else "активируйте .venv и выполните: pip install -r requirements.txt")

# 6. Старая база
db = BASE / "ujin_displays.db"
if db.is_file():
    try:
        cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(displays)")]
        if cols and "template_id" not in cols:
            bad("ujin_displays.db от старой версии", "удалите файл ujin_displays.db, он создастся заново")
        else:
            ok("база ujin_displays.db")
    except Exception as e:
        bad(f"база повреждена: {e}", "удалите файл ujin_displays.db")
else:
    ok("базы ещё нет, создастся при первом запуске")

# 7. Порт 8000
s = socket.socket()
try:
    s.bind(("0.0.0.0", 8000))
    ok("порт 8000 свободен")
except OSError:
    bad("порт 8000 занят", "закройте предыдущий запуск (Ctrl+C) или другую программу")
finally:
    s.close()

# 8. Интернет (нужен только для погоды и RSS)
try:
    socket.create_connection(("api.open-meteo.com", 443), timeout=3).close()
    ok("интернет доступен (погода и RSS заработают)")
except OSError:
    warn("интернета нет или он ограничен", "не критично: погода и RSS покажут «Нет данных»")

print()
if problems:
    print(f"ИТОГ: проблем: {len(problems)}. Исправьте пункты [ !! ] и запустите проверку снова.")
else:
    print("ИТОГ: всё готово. Запуск: активируйте .venv и выполните python main.py")
sys.exit(1 if problems else 0)
