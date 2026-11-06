"""会社の記録（SPEC F13、DESIGN 10章。TASKS M11）。

置き場所は `記録/会社の記録.json`。形は schema/会社の記録.schema.json（S6）で、書く前と読んだときに、
そのスキーマで確かめる（lib/schema_check.py。正本はスキーマのファイルだけ）。どの項目も id・覚えた日・出典を持つ。

- 事実を足す（add_fact）：同じ名前の事実があり、値も同じなら「最後に確かめた日」を今日にする。値が違えば
  上書きせず、何も書かずに食い違いとして返す（SPEC F13「食い違いは上書きしない」）。社長が決めたら、
  update_fact（新しい値にする）か confirm（記録のままでよい）で直す。
- 書き方の決まりを足す（add_rule）。同じ区分・同じ内容のものがあれば足さない。
- 開いたときの要約（session_note）：変わりうる情報、食い違いのある事実、最近増えた書き方の決まりと、件数。
- 書く前の取り出し（relevant）：kaku が書く項目の名前から、当たりそうな事実を先に並べ、ほかの事実、
  書き方の決まり、前の申請で受けた指摘も添える。記録から書いた箇所の根拠対照表の出典（記録の項目）も返す。

今日の日付は、差し替えを含む日付（lib/dates.py）。出典のファイルは、会社のフォルダからの場所で残す
（フォルダを別の場所に移しても使えるように。会社のフォルダの外を指すものは断る）。
変更の履歴は、応答の終わりの hook が「ツール」の版として残す（ここでは Git を読み込まない。開いたときの hook を軽く保つため）。
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib import dates, places, schema_check

RECORDS_DIR = "記録"
RECORD_FILE = f"{RECORDS_DIR}/会社の記録.json"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "会社の記録.schema.json"
SCHEMA_VERSION = 1

FACT = "事実"
RULE = "書き方の決まり"
DEFECT = "不備と差し戻し"
RESULT = "申請と採否"
KINDS = (FACT, RULE, DEFECT, RESULT)
ID_PREFIX = {FACT: "事実", RULE: "決まり", DEFECT: "不備", RESULT: "採否"}
SOURCE_KINDS = ("原本", "質問", "社長の手直し", "社長の発言")
RULE_KINDS = ("直した表現", "好む言い方", "避けたい言い方", "書き方の方針", "構成")
VALID = "有効"
CONFLICT = "食い違いあり"

# 開いたときの要約の長さの上限（仮）。開いたときに渡す情報は全体で10,000字まで（SPEC 共通の要件）で、
# 期限や共通の決まり（M3）と分け合うため、短くする
SUMMARY_MAX_CHARS = 1500
# 「最近増えた」書き方の決まりの日数（仮）
RECENT_RULE_DAYS = 30
# 要約で名前を挙げる数
SUMMARY_LIST_MAX = 8
# 要約で値を示す長さ
SUMMARY_VALUE_CHARS = 40
# kaku の取り出しの長さの上限（仮）。超えた分は、件数だけを示して一覧（record.py list）に回す
RELEVANT_MAX_CHARS = 8000


class RecordError(Exception):
    """会社の記録を読めない・書けない、引数が足りない・違うなど。社長に伝えられる日本語の文を持つ。"""


# ---- 読み書き ----

_schema_cache: Dict[str, Any] = {}


def load_schema() -> dict:
    if "schema" not in _schema_cache:
        try:
            _schema_cache["schema"] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise RecordError(f"会社の記録の形（schema/{SCHEMA_PATH.name}）を読めません（{e}）。"
                              "プラグインを入れ直してください") from e
    return _schema_cache["schema"]


def validate(data: Any) -> List[str]:
    """会社の記録の形を確かめ、合わない所の文の一覧を返す（空なら合っている）。"""
    errors = schema_check.validate(load_schema(), data)
    if errors:
        return errors
    seen = set()
    for i, item in enumerate(data["項目"]):
        if item["id"] in seen:
            errors.append(f"項目[{i}]：id「{item['id']}」がほかの項目と重なっています")
        seen.add(item["id"])
    return errors


def record_path(folder: Path) -> Path:
    return Path(folder) / RECORD_FILE


def empty() -> dict:
    return {"スキーマの版": SCHEMA_VERSION, "項目": []}


def _check_place(folder: Path) -> None:
    """記録の置き場が、会社のフォルダの中の本物のファイルか（別名で外を指していないか）を確かめる（lib/places.py）。"""
    try:
        places.no_link_on_the_way(folder, RECORD_FILE)
    except places.PlaceError as e:
        what = RECORD_FILE if e.link == RECORD_FILE else f"{e.link}/"
        raise RecordError(f"{what} が別名（シンボリックリンク）になっています。会社の記録は、会社のフォルダの中に"
                          "本物のファイルとして置きます。別名を消してから、もう一度試してください") from e
    path = record_path(folder)
    if path.exists() and not path.is_file():
        raise RecordError(f"{RECORD_FILE} がファイルではありません")


def _join_errors(errors: List[str], limit: int = 5) -> str:
    text = "／".join(errors[:limit])
    if len(errors) > limit:
        text += f"／ほか{len(errors) - limit}件"
    return text


def load(folder: Path) -> dict:
    """会社の記録を読み、形を確かめて返す。まだなければ空の記録。読めない・形が違うときは RecordError。"""
    _check_place(folder)
    path = record_path(folder)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return empty()
    except OSError as e:
        raise RecordError(f"{RECORD_FILE} を読めません（{e}）") from e
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise RecordError(f"{RECORD_FILE} が UTF-8 の文字ではありません") from e
    try:
        data = json.loads(text)
    except ValueError as e:
        raise RecordError(f"{RECORD_FILE} が JSON として読めません（{e}）") from e
    errors = validate(data)
    if errors:
        raise RecordError(f"{RECORD_FILE} の形が合いません：{_join_errors(errors)}")
    return data


def save(folder: Path, data: dict) -> None:
    """形を確かめてから、まとめて書き換える（途中で止まっても、半端なファイルを残さない）。"""
    errors = validate(data)
    if errors:
        raise RecordError(f"会社の記録の形に合わないので、書きませんでした：{_join_errors(errors)}")
    _check_place(folder)
    path = record_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            tmp.unlink()


# ---- 名前と値をそろえる ----

def normalize(text: str) -> str:
    """比べるために、全角・半角と空白をそろえる。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def value_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def same_value(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return normalize(a) == normalize(b)
    return json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)


