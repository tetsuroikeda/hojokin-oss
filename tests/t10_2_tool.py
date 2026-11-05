"""T10-2 模擬画面への入力（TASKS B29）のテストと、デスクトップでの通しの準備に共通の道具。

- 入力シートの値（demo_values）：制度データの正解（testdata/正解/省力化_第8回.json）の申請画面の、ツールが入れる
  すべての欄に、デモの会社（架空。testdata/デモの会社/回答表.md）の値を入れる。当てはまらない欄は「該当なし」
  （チェック欄は「いいえ」）。添付の欄の値は、段階のフォルダの「添付する書類/」に置く写しの場所。
- 添付する写し（ATTACHMENTS）：testdata/デモの会社/書類/ の架空の書類の写しと、小さな架空の Excel・PDF。
- 記録との照合（t10_2_problems）：模擬画面（mock/）が残した入力値.json と添付したファイルを、入力シートの
  ツールが入れる欄と照らし、合わないものを挙げる。空なら SPEC T10-2 の合格ライン（入力シートと100%一致。
  添付するファイルを含む。文字数の超過0件）を満たす。提出と担当者の欄は nyuryoku_tool.t10_3_violations で見る。
- 道具が画面に入れる代わり（fill_mock）：ブラウザを使わずに、入力シートの値を模擬画面へ送る（mock/test_server.py
  と同じ multipart の形）。照合の道具そのものを確かめるために使う。
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

import nyuryoku_tool as nt

from lib import input_sheet

REPO = Path(__file__).resolve().parent.parent
ANSWER = REPO / "testdata" / "正解" / "省力化_第8回.json"
DOCS = REPO / "testdata" / "デモの会社" / "書類"
DATA = REPO / "tests" / "data" / "t10_2"
ATTACH_DIR = "添付する書類"

# ---- 入力シートの値（デモの会社。架空） ----

ADDRESS = {"郵便番号": "144-0033", "都道府県": "東京都", "市区町村": "大田区", "町域": "東糀谷", "番地等": "八丁目12番5号",
           "建物名": "該当なし"}
TEXT_VALUES = {
    "基本情報": {
        "組織形態": "1-1.中小企業者（組合関連以外）", "事業者名（法人名/屋号・商号）": "株式会社やまぶき惣菜",
        "事業者名（カナ）": "ヤマブキソウザイ", "法人代表者役職": "代表取締役", "代表者氏名（姓）": "沢村",
        "代表者氏名（名）": "宏之", "代表者氏名（カナ）（セイ）": "サワムラ", "代表者氏名（カナ）（メイ）": "ヒロユキ",
        "代表電話番号": "03-0000-0000", "事業者HPのURL": "https://www.example.com/", "従業員数": 15,
        "資本金（出資金）": 10000000, "創業・設立日（西暦）": "2008/04/01", **ADDRESS, "業種コード": "0999",
        "担当者の役職": "代表取締役", "担当者氏名（姓）": "沢村", "担当者氏名（名）": "宏之",
        "担当者氏名（カナ）（セイ）": "サワムラ", "担当者氏名（カナ）（メイ）": "ヒロユキ",
        "担当者メールアドレス": "info@example.com", "担当者電話番号": "03-0000-0000",
    },
    "要件": {"小規模企業者/小規模事業者": "はい", "再生事業者": "いいえ"},
    "加点項目": {
        "②事業継続力強化計画／連携事業継続力強化計画に対する加点": "はい", "受付番号（半角10桁）": "2512345678",
        "実施期間始期（年）": "2025", "実施期間始期（月）": "4", "実施期間終期（年）": "2028", "実施期間終期（月）": "3",
        "⑤事業場内最低賃金引き上げに係る加点": "はい", "⑧省力化ナビ加点": "はい",
    },
    "事業計画名及び作成者情報": {
        "事業計画名（３０文字程度）": "盛り付けから検品までをつなぐ惣菜ラインの省力化",
        "本事業で取り組む対象分野となる業種（日本標準産業分類、中分類）": "食料品製造業",
        "事業計画の概要（１００字程度）": "手作業の盛り付け・計量・包装・検品を、つながったラインに置き換え、"
                                 "1日の作業時間を減らす。浮いた人手を冷凍惣菜と新しい取引先に回し、売上と給与を伸ばす。",
        "導入予定の機械装置・システムの名称": "メーカー名：つばさ台フードシステム：型式：TF-100：名称：惣菜盛付・包装ライン",
        **ADDRESS, "事業所名": "本店工場", "事業計画書作成に支援者は関与していない": "はい", "直近決算期の決算月": "3",
    },
    "最低賃金及び特例希望": {
        "直近月の事業場内の最低賃金（対象年月）（年）": "2026", "直近月の事業場内の最低賃金（対象年月）（月）": "10",
        "事業場内最低賃金": 1250,
    },
    "事業計画数値": {"計画年数": "5年"},
    "経費明細・資金調達内訳": {
        "機械装置・システム構築費（（A）事業に要する経費（税込みの額））": 24750000,
        "機械装置・システム構築費（（B）補助対象経費（税抜きの額））": 22500000,
        "機械装置・システム構築費（（C）積算基礎（B）の内訳）": "惣菜盛付・包装ライン一式 22,500,000円（見積書による）",
        "運搬費（（A）事業に要する経費（税込みの額））": 330000,
        "運搬費（（B）補助対象経費（税抜きの額））": 300000,
        "運搬費（（C）積算基礎（B）の内訳）": "ラインの運搬と据付 300,000円（見積書による）",
        "事業全体に要する経費調達一覧 自己資金（事業に要する経費（円））": 13080000,
        "事業全体に要する経費調達一覧 借入金（事業に要する経費（円））": 12000000,
        "事業全体に要する経費調達一覧 借入金（資金の調達先）": "取引のある信用金庫",
        "補助金申請額の経費内訳 自己資金（事業に要する経費（円））": 2400000,
        "補助金申請額の経費内訳 借入金（事業に要する経費（円））": 9000000,
        "補助金申請額の経費内訳 借入金（資金の調達先）": "取引のある信用金庫",
    },
}
# ❼ の表（基準年度と1〜5年目計画）。行の名前 → 6つの値（本補助金で導入する設備の減価償却費は1〜5年目だけ）
PLAN_YEARS = ("基準年度", "1年目計画", "2年目計画", "3年目計画", "4年目計画", "5年目計画")
PLAN_VALUES = {
    "売上高": (230000000, 236900000, 244000000, 251300000, 258800000, 266500000),
    "売上原価（製造原価）": (138000000, 141500000, 145400000, 149300000, 153300000, 157400000),
    "販売費及び一般管理費（人件費・減価償却費を含む）": (48600000, 49500000, 50300000, 51200000, 52100000, 53000000),
    "②人件費": (52400000, 54500000, 56700000, 59000000, 61400000, 63900000),
    "（内訳）既存設備の減価償却費": (3000000, 2900000, 2800000, 2700000, 2600000, 2500000),
    "本補助金で導入する設備の減価償却費": (None, 4500000, 4500000, 4500000, 4500000, 4500000),
    "労働者数のうち役員数（人）": (2, 2, 2, 2, 2, 2),
    "労働者数のうち常勤従業員数（人）": (15, 15, 15, 16, 16, 16),
    "①全月分の給与等の支給を受けた従業員の給与支給総額": (41600000, 43300000, 45000000, 46800000, 48700000, 50600000),
    "②全月分の給与等の支給を受けた従業員数": (15, 15, 15, 16, 16, 16),
}
_PLAN_CELL = re.compile(r"^(.+)（(" + "|".join(PLAN_YEARS) + r")）$")

# 添付する写し：入力シートの欄 → （写しの名前, 元の架空の書類か、作る形）
ATTACHMENTS = {
    "履歴事項全部証明書": ("履歴事項全部証明書.pdf", "履歴事項全部証明書.pdf"),
    "納税証明書（その2）直近3年分": ("納税証明書（その2）.pdf", "納税証明書_その2.pdf"),
    "損益計算書 1期前分": ("損益計算書_第18期.pdf", "決算書_第18期.pdf"),
    "損益計算書 2期前分": ("損益計算書_第17期.pdf", "決算書_第17期.pdf"),
    "貸借対照表 1期前分": ("貸借対照表_第18期.pdf", "決算書_第18期.pdf"),
    "貸借対照表 2期前分": ("貸借対照表_第17期.pdf", "決算書_第17期.pdf"),
    "法人事業概況説明書": ("法人事業概況説明書.pdf", "法人事業概況説明書_第18期.pdf"),
    "【指定様式】労働者名簿": ("労働者名簿.xlsx", "労働者名簿.xlsx"),
    "【指定様式】役員名簿": ("役員名簿.xlsx", "xlsx"),
    "【指定様式】株主・出資者名簿": ("株主・出資者名簿.xlsx", "xlsx"),
    "事業計画書（その１・その２）": ("事業計画書（その1・その2）.pdf", "pdf"),
    "【指定様式】事業計画書（その３）": ("事業計画書（その3）.xlsx", "xlsx"),
    "機械装置・システム構築費の積算根拠資料（その１）": ("見積書_つばさ台フードシステム.pdf", "見積書_つばさ台フードシステム.pdf"),
    "機械装置・システム構築費の積算根拠資料（その２）": ("見積書_ほしみ機工.pdf", "見積書_ほしみ機工.pdf"),
    "導入予定の機械装置についてのカタログや説明資料1": ("カタログ_つばさ台フードシステム.pdf", "カタログ_つばさ台フードシステム.pdf"),
}


def answer() -> dict:
    return json.loads(ANSWER.read_text(encoding="utf-8"))


def attach_rel(case: str, stage: str, name: str) -> str:
    return f"案件/{case}/{stage}/{ATTACH_DIR}/{name}"


def demo_values(seido: dict, case: str, stage: str) -> List[dict]:
    """制度データの申請画面の、ツールが入れるすべての欄の値（{画面, 欄, 値} の並び。yoshiki.py sheet --values の形）。"""
    out = []
    for screen, field in input_sheet.fields_of(seido):
        if field.get("担当者が入れる") is True:
            continue
        sname, fname, kind = screen.get("名前"), field.get("名前"), field.get("種類")
        value = TEXT_VALUES.get(sname, {}).get(fname)
        cell = _PLAN_CELL.match(fname or "")
        if value is None and sname == "事業計画数値" and cell and cell.group(1) in PLAN_VALUES:
            value = PLAN_VALUES[cell.group(1)][PLAN_YEARS.index(cell.group(2))]
        if value is None and kind == "添付" and fname in ATTACHMENTS:
            value = attach_rel(case, stage, ATTACHMENTS[fname][0])
        if value is None:
            value = "いいえ" if kind == "チェック" else input_sheet.NOT_APPLICABLE
        out.append({"画面": sname, "欄": fname, "値": value})
    return out


def write_sheet(seido: dict, values: List[dict]) -> bytes:
    """入力シートを作って値を書く（kaku の yoshiki.py sheet と同じく lib/input_sheet.py で書く。まとめて書く形）。"""
    fields = {(s.get("名前"), f.get("名前")): f for s, f in input_sheet.fields_of(seido)}
    entries = []
    for entry in values:
        field = fields[(entry["画面"], entry["欄"])]
        value = entry["値"]
        if field.get("種類") == "数字" and not input_sheet.is_not_applicable(value):
            value = input_sheet.parse_number(str(value))
        entries.append((entry["欄"], value, entry["画面"], input_sheet.limit_of(field)))
    blob, _summaries = input_sheet.write_values(input_sheet.build(seido), entries)
    return blob


# ---- 添付する写し（架空） ----

def tiny_xlsx(title: str) -> bytes:
    """1つのシートに架空の見出しだけを置いた、小さな Excel。"""
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
             f'<worksheet xmlns="{input_sheet.S}" xmlns:r="{input_sheet.R}"><sheetData>'
             f'<row r="1"><c r="A1" t="inlineStr"><is><t>{escape(title)}</t></is></c></row>'
             '<row r="2"><c r="A2" t="inlineStr"><is><t>（試しの架空の書類です）</t></is></c></row>'
             "</sheetData></worksheet>")
    parts = [("[Content_Types].xml", input_sheet.CONTENT_TYPES), ("_rels/.rels", input_sheet.ROOT_RELS),
             ("xl/workbook.xml", input_sheet.WORKBOOK), ("xl/_rels/workbook.xml.rels", input_sheet.WORKBOOK_RELS),
             ("xl/styles.xml", input_sheet.STYLES), ("xl/worksheets/sheet1.xml", sheet)]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in parts:
            zf.writestr(zipfile.ZipInfo(name, date_time=(2026, 11, 5, 0, 0, 0)), text.encode("utf-8"))
    return out.getvalue()


def tiny_pdf(title: str) -> bytes:
    """1ページの小さな PDF（ASCII の文字だけ。架空の書類の代わり）。"""
    text = title.encode("ascii", "replace").decode("ascii").replace("(", "[").replace(")", "]")
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> "
               b"/Contents 4 0 R >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = b"%PDF-1.4\n"
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def attachment_bytes(field: str) -> bytes:
    name, source = ATTACHMENTS[field]
    if source == "xlsx":
        return tiny_xlsx(f"（架空）{Path(name).stem}")
    if source == "pdf":
        return tiny_pdf("Jigyo keikakusho sono 1 2 (dummy)")
    return (DOCS / source).read_bytes()


def place_attachments(folder: Path, case: str, stage: str) -> List[str]:
    """段階のフォルダの「添付する書類/」に、添付する写しを置く。置いた場所の並びを返す。"""
    attach = Path(folder) / "案件" / case / stage / ATTACH_DIR
    attach.mkdir(parents=True, exist_ok=True)
    placed = []
    for field, (name, _source) in ATTACHMENTS.items():
        (attach / name).write_bytes(attachment_bytes(field))
        placed.append(attach_rel(case, stage, name))
    return placed


def make_company(root: Path, case: str = nt.CASE, stage: str = nt.STAGE, sheet: bytes = None) -> Path:
    """正解の制度データと、デモの会社の値を書いた入力シート、添付する写しを置いた試しの会社のフォルダ。"""
    seido = answer()
    folder = nt.make_company(root, values=(), scheme=seido)
    app = folder / "案件" / case / stage / "申請書"
    app.mkdir(parents=True, exist_ok=True)
    (app / input_sheet.FILE_NAME).write_bytes(sheet if sheet is not None else
                                              write_sheet(seido, demo_values(seido, case, stage)))
    place_attachments(folder, case, stage)
    return folder


# ---- 模擬画面の欄と、入力シートの行の対応 ----

def norm(text) -> str:
    return " ".join(unicodedata.normalize("NFC", str(text or "")).split())


def label_keys(label: str) -> List[str]:
    """守り（lib/browser_guard.py）と同じ照らし方：名前の全文と、「：」より前の項目名。"""
    keys = [norm(label)]
    if "：" in str(label):
        keys.append(norm(str(label).split("：", 1)[0]))
    return keys


def screen_title(section: str) -> str:
    """「❽ 経費明細・資金調達内訳」→「経費明細・資金調達内訳」。"""
    text = norm(section)
    return text.split(" ", 1)[1] if " " in text else text


def mock_fields() -> List[dict]:
    """模擬画面の欄の定義（表示だけの欄を除く。表の中の欄を含む）。"""
    nt.mock_modules()
    import screen as mock_screen  # noqa: E402

    return mock_screen.all_fields()


def match_fields(row: dict, fields: List[dict]) -> List[dict]:
    """入力シートの行（画面・欄）に当たる模擬画面の欄。"""
    want = norm(row["欄"])
    return [f for f in fields if screen_title(f["section"]) == norm(row["画面"]) and want in label_keys(f["label"])]


def number_text(text) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).replace(",", "").replace("円", "").strip()


def is_empty_value(value) -> bool:
    return value in (None, "", False, [])


def want_value(row: dict):
    """入力シートの行から、模擬画面に残るはずの値（チェック欄は真偽、ほかは文字）。空・「該当なし」は None。"""
    text = row["値"]
    if norm(text) == "" or input_sheet.is_not_applicable(text):
        return None
    if row["種類"] == "チェック":
        return norm(text) in nt.script_module().CHECK_ON
    return text


def values_equal(kind: str, want, seen) -> bool:
    if kind == "チェック":
        return bool(seen) is bool(want)
    a, b = norm(want).replace("\r\n", "\n"), norm(seen).replace("\r\n", "\n")
    if a == b or "".join(a.split()) == "".join(b.split()):
        return True
    return kind == "数字" and number_text(a) == number_text(b)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def t10_2_problems(state: dict, rows: List[dict], folder: Optional[Path] = None,
                   record_dir: Optional[Path] = None) -> Tuple[List[str], Dict[str, int]]:
    """模擬画面の入力値.json（state）を、入力シートの行（nyuryoku.py の read_sheet の形）と照らす。

    戻り値は（合わないものの一覧, 数の要約）。一覧が空なら、入力シートと100%一致（添付を含む）で、文字数の超過も0件。
    - ツールが入れる欄（担当者が入れる欄を除く）の、値のある行：画面の値が同じ（チェック欄は入っているか）。
    - 値が空か「該当なし」の行：画面の欄も空（ツールは入れない）。画面にない欄なら、それでよい。
    - 添付の行：模擬画面に添付したファイルがあり、中身（sha256）が会社のフォルダの写しと同じ（folder があるとき。
      なければファイルの名前で見る）。値が「該当なし」の欄には添付がない。
    - 入力シートにない、ツールが入れる模擬画面の欄（法人番号など）には、値も添付もない。
    - 文字数の上限（目安でないもの）を超える値が、画面に入っていない。
    """
    fields = mock_fields()
    values = state.get("fields") or {}
    files = state.get("files") or {}
    problems: List[str] = []
    counts = {"照らした行": 0, "値で合った行": 0, "添付で合った行": 0, "空のままの行": 0, "文字数の超過": 0,
              "目安を超えた行": 0}
    covered = set()
    for row in rows:
        hits = match_fields(row, fields)
        covered.update(f["id"] for f in hits)
        if row["担当者が入れる"]:
            continue
        counts["照らした行"] += 1
        where = f"{row['画面']}・{row['欄']}"
        want = want_value(row)
        if len(hits) > 1:
            problems.append(f"{where}：模擬画面に同じ名前の欄が{len(hits)}つある")
            continue
        if not hits:
            if (want is not None and row["種類"] != "チェック") or want is True:
                problems.append(f"{where}：入力シートに値があるのに、模擬画面に欄がない")
            continue
        field = hits[0]
        if row["種類"] == "添付":
            got = files.get(field["id"])
            if want is None:
                if got:
                    problems.append(f"{where}：入力シートは「該当なし」なのに、添付がある（{got.get('filename')}）")
                else:
                    counts["空のままの行"] += 1
                continue
            if not got:
                problems.append(f"{where}：添付がない（入力シート：{want}）")
                continue
            expected_name = str(want).replace("\\", "/").rsplit("/", 1)[-1]
            source = Path(folder) / str(want) if folder else None
            if source is not None and source.is_file():
                if got.get("sha256") != sha256_file(source):
                    problems.append(f"{where}：添付したファイルの中身が、写し（{want}）と違う")
                    continue
            elif norm(got.get("filename")) != norm(expected_name):
                problems.append(f"{where}：添付したファイルの名前が違う（入力シート：{expected_name}、"
                                f"模擬画面：{got.get('filename')}）")
                continue
            if record_dir is not None and got.get("path"):
                saved = Path(record_dir) / got["path"]
                if not saved.is_file() or sha256_file(saved) != got.get("sha256"):
                    problems.append(f"{where}：模擬画面に残った添付のファイルが、記録の sha256 と合わない")
                    continue
            counts["添付で合った行"] += 1
            continue
        seen = (values.get(field["id"]) or {}).get("value")
        if want is None:
            if not is_empty_value(seen):
                problems.append(f"{where}：入力シートは空か「該当なし」なのに、画面に値がある（{seen!r}）")
            else:
                counts["空のままの行"] += 1
            continue
        if not values_equal(row["種類"], want, seen):
            problems.append(f"{where}：入力シート {want!r}、模擬画面 {seen!r}")
            continue
        counts["値で合った行"] += 1
        limit = row.get("上限")
        if limit and isinstance(seen, str):
            kind, chars = limit
            if len(seen.replace("\r\n", "\n")) > chars:
                if kind in input_sheet.HARD_LIMITS:
                    counts["文字数の超過"] += 1
                    problems.append(f"{where}：{kind}の{chars}字を超えている（{len(seen)}字）")
                else:
                    counts["目安を超えた行"] += 1
    for field in fields:
        if field["id"] in covered or field["who"] != "tool":
            continue
        if field["kind"] == "file":
            if files.get(field["id"]):
                problems.append(f"{field['section']}・{field['label']}：入力シートにない欄に添付がある")
        elif not is_empty_value((values.get(field["id"]) or {}).get("value")):
            problems.append(f"{field['section']}・{field['label']}：入力シートにない欄に値がある")
    return problems, counts


# ---- 道具が画面に入れる代わり（ブラウザを使わない） ----

def multipart(fields: Dict[str, object], files: Dict[str, Tuple[str, bytes]] = None):
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in fields.items():
        for one in value if isinstance(value, list) else [value]:
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode()
            body += str(one).encode("utf-8") + b"\r\n"
    for name, (filename, data) in (files or {}).items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n").encode("utf-8") + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def form_for_screens(rows: List[dict], folder: Path, skip: Tuple[str, ...] = ()) -> Dict[int, dict]:
    """入力シートの値から、12画面版の画面ごとに送る欄と添付（ツールが入れる欄だけ）。skip の欄は送らない。"""
    nt.mock_modules()
    import screen as mock_screen  # noqa: E402

    fields = mock_fields()
    titles = {s["title"]: n for n, s in enumerate(mock_screen.SECTIONS, start=1)}
    out: Dict[int, dict] = {}
    for row in rows:
        if row["担当者が入れる"] or row["欄"] in skip:
            continue
        want = want_value(row)
        hits = match_fields(row, fields)
        if want is None or want is False or len(hits) != 1:
            continue
        field = hits[0]
        screen_no = titles[screen_title(field["section"])]
        entry = out.setdefault(screen_no, {"fields": {}, "files": {}})
        if row["種類"] == "添付":
            path = Path(folder) / str(want)
            entry["files"][field["id"]] = (path.name, path.read_bytes())
        elif row["種類"] == "チェック":
            entry["fields"][field["id"]] = "on"
        else:
            entry["fields"][field["id"]] = number_text(want) if row["種類"] == "数字" else str(want)
    return out


def fill_mock(base: str, rows: List[dict], folder: Path, skip: Tuple[str, ...] = (),
              change: Dict[str, str] = None) -> None:
    """ログインして、画面ごとに入力シートの値を入れ、添付して「一時保存」を押す（ツールが入れる欄だけ）。
    change（欄の id → 値）は、送る前に値を差し替える（照合が違いを見つけるかを確かめるため）。"""
    cookie = nt.mock_login(base)
    for screen_no, entry in sorted(form_for_screens(rows, folder, skip).items()):
        fields = dict(entry["fields"])
        for key, value in (change or {}).items():
            if key in fields:
                fields[key] = value
        body, headers = multipart({"button": "save", **fields}, entry["files"])
        status, _headers, _text = nt.http(f"{base}/shinsei/{screen_no}", body, headers, cookie)
        assert status == 303, (screen_no, status)
