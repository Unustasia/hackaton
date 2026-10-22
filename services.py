import json
import logging
from pathlib import Path
from config import settings

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent

def fetch_ujin_data_safe():
    """Безопасно возвращает мок-данные платформы Ujin."""
    # Мы убрали принудительную ошибку raise Exception. 
    # Теперь сервер сразу отдаёт стабильные тестовые данные, как на реальном хакатоне.
    return {
        "ujin_news": [
            {
                "title": "Плановое обновление ПО",
                "text": "Система умного дома Ujin OS обновлена до версии 2.4.",
                "date": "2026-10-22"
            }
        ],
        "ujin_infrastructure": {
            "free_parking_spots": 14,
            "free_storages": 8
        }
    }
