from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    DB_PATH: str = str(BASE_DIR / "ujin_displays.db")
    # Ujin (токен и url выдают организаторы)
    UJIN_BASE_URL: str = "https://hck-api.unicorn.icu"
    UJIN_TOKEN: str = ""          # пусто -> сразу работаем на fallback.json
    # Токен сотрудника УК для панели. Пусто -> демо-режим без проверки
    UK_TOKEN: str = ""
    CAMERA_URL: str = ""          # MJPEG-поток для виджета камеры (необязательно)
    EMERGENCY_DEFAULT_TIMEOUT_MIN: int = 30

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
