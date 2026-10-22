import os
from pathlib import Path
from pydantic_settings import BaseSettings

# Автоматически определяет корень проекта на любой ОС
BASE_DIR = Path(__file__).resolve().parent

class Settings(BaseSettings):
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    DEBUG_MODE: bool = True
    
    # Кроссплатформенный путь к БД (работает и на Windows, и на Linux)
    DB_PATH: str = str(BASE_DIR / "ujin_displays.db")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
