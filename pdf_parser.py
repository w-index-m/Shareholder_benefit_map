"""
pdf_parser.py
クリエイトレストランホールディングス株主優待PDF に特化したパーサー

PDF形式:
  各行: ブランド名 店舗名 住所（市区町村+番地） ビル名等 電話番号
  都道府県はセクション見出しとして単独行で出現

OCRは不要 (テキスト埋め込みPDF)。pdfplumber で直接読み取る。
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

SECTION_RE = re.compile(
    r'^(' + '|'.join(PREFS) + r')(?:都|道|府|県)?(?:　| )*$'
)
CITY_START_RE = re.compile(
    r'(?:' + '|'.join(PREFS) + r')(?:都|道|府|県)?'
    r'[\u4e00-\u9fff\w]{1,10}(?:市|区|郡)',
    re.UNICODE,
)
PREF_ONLY_RE = re.compile('(?:' + '|'.join(PREFS) + ')(?:都|道|府|県)?')
TEL_RE = re.compile(r'\d{2,4}-\d{2,4}-\d{4}')
SKIP_RE = re.compile(
    r'^(?:株主様|ご利用|店舗は|ご理解|なお|注|※|・・|ページ|\d+$|Copyright|http|年月日|利用上限|ゴルフ)',
    re.UNICODE,
)


def _find_address_start(text: str):
    m = CITY_START_RE.search(text)
    if m:
        return m.start()
    m = PREF_ONLY_RE.search(text)
    if m:
        return m.start()
    m = re.search(r'[\u4e00-\u9fff]{1,6}(?:市|区|町|村)', text)
    if m:
        return m.start()
    return None


def _parse_stores_from_text(text: str, company: str) -> list[dict]:
    stores: list[dict] = []
    current_pref = ""

    for line in text.split("\n"):
        line = line.strip()
        if not line or SKIP_RE.match(line):
            continue

        sec = SECTION_RE.match(line)
        if sec:
            current_pref = sec.group(1)
            continue

        tel_m = TEL_RE.search(line)
        if not tel_m:
            continue

        tel = tel_m.group(0)
        before_tel = line[:tel_m.start()].strip()

        addr_start = _find_address_start(before_tel)
        if addr_start is None:
            continue

        store_name = before_tel[:addr_start].strip()
        address    = before_tel[addr_start:].strip()

        if not store_name or len(store_name) < 1:
            continue
        if not address or len(address) < 4:
            continue

        stores.append({
            "name":    store_name,
            "address": address,
            "tel":     tel,
            "pref":    current_pref,
            "company": company,
        })

    return stores


def _read_bytes(source, source_type: str) -> bytes:
    if source_type == "upload":
        data = source.read()
        source.seek(0)
        return data
    return Path(source).read_bytes()


def extract_stores_from_pdf(
    source,
    source_type: str = "upload",
    ocr_lang: str = "jpn+eng",
) -> list[dict]:
    import pdfplumber

    raw_name = source.name if hasattr(source, "name") else Path(source).stem
    company = re.sub(
        r"\d{4}|\d+年度?|株主優待|優待|案内|ご利用|PDF|\.pdf|_|\s",
        "", raw_name
    ).strip() or raw_name

    data = _read_bytes(source, source_type)

    text_pages = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                text_pages.append(t)
    except Exception as e:
        raise RuntimeError(f"PDF読み取りエラー: {e}")

    full_text = "\n".join(text_pages)
    if not full_text.strip():
        raise ValueError("PDFからテキストを抽出できませんでした")

    stores = _parse_stores_from_text(full_text, company)

    seen: set[tuple] = set()
    unique = []
    for s in stores:
        key = (s["name"], s["address"])
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return unique
