"""申請書を確かめる道具の中身（SPEC F9、DESIGN 6章・8章。TASKS M7。道具の入口は skills/kaku/scripts/kakunin.py）。

1. コードによる確かめ（check）：今は、仮の印と空欄の数え上げ（T9-4）と、根拠対照表の出典のない行（根拠のない記述）。
   - 文章（Word・文字のファイル・Excel のセルの文字）では、決まった形の印を数える：【仮：…】、【空欄：…】
     （DESIGN 6章。全角・半角の「：」と、「：」のない【仮】【空欄】も数える。【仮説】のような言葉には当てない）。
   - 数字の欄（財務モデルの前提・経費明細など）は、隣の「状態」の欄が「仮」の行を、仮の印として数える（DESIGN 6章）。
   - 空欄には、印のほかに、まだ何も書いていない所も数える（仮の形。TASKS M7 の質問）：
     様式の項目のうち、書き込む位置を対応づけた項目で、説明の青字のほかに文字がないもの、
     入力シートの、ツールが入れる欄（担当者が入れる欄でないもの）で、値が空のもの。
   - 見るのは、申請書（`案件/<案件>/<段階>/申請書/` の Word・Excel・文字のファイル）と、会社のフォルダの直下の
     財務モデル.xlsx。根拠対照表.xlsx は、印ではなく、出典の空の行を数える。根拠対照表がなければ通さない。
   文字数・文体・財務モデルとの一致などの確かめは、後のタスクでここに足す。
2. 審査役に渡すもの（prepare）：コードの確かめが通ったときだけ、`記録/審査に渡すもの/` に、計画書の本文
   （様式の項目ごと）、制度データの抜き出し（審査項目・加点・様式の項目と分量）、根拠対照表、聞き取りの記録、
   会社の記録の書き方の決まりと過去に受けた指摘、文体の基準の C、コードの確かめの結果をまとめ、最後に控え
   （確かめの番号と申請書のハッシュ）を置く（DESIGN 8章）。審査役はプラグインのフォルダを読めない
   （会社のフォルダの外を読む道具は hook が拒む）ので、文体の基準の C もここに写す。書いたときの考えの経過は渡さない。
   - Excel の様式（その3 など）の数式のセル（省力化指数・投資回収期間など）は、書く道具がセルを書いた後も、ファイルに
     前の計算の値（0 や空）が残る。そこで、LibreOffice で計算し直した写し（`.hojokin/一時/計算し直した写し/`。毎回
     上書きする）から数式のセルの値を取り、様式の数の書式（小数の桁など）で渡す。様式のファイルそのものは計算し直して
     保存し直さない（LibreOffice で保存し直すと様式の部品が変わるため。DESIGN 5章）。LibreOffice が動かないときは、
     前の値のまま渡し、そのことを計画書の本文に一言書く（止めない。TASKS B19 の直し）。
     コードの確かめ（check）は入力の欄だけを読むので、写しは使わない。
3. 審査役の結果（review）：hook が保存した `記録/審査役の結果/<確かめの番号>.json`（lib/shinsa_result.py）を読む。
4. 完成の記録（complete）：コードの確かめが通り、今の控えの番号の審査役の結果が保存されていて、報告の文が保存した
   ときのまま（報告のハッシュが合う）、審査役が確かめたときの申請書のハッシュが今の申請書と合い、要修正が0件の
   ときだけ、`記録/完成の記録.json` に足す（DESIGN 8章「完成の記録は、確かめの道具だけが残す」）。

場所の確かめは lib/places.py で行う（書く先と、読む・一覧を取るフォルダの途中に別名があれば断る）。
openpyxl は使わない（標準のライブラリで Word・Excel の XML を読む）。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import datetime
import json
import os
import posixpath
import re
import shutil
import unicodedata
import xml.etree.ElementTree as ET
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lib import input_sheet, konkyo, places, shinsa_result
from lib import yoshiki_word as yw
from lib.shinsa_result import MODEL_FILE, PACKAGE_DIR, RESULTS_DIR

PROVISIONAL = "仮の印"
BLANK = "空欄"
UNSUPPORTED = "根拠なし"
_PROVISIONAL_RE = re.compile(r"【\s*仮\s*(?::|】)")
_BLANK_RE = re.compile(r"【\s*空欄\s*(?::|】)")
STATE_HEADER = "状態"
STATE_PROVISIONAL = "仮"
WORD_SUFFIXES = (".docx",)
EXCEL_SUFFIXES = (".xlsx", ".xlsm")
TEXT_SUFFIXES = (".md", ".txt")
SNIPPET = 40

CASES_DIR = "案件"
SEIDO_DIR = "記録/制度データ"
QUESTION_LOG = "記録/質問の記録.json"
COMPLETION_REL = "記録/完成の記録.json"
STAGE_NAME = re.compile(r"^([0-9]+)_[^/\\]+$")

PLAN_FILE = "計画書の本文.md"
SEIDO_FILE = "制度データの抜き出し.json"
EVIDENCE_FILE = "根拠対照表.md"
QUESTIONS_FILE = "聞き取りの記録.json"
RECORD_FILE = "会社の記録の抜き出し.json"
MODEL_TEXT_FILE = "財務モデルの前提.md"
STYLE_FILE = "文体の基準C.md"
YARDSTICK_FILE = "構成と効果の物差し.md"
CHECK_FILE = "コードの確かめの結果.json"
PACKAGE_FILES = (PLAN_FILE, SEIDO_FILE, EVIDENCE_FILE, QUESTIONS_FILE, RECORD_FILE, MODEL_TEXT_FILE, STYLE_FILE,
                 YARDSTICK_FILE, CHECK_FILE)
STYLE_CRITERIA = Path("docs") / "style-criteria.md"

SEVERITIES = ("要修正", "要確認", "助言")
MUST_FIX = "要修正"


class CheckError(ValueError):
    """確かめられない（案件・段階・制度データが決められない、別名がある、ファイルが読めない など）。"""


class NotPassed(Exception):
    """コードの確かめが通らない（審査役を呼ばない・完成にしない）。report に数え上げの結果。"""

    def __init__(self, report: dict) -> None:
        super().__init__("コードの確かめが通りません")
        self.report = report


# ---------------------------------------------------------------- 場所と材料


def _no_link(folder: Path, rel: str, what: str = "") -> None:
    try:
        places.no_link_on_the_way(folder, rel)
    except places.PlaceError as e:
        raise CheckError(f"{e.link} が別名（シンボリックリンク）になっているので、{what or '中を見ません'}。別名を外してください")


def find_case(folder: Path, given: Optional[str]) -> str:
    _no_link(folder, CASES_DIR)
    top = places.actual(folder, CASES_DIR)
    if top is None or not top.is_dir():
        raise CheckError(f"{CASES_DIR}/ がありません。先に junbi で案件を作ってください")
    names = sorted(places.nfc(p.name) for p in top.iterdir() if p.is_dir() and not p.name.startswith("."))
    if given:
        if places.nfc(given) not in names:
            raise CheckError(f"案件「{given}」が {CASES_DIR}/ にありません（あるもの：{'、'.join(names) or 'なし'}）")
        return places.nfc(given)
    if len(names) != 1:
        raise CheckError(f"{CASES_DIR}/ に案件が{len(names)}つあります。--case で、どれかを渡してください"
                         f"（{'、'.join(names) or 'なし'}）")
    return names[0]


def find_stage(folder: Path, case: str, given: Optional[str]) -> str:
    rel = f"{CASES_DIR}/{case}"
    _no_link(folder, rel)
    case_dir = places.actual(folder, rel)
    stages = sorted((p for p in case_dir.iterdir() if p.is_dir() and STAGE_NAME.match(places.nfc(p.name))),
                    key=lambda p: int(STAGE_NAME.match(places.nfc(p.name)).group(1)))
    names = [places.nfc(p.name) for p in stages]
    if given:
        if places.nfc(given) not in names:
            raise CheckError(f"段階のフォルダ「{given}」が {rel}/ にありません（あるもの：{'、'.join(names) or 'なし'}）")
        return places.nfc(given)
    if not names:
        raise CheckError(f"{rel}/ に段階のフォルダ（1_申請 など）がありません。先に junbi で作ってください")
    return names[0]


def _read_json_inside(folder: Path, given: str, what: str) -> Tuple[Any, str]:
    try:
        real = places.resolve_inside(folder, Path(given).expanduser())
    except places.PlaceError:
        raise CheckError(f"{what}（{given}）が会社のフォルダの外です。会社のフォルダの中のものだけを使います")
    try:
        return json.loads(real.read_text(encoding="utf-8")), places.relative_inside(folder, real)
    except OSError as e:
        raise CheckError(f"{what}（{given}）を読めませんでした（{e.strerror or e}）")
    except ValueError as e:
        raise CheckError(f"{what}（{given}）が JSON として読めません（{e}）")


def find_seido(folder: Path, given: Optional[str]) -> Tuple[Optional[dict], str]:
    """制度データ（記録/制度データ/ の中の JSON）。1つもなければ (None, "")。2つ以上で given がなければ断る。"""
    if given:
        data, rel = _read_json_inside(folder, given, "制度データ")
    else:
        _no_link(folder, SEIDO_DIR)
        top = places.actual(folder, SEIDO_DIR)
        if top is None or not top.is_dir():
            return None, ""
        found = sorted(p for p in top.iterdir() if p.suffix == ".json" and not p.name.startswith("."))
        if not found:
            return None, ""
        if len(found) != 1:
            raise CheckError(f"{SEIDO_DIR}/ に制度データが{len(found)}つあります。--seido で、どれを使うかを渡してください")
        data, rel = _read_json_inside(folder, str(found[0]), "制度データ")
    if not isinstance(data, dict):
        raise CheckError("制度データが { } の形ではありません")
    return data, rel


def application_files(folder: Path, case: str, stage: str) -> Dict[str, Path]:
    try:
        return shinsa_result.application_files(folder, case, stage)
    except places.PlaceError as e:
        raise CheckError(f"{e.link} が別名（シンボリックリンク）になっているので、申請書を確かめません。別名を外してください")


def _forms(seido: Optional[dict]) -> List[dict]:
    forms = seido.get("様式") if isinstance(seido, dict) else None
    return [f for f in forms if isinstance(f, dict)] if isinstance(forms, list) else []


def _mapped_items(seido: Optional[dict]) -> List[Tuple[str, dict]]:
    """対応づけた様式の項目と、項目の表の欄（「項目：欄：欄の名前」）の書き込む位置。"""
    out = []
    for form in _forms(seido):
        out += yw.item_positions(form)
    return out


def _screen_form(form: dict) -> bool:
    """入力先が申請画面の様式か（書き込む位置を持たず、入力シートの欄に書く。DESIGN 9章「様式」の入力先）。"""
    place = form.get("入力先")
    value = place.get("値") if isinstance(place, dict) else None
    return isinstance(value, dict) and value.get("種類") == "画面"


def _unmapped_items(seido: Optional[dict]) -> List[str]:
    out = []
    for form in _forms(seido):
        if _screen_form(form):
            continue  # 画面に入れる様式は、入力シートで書く（対応づける位置がない）
        for entry in form.get("項目") or []:
            if not isinstance(entry, dict):
                continue
            pos = entry.get("書き込む位置")
            if isinstance(pos, dict) and (pos.get("範囲") or pos.get("シート")):
                continue
            subs = [s for s in entry.get("欄") or [] if isinstance(s, dict)]
            if subs and all(isinstance(s.get("書き込む位置"), dict) and (s["書き込む位置"].get("範囲") or
                                                                        s["書き込む位置"].get("シート")) for s in subs):
                continue
            out.append(str(entry.get("名前")))
    return out


# ---------------------------------------------------------------- 印を数える


class Finding:
    """数えた1件。kind は 仮の印・空欄・根拠なし。where は項目・欄・セル・行など。"""

    def __init__(self, kind: str, file: str, where: str, text: str = "") -> None:
        self.kind = kind
        self.file = file
        self.where = where
        self.text = text

    def as_dict(self) -> Dict[str, str]:
        return {"種類": self.kind, "ファイル": self.file, "場所": self.where, "文字": self.text}

    def line(self) -> str:
        tail = f"：{self.text}" if self.text else ""
        return f"{self.file}（{self.where}）{tail}"


def marks(text: str) -> List[Tuple[str, str]]:
    """文の中の仮の印と空欄（種類、印から始まる短い抜き出し）。"""
    norm = unicodedata.normalize("NFKC", str(text or ""))
    found = []
    for kind, pattern in ((PROVISIONAL, _PROVISIONAL_RE), (BLANK, _BLANK_RE)):
        for m in pattern.finditer(norm):
            snippet = norm[m.start():m.start() + SNIPPET].replace("\n", " ")
            close = snippet.find("】")
            found.append((m.start(), kind, snippet[:close + 1] if close >= 0 else snippet + "…"))
    return [(kind, snippet) for _pos, kind, snippet in sorted(found)]


def _outer_paragraphs(root) -> List:
    """本文の段落（テキストボックスの中のように、段落の中にある段落は、外の段落の文字に含まれるので除く）。"""
    return [p for p in yw._paragraphs(root) if not any(a.is_(yw.W, "p") for a in p.ancestors())]


def _place(p) -> str:
    try:
        return yw.path_of(p)
    except ValueError:
        return "本文"


def _word_root(blob: bytes, rel: str):
    from lib import xml_spans

    _infos, parts = yw.read_parts(blob)
    if yw.DOC not in parts:
        raise CheckError(f"{rel} に Word の本文がありません")
    try:
        return xml_spans.parse(parts[yw.DOC])
    except ValueError as e:
        raise CheckError(f"{rel} の本文を読めません（{e}）")


def _item_ranges(root, seido: Optional[dict]) -> List[Tuple[str, List]]:
    """この Word で見つかった、書き込む位置を対応づけた様式の項目と、その範囲の段落。"""
    out = []
    for name, pos in _mapped_items(seido):
        try:
            rng = yw.resolve(root, pos, name)
        except ValueError:
            continue  # ほかの Word の様式の項目か、見出しが見つからない
        if pos.get("範囲") == yw.TABLE:  # 表ごとの範囲（スケジュールの表）は、表の中の段落
            out.append((name, _TableParagraphs(rng.nodes[0])))
            continue
        out.append((name, [n for n in rng.nodes if n.is_(yw.W, "p")]))
    return out


class _TableParagraphs(list):
    """表ごとの範囲の段落（表も持つ。文字は工程・作業と印の期間にまとめて渡す）。"""

    def __init__(self, table) -> None:
        super().__init__(p for p in table.iter() if p.is_(yw.W, "p"))
        self.table = table


def _item_text(ps, periods: bool = True) -> str:
    """項目の範囲の文字。表ごとの範囲（スケジュールの表）は、工程・作業と印の期間にまとめる。
    periods が偽なら、工程と作業の名前だけ（根拠対照表との照合用。月の境の日付は、列の見出しから作った文字なので照らさない）。"""
    if isinstance(ps, _TableParagraphs):
        return yw.table_text(ps.table, periods)
    return _non_blue_text(ps)


def form_table_notes(blob: bytes, rel: str, seido: Optional[dict]) -> List[str]:
    """見出しの後に書く様式の項目の中にある表（役割分担の表、スケジュールの表など）が、空か、記載例の青字が残ったもの。
    表を文章や自作の図で代えたままにしないため（11/7 のリハーサルで、5. の役割分担とスケジュールの表が空のままだった）。
    見出しの行（1行目）は数えない。完成を止めない注意にし、審査役が読む。"""
    root = _word_root(blob, rel)
    body = yw.body_of(root)

    def shown(node) -> str:
        return "".join(yw.text_of(p) for p in node.iter() if p.is_(yw.W, "p") and yw.blue_state(p) != "全部").strip()

    def blue(node) -> bool:
        return any(p.is_(yw.W, "p") and yw.blue_state(p) == "全部" for p in node.iter())

    out = []
    for form in _forms(seido):
        for entry in form.get("項目") or []:
            pos = entry.get("書き込む位置") if isinstance(entry, dict) else None
            place = str(pos.get("場所") or "") if isinstance(pos, dict) and pos.get("範囲") == "見出しの後" else ""
            cell = yw.node_at(body, place.rsplit(".p", 1)[0]) if ".p" in place else None
            if cell is None or not cell.is_(yw.W, "tc"):
                continue
            for tbl in cell.findall(yw.W, "tbl"):
                rows = tbl.findall(yw.W, "tr")
                if len(rows) < 2:
                    continue
                head = "／".join(t for t in (shown(c) for c in rows[0].findall(yw.W, "tc")) if t)[:40]
                label = f"{entry.get('名前')}（{head or '表'}）"
                if any(blue(r) for r in rows[1:]):
                    out.append(f"{label}：記載例の青字が残っています")
                elif not any(shown(r) for r in rows[1:]):
                    out.append(f"{label}：空です")
    return out


def word_findings(blob: bytes, rel: str, seido: Optional[dict]) -> List[Finding]:
    root = _word_root(blob, rel)
    items = _item_ranges(root, seido)
    labels = {id(p): name for name, ps in items for p in ps}
    out = []
    for p in _outer_paragraphs(root):
        for kind, snippet in marks(yw.text_of(p)):
            out.append(Finding(kind, rel, labels.get(id(p)) or _place(p), snippet))
    for name, ps in items:
        if isinstance(ps, _TableParagraphs):
            # スケジュールの表は、見出しの行の黒い文字では書いたことにせず、月の欄に印があるかで見る
            written = [p for p in ps if yw.blue_state(p) != "全部" and yw.text_of(p).strip() in yw.MARKS
                       and yw.text_of(p).strip()]
        else:
            written = [p for p in ps if yw.blue_state(p) != "全部" and yw.text_of(p).strip()]
        if not written:
            out.append(Finding(BLANK, rel, name, "（まだ何も書いていない項目）"))
    return out


def _sheets(blob: bytes, rel: str) -> List[Tuple[str, input_sheet.Grid]]:
    """Excel のシートごとの表（名前と、セルの文字）。グラフのシートなど、表でないものは飛ばす。"""
    _infos, parts = yw.read_parts(blob)
    S, R = input_sheet.S, input_sheet.R
    try:
        rels = ET.fromstring(parts["_rels/.rels"])
        book = next(r.get("Target") for r in rels if r.get("Type", "").endswith("/officeDocument"))
        book = input_sheet._rel_target("", book)
        wb = ET.fromstring(parts[book])
        book_rels_name = posixpath.join(posixpath.dirname(book), "_rels", posixpath.basename(book) + ".rels")
        targets = {r.get("Id"): r.get("Target") for r in ET.fromstring(parts[book_rels_name])}
    except (KeyError, StopIteration, AttributeError, ET.ParseError, TypeError) as e:
        raise CheckError(f"{rel} を Excel のファイルとして読めません（{e}）")
    shared = input_sheet._shared_strings(parts)
    out = []
    for sheet in wb.iter(f"{{{S}}}sheet"):
        target = targets.get(sheet.get(f"{{{R}}}id"))
        name = input_sheet._rel_target(book, target) if target else ""
        if name not in parts:
            continue
        try:
            out.append((sheet.get("name") or name, input_sheet.Grid(parts[name], shared)))
        except ValueError:
            continue
    return out


def _by_row(grid: input_sheet.Grid) -> Dict[int, Dict[str, str]]:
    rows: Dict[int, Dict[str, str]] = {}
    for ref, text in grid.texts.items():
        m = input_sheet._REF.fullmatch(ref)
        if m:
            rows.setdefault(int(m.group(2)), {})[m.group(1)] = text
    return rows


def _col_key(col: str) -> int:
    return input_sheet.col_index(col)


def sheet_findings(blob: bytes, rel: str) -> List[Finding]:
    out = []
    for sheet_name, grid in _sheets(blob, rel):
        rows = _by_row(grid)
        state_col = name_col = None
        for r in sorted(rows):
            cells = rows[r]
            for col in sorted(cells, key=_col_key):
                for kind, snippet in marks(cells[col]):
                    out.append(Finding(kind, rel, f"{sheet_name}!{col}{r}", snippet))
            texts = {col: unicodedata.normalize("NFKC", t).strip() for col, t in cells.items()}
            heads = [col for col, t in texts.items() if t == STATE_HEADER]
            if heads and sum(1 for t in texts.values() if t) >= 3:
                # 「状態」の欄のある見出しの行。ここから下の行の「状態」が「仮」なら、仮の印として数える
                state_col = heads[0]
                name_col = next((col for col, t in texts.items() if t in ("名前", "欄", "品名", "項目", "記述")), None)
                continue
            if state_col and texts.get(state_col) == STATE_PROVISIONAL:
                label = cells.get(name_col, "").strip() if name_col else ""
                out.append(Finding(PROVISIONAL, rel, f"{sheet_name}!{state_col}{r}", f"「状態」が仮{('（' + label + '）') if label else ''}"))
    if places.nfc(Path(rel).name) == input_sheet.FILE_NAME:
        try:
            _parts, _name, grid = input_sheet.read_grid(blob)
            _head, cols = grid.header()
            for r, screen, field, staff in grid.field_rows():
                if staff:
                    continue
                if not grid.texts.get(f"{cols[input_sheet.HEAD_VALUE]}{r}", "").strip():
                    out.append(Finding(BLANK, rel, f"{screen}／{field}" if screen else field, "（値が空）"))
        except ValueError as e:
            raise CheckError(f"{rel} の形が入力シートと違います（{e}）")
    return out


def text_findings(text: str, rel: str) -> List[Finding]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for kind, snippet in marks(line):
            out.append(Finding(kind, rel, f"{n}行目", snippet))
    return out


def _read_bytes(path: Path, rel: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as e:
        raise CheckError(f"{rel} を読めませんでした（{e.strerror or e}）")


_PLAIN_NUMBER = re.compile(r"^-?[0-9]+(?:\.[0-9]+)?$")
# 入力シートの欄のうち、財務モデルと照らす欄（制度データの「値の出どころ」がこの語を含む。T8-11）
MODEL_SOURCES = ("財務モデル", "その3")


def _model_fields(seido: Optional[dict]) -> set:
    out = set()
    if not isinstance(seido, dict):
        return out
    for screen, field in input_sheet.fields_of(seido):
        if any(w in str(field.get("値の出どころ") or "") for w in MODEL_SOURCES):
            out.add((str(screen.get("名前") or ""), str(field.get("名前") or "")))
    return out


def _texts_of(blob: bytes, rel: str, suffix: str, seido: Optional[dict]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """照合に使う本文（書いた場所 → 文）と、財務モデルと照らす数のセル（書いた場所 → 数の文字）。

    Word は様式の項目と欄ごと、入力シートは「画面／欄」ごと、Excel の様式（その3 など）は入力の欄のセルごと
    （「その3.xlsx／<シート>!<セル>」）、文字のファイルは全体。数だけのセルは、入力シートなら値の出どころが財務モデルか
    その3 の欄、Excel の様式なら入力の欄のすべてを、財務モデルと照らす（B16 の直し。T8-11）。
    """
    out: Dict[str, str] = {}
    cells: Dict[str, str] = {}
    name = places.nfc(Path(rel).name)
    if suffix in WORD_SUFFIXES:
        root = _word_root(blob, rel)
        items = _item_ranges(root, seido)
        if items:
            for item, ps in items:
                out[item] = _item_text(ps, periods=False)
        else:
            out[rel] = _non_blue_text(_outer_paragraphs(root))
    elif suffix in EXCEL_SUFFIXES and name == input_sheet.FILE_NAME:
        _parts, _name, grid = input_sheet.read_grid(blob)
        _head, cols = grid.header()
        model_fields = _model_fields(seido)
        for r, screen, field, staff in grid.field_rows():
            value = grid.texts.get(f"{cols[input_sheet.HEAD_VALUE]}{r}", "").strip()
            if value and not staff and not input_sheet.is_not_applicable(value):
                out[f"{screen}／{field}"] = value
                if _PLAIN_NUMBER.match(value.replace(",", "")) and (screen, field) in model_fields:
                    cells[f"{screen}／{field}"] = value
    elif suffix in EXCEL_SUFFIXES and name != konkyo.FILE_NAME:
        from lib import yoshiki_excel

        try:
            book = yoshiki_excel.Book(blob)
        except ValueError:
            return out, cells
        for sh in book.sheets:
            for ref in sorted(sh.inputs):
                value = sh.grid.texts.get(ref, "").strip()
                if not value:
                    continue
                place = f"{name}／{sh.name}!{ref}"
                if _PLAIN_NUMBER.match(value):
                    cells[place] = value
                else:
                    out[place] = value
    elif suffix in TEXT_SUFFIXES:
        out[rel] = blob.decode("utf-8", errors="replace")
    return out, cells


def _nouns(folder: Path) -> List[str]:
    """固有名詞の一覧（会社の記録の名前の事実と、書類の台帳の相手先）。DESIGN 6章。"""
    out: List[str] = []
    try:
        from lib import company_record

        for it in company_record.load(folder).get("項目", []):
            if it.get("種類") == company_record.FACT and re.search(r"会社名|社名|代表者|取引先|業者|仕入先", str(it.get("名前"))):
                value = str(it.get("値") or "")
                out += [v for v in re.split(r"[、,（）()]", value) if v.strip()]
    except Exception:
        pass
    try:
        ledger = json.loads(places.actual(folder, "記録/書類の台帳.json").read_text(encoding="utf-8"))
        for entry in ledger.get("原本") or []:
            if isinstance(entry, dict) and str(entry.get("相手先") or "").strip():
                out.append(str(entry["相手先"]).strip())
    except Exception:
        pass
    return out


def _model_numbers(folder: Path) -> Optional[dict]:
    path = places.actual(folder, zaimu_numbers_file())
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def zaimu_numbers_file() -> str:
    return "記録/財務モデルの数字.json"  # lib/zaimu.py の NUMBERS_FILE と同じ


# ---------------------------------------------------------------- 文字数（T8-9 の上限と目安。TASKS B19）

# 目安の範囲（仮）：目安の文字数の半分から、2割増しまで（「30字程度」なら15〜36字）。SPEC は範囲を決めていない
TARGET_LOW, TARGET_HIGH = 0.5, 1.2
LENGTH = "文字数"


def char_count(text: str) -> int:
    """数える文字数（改行と、行の頭と終わりの空白は数えない）。"""
    return sum(len(line.strip()) for line in (text or "").splitlines())


def _limits(seido: Optional[dict]) -> Dict[str, Tuple[str, int]]:
    out: Dict[str, Tuple[str, int]] = {}
    for form in _forms(seido):
        for entry in form.get("項目") or []:
            value = ((entry.get("分量の上限") or {}).get("値") or {}) if isinstance(entry, dict) else {}
            kind, n = value.get("種類"), value.get("文字数")
            if kind in ("上限", "目安") and isinstance(n, int) and not isinstance(n, bool) and n > 0:
                out[str(entry.get("名前"))] = (kind, n)
    return out


def length_findings(texts: Dict[str, str], seido: Optional[dict]) -> List[Dict[str, Any]]:
    """様式の項目の文字数が、上限を超える・目安の範囲（仮）から外れるもの。目安も上限もない項目は審査役が見る。"""
    out = []
    for name, (kind, n) in _limits(seido).items():
        if name not in texts:
            continue
        got = char_count(texts[name])
        if kind == "上限" and got > n:
            out.append({"場所": name, "文字数": got, "決まり": f"上限 {n}字", "理由": f"上限の{n}字を{got - n}字超えています"})
        elif kind == "目安" and not (n * TARGET_LOW <= got <= n * TARGET_HIGH):
            low, high = int(n * TARGET_LOW), int(n * TARGET_HIGH)
            out.append({"場所": name, "文字数": got, "決まり": f"目安 {n}字（{low}〜{high}字）",
                        "理由": f"目安の{n}字程度から外れています（{got}字）"})
    return out


# ---------------------------------------------------------------- 書く → 確かめる → 直すの回数（DESIGN 8章。TASKS B19）

ROUNDS_FILE = ".hojokin/一時/確かめの回数.json"
MAX_REVIEWS = 3  # 社長に返すまでに審査役を呼ぶ回数（仮）
MAX_CODE_FIXES = 5  # コードの確かめを直して確かめ直す回数（仮）


def _rounds(folder: Path) -> Dict[str, Any]:
    path = places.actual(folder, ROUNDS_FILE)
    state: Dict[str, Any] = {}
    if path is not None and path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
    # 社長の答えをもらった後は数え直す（質問の記録の、いちばん新しい答えの時刻が、数え始めより後なら）
    latest = _latest_answer(folder)
    if latest and latest > str(state.get("数え始め") or ""):
        state = {"数え始め": latest}
    return state


def _save_rounds(folder: Path, state: Dict[str, Any]) -> None:
    try:
        places.no_link_on_the_way(folder, ROUNDS_FILE)
        target = places.actual(folder, ROUNDS_FILE, partial=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except (places.PlaceError, OSError):
        pass


def _latest_answer(folder: Path) -> str:
    path = places.actual(folder, QUESTION_LOG)
    if path is None or not path.is_file():
        return ""
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("質問") or []
    except (OSError, ValueError, AttributeError):
        return ""
    return max((str(e.get("答えた時刻") or "") for e in entries if isinstance(e, dict) and e.get("答え")), default="")


def _stamp(folder: Path) -> str:
    from lib import dates

    return dates.now(folder).isoformat(timespec="seconds")


def after_check(folder: Path, passed: bool) -> Dict[str, Any]:
    """コードの確かめの後に、通らなかった回数を数える（通ったら0に戻す）。社長に返す理由があれば入れて返す。"""
    state = _rounds(folder)
    state.setdefault("数え始め", _stamp(folder))
    state["コードの確かめの回数"] = 0 if passed else int(state.get("コードの確かめの回数") or 0) + 1
    _save_rounds(folder, state)
    return state


def stop_reasons(state: Dict[str, Any]) -> List[str]:
    """社長に返す理由（審査役を呼ばずに返す）。"""
    out = []
    if state.get("社長の答えが要る"):
        out.append("審査役の指摘に、社長の答えや判断が要るものがあります。審査役を呼び直さずに、すぐ社長に返してください")
    if state.get("同じ指摘が続いた"):
        out.append("同じ指摘が2回続きました（直しても良くなっていません）。社長に返してください")
    if int(state.get("審査役を呼んだ回数") or 0) >= MAX_REVIEWS:
        out.append(f"社長に返すまでに審査役を{MAX_REVIEWS}回呼んでも、要修正が残っています。社長に返してください")
    if int(state.get("コードの確かめの回数") or 0) > MAX_CODE_FIXES:
        out.append(f"コードの確かめを直して確かめ直す繰り返しが{MAX_CODE_FIXES}回を超えました。社長に返してください")
    return out


def returning_text(reasons: Sequence[str]) -> str:
    lines = ["社長に返します（書く → 確かめる → 直すの繰り返しを、ここで止めます）："]
    lines += [f"- {r}" for r in reasons]
    lines.append("社長には、直したこと、残った指摘と直し方の案、質問（3つまで、理由を添えて）を示してください。"
                 "社長の答えをもらって直した後は、回数を数え直します。")
    return "\n".join(lines)


def _finding_key(item: dict) -> str:
    return f"{item.get('場所', '')}｜{item.get('観点', '')}"


def after_review(folder: Path, status: dict) -> Dict[str, Any]:
    """審査役の結果を読んだ後に、同じ指摘が続いたか・社長の答えが要るかを残す（同じ結果は1回だけ数える）。"""
    state = _rounds(folder)
    if not status.get("届いた") or state.get("読んだ結果") == status.get("確かめの番号"):
        return state
    items = status.get("指摘") or []
    keys = sorted({_finding_key(i) for i in items if (i.get("重さ") or "要修正") == "要修正"})
    prev = state.get("前の要修正")
    state["同じ指摘が続いた"] = bool(keys) and isinstance(prev, list) and bool(set(keys) & set(prev)) and keys == sorted(prev)
    asks = [i for i in items if str(i.get("社長に聞くこと") or "").strip()] + list(status.get("社長の答えが要ること") or [])
    state["社長の答えが要る"] = bool(asks)
    state["前の要修正"] = keys
    state["読んだ結果"] = status.get("確かめの番号")
    _save_rounds(folder, state)
    return state


def before_review(folder: Path) -> List[str]:
    """審査役を呼ぶ前に、社長に返す理由がないか。"""
    return stop_reasons(_rounds(folder))


def review_called(folder: Path, number: str) -> None:
    state = _rounds(folder)
    state.setdefault("数え始め", _stamp(folder))
    state["審査役を呼んだ回数"] = int(state.get("審査役を呼んだ回数") or 0) + 1
    state["最後の確かめの番号"] = number
    _save_rounds(folder, state)


def style_count(folder: Path, texts: Dict[str, str]) -> Tuple[Optional[dict], str]:
    """文体の A・B と会社の避けたい言い方の数え上げ（lib/buntai.py。TASKS B17）。基準のファイルがなければ (None, 理由)。"""
    from lib import buntai

    path = Path(__file__).resolve().parents[1] / STYLE_CRITERIA
    try:
        criteria = buntai.load(path)
    except OSError:
        return None, f"文体の基準（{STYLE_CRITERIA.as_posix()}）が読めないので、文体は数えていません"
    rules: List[dict] = []
    try:
        from lib import company_record

        rules = [it for it in company_record.load(folder).get("項目", []) if it.get("種類") == company_record.RULE]
    except Exception:
        pass
    avoid, keep = buntai.company_phrases(rules)
    return buntai.count(texts, criteria, avoid, keep), ""


def check(folder: Path, case: str, stage: str, seido: Optional[dict]) -> dict:
    """コードによる確かめ：仮の印・空欄・根拠のない記述の数え上げと、根拠対照表・財務モデルとの照合（lib/shogo.py）。"""
    from lib import shogo

    files = application_files(folder, case, stage)
    findings: List[Finding] = []
    problems: List[str] = []
    notes: List[str] = []
    looked: List[str] = []
    texts: Dict[str, str] = {}
    cells: Dict[str, str] = {}
    evidence_rel = f"{shinsa_result.application_rel(case, stage)}/{konkyo.FILE_NAME}"
    evidence_rows = None
    for rel, path in sorted(files.items()):
        suffix = path.suffix.lower()
        if rel == evidence_rel:
            try:
                evidence_rows = konkyo.read(_read_bytes(path, rel))
            except konkyo.EvidenceError as e:
                problems.append(f"{rel} を読めません（{e}）")
            continue
        try:
            if rel != MODEL_FILE:
                got_texts, got_cells = _texts_of(_read_bytes(path, rel), rel, suffix, seido)
                texts.update(got_texts)
                cells.update(got_cells)
            if suffix in WORD_SUFFIXES:
                findings += word_findings(_read_bytes(path, rel), rel, seido)
                tables = form_table_notes(_read_bytes(path, rel), rel, seido)
                if tables:
                    notes.append("様式の表に書いていない項目があります（表を文章や図で代えず、表の欄として対応づけて書く）："
                                 + "、".join(tables))
            elif suffix in EXCEL_SUFFIXES:
                findings += sheet_findings(_read_bytes(path, rel), rel)
            elif suffix in TEXT_SUFFIXES:
                findings += text_findings(_read_bytes(path, rel).decode("utf-8", errors="replace"), rel)
            else:
                notes.append(f"{rel} は Word・Excel・文字のファイルではないので、印を数えていません")
                continue
        except ValueError as e:  # Word・Excel として読めない（FormError・SpanError・CheckError）
            problems.append(f"{rel} を確かめられません（{e}）")
            continue
        looked.append(rel)
    if not looked:
        problems.append(f"{shinsa_result.application_rel(case, stage)}/ に、申請書のファイル（Word・Excel・文字のファイル）がありません")
    if evidence_rows is None:
        if not any(p.startswith(evidence_rel) for p in problems):
            problems.append(f"{evidence_rel} がありません。計画書に書いた数字・固有名詞・日付と出典を、konkyo で根拠対照表に残してください")
    else:
        for n, row in enumerate(evidence_rows, 1):
            if not row.get("出典"):
                findings.append(Finding(UNSUPPORTED, evidence_rel, f"{n}行目", row.get("記述", "")))
    matched = {k: [] for k in shogo.KINDS}
    numbers = _model_numbers(folder)
    if cells and numbers is None:
        notes.append("財務モデルの数字の控え（記録/財務モデルの数字.json）がないので、様式と入力シートの数字は財務モデルと照らしていません")
    if evidence_rows is not None and (texts or cells):
        matched = shogo.check(texts, evidence_rows, numbers, _nouns(folder), cells=cells)
        for f in matched[shogo.NO_SOURCE]:
            findings.append(Finding(UNSUPPORTED, "本文", f["場所"], f"{f['文字']}（{f['理由']}）"))
    newer = facts_after_model(folder, numbers)
    if newer:
        shown = "、".join(newer[:10]) + (f"、ほか{len(newer) - 10}件" if len(newer) > 10 else "")
        notes.append("財務モデルを作った後に、会社の記録に増えた・変わった事実があります：" + shown
                     + "。増産の量・取引先・単価・人の配置など、財務モデルの前提に関わるなら、財務モデルを作り直し、"
                     "計画書の数字もそろえてください")
    style, style_note = style_count(folder, texts)
    if style_note:
        notes.append(style_note)
    lengths = length_findings(texts, seido)
    if seido is None:
        notes.append("制度データがないので、様式の項目ごとの空欄（まだ書いていない項目）は数えていません")
    else:
        unmapped = _unmapped_items(seido)
        if unmapped:
            notes.append("様式の項目のうち、書き込む位置をまだ対応づけていないもの（まだ書いていないかは数えていません）："
                         + "、".join(unmapped))
    by_kind = {k: [f.as_dict() for f in findings if f.kind == k] for k in (PROVISIONAL, BLANK, UNSUPPORTED)}
    extra = {k: matched[k] for k in (shogo.MISMATCH, shogo.CITATION, shogo.MODEL_MISMATCH)}
    from lib import buntai

    style_failing = buntai.failing(style) if style else 0
    passed = not problems and not any(by_kind.values()) and not any(extra.values()) and not style_failing \
        and not lengths
    return {
        "案件": case,
        "段階": stage,
        "見たファイル": looked,
        "仮の印": by_kind[PROVISIONAL],
        "空欄": by_kind[BLANK],
        "根拠なし": by_kind[UNSUPPORTED],
        "食い違い": extra[shogo.MISMATCH],
        "本文の出典": extra[shogo.CITATION],
        "財務モデルとの食い違い": extra[shogo.MODEL_MISMATCH],
        "文体": style,
        LENGTH: lengths,
        "根拠対照表の行": len(evidence_rows) if evidence_rows is not None else None,
        "問題": problems,
        "注意": notes,
        "通った": passed,
    }


def report_text(report: dict) -> str:
    """数え上げの結果を、社長と Claude に見せる文にする。"""
    extra = [(k, report.get(k) or []) for k in ("食い違い", "本文の出典", "財務モデルとの食い違い")]
    lines = [f"案件：{report['案件']}　段階：{report['段階']}",
             f"仮の印 {len(report['仮の印'])}件、空欄 {len(report['空欄'])}件、根拠のない記述 {len(report['根拠なし'])}件、"
             + "、".join(f"{k} {len(v)}件" for k, v in extra)]
    for kind, title in ((PROVISIONAL, "仮の印"), (BLANK, "空欄"),
                        (UNSUPPORTED, "根拠のない記述（根拠対照表の出典が空か、本文の数字・固有名詞・日付が根拠対照表にない）")):
        if report[kind]:
            lines.append(f"{title}：")
            lines += [f"- {Finding(f['種類'], f['ファイル'], f['場所'], f['文字']).line()}" for f in report[kind]]
    titles = {"食い違い": "根拠対照表と本文の食い違い（表の記述が本文にない）",
              "本文の出典": "本文に書いた出典（出典は根拠対照表だけに書く）",
              "財務モデルとの食い違い": "財務モデルとの食い違い（数字は財務モデルの道具の出力から取る）"}
    for k, items in extra:
        if items:
            lines.append(f"{titles[k]}：")
            lines += [f"- {f['場所']}：{f['文字']}（{f['理由']}）" for f in items]
    for f in report.get(LENGTH) or []:
        lines.append(f"- 文字数：{f['場所']} {f['文字数']}字（{f['決まり']}。{f['理由']}）")
    style = report.get("文体")
    if style:
        lines.append(f"文体：要修正 {len(style['要修正'])}件、会社の避けたい言い方 {len(style['避けたい言い方'])}件"
                     f"（避ける言い回し {len(style['避ける言い回し'])}件・注意 {len(style['注意'])}件・"
                     f"弱い注意 {len(style['弱い注意'])}件は合否に使いません。避ける言い回しは、自然に言い換えられる所だけ直す）")
        for key in ("要修正", "避ける言い回し", "避けたい言い方"):
            for f in style[key]:
                fix = f"→ {f['直し方']}" if f.get("直し方") else ""
                lines.append(f"- {key}：{f['場所']}「{f['文字']}」（{f['基準']}）{fix}")
    for p in report["問題"]:
        lines.append(f"問題：{p}")
    for n in report["注意"]:
        lines.append(f"注意：{n}")
    lines.append("コードの確かめは通りました。" if report["通った"] else "コードの確かめは通っていません。")
    return "\n".join(lines)


# ---------------------------------------------------------------- 根拠対照表


def evidence_target(folder: Path, case: str, stage: str) -> Tuple[str, Path]:
    rel = f"{shinsa_result.application_rel(case, stage)}/{konkyo.FILE_NAME}"
    _no_link(folder, rel, "書きません")
    target = places.actual(folder, rel, partial=True)
    if not target.parent.is_dir():
        raise CheckError(f"{shinsa_result.application_rel(case, stage)}/ がありません。先に junbi で段階のフォルダを作ってください")
    return rel, target


def write_evidence(folder: Path, case: str, stage: str, data: Any, replace: bool = False) -> dict:
    """根拠対照表に行を足す（replace なら置き換える）。"""
    new = konkyo.normalize_rows(data)
    # 会社の記録から書いた行の出典は、記録の項目（id と名前）にそろえる。記録にない id は断る（T13-4）
    from lib import company_record

    try:
        new, from_record = company_record.evidence_rows(folder, new)
    except company_record.RecordError as e:
        raise konkyo.EvidenceError(str(e)) from e
    rel, target = evidence_target(folder, case, stage)
    existing = None
    if target.is_file():
        existing = konkyo.read(_read_bytes(target, rel))
    rows = konkyo.merged(existing, new, replace)
    blob = konkyo.build(rows)
    rel, target = evidence_target(folder, case, stage)  # 書く直前にもう一度確かめる
    from lib.docx_min import write_replacing

    write_replacing(target, blob)
    return {"場所": rel, "行": len(rows), "足した行": len(new), "出典のない行": len(konkyo.unsupported(rows)),
            "作った": existing is None, "記録から書いた行": from_record}


# ---------------------------------------------------------------- 審査役に渡すもの


def _now_text(folder: Path) -> str:
    return shinsa_result._now_text(folder)


def next_number(folder: Path) -> str:
    """次の確かめの番号（今の控え・保存された結果・完成の記録のうち、いちばん大きい番号の次）。"""
    seen = [0]
    note = shinsa_result.load_note(folder)
    if note is not None:
        seen.append(shinsa_result.number_of(note["確かめの番号"]) or 0)
    _no_link(folder, RESULTS_DIR)
    top = places.actual(folder, RESULTS_DIR)
    if top is not None and top.is_dir():
        for p in top.iterdir():
            if p.suffix == ".json":
                seen.append(shinsa_result.number_of(places.nfc(p.stem)) or 0)
    for entry in _completion_entries(folder):
        seen.append(shinsa_result.number_of(entry.get("確かめの番号")) or 0)
    return shinsa_result.number_text(max(seen) + 1)


def _non_blue_text(ps) -> str:
    # 図と写真の段落は「［図：題］」として渡す（審査役が、図があることと何の図かを読めるように。TASKS B33）
    return "\n".join(yw.text_of(p) if yw.text_of(p).strip() else yw.figure_text(p) for p in ps
                     if yw.blue_state(p) != "全部" and (yw.text_of(p).strip() or yw.figure_text(p)))


def _word_sections(blob: bytes, rel: str, seido: Optional[dict]) -> List[str]:
    root = _word_root(blob, rel)
    items = _item_ranges(root, seido)
    out = [f"## {rel}", ""]
    if items:
        for name, ps in items:
            out += [f"### {name}", "", _item_text(ps) or "（まだ何も書いていません）", ""]
    else:
        out += ["（様式の項目との対応がないので、本文の全体を載せます）", "", _non_blue_text(_outer_paragraphs(root)), ""]
    return out


def _sheet_rows_text(blob: bytes, rel: str, only: Optional[str] = None,
                     values: Optional[Dict[str, Dict[str, str]]] = None) -> List[str]:
    """シートごとに、行のセルの文字を並べる。values（シート → セル → 文字）があれば、そのセルは values の文字にする
    （計算し直した数式の値）。"""
    out = []
    for sheet_name, grid in _sheets(blob, rel):
        if only and sheet_name != only:
            continue
        out += [f"### シート「{sheet_name}」", ""]
        rows = _by_row(grid)
        for ref, shown in ((values or {}).get(sheet_name) or {}).items():
            m = input_sheet._REF.fullmatch(ref)
            if m:
                rows.setdefault(int(m.group(2)), {})[m.group(1)] = shown
        for r in sorted(rows):
            cells = [rows[r][c].replace("\n", " ") for c in sorted(rows[r], key=_col_key) if rows[r][c].strip()]
            if cells:
                out.append("- " + " | ".join(cells))
        out.append("")
    return out


def _input_sheet_text(blob: bytes, rel: str) -> List[str]:
    _parts, _name, grid = input_sheet.read_grid(blob)
    _head, cols = grid.header()
    out = [f"## {rel}", ""]
    for r, screen, field, staff in grid.field_rows():
        value = grid.texts.get(f"{cols[input_sheet.HEAD_VALUE]}{r}", "").strip()
        who = "（担当者が画面で入れる欄）" if staff else ""
        out.append(f"- {screen}／{field}{who}：{value or '（空）'}")
    out.append("")
    return out


def plan_text(folder: Path, files: Dict[str, Path], seido: Optional[dict], number: str, case: str, stage: str,
              recalcs: Optional[Dict[str, dict]] = None) -> str:
    """計画書の本文。recalcs（recalc_forms の戻り値）があれば、Excel の様式の数式のセルは、計算し直した値にする。"""
    out = [f"# 計画書の本文（確かめの番号：{number}）", "", f"案件：{case}　段階：{stage}", "",
           "申請書のファイルから、道具が文字を取り出したものです。様式の説明の青字は除いています。", ""]
    for rel, path in sorted(files.items()):
        name = places.nfc(path.name)
        suffix = path.suffix.lower()
        if rel == MODEL_FILE or name == konkyo.FILE_NAME:
            continue
        blob = _read_bytes(path, rel)
        if suffix in WORD_SUFFIXES:
            out += _word_sections(blob, rel, seido)
        elif suffix in EXCEL_SUFFIXES and name == input_sheet.FILE_NAME:
            out += _input_sheet_text(blob, rel)
        elif suffix in EXCEL_SUFFIXES:
            done = (recalcs or {}).get(rel)
            out += [f"## {rel}", ""]
            if done is not None:
                out += [recalc_line(done), ""]
            out += _sheet_rows_text(blob, rel, values=done.get("値") if done else None)
        elif suffix in TEXT_SUFFIXES:
            out += [f"## {rel}", "", blob.decode("utf-8", errors="replace"), ""]
    return "\n".join(out).rstrip() + "\n"


def seido_extract(seido: dict) -> dict:
    keys = ("名前", "分量の上限", "換算", "対応する審査項目", "役割")
    forms = [{"名前": f.get("名前"),
              "項目": [{k: e[k] for k in keys if k in e} for e in (f.get("項目") or []) if isinstance(e, dict)]}
             for f in _forms(seido)]
    return {"制度": seido.get("制度"), "審査項目": seido.get("審査項目"), "加点": seido.get("加点"), "様式": forms}


def _company_extract(folder: Path) -> Tuple[Optional[dict], str]:
    try:
        from lib import company_record

        data = company_record.load(folder)
    except Exception as e:  # 記録が読めない・形が違う。審査役には、渡せなかったことを伝える
        return None, f"会社の記録を読めませんでした（{e}）"
    rules = [it for it in data.get("項目", []) if it.get("種類") == company_record.RULE]
    results = [it for it in data.get("項目", []) if it.get("種類") == company_record.RESULT]
    if not rules and not results:
        return None, "会社の記録に、書き方の決まりと過去に受けた指摘がまだありません"
    return {"書き方の決まり": rules, "申請と採否（過去に受けた指摘）": results}, ""


_MADE_AT = re.compile(r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日")


def facts_after_model(folder: Path, numbers: Optional[dict]) -> List[str]:
    """財務モデルを作った後に増えた・値が変わった、会社の記録の事実（「名前（id）」）。
    控えに作ったときの事実の指紋があれば、それと比べる。前の控え（指紋なし）は、覚えた日が作った日より後のものを挙げる。
    完成を止めない注意にする（財務モデルの前提に関わるかは Claude が判断する。B37）。"""
    if not numbers:
        return []
    from lib import company_record

    try:
        data = company_record.load(folder)
    except Exception:  # 記録が読めないときは、ほかの確かめで分かる
        return []
    marks = numbers.get(company_record.FACT_MARKS_KEY)
    out = []
    if isinstance(marks, dict):
        for fid, mark in company_record.fact_marks(data).items():
            if marks.get(fid) != mark:
                item = company_record.find(data, fid, company_record.FACT)
                out.append(f"{item.get('名前')}（{fid}）")
        return out
    made = _MADE_AT.search(str(numbers.get("作った日時") or ""))
    if not made:
        return []
    made_day = datetime.date(int(made.group(1)), int(made.group(2)), int(made.group(3)))
    for it in data.get("項目", []):
        if it.get("種類") != company_record.FACT or it.get("状態") != company_record.VALID:
            continue
        try:
            learned = datetime.date.fromisoformat(str(it.get("覚えた日") or "")[:10])
        except ValueError:
            continue
        if learned > made_day:
            out.append(f"{it.get('名前')}（{it.get('id')}）")
    return out


def yardstick_text(folder: Path, plugin_root: Path) -> Tuple[Optional[str], str]:
    """審査役に渡す「構成と効果の物差し」。作者の知見の構成の型（段ごとに入れる事実の種類・つなぎ・図表を置く所）と
    審査の観点、財務モデルの「投資の効果の見え方」。浅い計画書と、設備投資の効果が少なく見える計画書を、審査役が
    見つけられるようにする（11/6 のリハーサルで、短く浅い計画書が完成になったため。前は知見を審査役に渡さなかった）。"""
    parts = ["# 構成と効果の物差し（作者の知見と、財務モデルの投資の効果の見え方）", ""]
    knowledge = Path(plugin_root) / "knowledge"
    for name in ("構成の型.json", "審査の観点.json"):
        try:
            data = json.loads((knowledge / name).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return None, f"作者の知見（knowledge/{name}）を読めませんでした（{e}）"
        parts += [f"## {name[:-5]}", "", "```json", json.dumps(data, ensure_ascii=False, indent=1), "```", ""]
    path = places.actual(folder, zaimu_numbers_file())
    effect = None
    if path is not None and path.is_file() and places.is_inside(folder, path):
        try:
            effect = (json.loads(path.read_text(encoding="utf-8")).get("中身") or {}).get("投資の効果の見え方")
        except (OSError, ValueError, AttributeError):
            effect = None
    parts.append("## 投資の効果の見え方（財務モデルの数字の控えから）")
    parts.append("")
    if effect:
        parts += ["```json", json.dumps(effect, ensure_ascii=False, indent=1), "```"]
    else:
        parts.append("財務モデルの数字の控えに、投資の効果の見え方がまだありません（財務モデルを作り直すと出ます）。")
    return "\n".join(parts) + "\n", ""


def style_c_text(plugin_root: Path) -> Tuple[Optional[str], str]:
    path = Path(plugin_root) / STYLE_CRITERIA
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"文体の基準（{STYLE_CRITERIA.as_posix()}）を読めませんでした（{e.strerror or e}）"
    m = re.search(r"^## C\..*?(?=^## |\Z)", text, flags=re.M | re.S)
    if m is None:
        return None, "文体の基準に C の節がありません"
    return m.group(0).rstrip() + "\n", ""


def _questions(folder: Path) -> Tuple[Optional[str], str]:
    try:
        places.no_link_on_the_way(folder, QUESTION_LOG)
    except places.PlaceError:
        return None, f"{QUESTION_LOG} が別名になっているので、渡していません"
    path = places.actual(folder, QUESTION_LOG)
    if path is None or not path.is_file():
        return None, "聞き取りの記録（記録/質問の記録.json）がまだありません"
    try:
        return path.read_text(encoding="utf-8"), ""
    except OSError as e:
        return None, f"聞き取りの記録を読めませんでした（{e.strerror or e}）"


def _write_text(folder: Path, rel: str, text: str) -> None:
    _no_link(folder, rel, "書きません")
    target = places.actual(folder, rel, partial=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    _no_link(folder, rel, "書きません")
    from lib.docx_min import write_replacing

    write_replacing(target, text.encode("utf-8"))


def _json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------- Excel の様式の数式の値（計算し直した写し。TASKS B19）

RECALC_DIR = ".hojokin/一時/計算し直した写し"
RECALC_WORK = "作業"
RECALC_FAILED = "数式の値は計算し直せなかった（Excel で開いて保存すると直る）"
GENERAL = "General"
# 組み込みの数の書式（番号 → 書式。日付の14は、日本の既定の形）
BUILTIN_FORMATS = {0: GENERAL, 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%",
                   14: "yyyy/m/d", 22: "yyyy/m/d"}
_DATE_TOKENS = re.compile(r"yyyy|yy|mm|m|dd|d", re.I)
EXCEL_EPOCH = datetime.date(1899, 12, 30)


def _excel_form(rel: str, path: Path) -> bool:
    """申請書の Excel の様式か（入力シート・根拠対照表・財務モデルは除く）。"""
    name = places.nfc(path.name)
    return path.suffix.lower() in EXCEL_SUFFIXES and rel != MODEL_FILE and \
        name not in (input_sheet.FILE_NAME, konkyo.FILE_NAME)


def number_formats(parts: Dict[str, bytes]) -> List[str]:
    """セルの書式の番号（セルの s）ごとの、数の書式の文字。"""
    S = input_sheet.S
    try:
        styles = ET.fromstring(parts["xl/styles.xml"])
    except (KeyError, ET.ParseError):
        return []
    codes: Dict[int, str] = {}
    fmts = styles.find(f"{{{S}}}numFmts")
    for f in list(fmts) if fmts is not None else []:
        try:
            codes[int(f.get("numFmtId", ""))] = f.get("formatCode") or ""
        except ValueError:
            continue
    out = []
    xfs = styles.find(f"{{{S}}}cellXfs")
    for xf in list(xfs) if xfs is not None else []:
        try:
            fid = int(xf.get("numFmtId", "0"))
        except ValueError:
            fid = 0
        out.append(codes.get(fid, BUILTIN_FORMATS.get(fid, GENERAL)))
    return out


def _sections(code: str) -> List[str]:
    """数の書式を「;」で節に分ける（"…" と […] の中の「;」では分けない）。"""
    out, cur, quoted, bracket = [], "", False, False
    for ch in code:
        if ch == '"' and not bracket:
            quoted = not quoted
        elif ch == "[" and not quoted:
            bracket = True
        elif ch == "]" and not quoted:
            bracket = False
        if ch == ";" and not quoted and not bracket:
            out.append(cur)
            cur = ""
            continue
        cur += ch
    out.append(cur)
    return out


def _tokens(section: str) -> List[Tuple[str, str]]:
    """書式の1つの節を、（種類、文字）に分ける。種類は 文字・数・日付・百分率・指数・不明。"""
    out: List[Tuple[str, str]] = []
    i = 0
    while i < len(section):
        ch = section[i]
        if ch == '"':
            end = section.find('"', i + 1)
            end = len(section) if end < 0 else end
            out.append(("文字", section[i + 1:end]))
            i = end + 1
        elif ch == "\\" and i + 1 < len(section):
            out.append(("文字", section[i + 1]))
            i += 2
        elif ch in "_*" and i + 1 < len(section):
            i += 2  # 幅をそろえる空き・埋める文字は、文字にしない
        elif ch == "[":
            end = section.find("]", i)
            end = len(section) if end < 0 else end
            inner = section[i + 1:end]
            if inner.startswith("$"):
                out.append(("文字", inner[1:].split("-", 1)[0]))  # 通貨の印（[$¥-411] の ¥）
            i = end + 1  # 色・条件は文字にしない
        elif ch in "0#?.,":
            out.append(("数", ch))
            i += 1
        elif ch == "%":
            out += [("百分率", ""), ("文字", "%")]
            i += 1
        elif ch in "Ee" and section[i + 1:i + 2] in ("+", "-"):
            out.append(("指数", ""))
            i += 2
        elif ch.lower() in "ymdhs":
            m = _DATE_TOKENS.match(section, i)
            if m is None or ch.lower() in "hs":
                out.append(("不明", ch))
                i += 1
            else:
                out.append(("日付", m.group(0).lower()))
                i = m.end()
        elif ch == "@":
            out.append(("不明", ch))
            i += 1
        else:
            out.append(("文字", ch))
            i += 1
    return out


def _general(value: float) -> str:
    if value != value or value in (float("inf"), float("-inf")):
        return str(value)
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return format(value, ".10g")


def format_number(value: float, code: str) -> str:
    """数を、様式の数の書式（小数の桁・桁区切り・百分率・通貨の印・前後の文字・日付）で見せる文字にする。
    読めない書式（指数・時刻など）は、書式を使わずに見せる。"""
    sections = _sections(code or GENERAL)
    section, sign = sections[0], "-" if value < 0 else ""
    if value < 0 and len(sections) >= 2 and sections[1].strip():
        section, sign = sections[1], ""
    elif value == 0 and len(sections) >= 3 and sections[2].strip():
        section = sections[2]
    if section.strip().lower() in ("general", "") or "general" in section.lower():
        return sign + _general(abs(value))
    tokens = _tokens(section)
    kinds = {k for k, _t in tokens}
    if kinds & {"指数", "不明"}:
        return sign + _general(abs(value))
    if "日付" in kinds and "数" not in kinds:
        try:
            day = EXCEL_EPOCH + datetime.timedelta(days=int(value))
        except (OverflowError, ValueError):
            return _general(value)
        parts = {"yyyy": f"{day.year:04d}", "yy": f"{day.year % 100:02d}", "mm": f"{day.month:02d}",
                 "m": str(day.month), "dd": f"{day.day:02d}", "d": str(day.day)}
        return "".join(parts[t] if k == "日付" else t for k, t in tokens)
    if "数" not in kinds:
        return sign + _general(abs(value))
    pattern = "".join(t for k, t in tokens if k == "数")
    whole, _dot, frac = pattern.partition(".")
    digits = sum(1 for ch in frac if ch in "0#?")
    amount = abs(value) * (100 if "百分率" in kinds else 1)
    try:
        rounded = Decimal(repr(amount)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return sign + _general(abs(value))
    shown = format(rounded, f"{',' if ',' in whole.strip(',') else ''}.{digits}f")
    first = next(n for n, (k, _t) in enumerate(tokens) if k == "数")
    last = max(n for n, (k, _t) in enumerate(tokens) if k == "数")
    before = "".join(t for k, t in tokens[:first] if k == "文字")
    after = "".join(t for k, t in tokens[last + 1:] if k == "文字")
    if rounded == 0:
        sign = ""
    return f"{sign}{before}{shown}{after}".strip()


def shown_value(raw: str, kind: str, code: str) -> str:
    """計算し直したセルの値（セルの文字と、セルの種類 t）を、見せる文字にする。"""
    if kind == "b":
        return "TRUE" if raw.strip() == "1" else "FALSE"
    if kind not in ("", "n"):
        return raw  # 文字・誤り（#VALUE! など）はそのまま
    try:
        value = float(raw)
    except ValueError:
        return raw
    return format_number(value, code)


def formula_values(original, recalced) -> Dict[str, Dict[str, str]]:
    """様式（yoshiki_excel.Book）の数式のセルごとに、計算し直した写しの値を、元の様式の数の書式で見せる文字。"""
    formats = number_formats(original.parts)
    by_name = {sh.name: sh for sh in recalced.sheets}
    out: Dict[str, Dict[str, str]] = {}
    for sh in original.sheets:
        if not sh.formulas:
            continue
        other = by_name.get(sh.name)
        if other is None:
            raise ValueError(f"計算し直した写しに、シート「{sh.name}」がありません")
        values = {}
        for ref in sh.formulas:
            cell = other.grid.cells.get(ref)
            try:
                style = int(sh.grid.cells[ref].attrs.get("s", "0"))
            except ValueError:
                style = 0
            code = formats[style] if 0 <= style < len(formats) else GENERAL
            raw = other.grid.texts.get(ref, "") if cell is not None else ""
            values[ref] = shown_value(raw, cell.attrs.get("t", "") if cell is not None else "", code)
        out[sh.name] = values
    return out


def _runnable(path: Optional[str]) -> bool:
    return bool(path) and os.path.isfile(str(path)) and os.access(str(path), os.X_OK)


def _recalc_copy(folder: Path, src: Path, name: str, soffice: str) -> Tuple[str, bytes]:
    """src の写しを LibreOffice で計算し直し、`.hojokin/一時/計算し直した写し/<name>` に上書きして置く。"""
    from lib import libreoffice
    from lib.docx_min import write_replacing

    work_rel = f"{RECALC_DIR}/{RECALC_WORK}"
    _no_link(folder, work_rel, "書きません")
    work = places.actual(folder, work_rel, partial=True)
    shutil.rmtree(str(work), ignore_errors=True)
    work.mkdir(parents=True)
    try:
        data = libreoffice.recalc_xlsx(src, work, soffice).read_bytes()
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    rel = f"{RECALC_DIR}/{name}"
    _no_link(folder, rel, "書きません")
    write_replacing(places.actual(folder, rel, partial=True), data)
    return rel, data


def recalc_forms(folder: Path, files: Dict[str, Path], soffice: Optional[str] = None) -> Dict[str, dict]:
    """申請書の Excel の様式（その3 など）のうち数式のあるものを、LibreOffice で計算し直した写しから、数式のセルの値を取る。

    様式のファイルは変えない。戻り値は、申請書の場所 → {"計算し直した", "写し", "値"（シート → セル → 見せる文字）, "理由"}。
    LibreOffice がない・動かない・写しが読めないときは「計算し直した」が False で、値は None（前の値のまま渡す。止めない）。
    soffice を省くと、LibreOffice を決まった場所と Spotlight で探す（lib/libreoffice.py）。
    """
    from lib import libreoffice, yoshiki_excel

    targets = []
    for rel, path in sorted(files.items()):
        if not _excel_form(rel, path):
            continue
        blob = _read_bytes(path, rel)
        try:
            book = yoshiki_excel.Book(blob)
        except ValueError:
            continue  # 様式として読めないものは、前のとおり文字だけを渡す
        if any(sh.formulas for sh in book.sheets):
            targets.append((rel, path, blob, book))
    out: Dict[str, dict] = {}
    if not targets:
        return out
    if soffice is None:
        soffice = libreoffice.find_soffice()
    for rel, path, blob, book in targets:
        done: Dict[str, Any] = {"計算し直した": False, "写し": None, "値": None, "理由": ""}
        try:
            if not _runnable(soffice):
                raise libreoffice.LibreOfficeError("LibreOffice が見つかりません")
            copy_rel, data = _recalc_copy(folder, path, places.nfc(path.name), str(soffice))
            done.update({"計算し直した": True, "写し": copy_rel,
                         "値": formula_values(book, yoshiki_excel.Book(data))})
        except (libreoffice.LibreOfficeError, OSError, ValueError) as e:
            done.update({"計算し直した": False, "値": None, "理由": str(e)})
        if _read_bytes(path, rel) != blob:  # 様式のファイルは変えない（DESIGN 5章）
            raise CheckError(f"{rel} が、数式を計算し直している間に変わりました。作者に知らせてください")
        out[rel] = done
    return out


def recalc_line(done: dict) -> str:
    """計画書の本文の、Excel の様式の節の頭に置く一言。"""
    if done.get("計算し直した"):
        return ("（数式のセル（省力化指数・投資回収期間・伸び率など）の値は、道具が LibreOffice で計算し直した写しから取り、"
                "様式の数の書式（小数の桁など）で示しています。様式のファイルそのものは変えていません。）")
    why = f"理由：{done['理由']}。" if done.get("理由") else ""
    return (f"（{RECALC_FAILED}。数式のセルの値は、ファイルに残っていた前の計算の値のままで、0 や空のことがあります。"
            f"{why}）")


def prepare(folder: Path, case: str, stage: str, seido: Optional[dict], plugin_root: Path,
            soffice: Optional[str] = None) -> dict:
    """コードの確かめが通ったら、審査役に渡すものをまとめ、控えを置く。通らなければ NotPassed（何も書かない）。

    Excel の様式の数式のセルは、LibreOffice（soffice。省くと探す）で計算し直した写しの値を渡す（recalc_forms）。
    """
    report = check(folder, case, stage, seido)
    if not report["通った"]:
        raise NotPassed(report)
    if seido is None:
        raise CheckError(f"{SEIDO_DIR}/ に制度データがありません。審査項目を渡せないので、先に junbi で制度データを作ってください")
    _no_link(folder, PACKAGE_DIR, "書きません")
    number = next_number(folder)
    files = application_files(folder, case, stage)
    hashes = shinsa_result.file_hashes(folder, case, stage)
    recalcs = recalc_forms(folder, files, soffice)
    # 先に前の控えを消す（まとめている途中に、前の控えに審査役の結果が結び付かないように）
    for name in (shinsa_result.NOTE_FILE,) + PACKAGE_FILES:
        rel = f"{PACKAGE_DIR}/{name}"
        _no_link(folder, rel, "書きません")
        old = places.actual(folder, rel)
        if old is not None and old.is_file():
            old.unlink()
    given: Dict[str, str] = {}
    missing: Dict[str, str] = {}
    evidence_rel = f"{shinsa_result.application_rel(case, stage)}/{konkyo.FILE_NAME}"
    evidence_rows = konkyo.read(_read_bytes(files[evidence_rel], evidence_rel))
    given[PLAN_FILE] = plan_text(folder, files, seido, number, case, stage, recalcs)
    given[SEIDO_FILE] = _json_text(seido_extract(seido))
    given[EVIDENCE_FILE] = f"# 根拠対照表（{evidence_rel}）\n\n" + konkyo.as_markdown(evidence_rows)
    questions, why = _questions(folder)
    if questions is not None:
        given[QUESTIONS_FILE] = questions
    else:
        missing[QUESTIONS_FILE] = why
    record, why = _company_extract(folder)
    if record is not None:
        given[RECORD_FILE] = _json_text(record)
    else:
        missing[RECORD_FILE] = why
    if MODEL_FILE in files:
        given[MODEL_TEXT_FILE] = "# 財務モデルの前提（財務モデル.xlsx の「前提」シート）\n\n" + "\n".join(
            _sheet_rows_text(_read_bytes(files[MODEL_FILE], MODEL_FILE), MODEL_FILE, only="前提"))
    else:
        missing[MODEL_TEXT_FILE] = "財務モデル.xlsx がまだありません"
    style, why = style_c_text(plugin_root)
    if style is not None:
        given[STYLE_FILE] = "# 文体の基準の C（docs/style-criteria.md から写したもの）\n\n" + style
    else:
        missing[STYLE_FILE] = why
    yardstick, why = yardstick_text(folder, plugin_root)
    if yardstick is not None:
        given[YARDSTICK_FILE] = yardstick
    else:
        missing[YARDSTICK_FILE] = why
    given[CHECK_FILE] = _json_text(report)
    for name, text in given.items():
        _write_text(folder, f"{PACKAGE_DIR}/{name}", text)
    note = {
        "確かめの番号": number,
        "案件": case,
        "段階": stage,
        "申請書のハッシュ": shinsa_result.combined_hash(hashes),
        "ファイルのハッシュ": hashes,
        "作った時刻": _now_text(folder),
        "渡したもの": sorted(given),
        "渡していないもの": missing,
    }
    # 控えは最後に置く（hook は控えがあるときだけ、審査役の結果を保存する）
    _write_text(folder, shinsa_result.NOTE_REL, _json_text(note))
    recalced = {rel: {k: done[k] for k in ("計算し直した", "写し", "理由")} for rel, done in recalcs.items()}
    return {"確かめの番号": number, "フォルダ": PACKAGE_DIR, "渡したもの": sorted(given), "渡していないもの": missing,
            "数式の計算し直し": recalced, "コードの確かめ": report}


# ---------------------------------------------------------------- 審査役の結果


def findings_of(result: Optional[dict]) -> Optional[List[dict]]:
    """審査役の結果の「指摘」の並び。形が違えば None。"""
    if not isinstance(result, dict):
        return None
    items = result.get("指摘")
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        return None
    return items


def severity_counts(items: Sequence[dict]) -> Dict[str, int]:
    counts = {s: 0 for s in SEVERITIES}
    for item in items:
        sev = str(item.get("重さ") or "").strip()
        counts[sev if sev in counts else MUST_FIX] += 1  # 重さの分からない指摘は、要修正として扱う
    return counts


def review(folder: Path, number: Optional[str] = None) -> dict:
    """今の控え（か number）の審査役の結果の様子。"""
    note = shinsa_result.load_note(folder)
    if number is None:
        if note is None:
            raise CheckError(f"{shinsa_result.NOTE_REL} がありません。先に prepare で審査役に渡すものをまとめてください")
        number = str(note["確かめの番号"])
    if shinsa_result.number_of(number) is None:
        raise CheckError(f"確かめの番号は「確かめ-0001」の形で渡してください（いまは「{number}」）")
    rel = shinsa_result.result_rel(number)
    _no_link(folder, rel)
    saved = shinsa_result.load_result(folder, number)
    status = {"確かめの番号": number, "結果の場所": rel, "届いた": saved is not None, "問題": []}
    if saved is None:
        return status
    problems = status["問題"]
    report = saved.get("報告")
    if not isinstance(report, str) or not report.strip():
        problems.append("報告の文が空です")
    elif saved.get("報告のハッシュ") != shinsa_result.text_hash(report):
        problems.append("報告の文が、保存したときから変わっています（報告のハッシュが合いません）")
    result = saved.get("結果")
    items = findings_of(result)
    if result is None:
        problems.append(f"報告を JSON として読めませんでした（{saved.get('読めなかった理由') or '理由なし'}）")
    elif items is None:
        problems.append("報告の JSON に「指摘」の並びがありません")
    if isinstance(result, dict) and result.get("確かめの番号") != number:
        problems.append(f"報告の確かめの番号（{result.get('確かめの番号')}）が、{number} と合いません")
    if not saved.get("控えと合う"):
        problems.append("この結果は、今の控え（審査役に渡したもの）と結び付いていません")
    elif not saved.get("ハッシュが合う"):
        problems.append("審査役が確かめている間に、申請書が変わっていました（保存したときの申請書のハッシュが控えと合いません）")
    status.update({
        "取り出した所": saved.get("取り出した所"),
        "保存した時刻": saved.get("保存した時刻"),
        "控えの申請書のハッシュ": saved.get("控えの申請書のハッシュ"),
        "指摘": items or [],
        "重さごとの数": severity_counts(items or []),
        "審査項目": result.get("審査項目") if isinstance(result, dict) else None,
        "加点項目": result.get("加点項目") if isinstance(result, dict) else None,
        "社長の答えが要ること": (result.get("社長の答えが要ること") or []) if isinstance(result, dict) else [],
        "そろい具合": saved.get("そろい具合"),
        "まとめ": result.get("まとめ") if isinstance(result, dict) else None,
    })
    return status


def review_text(status: dict) -> str:
    if not status["届いた"]:
        return (f"{status['確かめの番号']} の審査役の結果は、まだ {status['結果の場所']} に届いていません。"
                "審査役が終わったという知らせを待ってから、もう一度確かめてください。")
    counts = status["重さごとの数"]
    lines = [f"{status['確かめの番号']} の審査役の結果（{status['結果の場所']}。取り出した所：{status['取り出した所']}）",
             f"要修正 {counts['要修正']}件、要確認 {counts['要確認']}件、助言 {counts['助言']}件"]
    for item in status["指摘"]:
        sev = item.get("重さ") or "要修正"
        where = f"（{item['場所']}）" if item.get("場所") else ""
        fix = f" → 直し方の案：{item['直し方の案']}" if item.get("直し方の案") else ""
        lines.append(f"- [{sev}]{where} {item.get('内容', '')}{fix}")
        if item.get("社長に聞くこと"):
            lines.append(f"    社長に聞くこと：{item['社長に聞くこと']}")
    for item in status.get("社長の答えが要ること") or []:
        if isinstance(item, dict) and item.get("社長に聞くこと"):
            lines.append(f"- 社長の答えが要ること（{item.get('場所', '')}）：{item['社長に聞くこと']}")
    full = status.get("そろい具合")
    if isinstance(full, dict) and "文体の基準C" in full:
        lines.append(f"審査役の結果のそろい具合：文体の基準 C {full['文体の基準C']}、審査項目と加点項目 "
                     f"{full['審査項目と加点項目']}、4つの段 {full['4つの段']}（切れ目 {full['切れ目']}件）、"
                     f"目安のない項目の分量 {full['分量']}（足りない・長すぎる {full['足りない・長すぎる']}件）")
        if not full.get("そろった"):
            gaps = full.get("判定と理由のない観点", []) + full.get("点数と理由のない項目", []) + full.get("分量の判定のない項目", [])
            lines.append("そろっていない所：" + "、".join(str(g) for g in gaps[:20]) +
                         "。足りない所を審査役に伝えて、呼び直してください（呼んだ回数に数えます）")
    for p in status["問題"]:
        lines.append(f"問題：{p}")
    if status.get("まとめ"):
        lines.append(f"まとめ：{status['まとめ']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 完成の記録


def _completion_entries(folder: Path) -> List[dict]:
    data = shinsa_result._read_json(folder, COMPLETION_REL)
    entries = data.get("記録") if isinstance(data, dict) else None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def complete(folder: Path, case: str, stage: str, seido: Optional[dict]) -> dict:
    """完成の条件を確かめ、満たせば完成の記録に足す。戻り値の「完成」が False なら、「理由」に満たさない条件の一覧。"""
    reasons: List[str] = []
    report = check(folder, case, stage, seido)
    if not report["通った"]:
        reasons.append(f"コードの確かめが通っていません（仮の印 {len(report['仮の印'])}件、空欄 {len(report['空欄'])}件、"
                       f"根拠のない記述 {len(report['根拠なし'])}件、問題 {len(report['問題'])}件）")
    note = shinsa_result.load_note(folder)
    status = None
    try:
        hashes = shinsa_result.file_hashes(folder, case, stage)
    except (places.PlaceError, OSError) as e:
        raise CheckError(f"申請書のハッシュを計算できません（{e}）")
    current = shinsa_result.combined_hash(hashes)
    if note is None:
        reasons.append("審査役に渡したものの控えがありません（prepare で審査役に渡すものをまとめ、審査役を呼んでください）")
    elif (note.get("案件"), note.get("段階")) != (case, stage):
        reasons.append(f"今の控えは、別の案件・段階（{note.get('案件')}／{note.get('段階')}）のものです")
    else:
        status = review(folder, str(note["確かめの番号"]))
        if not status["届いた"]:
            reasons.append(f"{status['確かめの番号']} の審査役の結果が、まだ届いていません")
        else:
            reasons += status["問題"]
            if note.get("申請書のハッシュ") != current:
                reasons.append("審査役が確かめた後に、申請書が変わっています。今の版をもう一度確かめてください")
            if status["重さごとの数"][MUST_FIX]:
                reasons.append(f"審査役の要修正の指摘が {status['重さごとの数'][MUST_FIX]}件 残っています")
            full = status.get("そろい具合")
            if isinstance(full, dict) and "4つの段" in full:
                # 筋立ての切れ目と、目安のない項目の「足りない」「長すぎる」は、要修正として残す（T8-8・T8-9）
                if full.get("4つの段") != "4/4" or full.get("切れ目"):
                    reasons.append(f"審査役の筋立ての判定で、4つの段 {full.get('4つの段')}、切れ目 {full.get('切れ目')}件です")
                if full.get("足りない・長すぎる"):
                    reasons.append(f"審査役の分量の判定で、足りない・長すぎる項目が {full['足りない・長すぎる']}件あります")
    if reasons:
        return {"完成": False, "理由": reasons, "コードの確かめ": report, "審査役の結果": status}
    if any(e.get("確かめの番号") == status["確かめの番号"] for e in _completion_entries(folder)):
        return {"完成": True, "もうある": True, "理由": [], "コードの確かめ": report, "審査役の結果": status}
    entry = {
        "案件": case,
        "段階": stage,
        "確かめの番号": status["確かめの番号"],
        "申請書のハッシュ": current,
        "ファイルのハッシュ": hashes,
        "審査役の結果": status["結果の場所"],
        "重さごとの数": status["重さごとの数"],
        "審査役の結果のそろい具合": status.get("そろい具合"),
        "コードの確かめ": {k: len(report[k]) for k in (PROVISIONAL, BLANK, UNSUPPORTED)},
        "完成にした時刻": _now_text(folder),
    }
    entries = _completion_entries(folder)
    entries.append(entry)
    data = {"説明": "確かめの道具が、完成の条件（DESIGN 8章）をすべて満たしたときだけ足す記録", "記録": entries}
    try:
        shinsa_result.write_json(folder, COMPLETION_REL, data)
    except places.PlaceError as e:
        raise CheckError(f"{e.link or COMPLETION_REL} が別名（シンボリックリンク）になっているので、完成の記録を書きません")
    return {"完成": True, "もうある": False, "理由": [], "記録": entry, "コードの確かめ": report, "審査役の結果": status}