def short(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: max(limit - 1, 1)] + "…"


def _date_arg(value: Optional[str], what: str) -> Optional[str]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as e:
        raise RecordError(f"{what}（{value}）は、「2026-11-04」の形の日付で書いてください") from e


def inside_path(folder: Path, raw: str) -> str:
    """出典のファイルを、会社のフォルダからの場所（区切りは /、文字の形は NFC）にする。

    外を指すもの（別名の先が外のものも）、ないもの、ツールの置き場（「.」で始まる場所）の中は断る。
    """
    text = unicodedata.normalize("NFC", str(raw).strip())
    if not text:
        raise RecordError("出典の書類（--file）を指してください")
    given = Path(text).expanduser()
    try:
        relative = places.relative_inside(folder, given)
    except places.PlaceError:
        relative = "."
    if relative == ".":  # 外か、会社のフォルダそのもの
        raise RecordError(f"出典の書類（{raw}）が会社のフォルダの外にあります。外のファイルは、取り込みの道具で"
                          "会社のフォルダに写してから指してください")
    rel = Path(relative)
    if any(part.startswith(".") for part in rel.parts):
        raise RecordError(f"出典の書類（{raw}）が、ツールの置き場（「.」で始まるフォルダ）の中にあります")
    if not (places.real(folder) / rel).is_file():
        raise RecordError(f"出典の書類（{raw}）が会社のフォルダにありません。場所を確かめてください")
    return rel.as_posix()


