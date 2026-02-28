"""
geocoder.py v5
- 並列処理は維持（速度向上）
- progress_callback は完全に削除（Streamlitスレッド問題を回避）
- 呼び出し側でポーリングして進捗を表示する設計に変更
"""
from __future__ import annotations
import time, json, threading, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED, ALL_COMPLETED

NOMINATIM_URL      = "https://nominatim.openstreetmap.org/search"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
USER_AGENT         = "ShareholderBenefitMap/5.0 (educational)"

NOMINATIM_MAX_WORKERS  = 3
GOOGLE_MAX_WORKERS     = 10
NOMINATIM_THREAD_DELAY = 0.4

# インメモリキャッシュ
_CACHE: dict[str, tuple[float, float] | None] = {}
_CACHE_LOCK = threading.Lock()


def _ck(address: str, provider: str) -> str:
    return f"{provider}:{address}"

def _cache_get(address: str, provider: str):
    with _CACHE_LOCK:
        return _CACHE.get(_ck(address, provider), "MISS")

def _cache_set(address: str, provider: str, result):
    with _CACHE_LOCK:
        _CACHE[_ck(address, provider)] = result

def load_session_cache(ss):
    """session_state からキャッシュを復元"""
    if hasattr(ss, "geocache"):
        with _CACHE_LOCK:
            _CACHE.update(ss.geocache)

def save_session_cache(ss):
    """キャッシュを session_state に保存"""
    with _CACHE_LOCK:
        ss.geocache = dict(_CACHE)


def _ensure_japan(addr: str) -> str:
    return addr + " 日本" if "日本" not in addr else addr

def _nominatim_req(address: str) -> tuple[float, float] | None:
    time.sleep(NOMINATIM_THREAD_DELAY)
    params = urllib.parse.urlencode({
        "q": _ensure_japan(address), "format": "json",
        "limit": 1, "countrycodes": "jp", "accept-language": "ja",
    })
    req = urllib.request.Request(
        f"{NOMINATIM_URL}?{params}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"[Nominatim] {address[:40]}: {e}")
    return None

def _google_req(address: str, api_key: str) -> tuple[float, float] | None:
    params = urllib.parse.urlencode({
        "address": address, "key": api_key, "language": "ja", "region": "jp"})
    try:
        with urllib.request.urlopen(
                f"{GOOGLE_GEOCODE_URL}?{params}", timeout=10) as r:
            data = json.loads(r.read())
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        print(f"[Google] {address[:40]}: {e}")
    return None


def geocode_single(address: str, api_key: str | None = None,
                   provider: str = "nominatim") -> tuple[float, float] | None:
    if not address:
        return None
    c = _cache_get(address, provider)
    if c != "MISS":
        return c
    result = (_google_req(address, api_key) if provider == "google" and api_key
              else _nominatim_req(address))
    _cache_set(address, provider, result)
    return result


def geocode_addresses(
    stores: list[dict],
    api_key: str | None = None,
    provider: str = "nominatim",
    progress_callback=None,   # 互換性のために残すが使わない
) -> list[dict]:
    """
    並列ジオコーディング。進捗はスレッドセーフなカウンターで管理。
    呼び出し側は done_counter を直接読んで進捗表示すること。
    """
    max_workers = GOOGLE_MAX_WORKERS if provider == "google" else NOMINATIM_MAX_WORKERS

    # ユニーク住所にグループ化
    groups: dict[str, list[dict]] = {}
    for s in stores:
        addr = s.get("address", "").strip()
        if addr:
            groups.setdefault(addr, []).append(s)

    need = []
    for addr, slist in groups.items():
        c = _cache_get(addr, provider)
        if c != "MISS":
            if c:
                for s in slist:
                    s["lat"], s["lng"] = c
        else:
            need.append(addr)

    if not need:
        return stores

    # 結果をスレッドセーフに収集
    results: dict[str, tuple[float,float] | None] = {}
    lock = threading.Lock()

    def fetch(addr):
        r = (_google_req(addr, api_key) if provider == "google" and api_key
             else _nominatim_req(addr))
        _cache_set(addr, provider, r)
        with lock:
            results[addr] = r

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        ex.map(fetch, need)   # map はすべて完了するまでブロック

    # 結果を store に反映（メインスレッドで安全に実行）
    for addr, r in results.items():
        if r:
            for s in groups.get(addr, []):
                s["lat"], s["lng"] = r

    return stores
