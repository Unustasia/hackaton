import json
import logging
import time
import urllib.request
import xml.etree.ElementTree as ET
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
    # Пути берутся из .env (UJIN_*_PATH) — сверьте их с Open API.yaml
    news = [n for n in _items(_get(settings.UJIN_NEWS_PATH)) if _alive(n)]
    parking = _items(_get(settings.UJIN_PARKING_PATH))
    storages = _items(_get(settings.UJIN_STORAGE_PATH))
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


# ---------- Дополнительные источники: RSS и погода (внешние, без ключей) ----------
_extra_cache: dict = {}
WMO = {0: "Ясно", 1: "Преим. ясно", 2: "Переменная облачность", 3: "Пасмурно", 45: "Туман", 48: "Туман",
       51: "Морось", 53: "Морось", 55: "Морось", 61: "Дождь", 63: "Дождь", 65: "Сильный дождь",
       71: "Снег", 73: "Снег", 75: "Сильный снег", 80: "Ливень", 81: "Ливень", 82: "Сильный ливень",
       95: "Гроза", 96: "Гроза с градом", 99: "Гроза с градом"}


def _cached(key, ttl, fn):
    e = _extra_cache.get(key)
    if e and time.time() - e[0] < (ttl if e[1] is not None else 60):
        return e[1]
    try:
        val = fn()
    except Exception as ex:
        logger.warning("Внешний источник %s недоступен: %s", key, ex)
        val = e[1] if e else None  # при ошибке показываем последнее удачное значение
    _extra_cache[key] = (time.time(), val)
    return val


def _rss(url: str, limit: int = 5):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=4) as r:
        root = ET.fromstring(r.read())
    return [{"title": (i.findtext("title") or "").strip(), "date": (i.findtext("pubDate") or "")[:16]}
            for i in root.iter("item")][:limit]


def _weather(lat: str, lon: str):
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&current=temperature_2m,weather_code,wind_speed_10m")
    with urllib.request.urlopen(url, timeout=4) as r:
        cur = json.load(r)["current"]
    return {"temp": round(cur["temperature_2m"]), "wind": round(cur["wind_speed_10m"]),
            "desc": WMO.get(cur["weather_code"], "")}


def fetch_extras(cfg: dict) -> dict:
    """cfg — настройки источников из БД (rss_url, weather_*)."""
    out = {"rss": [], "weather": None, "weather_city": cfg.get("weather_city", "")}
    if cfg.get("rss_url"):
        out["rss"] = _cached("rss:" + cfg["rss_url"], 300, lambda: _rss(cfg["rss_url"])) or []
    if cfg.get("weather_lat") and cfg.get("weather_lon"):
        lat, lon = cfg["weather_lat"], cfg["weather_lon"]
        out["weather"] = _cached(f"w:{lat},{lon}", 600, lambda: _weather(lat, lon))
    return out