def make_source(folder: Path, kind: str, *, file: Optional[str] = None, page: Optional[int] = None,
                question: Optional[str] = None, answered: Optional[str] = None,
                utterance: Optional[str] = None, day: Optional[str] = None,
                today: Optional[date] = None) -> dict:
    """出典（原本とページ／質問と答えた日／社長の手直し／社長の発言）を組み立てる。日付を省けば今日。"""
    if kind not in SOURCE_KINDS:
        raise RecordError(f"出典の種類（{kind}）は、{'・'.join(SOURCE_KINDS)} のどれかにしてください")
    today_text = (today or dates.today(folder)).isoformat()
    source: Dict[str, Any] = {"種類": kind}
    if kind in ("原本", "社長の手直し"):
        if not file:
            raise RecordError(f"出典が「{kind}」のときは、書類の場所（--file）を指してください")
        source["ファイル"] = inside_path(folder, file)
        if page is not None:
            if page < 1:
                raise RecordError("ページ（--page）は1以上にしてください")
            source["ページ"] = page
    elif file or page is not None:
        raise RecordError("書類の場所（--file）とページ（--page）は、出典が「原本」か「社長の手直し」のときだけ指します")
    if kind == "質問":
        if not (question or "").strip():
            raise RecordError("出典が「質問」のときは、聞いた質問の文（--question）を渡してください")
        source["質問"] = question.strip()
        source["答えた日"] = _date_arg(answered, "答えた日（--answered-date）") or today_text
    elif answered:
        raise RecordError("答えた日（--answered-date）は、出典が「質問」のときだけ指します")
    if kind == "社長の発言":
        if not (utterance or "").strip():
            raise RecordError("出典が「社長の発言」のときは、社長の発言（--utterance）をそのまま渡してください")
        source["発言"] = utterance.strip()
    elif utterance:
        raise RecordError("社長の発言（--utterance）は、出典が「社長の発言」のときだけ指します")
    if kind in ("社長の手直し", "社長の発言"):
        source["日付"] = _date_arg(day, "日付（--date）") or today_text
    elif day:
        raise RecordError("日付（--date）は、出典が「社長の手直し」か「社長の発言」のときだけ指します")
    return source


# ---- 項目 ----

def _items(data: dict, kind: Optional[str] = None) -> List[dict]:
    return [it for it in data["項目"] if kind is None or it["種類"] == kind]


FACT_MARKS_KEY = "作ったときの事実"  # 財務モデルの数字の控えに、作ったときの指紋を残す欄


def fact_marks(data: dict) -> Dict[str, str]:
    """有効な事実ごとの、値の短い指紋（id → 指紋）。財務モデルを作ったときに控え、後で増えた・変わった事実を見つける（B37）。"""
    import hashlib

    out = {}
    for it in _items(data, FACT):
        if it.get("状態") != VALID:
            continue
        raw = json.dumps(it.get("値"), ensure_ascii=False, sort_keys=True)
        out[it["id"]] = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return out


def _next_id(data: dict, kind: str) -> str:
    prefix = f"{ID_PREFIX[kind]}-"
    numbers = [0]
    for item in data["項目"]:
        m = re.fullmatch(re.escape(prefix) + r"([0-9]+)", item["id"])
        if m:
            numbers.append(int(m.group(1)))
    return f"{prefix}{max(numbers) + 1:04d}"


def find(data: dict, item_id: str, kind: Optional[str] = None) -> dict:
    for item in data["項目"]:
        if item["id"] == item_id.strip():
            if kind is not None and item["種類"] != kind:
                raise RecordError(f"{item_id} は「{item['種類']}」の項目です（「{kind}」ではありません）")
            return item
    raise RecordError(f"会社の記録に {item_id} がありません。record.py list で id を確かめてください")


