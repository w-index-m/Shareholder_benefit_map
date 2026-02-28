"""
株主優待 店舗検索 v11
- 駅名入力 → 内蔵座標DB + エリア座標DBで半径N km以内の市区町村を特定
- 該当エリアの住所を持つ店舗を絞り込み表示
- 各店舗にGoogleマップリンク
- 絞り込み結果をまとめてGoogleマップで開くボタン
"""
import streamlit as st
import pandas as pd
import urllib.parse
import math
from pathlib import Path
from pdf_parser import extract_stores_from_pdf
from area_coords import AREA_COORDS, get_station_coord, get_nearby_areas

st.set_page_config(page_title="株主優待 店舗検索", page_icon="🎫", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700&display=swap');
* { font-family: 'Noto Sans JP', sans-serif; }
.store-card {
    background: #fff;
    border: 1px solid #e0e0e0;
    border-left: 5px solid #1a73e8;
    border-radius: 6px;
    padding: 10px 14px;
    margin: 4px 0;
}
.store-name { font-size: 1em; font-weight: 700; color: #202124; }
.store-addr { font-size: 0.85em; color: #444; margin-top: 2px; }
.store-tel  { font-size: 0.82em; color: #888; }
.area-hint  { font-size: 0.78em; color: #1a73e8; margin-top: 2px; }
</style>
""", unsafe_allow_html=True)

st.title("🎫 株主優待 店舗検索")

# ── サイドバー ──────────────────────────────────────
with st.sidebar:
    st.header("📂 PDF読み込み")
    uploaded = st.file_uploader("株主優待PDF", type=["pdf"], accept_multiple_files=True)
    pdf_dir = Path("pdfs")
    preloaded = sorted(pdf_dir.glob("*.pdf")) if pdf_dir.exists() else []
    if preloaded:
        st.caption(f"📁 pdfs/ から {len(preloaded)} 件を自動読み込み")

    st.divider()
    st.header("🔍 駅名・エリア検索")
    keyword = st.text_input(
        "駅名・市区町村",
        placeholder="例：矢向、横浜、新宿、川崎市幸区",
        help="駅名を入力すると周辺エリアの店舗を半径指定で絞り込めます"
    )
    radius_km = st.slider("検索半径 (km)", 1, 30, 10)

# ── PDF解析 ─────────────────────────────────────────
class _FileProxy:
    def __init__(self, p):
        self.name = p.name
        self._data = p.read_bytes()
        self._pos = 0
    def read(self, n=-1):
        d = self._data[self._pos:]; self._pos = len(self._data); return d
    def seek(self, p): self._pos = p

sources = list(uploaded or []) + [_FileProxy(p) for p in preloaded]

if not sources:
    st.info("👆 サイドバーからPDFをアップロードしてください")
    st.stop()

all_stores = []
for src in sources:
    try:
        all_stores.extend(extract_stores_from_pdf(src, source_type="upload"))
    except Exception as e:
        st.error(f"❌ {src.name}: {e}")

if not all_stores:
    st.error("店舗情報を抽出できませんでした")
    st.stop()

# ── 都道府県フィルター ──────────────────────────────
all_prefs = sorted(set(s.get("pref", "") for s in all_stores if s.get("pref")))
with st.sidebar:
    selected_prefs = st.multiselect("都道府県で絞り込み", all_prefs, default=all_prefs)

# ── 駅名→座標→周辺エリア絞り込み ───────────────────
kw = keyword.strip()
station_coord = None
nearby_areas = []
search_mode = "keyword"  # "station" or "keyword"

if kw:
    coord = get_station_coord(kw)
    if coord:
        station_coord = coord
        nearby_areas = get_nearby_areas(coord[0], coord[1], radius_km)
        search_mode = "station"

# ── フィルタリング ───────────────────────────────────
filtered = [s for s in all_stores if s.get("pref") in selected_prefs]

if kw:
    if search_mode == "station" and nearby_areas:
        # 駅モード：周辺エリアの住所を持つ店舗
        filtered = [
            s for s in filtered
            if any(area in s.get("address", "") for area in nearby_areas)
        ]
    else:
        # キーワードモード：住所・店舗名の部分一致
        filtered = [
            s for s in filtered
            if kw in s.get("address", "") or kw in s.get("name", "")
               or kw.replace("駅","") in s.get("address", "")
        ]

# ── ヘッダー表示 ─────────────────────────────────────
if kw and search_mode == "station":
    st.markdown(
        f"📍 **{kw}** 周辺 **{radius_km}km** 以内のエリア: "
        f"`{'` `'.join(nearby_areas[:6])}{'` など' if len(nearby_areas)>6 else '`'}"
    )
    st.markdown(f"全 **{len(all_stores)}** 件中 **{len(filtered)}** 件を表示")
elif kw:
    st.markdown(f"全 **{len(all_stores)}** 件中 **{len(filtered)}** 件（「{kw}」で絞り込み）")
else:
    st.markdown(f"全 **{len(all_stores)}** 件を表示")

# ── アクションボタン ─────────────────────────────────
if filtered and kw:
    col1, col2 = st.columns(2)
    with col1:
        # Googleマップで駅周辺を開く
        gmap_q = urllib.parse.quote(kw)
        st.link_button(
            f"🗺️ 「{kw}」周辺をGoogleマップで開く",
            f"https://www.google.com/maps/search/{gmap_q}",
            use_container_width=True,
        )
    with col2:
        df_dl = pd.DataFrame([{
            "店舗名": s["name"], "住所": s["address"], "電話": s.get("tel",""),
            "GoogleMap": "https://www.google.com/maps/search/?api=1&query="
                         + urllib.parse.quote(s["address"])
        } for s in filtered])
        st.download_button(
            "⬇️ CSVダウンロード（Googleマイマップ用）",
            df_dl.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"優待_{kw or '全件'}.csv", mime="text/csv",
            use_container_width=True,
        )

if not filtered:
    if kw and search_mode == "station":
        st.warning(f"「{kw}」周辺 {radius_km}km 以内に店舗が見つかりませんでした。半径を広げるか、市区町村名で直接検索してみてください。")
    elif kw:
        st.warning(f"「{kw}」に一致する店舗が見つかりませんでした。\n\n💡 **ヒント**: 矢向駅のような駅名は「矢向」と入力してください（駅データに登録されている場合、半径検索が使えます）")
    else:
        st.info("キーワードを入力してください")
    st.stop()

st.divider()

# ── 店舗リスト ───────────────────────────────────────
pref_order = {p: i for i, p in enumerate(all_prefs)}
filtered_sorted = sorted(
    filtered,
    key=lambda s: (pref_order.get(s.get("pref",""), 999), s.get("address",""))
)

cur_pref = None
for s in filtered_sorted:
    pref = s.get("pref", "")
    if pref != cur_pref:
        cur_pref = pref
        st.subheader(f"📍 {pref}")

    addr = s.get("address", "")
    gmap_url = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(addr)

    # どのエリアにマッチしたか表示
    matched_area = next((a for a in nearby_areas if a in addr), "") if nearby_areas else ""

    c1, c2 = st.columns([6, 1])
    with c1:
        area_hint = f'<div class="area-hint">📌 {matched_area}</div>' if matched_area else ""
        st.markdown(
            f'<div class="store-card">'
            f'<div class="store-name">{s.get("name","")}</div>'
            f'<div class="store-addr">📮 {addr}</div>'
            f'<div class="store-tel">📞 {s.get("tel","")}</div>'
            f'{area_hint}'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.link_button("🗺️ 地図", gmap_url, use_container_width=True)
