"""
株主優待 近隣店舗マップ
- 複数社PDF 対応
- Google Maps APIキー不要（OpenStreetMap + Folium）
- スキャンPDF OCR 対応（pytesseract）
- 現在地から近い順に表示
"""

import streamlit as st
import pandas as pd
import math
import urllib.parse
from pathlib import Path


def urllib_quote(s: str) -> str:
    return urllib.parse.quote(str(s))

from pdf_parser import extract_stores_from_pdf
from geocoder import geocode_addresses, geocode_single

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ページ設定
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.set_page_config(
    page_title="株主優待 近隣店舗マップ",
    page_icon="🎫",
    layout="wide",
    initial_sidebar_state="expanded",
)

# カスタムCSS
st.markdown("""
<style>
.store-card {
    background: #f8f9fa;
    border-left: 4px solid #e74c3c;
    padding: 10px 14px;
    margin: 6px 0;
    border-radius: 4px;
}
.distance-badge {
    background: #e74c3c;
    color: white;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.8em;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

st.title("🎫 株主優待 近隣店舗マップ")
st.caption("PDFをアップロードして、現在地から近い優待店舗を地図で確認できます（無料・APIキー不要）")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# サイドバー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with st.sidebar:
    st.header("📍 現在地を設定")
    current_address = st.text_input(
        "住所 / 駅名 / ランドマーク",
        placeholder="例: 東京駅、渋谷区渋谷2-1-1、梅田駅",
        help="都市名・駅名でも検索できます"
    )

    st.divider()
    st.header("🔍 絞り込み")
    max_distance_km = st.slider("最大距離 (km)", 1, 200, 50)
    max_results = st.slider("最大表示件数", 5, 200, 50)

    st.divider()
    st.header("⚙️ 詳細設定")
    ocr_lang = st.selectbox(
        "OCR 言語",
        ["jpn+eng", "jpn", "eng"],
        index=0,
        help="スキャンPDFのOCR言語設定"
    )
    geocode_provider = st.selectbox(
        "住所変換（ジオコーダー）",
        ["Nominatim（無料・日本語OK）", "Google Maps API（高精度）"],
        index=0,
    )
    if "Google Maps" in geocode_provider:
        gmaps_key = st.text_input("Google Maps API キー", type="password")
    else:
        gmaps_key = None
        st.info("💡 Nominatimは無料で使えます（精度はGoogle比でやや劣ります）")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PDF アップロード + pdfs/ フォルダ自動検出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.subheader("📄 株主優待PDF をアップロード")

col_up, col_hint = st.columns([3, 2])
with col_up:
    uploaded_files = st.file_uploader(
        "PDFを選択（複数社・複数ファイル可）",
        type=["pdf"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
with col_hint:
    st.info(
        "**複数社対応:** 複数のPDFを同時にアップロードできます。\n\n"
        "または `pdfs/` フォルダに入れておくと自動読み込みされます。"
    )

# pdfs/ フォルダ内の既存PDF
pdf_folder = Path("pdfs")
existing_pdfs = sorted(pdf_folder.glob("*.pdf")) if pdf_folder.exists() else []

# 全PDF ソース統合
sources: list[tuple[str, any, str]] = []  # (type, source, label)
for f in (uploaded_files or []):
    sources.append(("upload", f, f.name))
for p in existing_pdfs:
    sources.append(("file", p, p.name))

if not sources:
    st.markdown("---")
    st.markdown("""
    ### 📋 使い方
    1. 上の「PDFを選択」から株主優待PDFをアップロード
    2. 左のサイドバーで現在地（住所・駅名）を入力
    3. 地図に近い店舗が表示されます
    
    **対応PDF形式:**
    - 📝 テキストPDF（そのまま読み取り）
    - 🖼️ スキャン画像PDF（OCRで自動認識）
    """)
    st.stop()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PDF 解析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
all_stores: list[dict] = []
company_labels: list[str] = []

progress_bar = st.progress(0, text="PDF を解析中...")
errors = []

for idx, (src_type, source, label) in enumerate(sources):
    progress_bar.progress((idx) / len(sources), text=f"📖 解析中: {label}")
    try:
        stores = extract_stores_from_pdf(source, src_type, ocr_lang=ocr_lang)
        for s in stores:
            s.setdefault("source_file", label)
        all_stores.extend(stores)
        if stores:
            company_labels.append(f"✅ {label}（{len(stores)} 件）")
        else:
            company_labels.append(f"⚠️ {label}（店舗情報なし）")
    except Exception as e:
        errors.append(f"❌ {label}: {e}")
        company_labels.append(f"❌ {label}（エラー）")

progress_bar.progress(1.0, text="解析完了")

# 結果サマリー
with st.expander("📊 PDF 解析結果", expanded=bool(errors)):
    for lbl in company_labels:
        st.markdown(f"- {lbl}")
    for err in errors:
        st.error(err)

if not all_stores:
    st.error("店舗情報を抽出できませんでした。PDFの内容・形式を確認してください。")
    st.stop()

# 会社フィルター
all_companies = sorted(set(s.get("company", "不明") for s in all_stores))
if len(all_companies) > 1:
    selected_companies = st.multiselect(
        "🏢 表示する会社を選択",
        options=all_companies,
        default=all_companies,
    )
    filtered_stores = [s for s in all_stores if s.get("company") in selected_companies]
else:
    filtered_stores = all_stores

st.success(f"✅ 合計 **{len(filtered_stores)}** 件の店舗情報を取得")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ジオコーディング（住所 → 緯度経度）並列処理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
use_google = gmaps_key is not None and len(gmaps_key) > 10
provider   = "google" if use_google else "nominatim"
workers    = 10 if use_google else 3

# ユニーク住所数（実際のAPI呼び出し回数）
unique_addr_count = len(set(
    s.get("address","") for s in filtered_stores if s.get("address")
))

st.markdown(
    f"📍 **座標変換中** — {unique_addr_count} 件のユニーク住所を "
    f"{'Google API' if use_google else 'Nominatim'}（**{workers}並列**）で処理します"
)

geo_progress  = st.progress(0)
geo_status    = st.empty()

# キャッシュ済み件数を事前カウントして表示
from pathlib import Path as _Path
import sqlite3 as _sqlite3, hashlib as _hashlib
_cache_exists = _Path("geocode_cache.db").exists()
if _cache_exists:
    try:
        _conn = _sqlite3.connect("geocode_cache.db")
        _cached_keys = {
            row[0] for row in _conn.execute("SELECT key FROM geocache").fetchall()
        }
        _conn.close()
        _pre_hits = sum(
            1 for s in filtered_stores
            if _hashlib.md5(f"{provider}:{s.get('address','')}".encode()).hexdigest()
               in _cached_keys
        )
        if _pre_hits > 0:
            geo_status.info(f"⚡ {_pre_hits} 件はキャッシュから即時取得、残り {unique_addr_count - _pre_hits} 件をAPIで取得します")
    except Exception:
        pass

def _update_progress(done: int, total: int):
    pct = done / total if total > 0 else 1.0
    geo_progress.progress(min(pct, 1.0))
    elapsed_est = ""
    if provider == "nominatim" and done > 0:
        remaining = total - done
        # 3並列×0.4秒 → 実効速度 約7.5件/秒
        est_sec = remaining / 7.5
        if est_sec > 60:
            elapsed_est = f"（残り約 {est_sec/60:.0f} 分）"
        else:
            elapsed_est = f"（残り約 {est_sec:.0f} 秒）"
    geo_status.markdown(f"🔄 {done} / {total} 件完了 {elapsed_est}")

filtered_stores = geocode_addresses(
    filtered_stores,
    api_key=gmaps_key if use_google else None,
    provider=provider,
    progress_callback=_update_progress,
)

geo_progress.progress(1.0)
geocoded = [s for s in filtered_stores if s.get("lat") and s.get("lng")]
geo_status.success(f"✅ 座標取得完了: {len(geocoded)}/{len(filtered_stores)} 件成功")

if not geocoded:
    st.error("住所から座標を取得できませんでした。住所の書式を確認してください。")
    st.stop()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 現在地の取得
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
origin_lat, origin_lng = None, None

if current_address:
    with st.spinner(f"🔍 「{current_address}」の座標を検索中..."):
        result = geocode_single(
            current_address,
            api_key=gmaps_key if use_google else None,
            provider="google" if use_google else "nominatim",
        )
    if result:
        origin_lat, origin_lng = result
        st.success(f"✅ 現在地: {current_address}")
    else:
        st.warning("現在地の座標を取得できませんでした。もう少し詳しい住所を試してください。")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 距離計算・ソート
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def haversine(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


display_stores = geocoded
if origin_lat and origin_lng:
    for s in display_stores:
        s["distance_km"] = haversine(origin_lat, origin_lng, s["lat"], s["lng"])
    display_stores.sort(key=lambda x: x.get("distance_km", 9999))
    display_stores = [s for s in display_stores if s.get("distance_km", 9999) <= max_distance_km]

display_stores = display_stores[:max_results]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 地図表示（Folium × OpenStreetMap → APIキー不要）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.subheader("🗺️ 近隣店舗マップ")

try:
    import folium
    from streamlit_folium import st_folium

    center_lat = origin_lat or display_stores[0]["lat"]
    center_lng = origin_lng or display_stores[0]["lng"]

    # ズームレベル自動計算
    if origin_lat and display_stores:
        dists = [s.get("distance_km", 10) for s in display_stores]
        max_d = max(dists) if dists else 10
        zoom = 13 if max_d < 5 else 11 if max_d < 20 else 9 if max_d < 50 else 7
    else:
        zoom = 11

    m = folium.Map(
        location=[center_lat, center_lng],
        zoom_start=zoom,
        tiles="OpenStreetMap",
    )

    # 現在地マーカー
    if origin_lat and origin_lng:
        folium.Marker(
            [origin_lat, origin_lng],
            popup=folium.Popup(f"<b>📍 現在地</b><br>{current_address}", max_width=200),
            tooltip="📍 現在地",
            icon=folium.Icon(color="blue", icon="home", prefix="fa"),
        ).add_to(m)

    # 会社ごとに色分け
    company_colors = {}
    color_list = ["red", "green", "orange", "purple", "darkblue", "darkred",
                  "cadetblue", "darkgreen", "pink", "gray"]
    for i, c in enumerate(all_companies):
        company_colors[c] = color_list[i % len(color_list)]

    # 店舗マーカー
    for i, s in enumerate(display_stores, 1):
        company = s.get("company", "")
        color = company_colors.get(company, "red")
        dist_text = f"<br>📏 現在地から {s['distance_km']:.1f} km" if "distance_km" in s else ""
        gmaps_url = f"https://www.google.com/maps/search/?api=1&query={s['lat']},{s['lng']}"

        popup_html = f"""
        <div style='min-width:200px'>
        <b style='font-size:1.1em'>{s.get('name', '不明')}</b><br>
        🏢 {company}<br>
        📮 {s.get('address', '不明')}{dist_text}<br><br>
        <a href='{gmaps_url}' target='_blank'
           style='background:#4285F4;color:white;padding:4px 8px;
                  border-radius:4px;text-decoration:none;font-size:0.85em'>
           🗺️ Google Maps で開く
        </a>
        </div>
        """
        folium.Marker(
            [s["lat"], s["lng"]],
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=f"{i}. {s.get('name', '不明')} ({company})",
            icon=folium.Icon(color=color, icon="cutlery", prefix="fa"),
        ).add_to(m)

    # 凡例
    if len(all_companies) > 1:
        legend_html = "<div style='background:white;padding:8px;border-radius:4px;border:1px solid #ccc'>"
        for comp, col in company_colors.items():
            icon_colors = {
                "red": "#e74c3c", "green": "#27ae60", "orange": "#e67e22",
                "purple": "#8e44ad", "darkblue": "#2c3e50", "darkred": "#c0392b",
                "cadetblue": "#5dade2", "darkgreen": "#1e8449", "pink": "#f1948a",
                "gray": "#95a5a6"
            }
            hex_col = icon_colors.get(col, "#e74c3c")
            legend_html += f"<span style='color:{hex_col}'>●</span> {comp}<br>"
        legend_html += "</div>"
        m.get_root().html.add_child(folium.Element(
            f"<div style='position:fixed;top:10px;right:10px;z-index:9999'>{legend_html}</div>"
        ))

    st_folium(m, use_container_width=True, height=520, returned_objects=[])

except ImportError:
    st.warning(
        "地図表示には `folium` と `streamlit-folium` が必要です。\n"
        "`pip install folium streamlit-folium` を実行してください。"
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 店舗リスト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.subheader(f"📋 店舗一覧（{len(display_stores)} 件）")

rows = []
for i, s in enumerate(display_stores, 1):
    dist = f"{s['distance_km']:.1f} km" if "distance_km" in s else "-"
    gmaps_url = f"https://www.google.com/maps/search/?api=1&query={urllib_quote(s.get('address', ''))}"
    rows.append({
        "#": i,
        "店舗名": s.get("name", "不明"),
        "会社": s.get("company", ""),
        "住所": s.get("address", "不明"),
        "現在地からの距離": dist,
        "Google Maps": f"https://www.google.com/maps/search/?api=1&query={s['lat']},{s['lng']}",
    })

df = pd.DataFrame(rows)

st.dataframe(
    df,
    column_config={
        "Google Maps": st.column_config.LinkColumn("🗺️ 地図", display_text="開く"),
    },
    use_container_width=True,
    hide_index=True,
)

# CSV ダウンロード
csv_df = df.drop(columns=["Google Maps"])
st.download_button(
    label="⬇️ CSV でダウンロード",
    data=csv_df.to_csv(index=False, encoding="utf-8-sig"),
    file_name="優待店舗リスト.csv",
    mime="text/csv",
)