def _clean_value(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        if not value:
            raise RecordError("値（--value）が空です")
    return value


def add_fact(folder: Path, name: str, value: Any, changeable: bool, source: dict) -> Tuple[str, dict, List[dict]]:
    """事実を足す。(結果, 項目, 食い違う記録) を返す。結果は added・same・conflict。

    - same：同じ名前・同じ値の事実がある。最後に確かめた日を今日にする（出典は前のまま）。
    - conflict：同じ名前で値が違う事実がある。何も書かない（上書きしない）。項目は足そうとしたもの。
    """
    name = (name or "").strip()
    if not name:
        raise RecordError("事実の名前（--name）が空です")
    value = _clean_value(value)
    today = dates.today(folder).isoformat()
    data = load(folder)
    same_name = [it for it in _items(data, FACT) if normalize(it["名前"]) == normalize(name)]
    for item in same_name:
        if same_value(item["値"], value):
            item["最後に確かめた日"] = today
            save(folder, data)
            return "same", item, []
    item = {"id": "", "種類": FACT, "名前": name, "値": value, "変わりうる": bool(changeable), "出典": source,
            "覚えた日": today, "最後に確かめた日": today, "状態": VALID}
    if same_name:
        return "conflict", item, same_name
    item["id"] = _next_id(data, FACT)
    data["項目"].append(item)
    save(folder, data)
    return "added", item, []


def add_rule(folder: Path, kind: str, content: str, trigger: str, source: dict,
             case: Optional[str] = None) -> Tuple[str, dict]:
    """書き方の決まりを足す。(結果, 項目) を返す。同じ区分・同じ内容があれば足さない（same）。"""
    if kind not in RULE_KINDS:
        raise RecordError(f"書き方の決まりの区分（{kind}）は、{'・'.join(RULE_KINDS)} のどれかにしてください")
    content = (content or "").strip()
    trigger = (trigger or "").strip()
    if not content:
        raise RecordError("決まりの内容（--content）が空です")
    if not trigger:
        raise RecordError("きっかけ（--trigger。社長の発言や手直し）が空です")
    today = dates.today(folder).isoformat()
    data = load(folder)
    for item in _items(data, RULE):
        if item["区分"] == kind and normalize(item["内容"]) == normalize(content):
            return "same", item
    occasion: Dict[str, Any] = {"発言や手直し": trigger, "日付": today}
    if case and case.strip():
        occasion["案件"] = case.strip()
    item = {"id": _next_id(data, RULE), "種類": RULE, "区分": kind, "内容": content, "きっかけ": occasion,
            "出典": source, "覚えた日": today}
    data["項目"].append(item)
    save(folder, data)
    return "added", item


def confirm(folder: Path, fact_id: str) -> dict:
    """事実を社長に確かめた（記録のままでよい）。最後に確かめた日を今日にし、食い違いの印を外す。"""
    data = load(folder)
    item = find(data, fact_id, FACT)
    item["最後に確かめた日"] = dates.today(folder).isoformat()
    item["状態"] = VALID
    save(folder, data)
    return item


def update_fact(folder: Path, fact_id: str, value: Any, source: dict,
                changeable: Optional[bool] = None) -> Tuple[dict, dict]:
    """社長が決めた新しい値にする。(前の項目, 直した項目) を返す。覚えた日・最後に確かめた日は今日。"""
    value = _clean_value(value)
    data = load(folder)
    item = find(data, fact_id, FACT)
    before = json.loads(json.dumps(item, ensure_ascii=False))
    today = dates.today(folder).isoformat()
    item.update({"値": value, "出典": source, "覚えた日": today, "最後に確かめた日": today, "状態": VALID})
    if changeable is not None:
        item["変わりうる"] = bool(changeable)
    save(folder, data)
    return before, item


# ---- 見せ方 ----

def source_text(source: dict) -> str:
    kind = source.get("種類")
    if kind == "原本":
        page = f" {source['ページ']}ページ" if "ページ" in source else ""
        return f"原本 {source.get('ファイル')}{page}"
    if kind == "質問":
        return f"質問「{source.get('質問')}」（答えた日 {source.get('答えた日')}）"
    if kind == "社長の手直し":
        page = f" {source['ページ']}ページ" if "ページ" in source else ""
        return f"社長の手直し {source.get('ファイル')}{page}（{source.get('日付')}）"
    if kind == "社長の発言":
        return f"社長の発言「{source.get('発言')}」（{source.get('日付')}）"
    return str(kind)


def evidence_label(item: dict) -> str:
    """記録から書いた箇所の、根拠対照表の出典（記録の項目）。"""
    if item["種類"] == FACT:
        return f"会社の記録 {item['id']}（{item['名前']}）"
    if item["種類"] == RULE:
        return f"会社の記録 {item['id']}（{item['区分']}）"
    return f"会社の記録 {item['id']}（{item['種類']}）"


def needs_check(fact: dict, today: date) -> bool:
    """使い回す前に社長に確かめるか：変わりうる事実で、今日まだ確かめていないもの（仮。TASKS M11 の質問）。"""
    return bool(fact["変わりうる"]) and fact["最後に確かめた日"] < today.isoformat()


def check_question(fact: dict) -> str:
    return f"前回は「{short(value_text(fact['値']), 60)}」でしたが、変わりましたか"


def fact_line(fact: dict) -> str:
    return (f"[{fact['id']}] {fact['名前']}＝{value_text(fact['値'])}（出典：{source_text(fact['出典'])}。"
            f"覚えた日 {fact['覚えた日']}、最後に確かめた日 {fact['最後に確かめた日']}"
            f"{'、変わりうる情報' if fact['変わりうる'] else ''}{'、' + CONFLICT if fact['状態'] == CONFLICT else ''}）")


def rule_line(rule: dict) -> str:
    occasion = rule["きっかけ"]
    case = f"{occasion['案件']}で、" if occasion.get("案件") else ""
    return (f"[{rule['id']}] {rule['区分']}：{rule['内容']}（きっかけ：{case}{occasion['発言や手直し']}。"
            f"覚えた日 {rule['覚えた日']}）")


def listing(folder: Path, changes: Optional[Dict[str, List[dict]]] = None) -> str:
    """覚えていることの一覧（何を、いつ、どこから）。

    changes（lib/record_changes.py の changes()）を渡すと、変わった項目の下に変更の履歴（いつ、何から何に、だれが）を添え、
    消えた項目も挙げる。履歴は版の履歴から作る（ここでは Git を読み込まない。開いたときの hook を軽く保つため）。
    """
    data = load(folder)
    if not data["項目"] and not changes:
        return "会社の記録には、まだ何も覚えていません。"
    lines = [f"会社の記録（{RECORD_FILE}）に覚えていること（{len(data['項目'])}件）："]
    lines += _listing_body(data)
    if changes:
        from lib import record_changes

        with_history = []
        for line in lines:
            with_history.append(line)
            m = re.match(r"^- \[([^\]]+)\]", line)
            if m:
                with_history += record_changes.change_lines(changes, m.group(1))
        lines = with_history
        gone = record_changes.removed_lines(changes, [it["id"] for it in data["項目"]])
        if gone:
            lines.append(f"## 消えた項目（{len(gone)}件。前の版から戻せます）")
            lines += gone
    return "\n".join(lines)


def _listing_body(data: dict) -> List[str]:
    lines: List[str] = []
    for kind in KINDS:
        items = _items(data, kind)
        if not items:
            continue
        lines.append(f"## {kind}（{len(items)}件）")
        for item in items:
            if kind == FACT:
                lines.append(f"- {fact_line(item)}")
            elif kind == RULE:
                lines.append(f"- {rule_line(item)}")
            elif kind == DEFECT:
                lines.append(f"- [{item['id']}] {item['案件']} {item['手続きの段階']}：{item['内容']}"
                             f"（原因：{item['原因']}。出典：{source_text(item['出典'])}。覚えた日 {item['覚えた日']}）")
            else:
                pointed = "、".join(item["指摘された審査項目"]) or "なし"
                lines.append(f"- [{item['id']}] {item['案件']}：{item['結果']}（指摘された審査項目：{pointed}。"
                             f"出典：{source_text(item['出典'])}。覚えた日 {item['覚えた日']}）")
    return lines


# ---- 根拠対照表の出典（記録から書いた箇所。SPEC F13「記録から書いた箇所は根拠対照表で分かるようにする」、T13-4） ----

_EVIDENCE_REF = re.compile(r"会社の記録\s*[:：]?\s*((?:事実|決まり|不備|採否)-[0-9]{4})(?:（([^）]*)）)?")


def evidence_rows(folder: Path, rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], int]:
    """根拠対照表の行の出典のうち、会社の記録の項目を指すもの（「会社の記録 事実-0005」）を確かめてそろえる。

    - 項目の id が記録になければ RecordError（記録にない項目を出典にしない）。
    - 「会社の記録」とだけ書いて id がなければ RecordError（どの項目から書いたか分かるようにする）。
    - あれば、出典の文の中の「会社の記録 <id>（…）」を、記録の項目の見せ方（evidence_label。名前や区分つき）にそろえる。
      ほかの出典（書類とページなど）と並べて書いてあれば、そちらはそのまま残す。
    (そろえた行, 記録から書いた行の数) を返す。記録がまだなく、記録を指す行もなければ、そのまま返す。
    """
    if not any("会社の記録" in (r.get("出典") or "") for r in rows):
        return rows, 0
    data = load(folder)
    out = []
    problems = []
    used = 0
    for n, row in enumerate(rows, 1):
        source = row.get("出典") or ""
        if "会社の記録" not in source:
            out.append(row)
            continue
        refs = [ref for ref, _note in _EVIDENCE_REF.findall(source)]
        if not refs:
            problems.append(f"{n}行目の出典「{short(source, 40)}」に、会社の記録の項目の id（事実-0001 など）がありません")
            continue
        missing = [r for r in refs if not any(it["id"] == r for it in data["項目"])]
        if missing:
            problems.append(f"{n}行目の出典の {'・'.join(missing)} は、会社の記録にありません（record.py list で id を確かめる）")
            continue

        def label(m):
            canonical = evidence_label(find(data, m.group(1)))
            note = (m.group(2) or "").strip()
            # 書いた人が添えた補足（「履歴事項全部証明書 1ページ」など）は残す。名前や区分と同じなら重ねない
            if note and f"（{note}）" not in canonical:
                canonical += f"（{note}）"
            return canonical

        out.append(dict(row, 出典=_EVIDENCE_REF.sub(label, source)))
        used += 1
    if problems:
        raise RecordError("。".join(problems))
    return out, used


