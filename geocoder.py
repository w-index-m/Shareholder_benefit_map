"""
geocoder.py  v2
住所 → 緯度経度 変換モジュール

修正点:
- 現在地検索時に「日本」を付加して誤認識を防止
- 住所のジオコーディングでも都道府県が含まれない場合に国名を補完
- Nominatim の structured query を活用
"""

from __future__ import annotations
import time
import json
import urllib.parse
import urllib.request
from functools import lru_cache

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
USER_AGENT = "SharHolder-Benefit-Map/1.0 (educational project)"


def _ensure_japan(address: str) -> str:
    """住所に「日本」が含まれていなければ末尾に付加（Nominatim誤認識防止）"""
    if "日本" not in address and "Japan" not in address:
        return address + " 日本"
    return address


@lru_cache(maxsize=512)
def _nominatim_geocode(address: str) -> tuple[float, float] | None:
    """Nominatim で住所 → (lat, lng)。日本に限定。"""
    query = _ensure_japan(address)
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "jp",
        "accept-language": "ja",
    })
    url = f"{NOMINATIM_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read())
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"[Nominatim] {address}: {e}")
    return None


@lru_cache(maxsize=512)
def _google_geocode(address: str, api_key: str) -> tuple[float, float] | None:
    """Google Geocoding API で住所 → (lat, lng)"""
    params = urllib.parse.urlencode({
        "address": address,
        "key": api_key,
        "language": "ja",
        "region": "jp",
    })
    url = f"{GOOGLE_GEOCODE_URL}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        print(f"[Google Geocode] {address}: {e}")
    return None


def geocode_single(
    address: str,
    api_key: str | None = None,
    provider: str = "nominatim",
) -> tuple[float, float] | None:
    """
    1件の住所/地名を (lat, lng) に変換。失敗時は None。
    駅名・ランドマーク名も対応（Nominatim に「日本」を付加して誤認識を防ぐ）。
    """
    if not address:
        return None
    if provider == "google" and api_key:
        return _google_geocode(address, api_key)
    return _nominatim_geocode(address)


def geocode_addresses(
    stores: list[dict],
    api_key: str | None = None,
    provider: str = "nominatim",
    delay: float = 1.1,
) -> list[dict]:
    """店舗リスト全件をジオコーディングして lat/lng を追加。"""
    if provider == "nominatim":
        delay = max(delay, 1.1)   # Nominatim 利用規約: 1秒以上
    else:
        delay = max(delay, 0.1)

    for store in stores:
        address = store.get("address", "")
        if not address:
            continue
        result = geocode_single(address, api_key=api_key, provider=provider)
        if result:
            store["lat"], store["lng"] = result
        time.sleep(delay)
    return stores
