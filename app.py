"""
株主優待 店舗検索アプリ v9
- Nominatim/座標変換 完全削除
- キーワード（駅名・市区町村）で住所文字列を検索
- 各店舗にGoogleマップリンク（住所渡し、APIキー不要）
- 絞り込み結果をまとめてGoogleマップ検索するボタン
- CSVダウンロード（Googleマイマップにインポート可能）
"""
import streamlit as st
import pandas as pd
import urllib.parse
from pathlib import Path
from pdf_parser import extract_stores_from_pdf

st.set_page_config(
    page_title="株主優待 店舗検索",
    page_icon="🎫",
    layout="wide",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700&display=swap');
html, body, [class*="css"] { font-family: 'Noto Sans JP', sans-serif; }
.store-card {
    background: #fff;
    border: 1px solid #e0e0e0;
    border-left: 5px solid #1a73e8;
    border-radius: 6px;
    padding: 12px 16px;
    margin: 6px 0;
}
.store-brand { font-size: 0.8em; color: #666; }
.store-name  { font-size: 1.05em; font-weight: 700; color: #202124; }
.store-addr  { font-size: 0.85em; color: #444; margin-top: 2px; }
.store-tel   { font-size: 0.82em; color: #888; }
</style>
""", unsafe_allow_html=True)

st.title("🎫 株主優待 店舗検索")
st.caption("PDFを読み込んで、駅名・エリアで優待店舗を絞り込めます（完全無料・APIキー不要）")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# サイドバー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with st.sidebar:
    st.header("📂 PDFを読み込む")
    uploaded = st.file_uploader(
        "株主優待PDF",
        type=["pdf"],
        accept_multiple_files=True,
    )

    # pdfs/ フォルダも自動読み込み
    pdf_dir = Path("pdfs")
    preloaded = sorted(pdf_dir.glob("*.pdf")) if pdf_dir.exists() else []
    if preloaded:
        st.caption(f"📁 pdfs/ フォルダから {len(preloaded)} 件自動読み込み")

    st.divider()
    st.header("🔍 エリア絞り込み")
    keyword = st.text_input(
        "駅名・市区町村・キーワード",
        placeholder="例：横浜、新宿、川崎市、渋谷",
        help="住所・店舗名を部分一致で検索します"
    )

    st.divider()
    st.header("🗂️ 都道府県フィルター")
    selected_prefs = []  # 後で動的生成

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PDF 解析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
all_stores = []

sources = list(uploaded or [])

# preloaded ファイルを File-like に変換
class _FileProxy:
    def __init__(self, p: Path):
        self.name = p.name
        self._data = p.read_bytes()
        self._pos = 0
    def read(self, n=-1):
        d = self._data[self._pos:]
        self._pos = len(self._data)
        return d
    def seek(self, p): self._pos = p

for p in preloaded:
    sources.append(_FileProxy(p))

if not sources:
    st.info("👆 サイドバーからPDFをアップロードしてください")
    st.stop()

for src in sources:
    try:
        stores = extract_stores_from_pdf(src, source_type="upload")
        all_stores.extend(stores)
    except Exception as e:
        st.error(f"❌ {src.name}: {e}")

if not all_stores:
    st.error("店舗情報を抽出できませんでした")
    st.stop()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 都道府県フィルター（サイドバー動的生成）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
all_prefs = sorted(set(s.get("pref", "") for s in all_stores if s.get("pref")))

with st.sidebar:
    selected_prefs = st.multiselect(
        "都道府県",
        options=all_prefs,
        default=all_prefs,
        help="表示する都道府県を選択"
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 絞り込み
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
filtered = all_stores

# 都道府県フィルター
if selected_prefs:
    filtered = [s for s in filtered if s.get("pref") in selected_prefs]

# キーワード検索（住所・店舗名を部分一致）
if keyword.strip():
    kw = keyword.strip()
    filtered = [
        s for s in filtered
        if kw in s.get("address", "") or kw in s.get("name", "")
    ]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 結果ヘッダー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
col_stat, col_btn = st.columns([3, 2])
with col_stat:
    total_msg = f"全 **{len(all_stores)}** 件中 **{len(filtered)}** 件を表示"
    if keyword.strip():
        total_msg += f"（キーワード: 「{keyword}」）"
    st.markdown(total_msg)

with col_btn:
    if filtered:
        # まとめてGoogleマップで検索（最初の1件の住所で検索し、周辺を確認）
        if keyword.strip():
            gmaps_area_url = (
                "https://www.google.com/maps/search/"
                + urllib.parse.quote(keyword.strip() + " 周辺")
            )
        else:
            gmaps_area_url = "https://www.google.com/maps"
        st.link_button(
            f"🗺️ 「{keyword or 'エリア'}」をGoogleマップで開く",
            gmaps_area_url,
            use_container_width=True,
        )

if not filtered:
    st.warning("条件に一致する店舗が見つかりませんでした")
    st.stop()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CSVダウンロード（Googleマイマップインポート用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
df = pd.DataFrame([{
    "店舗名":     s.get("name", ""),
    "住所":       s.get("address", ""),
    "電話番号":   s.get("tel", ""),
    "都道府県":   s.get("pref", ""),
    "GoogleMap":  "https://www.google.com/maps/search/?api=1&query="
                  + urllib.parse.quote(s.get("address", "")),
} for s in filtered])

col_dl1, col_dl2 = st.columns(2)
with col_dl1:
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ CSVダウンロード（Googleマイマップ用）",
        data=csv_bytes,
        file_name=f"優待店舗_{keyword or '全件'}.csv",
        mime="text/csv",
        use_container_width=True,
        help="Googleマイマップ → インポート → このCSVを選ぶと地図にピンが立ちます",
    )
with col_dl2:
    st.caption("💡 Googleマイマップにこの CSV をインポートすると全店舗が地図上にピン表示されます")

st.divider()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 店舗リスト表示
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 都道府県ごとにグループ表示
from itertools import groupby

pref_order = {p: i for i, p in enumerate(all_prefs)}
filtered_sorted = sorted(filtered, key=lambda s: (
    pref_order.get(s.get("pref", ""), 999),
    s.get("address", "")
))

current_pref = None
for s in filtered_sorted:
    pref = s.get("pref", "")
    if pref != current_pref:
        current_pref = pref
        st.subheader(f"📍 {pref}")

    name    = s.get("name", "")
    address = s.get("address", "")
    tel     = s.get("tel", "")
    gmaps_url = (
        "https://www.google.com/maps/search/?api=1&query="
        + urllib.parse.quote(address)
    )

    with st.container():
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(
                f"""<div class="store-card">
                  <div class="store-name">{name}</div>
                  <div class="store-addr">📮 {address}</div>
                  <div class="store-tel">📞 {tel}</div>
                </div>""",
                unsafe_allow_html=True,
            )
        with c2:
            st.link_button("🗺️ 地図", gmaps_url, use_container_width=True)