# ---- 開いたときの要約（SessionStart） ----

def _cap(lines: List[str], limit: int, tail: str) -> str:
    """上限を超えたら、行を後ろから落として、続きの場所を添える（行の途中では切らない）。"""
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    kept: List[str] = []
    for line in lines:
        if len("\n".join(kept + [line, tail])) > limit:
            break
        kept.append(line)
    return "\n".join(kept + [tail])


def summary(folder: Path, data: dict) -> str:
    items = data["項目"]
    if not items:
        return ""
    today = dates.today(folder)
    facts = _items(data, FACT)
    rules = _items(data, RULE)
    counts = "、".join(f"{kind} {len(_items(data, kind))}件" for kind in KINDS)
    lines = [f"【hojokin】会社の記録（{RECORD_FILE}）の要約：{counts}。"]

    def names(rows: List[str]) -> str:
        shown = "、".join(rows[:SUMMARY_LIST_MAX])
        return shown + (f"、ほか{len(rows) - SUMMARY_LIST_MAX}件" if len(rows) > SUMMARY_LIST_MAX else "")

    changeable = [f for f in facts if f["変わりうる"]]
    if changeable:
        rows = [f"{f['名前']}＝{short(value_text(f['値']), SUMMARY_VALUE_CHARS)}（最後に確かめた日 "
                f"{f['最後に確かめた日']}{'。今日はまだ確かめていない' if needs_check(f, today) else ''}）"
                for f in changeable]
        lines.append(f"- 変わりうる情報（新しい申請で使い回す前に、「前回は◯でしたが、変わりましたか」と確かめる）："
                     f"{names(rows)}")
    conflicts = [f for f in facts if f["状態"] == CONFLICT]
    if conflicts:
        rows = [f"[{f['id']}] {f['名前']}" for f in conflicts]
        lines.append(f"- 食い違いあり（使う前に、両方を出典付きで示して社長に決めてもらう）：{names(rows)}")
    since = (today - timedelta(days=RECENT_RULE_DAYS)).isoformat()
    recent = sorted((r for r in rules if r["覚えた日"] >= since), key=lambda r: r["覚えた日"], reverse=True)
    if recent:
        rows = [f"{r['区分']}「{short(r['内容'], SUMMARY_VALUE_CHARS)}」（{r['覚えた日']}）" for r in recent]
        lines.append(f"- 最近増えた書き方の決まり（{RECENT_RULE_DAYS}日以内）：{names(rows)}")
    lines.append("- 申請書を書く前に、kaku の取り出しの道具（relevant_records.py）で、その項目に関係する事実と書き方の"
                 "決まりを取り出す。記録にあることは、社長に聞かずに使う。社長の答えで分かった事実は、kiroku の記録の"
                 "道具（record.py add-fact）で出典と一緒に残す。")
    return _cap(lines, SUMMARY_MAX_CHARS, "- （続きは record.py list で一覧にできる）")


