# Умный дисплей ЖК (Ujin)

## Структура
```
main.py  config.py  database.py  services.py  fallback.json
requirements.txt  .env.example  (-> скопировать в .env)
static/  index.html (панель УК)  display.html (дисплей)  preview.html (предпросмотр 9:16)
```

## Запуск
Windows (PowerShell):
```
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python main.py
```
Linux / macOS:
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

- Панель УК: http://localhost:8000/
- Дисплей: http://localhost:8000/display/main_hall_01
- Предпросмотр: кнопка «Предпросмотр» в панели

## API ЧС в формате из ТЗ
POST /api/v1/emergency       {"tablo_id":"main_hall_01","emergency_text":"...","priority":1}
POST /api/v1/emergency_reset {"tablo_id":"main_hall_01"}
tablo_id: ID экрана | "a,b,c" | "group:entrance_1" | "all". Токен: Authorization: Bearer ... или ?token=...

При смене схемы БД удалите `ujin_displays.db`.
