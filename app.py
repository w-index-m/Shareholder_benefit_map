"""
株主優待 店舗検索 v10
- 駅名・エリア入力 → 住所一致で絞り込み
- 絞り込み結果を「Googleマップで一括検索」ボタンで開く
- 各店舗にも個別Googleマップリンク
- Nominatim/座標変換なし・完全無料
"""
import streamlit as st
import pandas as pd
import urllib.parse
from pathlib import Path
from pdf_parser import extract_stores_from_pdf

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
    st.header("🔍 エリア検索")
    keyword = st.text_input(
        "駅名・市区町村",
        placeholder="例：横浜、新宿、川崎市",
    )

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

# ── キーワード絞り込み ──────────────────────────────
filtered = [s for s in all_stores if s.get("pref") in selected_prefs]

kw = keyword.strip()
if kw:
    filtered = [
        s for s in filtered
        if kw in s.get("address", "") or kw in s.get("name", "")
    ]

# ── 結果ヘッダー＋一括Googleマップボタン ─────────────
st.markdown(f"**{len(all_stores)}件中 {len(filtered)}件**を表示" +
            (f"（「{kw}」で絞り込み）" if kw else ""))

if filtered and kw:
    # 絞り込み結果の住所を「/」で連結してGoogleマップ検索
    # ※ 多すぎるとURLが長くなるので最大15件
    addrs = [s.get("address", "") for s in filtered[:15]]
    # Googleマップの複数地点検索：住所をスペース区切りでまとめて検索
    # 実用的には「エリア名 + 最初の数店舗名」で検索するのが見やすい
    store_names = "　".join(s.get("name", "") for s in filtered[:8])
    bulk_query = urllib.parse.quote(f"{kw} {store_names}")
    bulk_url = f"https://www.google.com/maps/search/{bulk_query}"

    # シンプルに「駅名」だけで検索してその周辺を見せる方が実用的
    area_url = f"https://www.google.com/maps/search/{urllib.parse.quote(kw)}"

    col1, col2 = st.columns(2)
    with col1:
        st.link_button(
            f"🗺️ 「{kw}」をGoogleマップで開く（周辺確認）",
            area_url,
            use_container_width=True,
        )
    with col2:
        # CSVダウンロード
        df_dl = pd.DataFrame([{
            "店舗名": s["name"], "住所": s["address"], "電話": s.get("tel",""),
            "GoogleMap": "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(s["address"])
        } for s in filtered])
        st.download_button(
            "⬇️ CSVダウンロード（Googleマイマップ用）",
            df_dl.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"優待_{kw or '全件'}.csv", mime="text/csv",
            use_container_width=True,
        )

if not filtered:
    st.warning("条件に一致する店舗がありません")
    st.stop()

st.divider()

# ── 店舗リスト（都道府県グループ表示）───────────────
pref_order = {p: i for i, p in enumerate(all_prefs)}
filtered_sorted = sorted(filtered, key=lambda s: (pref_order.get(s.get("pref",""), 999), s.get("address","")))

cur_pref = None
for s in filtered_sorted:
    pref = s.get("pref", "")
    if pref != cur_pref:
        cur_pref = pref
        st.subheader(f"📍 {pref}")

    addr = s.get("address", "")
    gmap_url = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(addr)

    c1, c2 = st.columns([6, 1])
    with c1:
        st.markdown(
            f'<div class="store-card">'
            f'<div class="store-name">{s.get("name","")}</div>'
            f'<div class="store-addr">📮 {addr}</div>'
            f'<div class="store-tel">📞 {s.get("tel","")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.link_button("🗺️ 地図", gmap_url, use_container_width=True)