def session_note(folder: Path) -> str:
    """開いたときに Claude に渡す、会社の記録の要約。記録がまだなければ空。読めなければ、そのことを伝える文。"""
    try:
        data = load(folder)
    except RecordError as e:
        return (f"【hojokin】会社の記録を使えません：{e}。記録を使う前に社長に知らせ、kiroku の版の道具で前の版に戻すか、"
                "直してもらってください。直すまで、記録にあるはずのことも推測で書かずに社長に確かめる。")
    return summary(folder, data)


# ---- 書く前の取り出し（kaku） ----

# 比べる語の材料：漢字・カタカナ・英字・数字のつながり（ひらがなと記号で区切る）
_TOKEN = re.compile(r"[㐀-䶿一-鿿々〆ァ-ヺー0-9a-z]+")


def keys(text: str) -> set:
    """名前を比べるための、2文字ずつの組（「従業員の数」→ 従業・業員）。"""
    found = set()
    for run in _TOKEN.findall(unicodedata.normalize("NFKC", text).lower()):
        found.update(run[i:i + 2] for i in range(len(run) - 1))
    return found


def fact_view(fact: dict, today: date, hit: bool) -> dict:
    check = needs_check(fact, today)
    return {
        "id": fact["id"],
        "名前": fact["名前"],
        "値": fact["値"],
        "変わりうる": fact["変わりうる"],
        "出典": fact["出典"],
        "出典の文": source_text(fact["出典"]),
        "覚えた日": fact["覚えた日"],
        "最後に確かめた日": fact["最後に確かめた日"],
        "状態": fact["状態"],
        "当たる": hit,
        "使う前に確かめる": check,
        "確かめ方": check_question(fact) if check else "",
        "根拠対照表の出典": evidence_label(fact),
    }


