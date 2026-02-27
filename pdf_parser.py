"""
pdf_parser.py
株主優待PDF から店舗名・住所を抽出するモジュール

優先順位:
1. pdfplumber でテキスト抽出（通常のPDF）
2. pytesseract OCR（スキャン画像PDF）← デフォルト有効
"""

from __future__ import annotations
import re
import io
from pathlib import Path


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# テキスト抽出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _read_bytes(source, source_type: str) -> bytes:
    """source から bytes を読み出す"""
    if source_type == "upload":
        data = source.read()
        source.seek(0)
        return data
    else:
        return Path(source).read_bytes()


def _extract_text_pdfplumber(data: bytes) -> str:
    """pdfplumber でテキスト抽出（テキストPDF 向け）"""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = []
        for page in pdf.pages:
            # テキスト抽出
            text = page.extract_text() or ""
            # テーブルも抽出して結合
            tables = page.extract_tables() or []
            for table in tables:
                for row in table:
                    if row:
                        text += "\n" + "\t".join(str(c) if c else "" for c in row)
            pages.append(text)
    return "\n".join(pages)


def _extract_text_ocr(data: bytes, lang: str = "jpn+eng") -> str:
    """
    pytesseract OCR でスキャンPDF を読み取る
    
    事前インストール:
      macOS:   brew install tesseract tesseract-lang
      Ubuntu:  sudo apt install tesseract-ocr tesseract-ocr-jpn
      pip:     pip install pytesseract pdf2image Pillow
    """
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as e:
        raise ImportError(
            f"OCR 必要パッケージ未インストール: {e}\n"
            "実行: pip install pytesseract pdf2image Pillow\n"
            "Tesseract: brew install tesseract tesseract-lang  or  "
            "sudo apt install tesseract-ocr tesseract-ocr-jpn"
        )

    # PDF → 画像変換（解像度300dpiで精度UP）
    images = convert_from_bytes(data, dpi=300)
    texts = []
    for img in images:
        # ページごとOCR
        custom_config = r"--oem 3 --psm 6"  # LSTM OCR, 単一ブロック
        text = pytesseract.image_to_string(img, lang=lang, config=custom_config)
        texts.append(text)
    return "\n".join(texts)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 住所・店舗名の抽出パターン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 都道府県名
_PREFS = (
    "北海道|青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|千葉|東京|神奈川"
    "|新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|三重|滋賀|京都|大阪|兵庫|奈良|和歌山"
    "|鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|高知"
    "|福岡|佐賀|長崎|熊本|大分|宮崎|鹿児島|沖縄"
)

# 日本の住所パターン
ADDRESS_RE = re.compile(
    r"(?:〒\s*\d{3}[-－]\d{4}\s*)?"          # 〒郵便番号（任意）
    r"(?:" + _PREFS + r")(?:都|道|府|県)?"   # 都道府県
    r"[\u4e00-\u9fff\w０-９0-9\s\-－ー−〜～丁目番地号の]+"  # 市区町村以降
    r"(?:[0-9０-９]+[-－ー−][0-9０-９]+(?:[-－ー−][0-9０-９]+)?)?"  # 番地
    r"(?:[　 \s]*(?:ビル|館|タワー|センター|プラザ|モール|SC|マンション|アベニュー|棟|階|[0-9０-９]+F))?",
    re.UNICODE,
)

# 郵便番号単体（〒付き行）
POSTAL_RE = re.compile(r"〒\s*(\d{3}[-－]\d{4})")

# 行頭記号（店舗リスト行の識別）
BULLET_RE = re.compile(r"^[\s　]*[●・■◆○◎▶▷➤▸►▻◉\u25a0-\u25ff①-⑳\d]+[\s　.．、）)\]】]+")

# 不要テキストのスキップパターン
SKIP_RE = re.compile(
    r"ページ|page|年|月|日|Copyright|http|www\.|@|株式会社.*?株式会社"
    r"|目次|contents|はじめに|ご注意|注意事項|お問い合わせ|取扱説明",
    re.IGNORECASE
)


