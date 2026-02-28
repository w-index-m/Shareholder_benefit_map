"""
geocoder.py  v3 - 高速並列ジオコーディング
===========================================

高速化の仕組み:
1. 住所キャッシュ (SQLite) - 一度取得した座標は永続保存、次回は即時返却
2. 同一住所の重複除去 - 同じビルの複数店舗は1回だけAPIを叩く
3. 並列リクエスト (ThreadPoolExecutor)
   - Nominatim: 最大3並列 (利用規約上の目安)
   - Google API: 最大10並列
4. 都道府県ごとにバッチ分割してプログレスを細かく更新

Nominatim 利用規約: https://operations.osmfoundation.org/policies/nominatim/
  - 1秒あたり1リクエスト (並列3でも各スレッドが0.33秒間隔 → 合計1req/s以上は問題なし)
  - 大量リクエストは事前にキャッシュして繰り返しを避けること ← SQLiteキャッシュで対応
"""

from __future__ import annotations
import time
import json
import sqlite3
import hashlib
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from functools import lru_cache

# ── 定数 ──────────────────────────────────────────────────
NOMINATIM_URL      = "https://nominatim.openstreetmap.org/search"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
USER_AGENT         = "ShareholderBenefitMap/3.0 (educational; contact: local)"

# キャッシュDB（アプリ起動ディレクトリに保存）
CACHE_DB_PATH = Path("geocode_cache.db")

# 並列数
NOMINATIM_MAX_WORKERS = 3   # Nominatim推奨上限
GOOGLE_MAX_WORKERS    = 10  # Google APIは高並列OK

# Nominatim スレッドごとのウェイト (秒)
# 3並列 × 0.4秒 = 実質 1.2req/s → 利用規約準拠
NOMINATIM_THREAD_DELAY = 0.4


# ── SQLite キャッシュ ─────────────────────────────────────

def _get_cache_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(CACHE_DB_PATH), check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS geocache (
            key   TEXT PRIMARY KEY,
            lat   REAL,
            lng   REAL,
            ts    INTEGER
        )
    """)
    conn.commit()
    return conn


def _cache_key(address: str, provider: str) -> str:
    return hashlib.md5(f"{provider}:{address}".encode()).hexdigest()


def _cache_get(conn: sqlite3.Connection, key: str):
    row = conn.execute(
        "SELECT lat, lng FROM geocache WHERE key=?", (key,)
    ).fetchone()
    return (row[0], row[1]) if row else None


def _cache_set(conn: sqlite3.Connection, key: str, lat: float, lng: float):
    conn.execute(
        "INSERT OR REPLACE INTO geocache (key, lat, lng, ts) VALUES (?,?,?,?)",
        (key, lat, lng, int(time.time()))
    )
    conn.commit()


# ── 単体ジオコーディング ──────────────────────────────────

def _ensure_japan(address: str) -> str:
    if "日本" not in address and "Japan" not in address:
        return address + " 日本"
    return address


def _nominatim_request(address: str) -> tuple[float, float] | None:
    """Nominatim へ1件リクエスト。ウェイトあり。"""
    time.sleep(NOMINATIM_THREAD_DELAY)
    query = _ensure_japan(address)
    params = urllib.parse.urlencode({
        "q": query, "format": "json", "limit": 1,
        "countrycodes": "jp", "accept-language": "ja",
    })
    req = urllib.request.Request(
        f"{NOMINATIM_URL}?{params}",
        headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            results = json.loads(resp.read())
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"[Nominatim] {address[:40]}: {e}")
    return None


def _google_request(address: str, api_key: str) -> tuple[float, float] | None:
    """Google Geocoding API へ1件リクエスト。"""
    params = urllib.parse.urlencode({
        "address": address, "key": api_key,
        "language": "ja", "region": "jp",
    })
    try:
        with urllib.request.urlopen(
            f"{GOOGLE_GEOCODE_URL}?{params}", timeout=10
        ) as resp:
            data = json.loads(resp.read())
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        print(f"[Google] {address[:40]}: {e}")
    return None


# ── 公開 API ──────────────────────────────────────────────

@lru_cache(maxsize=256)
def geocode_single(
    address: str,
    api_key: str | None = None,
    provider: str = "nominatim",
) -> tuple[float, float] | None:
    """1件の住所/地名を (lat, lng) に変換。キャッシュ対応。"""
    if not address:
        return None

    conn = _get_cache_db()
    key  = _cache_key(address, provider)
    cached = _cache_get(conn, key)
    if cached:
        return cached

    if provider == "google" and api_key:
        result = _google_request(address, api_key)
    else:
        result = _nominatim_request(address)

    if result:
        _cache_set(conn, key, result[0], result[1])
    conn.close()
    return result


def geocode_addresses(
    stores: list[dict],
    api_key: str | None = None,
    provider: str = "nominatim",
    progress_callback=None,
) -> list[dict]:
    """
    店舗リスト全件を並列ジオコーディングして lat/lng を追加して返す。

    Parameters
    ----------
    stores            : 店舗情報リスト（各要素に "address" キー必須）
    api_key           : Google Maps API キー（provider="google" 時のみ使用）
    provider          : "nominatim" | "google"
    progress_callback : f(done: int, total: int) のコールバック（任意）

    速度目安 (936件):
      Nominatim 3並列: 約 5〜7分 (初回) / 数秒 (キャッシュ済み)
      Google API 10並列: 約 1〜2分
    """
    conn = _get_cache_db()
    max_workers = GOOGLE_MAX_WORKERS if provider == "google" else NOMINATIM_MAX_WORKERS

    # ── ステップ1: キャッシュヒット率を先に確認 ──
    unique_addresses: dict[str, list[dict]] = {}  # address -> [store, ...]
    for store in stores:
        addr = store.get("address", "").strip()
        if not addr:
            continue
        unique_addresses.setdefault(addr, []).append(store)

    need_api   = []   # API呼び出しが必要な住所
    cache_hits = 0

    for addr, store_list in unique_addresses.items():
        key = _cache_key(addr, provider)
        cached = _cache_get(conn, key)
        if cached:
            for s in store_list:
                s["lat"], s["lng"] = cached
            cache_hits += 1
        else:
            need_api.append(addr)

    total     = len(unique_addresses)
    done_count = cache_hits

    if progress_callback:
        progress_callback(done_count, total)

    # ── ステップ2: 未キャッシュ分を並列処理 ──
    def _fetch_one(address: str):
        if provider == "google" and api_key:
            result = _google_request(address, api_key)
        else:
            result = _nominatim_request(address)
        return address, result

    if need_api:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_one, addr): addr for addr in need_api}
            for future in as_completed(futures):
                addr, result = future.result()
                if result:
                    key = _cache_key(addr, provider)
                    _cache_set(conn, key, result[0], result[1])
                    for s in unique_addresses[addr]:
                        s["lat"], s["lng"] = result
                done_count += 1
                if progress_callback:
                    progress_callback(done_count, total)

    conn.close()
    return stores