def relevant(folder: Path, items: List[str]) -> dict:
    """kaku が書く項目（様式の項目の名前など）に関係する記録を取り出す。

    事実は、項目の名前と2文字ずつの組が重なるものを「当たる」として先に並べる（名前が重なるものを重く見る）。
    当たらない事実も、記録にあることを聞き直さないよう、後ろに並べる（使うかは Claude が判断する）。
    制度では絞らない（会社の事実は制度をまたいで使うため。会社の記録の形に、制度や項目とのつながりの欄はない）。
    書き方の決まりと、前の申請で受けた指摘は、どの申請書にも当てるので、すべて添える。
    """
    data = load(folder)
    today = dates.today(folder)
    wanted = [i.strip() for i in items if i and i.strip()]
    query = set()
    for item in wanted:
        query |= keys(item)
    scored = []
    for order, fact in enumerate(_items(data, FACT)):
        name_hits = len(query & keys(fact["名前"]))
        value_hits = len(query & keys(value_text(fact["値"])))
        hit = bool(wanted) and (name_hits >= 1 or value_hits >= 2)
        scored.append((not hit, -(name_hits * 3 + value_hits), order, fact, hit))
    scored.sort(key=lambda row: row[:3])
    results = []
    for item in _items(data, RESULT):
        results.append({"id": item["id"], "案件": item["案件"], "結果": item["結果"],
                        "指摘された審査項目": item["指摘された審査項目"], "審査コメント": item.get("審査コメント", ""),
                        "出典の文": source_text(item["出典"]), "根拠対照表の出典": evidence_label(item)})
    return {
        "記録": RECORD_FILE,
        "今日": today.isoformat(),
        "項目": wanted,
        "事実": [fact_view(fact, today, hit) for _, _, _, fact, hit in scored],
        "書き方の決まり": [{**rule, "根拠対照表の出典": evidence_label(rule)} for rule in _items(data, RULE)],
        "前の申請の指摘": results,
        "不備と差し戻しの件数": len(_items(data, DEFECT)),
    }


