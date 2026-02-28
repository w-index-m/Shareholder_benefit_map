"""
pdf_parser.py
クリエイト・レストランツ(CRH) と WDI の両方の株主優待PDFに対応したパーサー
"""

from __future__ import annotations
import re
import io
from pathlib import Path

PREFS = [
    "北海道","青森","岩手","宮城","秋田","山形","福島",
    "茨城","栃木","群馬","埼玉","千葉","東京","神奈川",
    "新潟","富山","石川","福井","山梨","長野","岐阜","静岡","愛知","三重",
    "滋賀","京都","大阪","兵庫","奈良","和歌山",
    "鳥取","島根","岡山","広島","山口",
    "徳島","香川","愛媛","高知",
    "福岡","佐賀","長崎","熊本","大分","宮崎","鹿児島","沖縄"
]

# 都道府県の見出し判定用（クリレス用）
SECTION_RE = re.compile(r'^(' + '|'.join(PREFS) + r')(?:都|道|府|県)?(?:　| )*$')

def clean_text(text: str) -> str:
    """不要な引用符や連続する改行を整理する"""
    # WDI形式の引用符と改行を削除
    text = text.replace('"', '').replace('\r', '')
    # 住所内の不自然な改行（スペース+改行など）を結合
    text = re.sub(r'\n\s+', '', text)
    return text

def parse_wdi_format(full_text: str, company: str) -> list[dict]:
    """WDI形式（カンマ区切り風）の解析"""
    stores = []
    # 引用符とカンマのパターンで分割を試みる
    # WDIのPDFは "店名","住所","営業時間","電話番号" の並びが多い
    blocks = full_text.split('"\n"')
    
    for block in blocks:
        # クリーンアップ
        parts = [p.strip().replace('\n', '') for p in block.split('","')]
        
        if len(parts) >= 2:
            name = parts[0].replace('"', '')
            address = parts[1].replace('"', '')
            tel = ""
            # 電話番号を探す（0から始まる数字とハイフン）
            for p in parts:
                tel_match = re.search(r'\d{2,4}-\d{2,4}-\d{4}', p)
                if tel_match:
                    tel = tel_match.group()
                    break
            
            # 住所から都道府県を特定
            pref = ""
            for p in PREFS:
                if address.startswith(p):
                    pref = p
                    break
            
            if "店名" in name or not address:
                continue

            stores.append({
                "name": name,
                "address": address,
                "tel": tel,
                "pref": pref,
                "company": company
            })
    return stores

def parse_create_res_format(full_text: str, company: str) -> list[dict]:
    """クリエイト・レストランツ形式（行ベース）の解析"""
    stores = []
    current_pref = ""
    
    for line in full_text.split('\n'):
        line = line.strip()
        if not line: continue
        
        # 都道府県見出しの更新
        m = SECTION_RE.match(line)
        if m:
            current_pref = m.group(1)
            continue
        
        # 住所と電話番号の抽出
        tel_match = re.search(r'\d{2,4}-\d{2,4}-\d{4}', line)
        if not tel_match: continue
        
        tel = tel_match.group()
        # 電話番号より前を店名・住所として扱う
        pre_tel = line[:tel_match.start()].strip()
        
        # 住所の開始位置（都道府県名）を探す
        addr_start = -1
        for p in PREFS:
            idx = pre_tel.find(p)
            if idx != -1:
                addr_start = idx
                if not current_pref: current_pref = p
                break
        
        if addr_start != -1:
            store_name = pre_tel[:addr_start].strip()
            address = pre_tel[addr_start:].strip()
            
            stores.append({
                "name": store_name,
                "address": address,
                "tel": tel,
                "pref": current_pref,
                "company": company
            })
            
    return stores

def extract_stores_from_pdf(source, source_type: str = "upload") -> list[dict]:
    import pdfplumber
    
    # 会社名の取得
    raw_name = source.name if hasattr(source, "name") else Path(source).stem
    company = re.sub(r"\d+|株主優待|優待|案内|PDF|\.pdf|_|\s", "", raw_name).strip() or raw_name

    # PDF読み込み
    if source_type == "upload":
        data = source.read()
        source.seek(0)
    else:
        data = Path(source).read_bytes()

    text_pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text_pages.append(page.extract_text() or "")
    
    full_text = "\n".join(text_pages)

    # 形式判定と実行
    if '"' in full_text and '","' in full_text:
        # WDI形式と判断
        return parse_wdi_format(full_text, company)
    else:
        # クレス（標準行）形式と判断
        return parse_create_res_format(full_text, company)
      
