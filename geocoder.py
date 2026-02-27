"""
geocoder.py
住所 → 緯度経度 変換モジュール

Nominatim（無料・APIキー不要）と Google Maps API の両対応
"""

from __future__ import annotations
import time
import json
import urllib.parse
import urllib.request
from functools import lru_cache

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Nominatim（OpenStreetMap、無料・APIキー不要）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "SharHolder-Benefit-Map/1.0 (educational project)"


@lru_cache(maxsize=512)
def _nominatim_geocode(address: str) -> tuple[float, float] | None:
    """Nominatim で住所 → (lat, lng) を取得。失敗時は None"""
    params = urllib.parse.urlencode({
        "q": address,
        "format": "json",
        "limit": 1,
        "countrycodes": "jp",   # 日本に限定
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Google Maps Geocoding API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


@lru_cache(maxsize=512)
def _google_geocode(address: str, api_key: str) -> tuple[float, float] | None:
    """Google Geocoding API で住所 → (lat, lng) を取得。失敗時は None"""
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 公開インターフェース
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def geocode_single(
    address: str,
    api_key: str | None = None,
    provider: str = "nominatim",
) -> tuple[float, float] | None:
    """
    1件の住所を (lat, lng) に変換。失敗時は None。

    Parameters
    ----------
    address  : 住所文字列
    api_key  : Google Maps API キー（provider="google" の場合のみ必要）
    provider : "nominatim" | "google"
    """
    if not address:
        return None

    if provider == "google" and api_key:
        return _google_geocode(address, api_key)
    else:
        return _nominatim_geocode(address)


def geocode_addresses(
    stores: list[dict],
    api_key: str | None = None,
    provider: str = "nominatim",
    delay: float = 1.1,   # Nominatim の利用規約: 1秒以上の間隔
) -> list[dict]:
    """
    店舗リスト全件をジオコーディングして lat/lng を追加して返す。

    Parameters
    ----------
    stores   : 店舗情報リスト（各要素に "address" キー必須）
    api_key  : Google Maps API キー（Nominatim 使用時は不要）
    provider : "nominatim" | "google"
    delay    : リクエスト間隔（秒）- Nominatim は 1 秒以上必須
    """
    if provider == "nominatim":
        # Nominatim は 1リクエスト/秒 の制限
        delay = max(delay, 1.1)
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