def relevant_text(found: dict) -> str:
    """relevant() の結果を、Claude が読む文にする（RELEVANT_MAX_CHARS まで）。"""
    facts = found["事実"]
    rules = found["書き方の決まり"]
    if not facts and not rules and not found["前の申請の指摘"]:
        return (f"会社の記録（{found['記録']}）には、まだ何も覚えていません。書くのに要る会社のことは社長に聞き、"
                "答えは record.py add-fact で出典と一緒に残してください。")
    target = "、".join(found["項目"]) if found["項目"] else "（項目を指していないので、すべての事実）"
    head = [f"会社の記録（{found['記録']}）から、書く前に使えるもの。今日 {found['今日']}。書く項目：{target}",
            "記録にあることは、社長に聞かずに使う。記録から書いた箇所は、根拠対照表に「根拠対照表の出典」を残す。"]
    hits = [f for f in facts if f["当たる"]]
    others = [f for f in facts if not f["当たる"]]

    def fact_block(f: dict, full: bool) -> List[str]:
        line = (f"- [{f['id']}] {f['名前']}：{value_text(f['値'])}" if full
                else f"- [{f['id']}] {f['名前']}：{short(value_text(f['値']), 80)}")
        rows = [line, f"  出典：{f['出典の文']}。覚えた日 {f['覚えた日']}、最後に確かめた日 {f['最後に確かめた日']}"]
        if f["状態"] == CONFLICT:
            rows.append("  食い違いあり：使う前に、両方を出典付きで示して社長に決めてもらう")
        if f["使う前に確かめる"]:
            rows.append(f"  変わりうる情報：使い回す前に「{f['確かめ方']}」と確かめる（変わらなければ record.py confirm、"
                        "変わったら record.py update-fact）")
        elif f["変わりうる"]:
            rows.append("  変わりうる情報：今日確かめた（聞き直さない）")
        rows.append(f"  根拠対照表の出典：{f['根拠対照表の出典']}")
        return rows

    body: List[str] = []
    if found["項目"]:
        body.append(f"## この項目に当たりそうな事実（{len(hits)}件）")
        for f in hits:
            body.extend(fact_block(f, True))
        if not hits:
            body.append("- なし（下の事実から、使えるものを選ぶ）")
        if others:
            body.append(f"## そのほかの事実（{len(others)}件。使うかは内容で判断する）")
    else:
        body.append(f"## 事実（{len(others)}件）")
    tail_facts = [fact_block(f, False) for f in others]

    rule_rows: List[str] = []
    if rules:
        rule_rows.append(f"## 書き方の決まり（{len(rules)}件。どの申請書にも当てる。避けたい言い方は使わない）")
        rule_rows.extend(f"- {rule_line(r)}" for r in rules)
    if found["前の申請の指摘"]:
        rule_rows.append("## 前の申請で受けた指摘（応える記述を入れる）")
    for r in found["前の申請の指摘"]:
        pointed = "、".join(r["指摘された審査項目"]) or "なし"
        comment = f"。コメント：{r['審査コメント']}" if r["審査コメント"] else ""
        rule_rows.append(f"- [{r['id']}] {r['案件']}：{r['結果']}。指摘された審査項目：{pointed}{comment}"
                         f"（出典：{r['出典の文']}）")
    if found["不備と差し戻しの件数"]:
        rule_rows.append(f"（不備と差し戻し {found['不備と差し戻しの件数']}件は、書類を集めるときに照らす）")

    lines = head + body
    budget = RELEVANT_MAX_CHARS - len("\n".join(lines + rule_rows)) - 80
    left = len(tail_facts)
    for block in tail_facts:
        size = len("\n".join(block)) + 1
        if size > budget:
            break
        lines.extend(block)
        budget -= size
        left -= 1
    if left:
        lines.append(f"- ほか{left}件（長くなるので省いた。record.py list で一覧にできる）")
    return "\n".join(lines + rule_rows)