def _normalize(text: str) -> str:
    """全角数字・スペースを正規化"""
    text = text.translate(str.maketrans("　０１２３４５６７８９", " 0123456789"))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_stores(text: str, company: str) -> list[dict]:
    """テキストから店舗情報リストを抽出"""
    text = _normalize(text)
    lines = text.split("\n")
    stores = []

    def add_store(name: str, address: str):
        name = BULLET_RE.sub("", name).strip()
        name = re.sub(r"[\s　]{2,}", " ", name).strip()
        address = address.strip()
        if (
            name and address
            and 2 <= len(name) <= 60
            and 5 <= len(address) <= 100
            and not SKIP_RE.search(name)
        ):
            stores.append({"name": name, "address": address, "company": company})

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # ── パターン1: 同一行に「店舗名  住所」が並ぶ（タブ・連続スペース区切り）
        parts = re.split(r"\t|　{2,}| {3,}", line)
        if len(parts) >= 2:
            for pi in range(len(parts) - 1):
                addr_match = ADDRESS_RE.search(parts[pi + 1])
                if addr_match:
                    add_store(parts[pi], addr_match.group(0))
                    break

        # ── パターン2: 住所が含まれる行 → 前の行を店舗名に
        addr_m = ADDRESS_RE.search(line)
        if addr_m:
            address = addr_m.group(0)
            # 同じ行の住所より前の部分を店舗名候補に
            before = line[:addr_m.start()].strip()
            before = BULLET_RE.sub("", before).strip()
            if before and len(before) >= 2:
                add_store(before, address)
            elif i > 0:
                # 前行を店舗名候補に
                prev = lines[i - 1].strip()
                if prev and not ADDRESS_RE.search(prev) and not SKIP_RE.search(prev):
                    add_store(prev, address)
            i += 1
            continue

        # ── パターン3: 〒がある行の次行に住所（2行形式）
        if POSTAL_RE.search(line) and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            addr_m2 = ADDRESS_RE.search(line + next_line)
            if addr_m2:
                store_name = lines[i - 1].strip() if i > 0 else ""
                add_store(store_name, addr_m2.group(0))

        i += 1

    return stores


def _deduplicate(stores: list[dict]) -> list[dict]:
    """住所 + 店舗名の重複を除去"""
    seen: set[tuple] = set()
    result = []
    for s in stores:
        key = (s.get("company", ""), s.get("name", ""), s.get("address", ""))
        if key not in seen:
            seen.add(key)
            result.append(s)
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メイン公開関数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_stores_from_pdf(
    source,
    source_type: str = "upload",
    ocr_lang: str = "jpn+eng",
) -> list[dict]:
    """
    PDF から店舗情報（店舗名・住所）を抽出して返す。

    Parameters
    ----------
    source      : Streamlit UploadedFile または pathlib.Path
    source_type : "upload" | "file"
    ocr_lang    : tesseract 言語コード（デフォルト "jpn+eng"）

    Returns
    -------
    list of dict  {"name", "address", "company", "source_file"}
    """
    # 会社名をファイル名から推定
    raw_name = source.name if hasattr(source, "name") else Path(source).stem
    company = re.sub(
        r"\d{4}|\d+年度?|株主優待|優待|案内|ご利用|のご案内|PDF|\.pdf|_|\s",
        "", raw_name
    ).strip() or raw_name

    data = _read_bytes(source, source_type)

    # ① テキストPDF を試みる
    text = ""
    try:
        text = _extract_text_pdfplumber(data)
    except Exception as e:
        print(f"[pdfplumber] {e}")

    # テキストが薄い（スキャンPDFの可能性）→ OCR
    meaningful_chars = re.sub(r"\s", "", text)
    if len(meaningful_chars) < 200:
        print("[pdf_parser] テキストが少ないため OCR を試みます")
        try:
            text_ocr = _extract_text_ocr(data, lang=ocr_lang)
            # OCR の方が文字数が多ければ採用
            if len(re.sub(r"\s", "", text_ocr)) > len(meaningful_chars):
                text = text_ocr
        except Exception as e:
            print(f"[OCR] {e}")
            if not text:
                raise RuntimeError(
                    f"テキスト抽出も OCR も失敗しました。\n"
                    f"OCRエラー: {e}\n"
                    "Tesseract のインストールを確認してください:\n"
                    "  macOS: brew install tesseract tesseract-lang\n"
                    "  Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-jpn"
                )

    if not text.strip():
        raise ValueError("PDFからテキストを抽出できませんでした")

    stores = _parse_stores(text, company)
    return _deduplicate(stores)
