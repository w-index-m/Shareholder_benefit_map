"""
geocoder.py v6
- 住所を段階的に短縮して再試行（日本の複雑な住所対応）
- 現在地検索は駅名・地名に特化
- 並列処理維持
- Streamlit Cloud対応（メモリキャッシュ）
"""
from __future__ import annotations
import time, json, threading, urllib.parse, urllib.request, re
from concurrent.futures import ThreadPoolExecutor

NOMINATIM_URL      = "https://nominatim.openstreetmap.org/search"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
USER_AGENT         = "ShareholderBenefitMap/6.0 (educational)"

NOMINATIM_MAX_WORKERS  = 3
GOOGLE_MAX_WORKERS     = 10
NOMINATIM_THREAD_DELAY = 0.45

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
    if hasattr(ss, "geocache"):
        with _CACHE_LOCK:
            _CACHE.update(ss.geocache)

def save_session_cache(ss):
    with _CACHE_LOCK:
        ss.geocache = dict(_CACHE)


# ── 住所の短縮バリエーションを生成 ────────────────────────
def _address_variants(address: str) -> list[str]:
    """
    住所を段階的に短縮したバリエーションを返す。
    Nominatimは詳細住所が苦手なので、短い方が当たりやすい。

    例: "川崎市川崎区砂子1-1-6 川崎銀座街ビル 1・2F"
    → ["川崎市川崎区砂子1-1-6", "川崎市川崎区砂子", "川崎市川崎区", "川崎市"]
    """
    # ビル名・フロア情報を除去
    addr = re.sub(r'\s*[\d]+F.*$', '', address, flags=re.IGNORECASE)
    addr = re.sub(r'\s*B[\d]+F.*$', '', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\s*[（(].*?[）)]', '', addr)
    # ビル・館・センター等の施設名を除去
    addr = re.sub(
        r'\s+(?:[^\s]{1,20}(?:ビル|タワー|センター|プラザ|モール|館|店|内|構内)).*$',
        '', addr
    )
    addr = addr.strip()

    variants = []

    # バリアント1: 番地まで（ハイフンを段階的に削る）
    variants.append(addr)

    # バリアント2: 最後のハイフン以降を削除（1-1-6 → 1-1）
    m = re.search(r'(\d+[-－]\d+)[-－]\d+\s*$', addr)
    if m:
        variants.append(addr[:m.end(1)])

    # バリアント3: 番地を全部削除（丁目・番地・号）
    no_banchi = re.sub(
        r'[\d０-９]+(?:[-－][\d０-９]+)*(?:丁目|番地?|号)?[\d０-９]*[-－]?[\d０-９]*\s*$',
        '', addr
    ).strip()
    if no_banchi and no_banchi != addr:
        variants.append(no_banchi)

    # バリアント4: 市区町村レベル（町名を削除）
    city_m = re.match(
        r'((?:北海道|[^\s]{2,4}(?:都|道|府|県))?[\s　]?'
        r'[\u4e00-\u9fff]{1,8}(?:市|区|郡)(?:[\u4e00-\u9fff]{1,8}(?:市|区|町|村))?)',
        no_banchi or addr
    )
    if city_m:
        city = city_m.group(1).strip()
        if city and city not in variants:
            variants.append(city)

    # 重複排除・空文字除去
    seen = set()
    result = []
    for v in variants:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            result.append(v)
    return result


# ── HTTP リクエスト ───────────────────────────────────────
def _nominatim_single(query: str) -> tuple[float, float] | None:
    """Nominatimに1クエリ送信。ウェイトあり。"""
    time.sleep(NOMINATIM_THREAD_DELAY)
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "jp",
        "accept-language": "ja",
    })
    req = urllib.request.Request(
        f"{NOMINATIM_URL}?{params}",
        headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"[Nominatim] {query[:50]}: {e}")
    return None


def _nominatim_with_fallback(address: str) -> tuple[float, float] | None:
    """住所を段階的に短縮しながら Nominatim に問い合わせる。"""
    for variant in _address_variants(address):
        result = _nominatim_single(variant)
        if result:
            return result
    return None


def _google_req(address: str, api_key: str) -> tuple[float, float] | None:
    params = urllib.parse.urlencode({
        "address": address, "key": api_key,
        "language": "ja", "region": "jp",
    })
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


# ── 公開 API ──────────────────────────────────────────────
def geocode_single(
    address: str,
    api_key: str | None = None,
    provider: str = "nominatim",
) -> tuple[float, float] | None:
    """
    1件の住所/地名/駅名を (lat, lng) に変換。
    駅名・地名はそのまま、住所はフォールバック付きで検索。
    """
    if not address:
        return None

    c = _cache_get(address, provider)
    if c != "MISS":
        return c

    if provider == "google" and api_key:
        result = _google_req(address, api_key)
    else:
        # 現在地検索（駅名・地名）: そのまま + "駅" を試す
        result = _nominatim_single(address)
        if not result and not address.endswith("駅"):
            result = _nominatim_single(address + "駅")
        if not result:
            result = _nominatim_single(address + " 日本")

    _cache_set(address, provider, result)
    return result


def geocode_addresses(
    stores: list[dict],
    api_key: str | None = None,
    provider: str = "nominatim",
    progress_callback=None,  # 互換性のため残す（使用しない）
) -> list[dict]:
    """店舗リスト全件を並列ジオコーディング。"""
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

    results: dict[str, tuple[float, float] | None] = {}
    lock = threading.Lock()

    def fetch(addr):
        if provider == "google" and api_key:
            r = _google_req(addr, api_key)
        else:
            r = _nominatim_with_fallback(addr)  # ← フォールバック付き
        _cache_set(addr, provider, r)
        with lock:
            results[addr] = r

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        ex.map(fetch, need)

    for addr, r in results.items():
        if r:
            for s in groups.get(addr, []):
                s["lat"], s["lng"] = r

    return stores
