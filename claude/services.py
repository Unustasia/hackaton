import json
import logging
import time
import urllib.request
from datetime import datetime
from config import settings, BASE_DIR

logger = logging.getLogger(__name__)
_cache = {"ts": 0, "data": None}
CACHE_TTL = 60


def _get(path: str):
    req = urllib.request.Request(
        settings.UJIN_BASE_URL.rstrip("/") + path,
        headers={"Authorization": f"Bearer {settings.UJIN_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def _items(payload):
    if isinstance(payload, list):
        return payload
    for k in ("data", "items", "results"):
        v = payload.get(k) if isinstance(payload, dict) else None
        if isinstance(v, list):
            return v
        if isinstance(v, dict) and isinstance(v.get("items"), list):
            return v["items"]
    return []


def _is_free(item: dict) -> bool:
    # TODO: свериться с Open API (поле «unassigned»/«не выкуплено»)
    for k in ("unassigned", "is_free", "free"):
        if k in item:
            return bool(item[k])
    return not item.get("owner") and not item.get("user_id")


def _alive(news: dict) -> bool:
    """Новость показываем, только пока не истекло время жизни."""
    exp = news.get("expires_at") or news.get("date_end") or news.get("expire_date")
    if not exp:
        return True
    try:
        return datetime.fromisoformat(str(exp).replace("Z", "+00:00")).replace(tzinfo=None) > datetime.now()
    except ValueError:
        return True


def _from_ujin() -> dict:
    # TODO: пути методов сверить с Open API.yaml
    news = [n for n in _items(_get("/api/v1/news/list")) if _alive(n)]
    parking = _items(_get("/api/v1/parking/list"))
    storages = _items(_get("/api/v1/storage/list"))
    return {
        "source": "ujin",
        "ujin_news": [{"title": n.get("title", ""), "text": n.get("text") or n.get("description", ""),
                       "date": str(n.get("date") or n.get("created_at") or "")[:10]} for n in news[:5]],
        "ujin_infrastructure": {
            "free_parking_spots": sum(_is_free(p) for p in parking),
            "free_storages": sum(_is_free(s) for s in storages),
        },
    }


def _fallback() -> dict:
    with open(BASE_DIR / "fallback.json", encoding="utf-8") as f:
        d = json.load(f)
    d["source"] = "fallback"
    return d


def fetch_ujin_data_safe() -> dict:
    if time.time() - _cache["ts"] < CACHE_TTL and _cache["data"]:
        return _cache["data"]
    try:
        if not settings.UJIN_TOKEN:
            raise RuntimeError("UJIN_TOKEN не задан")
        data = _from_ujin()
    except Exception as e:
        logger.warning("Ujin недоступен (%s) -> fallback.json", e)
        data = _fallback()
    data["camera_url"] = settings.CAMERA_URL
    _cache.update(ts=time.time(), data=data)
    return data
