"""章ごとの読み取りの結果を1つの制度データにまとめ、確かめ、段階のフォルダを作る（SPEC F3、DESIGN 4.5・9章・9.2、TASKS M2c）。

流れ：
1. まとめる（merge）
   - 読む：`記録/制度データ/読み取り/<案件>/` の章ごとの結果のうち、1回目のもの（lib/urakadori.py が置いたもの）。
     2回目（重要な項目を別の呼び出しで読み直したもの）は、ここでは使わない。2回の読み取りを突き合わせるのは B25。
   - 章の順番は、読んだページのはじめ（資料の一覧の順と、ページ）で決める。
   - 項目ごとに合わせる。
     - 配列の項目（補助額・書類など）は、章の順につなぐ（まったく同じ件は1つにする）。
     - { } の項目（加点・申請画面・提出するファイルの決まり・支援者の欄）は、欄ごとに合わせる。
       配列の欄はつなぎ、同じ欄を2つの章が違う値で読んでいたら、前の章の値を使い、そのことを結果に書く。
   - 「スキーマの版」「制度」「資料」は、案件の `資料の一覧.json`（lib/official_docs.py が作るもの）から入れる。
     制度の「公募回」は、制度データを作った資料の回（直近回の資料に基づくときは、その回。lib/official_docs.round_notices と同じ決め方）。
   - どの章も読んでいない項目は、推測で埋めない。配列は空、{ } の項目は必須の欄を「読み取れない」にし、
     「読み取れなかった項目」に「どの章でも読み取っていない」と書く。
     「読み取れない」の値も、場所と理由を「読み取れなかった項目」に並べる（問い合わせ文の案は Claude が足す）。
   - まとめたものを lib/urakadori.run に渡す。全体の形を確かめ、どの値も裏取りし直して、
     `記録/制度データ/<制度の略称>_<公募回>.json` に置く（置き場所は lib/urakadori が決める。DESIGN 9章）。
2. 確かめる（check）
   - 形（スキーマ）が合うか。
   - 重要な項目（SPEC F3・DESIGN 9.2 の、締切・補助上限・補助率・数値の要件・必須書類・補助の対象にならない経費）が、
     1件以上あり、どの値も「値」か「要確認」で埋まっているか（「読み取れない」や、値が空の確認済み・資料で食い違いは、埋まっていない。
     空は null・空白だけの文字・[]・{}・中の値がどれも空のもの。読み取り役が「読み取れない」にせず空の値を返したときに、
     確認済みの空欄のまま社長に渡さないため）。
   - 出典のない値の数。読み取れないでない値のうち、出典か根拠の文がないもの、出典の資料が「資料」にないもの。
3. 段階のフォルダを作る（make_stage_folders）
   - 制度データの「手続きの段階」のうち「フォルダ」のある段階から作る（DESIGN 4.5）。中は「申請書」と「添付する書類」。
   - はじめは、いちばん前の段階（申請）だけを作る。採択後に次の段階へ進むときは、その段階の名前を渡して作る（M10）（仮）。
   - 段階のフォルダの名前が、段階の順に 1 から数えた「1_申請」「2_交付申請」…でなければ、どのフォルダも作らない（仮）。
     読み取り役が申請の段階を落とすと、いちばん前のフォルダが「2_採択発表」のようになるため。
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib import case_folder, urakadori
from lib.official_docs import LIST_FILE, RECORDS_DIR, TEXT_DIR, round_number

SCHEMA_VERSION = 1
FIRST_ROUND = 1
# 「制度」「資料」と同じく、まとめる道具が入れる項目（章の読み取りからは取らない）
OWN_KEYS = ("スキーマの版", "制度", "資料")
# どの章も読んでいなくても「読み取れなかった項目」に書かない項目（空でよいもの）
MAY_BE_EMPTY = ("資料どうしの食い違い", "読み取れなかった項目")
NOT_READ = "どの章の読み取りにもありません（資料に書かれていないか、まだ読んでいない章にあります）"

CONFIRMED = urakadori.CONFIRMED
CHECK = urakadori.CHECK
CONFLICT = urakadori.CONFLICT
UNREADABLE = urakadori.UNREADABLE

# 重要な項目（SPEC F3、DESIGN 9.2）。名前と、制度データのどの値を見るか（下の _important_values）
IMPORTANT = ("締切", "補助上限", "補助率", "数値の要件", "必須書類", "補助の対象にならない経費")
DEADLINE_WORD = "締切"


class MergeError(ValueError):
    """まとめられない（読み取りの結果がない、資料の一覧が読めない など）。何も書かない。"""


class DataMissing(ValueError):
    """確かめる制度データがない。"""


@dataclass
class MergeResult:
    chapters: List[Tuple[str, List[str]]] = field(default_factory=list)  # 章の名前と、その章が読んだ項目
    skipped: List[str] = field(default_factory=list)                      # 使わなかった結果（2回目など）
    conflicts: List[str] = field(default_factory=list)                    # 2つの章が違う値で読んだ欄
    duplicates: List[str] = field(default_factory=list)                   # 同じ名前の件が2つ以上ある項目
    not_read: List[str] = field(default_factory=list)                     # どの章も読んでいない項目
    data_round: str = ""


@dataclass
class ImportantItem:
    name: str
    entries: int = 0
    values: int = 0
    filled: int = 0
    unfilled: List[str] = field(default_factory=list)  # 埋まっていない値の場所

    @property
    def ok(self) -> bool:
        return self.entries > 0 and not self.unfilled


@dataclass
class CheckResult:
    schema_errors: List[str] = field(default_factory=list)
    important: List[ImportantItem] = field(default_factory=list)
    unsourced: List[str] = field(default_factory=list)  # 出典のない値の場所と理由
    values: int = 0
    states: Dict[str, int] = field(default_factory=dict)
    downgraded: int = 0          # 裏取りの道具が要確認にした値
    unreadable_items: List[str] = field(default_factory=list)
    unread_listed: int = 0       # 「読み取れなかった項目」の件数
    unread_with_question: int = 0  # そのうち、問い合わせ文の案があるもの

    @property
    def ok(self) -> bool:
        return not self.schema_errors and all(i.ok for i in self.important) and not self.unsourced


# ---- 場所 ----


def reading_dir(company: Path, case: str) -> Path:
    return urakadori.seido_dir(company) / urakadori.READING_DIR / case_folder.safe_name(case)


def doc_list_path(company: Path, case: str) -> Path:
    return company / RECORDS_DIR / TEXT_DIR / case_folder.safe_name(case) / LIST_FILE


def load_doc_list(company: Path, case: str) -> Dict:
    path = doc_list_path(company, case)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise MergeError(f"案件の資料の一覧（{path.relative_to(company)}）が読めません（{type(e).__name__}）。"
                         "先に公式資料を取ってください") from e
    if not isinstance(data, dict) or not isinstance(data.get("制度"), dict) or not isinstance(data.get("資料"), list):
        raise MergeError(f"案件の資料の一覧（{path.relative_to(company)}）の形が違います。公式資料を取り直してください")
    return data


def data_round(listed: Dict) -> str:
    """制度データの公募回：制度データを作った資料の回（lib/official_docs.round_notices と同じ決め方）。

    案件の回の資料があればその回。なければ（直近回の資料に基づくとき）、案件の回より前でいちばん新しい資料の回。
    """
    target = str(listed["制度"].get("公募回") or listed.get("案件の回") or "")
    target_n = round_number(target)
    rounds = sorted({n for n in (round_number(str(d.get("公募回", ""))) for d in listed["資料"] if isinstance(d, dict))
                     if n is not None})
    if target_n is None or not rounds or target_n in rounds:
        return target
    earlier = [n for n in rounds if n < target_n]
    return f"第{max(earlier) if earlier else max(rounds)}回"


def seido_path(company: Path, case: str) -> Path:
    """この案件の制度データの置き場所（lib/urakadori.full_out_path と同じ）。"""
    listed = load_doc_list(company, case)
    return urakadori.full_out_path(company, case, {"制度": seido_part(listed)})


def seido_part(listed: Dict) -> Dict:
    src = listed["制度"]
    out = {"名前": src.get("名前")}
    if src.get("枠"):
        out["枠"] = src["枠"]
    out["種類"] = src.get("種類")
    out["公募回"] = data_round(listed)
    return out


def docs_part(listed: Dict, schema: Dict) -> List[Dict]:
    allowed = set(schema["properties"]["資料"]["items"]["properties"])
    return [{k: v for k, v in d.items() if k in allowed} for d in listed["資料"] if isinstance(d, dict)]


# ---- まとめる ----


def _first_page(chapter: Dict, order: Dict[str, int]) -> Tuple[int, int]:
    pages = (chapter.get("読み取り") or {}).get("読んだページ") or []
    if not pages or not isinstance(pages[0], dict):
        return (len(order), 0)
    first = pages[0]
    page = first.get("ページ") if isinstance(first.get("ページ"), int) else 0
    return (order.get(first.get("資料"), len(order)), page)


def load_chapters(company: Path, case: str, order: Dict[str, int], result: MergeResult) -> List[Dict]:
    base = reading_dir(company, case)
    if not base.is_dir():
        raise MergeError(f"章ごとの読み取りの結果（{base.relative_to(company)}/）がありません。"
                         "先に、読み取り役に章ごとに読ませ、裏取りの道具に通してください")
    chapters = []
    for path in sorted(base.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result.skipped.append(f"{path.name}（読めない）")
            continue
        info = data.get("読み取り") if isinstance(data, dict) else None
        if not isinstance(info, dict) or not isinstance(data.get("制度データ"), dict):
            result.skipped.append(f"{path.name}（形が違う）")
            continue
        if info.get("回目", FIRST_ROUND) != FIRST_ROUND:
            result.skipped.append(f"{path.name}（{info.get('回目')}回目。2回の読み取りの突き合わせは B25）")
            continue
        chapters.append(data)
    if not chapters:
        raise MergeError(f"1回目の読み取りの結果が、{base.relative_to(company)}/ に1つもありません")
    chapters.sort(key=lambda c: (_first_page(c, order), str(c["読み取り"].get("章"))))
    return chapters


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)


def _extend(target: List, items: List) -> None:
    for item in items:
        if not any(_same(item, t) for t in target):
            target.append(copy.deepcopy(item))


def _merge_object(key: str, target: Dict, part: Dict, chapter: str, result: MergeResult) -> None:
    for sub, value in part.items():
        if sub not in target:
            target[sub] = copy.deepcopy(value)
        elif isinstance(target[sub], list) and isinstance(value, list):
            _extend(target[sub], value)
        elif not _same(target[sub], value):
            result.conflicts.append(f"「{key}」の「{sub}」を2つ以上の章が違う値で読んでいます（前の章の値を使い、章「{chapter}」の値は使っていません）")


def _unread(reason: str) -> Dict:
    return {"値": None, "状態": UNREADABLE, "理由": reason}


def _empty_value(key: str, schema_prop: Dict) -> Any:
    """どの章も読んでいない項目の、空の形（推測で埋めない）。"""
    if schema_prop.get("type") == "array":
        return []
    if key == "支援者の欄":
        return None
    out: Dict[str, Any] = {}
    for sub in schema_prop.get("required", []):
        sub_schema = schema_prop["properties"][sub]
        out[sub] = [] if sub_schema.get("type") == "array" else _unread(NOT_READ)
    return out


def _fill_object(key: str, value: Dict, schema_prop: Dict, result: MergeResult) -> None:
    """{ } の項目で、必須の欄をどの章も読んでいなければ「読み取れない」にする。"""
    for sub in schema_prop.get("required", []):
        if sub not in value:
            sub_schema = schema_prop["properties"][sub]
            value[sub] = [] if sub_schema.get("type") == "array" else _unread(NOT_READ)
            result.not_read.append(f"{key}の{sub}")


def _duplicates(key: str, items: List) -> Optional[str]:
    names: Dict[str, int] = {}
    for item in items:
        if isinstance(item, dict):
            name = item.get("名前") or item.get("区分") or item.get("id") or item.get("項目")
            if isinstance(name, str):
                names[name] = names.get(name, 0) + 1
    dup = sorted(n for n, c in names.items() if c > 1)
    return f"{key}：{'・'.join(dup)}" if dup else None


def _unreadable_entries(data: Dict) -> List[Dict]:
    """「読み取れない」の値の、場所と理由（「読み取れなかった項目」に並べる）。"""
    out: List[Dict] = []

    def visit(node: Any, path: List[Any]) -> None:
        if isinstance(node, dict) and "値" in node and "状態" in node:
            if node["状態"] == UNREADABLE:
                out.append({"項目": urakadori.readable(path, data), "理由": node.get("理由") or NOT_READ})
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if path == [] and k in ("資料", "資料どうしの食い違い", "読み取れなかった項目"):
                    continue
                visit(v, path + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                visit(v, path + [i])

    visit(data, [])
    return out


def merge(company: Path, case: str) -> Tuple[Dict, MergeResult]:
    """章ごとの読み取りの結果（1回目）を、1つの制度データにまとめる（まだ書かない）。"""
    result = MergeResult()
    schema = urakadori.load_schema()
    props = schema["properties"]
    listed = load_doc_list(company, case)
    order = {d.get("id"): i for i, d in enumerate(listed["資料"]) if isinstance(d, dict)}
    chapters = load_chapters(company, case, order, result)

    merged: Dict[str, Any] = {}
    for chapter in chapters:
        name = str(chapter["読み取り"].get("章"))
        part = chapter["制度データ"]
        result.chapters.append((name, [k for k in part if k in props and k not in OWN_KEYS]))
        for key, value in part.items():
            if key not in props or key in OWN_KEYS:
                continue  # 形の確かめ（urakadori）で、制度データにない項目は通らない
            if isinstance(value, list):
                _extend(merged.setdefault(key, []), value)
            elif isinstance(value, dict):
                if not isinstance(merged.get(key), dict):
                    merged[key] = {}
                _merge_object(key, merged[key], value, name, result)
            elif value is None:
                merged.setdefault(key, None)

    full: Dict[str, Any] = {"スキーマの版": SCHEMA_VERSION, "制度": seido_part(listed), "資料": docs_part(listed, schema)}
    result.data_round = full["制度"]["公募回"]
    for key, prop in props.items():
        if key in OWN_KEYS:
            continue
        if key in merged:
            full[key] = merged[key]
            if isinstance(full[key], dict) and prop.get("type") == "object":
                _fill_object(key, full[key], prop, result)
        else:
            full[key] = _empty_value(key, prop)
            if key not in MAY_BE_EMPTY:
                result.not_read.append(key)
        if isinstance(full[key], list):
            dup = _duplicates(key, full[key])
            if dup:
                result.duplicates.append(dup)

    # 読み取れなかった項目：章が書いたもの、どの章も読んでいない項目、読み取れないの値
    unread = list(full.get("読み取れなかった項目") or [])
    for key in result.not_read:
        unread.append({"項目": key, "理由": NOT_READ})
    for entry in _unreadable_entries(full):
        if not any(isinstance(u, dict) and u.get("項目") == entry["項目"] for u in unread):
            unread.append(entry)
    full["読み取れなかった項目"] = unread
    return full, result


def merge_and_save(company: Path, case: str) -> Tuple[Dict, MergeResult, urakadori.Result]:
    """まとめて、裏取りし直して、`記録/制度データ/<略称>_<公募回>.json` に置く。

    形が合わなければ urakadori.InputError（何も書かない）。
    """
    full, merged = merge(company, case)
    verified, saved = urakadori.run(company, case, full)
    return saved, merged, verified


# ---- 確かめる ----


def _is_sourced(node: Any) -> bool:
    return isinstance(node, dict) and "値" in node and "状態" in node


def _important_values(data: Dict) -> Dict[str, Tuple[int, List[Tuple[str, Any]]]]:
    """重要な項目ごとの（件数、（場所、出典つき値）の一覧）。"""

    def where(*path: Any) -> str:
        return urakadori.readable(list(path), data)

    out: Dict[str, Tuple[int, List[Tuple[str, Any]]]] = {}
    deadlines = [(i, d) for i, d in enumerate(data.get("決まった期日") or [])
                 if isinstance(d, dict) and DEADLINE_WORD in str(d.get("名前", ""))]
    out["締切"] = (len(deadlines), [(where("決まった期日", i, "日時"), d.get("日時")) for i, d in deadlines])

    caps: List[Tuple[str, Any]] = []
    rates: List[Tuple[str, Any]] = []
    amounts = [a for a in data.get("補助額") or [] if isinstance(a, dict)]
    for i, a in enumerate(data.get("補助額") or []):
        if not isinstance(a, dict):
            continue
        caps.append((where("補助額", i, "上限"), a.get("上限")))
        rates.append((where("補助額", i, "補助率"), a.get("補助率")))
        for j, s in enumerate(a.get("特例") or []):
            if not isinstance(s, dict):
                continue
            target = rates if s.get("種類") == "補助率の置き換え" else caps
            target.append((where("補助額", i, "特例", j, "値"), s.get("値")))
    out["補助上限"] = (len(amounts), caps)
    out["補助率"] = (len(amounts), rates)

    reqs = [(i, r) for i, r in enumerate(data.get("数値の要件") or []) if isinstance(r, dict)]
    out["数値の要件"] = (len(reqs), [(where("数値の要件", i, k), r.get(k)) for i, r in reqs
                                  for k in ("基準", "計算式", "元の数字の決め方", "満たせないとき") if k == "基準" or k in r])

    docs = [(i, d) for i, d in enumerate(data.get("書類") or []) if isinstance(d, dict) and d.get("区分") == "必須"]
    out["必須書類"] = (len(docs), [(where("書類", i, k), d.get(k)) for i, d in docs
                               for k in ("内容", "有効期限", "期数") if k == "内容" or k in d])

    costs = [(i, c) for i, c in enumerate(data.get("補助の対象にならない経費") or []) if isinstance(c, dict)]
    out["補助の対象にならない経費"] = (len(costs), [(where("補助の対象にならない経費", i, k), c.get(k)) for i, c in costs
                                         for k in ("内容", "上限", "例外") if k == "内容" or k in c])
    return out


def _is_empty(value: Any) -> bool:
    """値が空か：null、空白だけの文字、[]、{}、中の値がどれも空の [ ] や { }（{"日時": ""} など）。"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return all(_is_empty(v) for v in value)
    if isinstance(value, dict):
        return all(_is_empty(v) for v in value.values())
    return False


def _filled(node: Any) -> bool:
    """値で埋まっているか。確認済み・資料で食い違いは、値が空でないこと。要確認は、社長に確かめてもらう印なので埋まっているに数える。"""
    if not _is_sourced(node):
        return False
    if node["状態"] == CHECK:
        return True
    return node["状態"] in (CONFIRMED, CONFLICT) and not _is_empty(node.get("値"))


def _unfilled_reason(node: Any) -> str:
    if not _is_sourced(node):
        return "値がない"
    if node["状態"] in (CONFIRMED, CONFLICT):
        return "値が空"  # 「読み取れない」にせず、空の値を確認済みで返した（読み取り直すか、読み取れないにする）
    return str(node["状態"])


def _source_problems(item: Dict, doc_ids: set) -> List[str]:
    problems = []
    sources = item.get("出典")
    if not isinstance(sources, list) or not sources:
        problems.append("出典がありません")
    else:
        for s in sources:
            doc = s.get("資料") if isinstance(s, dict) else None
            if doc not in doc_ids:
                problems.append(f"出典の資料「{doc}」が、制度データの「資料」にありません")
    if not isinstance(item.get("根拠の文"), str) or not item.get("根拠の文", "").strip():
        problems.append("根拠の文がありません")
    return problems


def check(data: Any) -> CheckResult:
    """制度データの全体を確かめる（形、重要な項目、出典のない値）。"""
    result = CheckResult()
    if not isinstance(data, dict):
        result.schema_errors = ["（全体）：いちばん外側を { } の形にしてください"]
        return result
    result.schema_errors = urakadori.shape_errors(data)
    doc_ids = {d.get("id") for d in data.get("資料") or [] if isinstance(d, dict)}

    def visit(node: Any, path: List[Any]) -> None:
        if _is_sourced(node):
            result.values += 1
            state = node["状態"]
            result.states[state] = result.states.get(state, 0) + 1
            if isinstance(node.get("注記"), str) and urakadori.NOTE_PREFIX in node["注記"]:
                result.downgraded += 1
            if state == UNREADABLE:
                result.unreadable_items.append(urakadori.readable(path, data))
            else:
                for p in _source_problems(node, doc_ids):
                    result.unsourced.append(f"{urakadori.readable(path, data)}：{p}")
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if path == [] and k in ("資料", "資料どうしの食い違い", "読み取れなかった項目"):
                    continue
                visit(v, path + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                visit(v, path + [i])

    visit(data, [])
    for i, entry in enumerate(data.get("資料どうしの食い違い") or []):
        if not isinstance(entry, dict):
            continue
        for j, item in enumerate(entry.get("値") or []):
            if isinstance(item, dict):
                for p in _source_problems(item, doc_ids):
                    result.unsourced.append(f"資料どうしの食い違い「{entry.get('項目')}」の{j + 1}つ目の値：{p}")

    listed = [u for u in data.get("読み取れなかった項目") or [] if isinstance(u, dict)]
    result.unread_listed = len(listed)
    result.unread_with_question = sum(1 for u in listed if str(u.get("問い合わせ文の案") or "").strip())

    found = _important_values(data)
    for name in IMPORTANT:
        entries, nodes = found.get(name, (0, []))
        item = ImportantItem(name=name, entries=entries, values=len(nodes))
        for place, node in nodes:
            if _filled(node):
                item.filled += 1
            else:
                item.unfilled.append(f"{place}（{_unfilled_reason(node)}）")
        result.important.append(item)
    return result


def load_data(company: Path, case: str) -> Tuple[Path, Any]:
    path = seido_path(company, case)
    if not path.is_file():
        raise DataMissing(f"制度データ（{path.relative_to(company)}）がありません。先に章ごとの読み取りをまとめてください")
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise DataMissing(f"制度データ（{path.relative_to(company)}）が JSON として読めません（{e}）") from e


# ---- 段階のフォルダ ----


def numbering_problems(folders: List[str]) -> List[str]:
    """段階のフォルダの名前（段階の順）が、1 から順に数えた「<番号>_<名前>」か（DESIGN 4.5：1_申請・2_交付申請・3_実績報告…）。

    読み取り役が、申請の段階を落としたり、書類を出さない段階にもフォルダを付けたりすると、
    いちばん前の段階のフォルダが「2_採択発表」のようになり、社長に見えるフォルダが崩れる（仮の決まり。M2c の差し戻し1回目）。
    """
    problems = []
    for i, name in enumerate(folders, start=1):
        head = name.split("_", 1)[0]
        if not head.isdigit() or int(head) != i:
            problems.append(f"{i}つ目の段階のフォルダが「{name}」です")
    return problems


def make_stage_folders(company: Path, case: str, data: Dict, only: Optional[List[str]] = None) -> Tuple[List[str], List[str]]:
    """制度データの手続きの段階から、段階のフォルダを作る。返すのは（作ったフォルダ、対象にした段階のフォルダの名前）。

    only がなければ、いちばん前の段階（申請）のフォルダだけ。名前のない段階を渡されたら case_folder.CaseError。
    """
    folders = case_folder.stage_folders([s for s in data.get("手続きの段階") or [] if isinstance(s, dict)])
    if not folders:
        raise case_folder.CaseError("制度データの手続きの段階に、フォルダの名前（1_申請 など）のある段階がありません")
    numbering = numbering_problems(folders)
    if numbering:
        raise case_folder.CaseError("段階のフォルダの名前が、書類を出す段階を順に数えた「1_申請」「2_交付申請」…の形になっていません"
                                    f"（{'。'.join(numbering)}）。手続きの段階を読み取り役に読ませ直してください")
    wanted = list(only) if only else [folders[0]]
    unknown = [w for w in wanted if w not in folders]
    if unknown:
        raise case_folder.CaseError(f"手続きの段階にないフォルダの名前です：{'・'.join(unknown)}（段階のフォルダは {'・'.join(folders)}）")
    made = case_folder.ensure_stage_folders(company, case, folders, only=wanted)
    return made, wanted


# ---- 結果の文 ----


def _states_line(states: Dict[str, int]) -> str:
    return "、".join(f"{s} {states.get(s, 0)}" for s in (CONFIRMED, CHECK, CONFLICT, UNREADABLE))


def check_report(result: CheckResult, rel: str) -> str:
    lines = [f"制度データを確かめました（{rel}）。", ""]
    if result.schema_errors:
        lines.append(f"- 形（スキーマ）：合いません（{len(result.schema_errors)} か所）")
        lines += [f"  - {e}" for e in result.schema_errors[:20]]
        if len(result.schema_errors) > 20:
            lines.append(f"  - ほかに {len(result.schema_errors) - 20} か所")
    else:
        lines.append("- 形（スキーマ）：合っています")
    lines.append(f"- 出典つき値：{result.values}（{_states_line(result.states)}）。"
                 f"要確認のうち、裏取りで外れた値 {result.downgraded}")
    lines.append(f"- 出典のない値：{len(result.unsourced)}")
    lines += [f"  - {u}" for u in result.unsourced[:20]]
    lines += ["", "重要な項目（締切・補助上限・補助率・数値の要件・必須書類・補助の対象にならない経費）：", "",
              "| 項目 | 件数 | 値 | 値か要確認で埋まった値 | 埋まっていない値 |", "|---|---|---|---|---|"]
    for item in result.important:
        lines.append(f"| {item.name} | {item.entries} | {item.values} | {item.filled} | {len(item.unfilled)} |")
    for item in result.important:
        if item.entries == 0:
            lines.append(f"- {item.name}：1件もありません。読み取り役に、その章を読ませてください")
        for u in item.unfilled[:10]:
            lines.append(f"- {item.name}の埋まっていない値：{u}")
    if result.unreadable_items:
        lines += ["", f"読み取れない値：{len(result.unreadable_items)}（空けたまま社長に伝え、問い合わせ文の案を作る）"]
        lines += [f"- {u}" for u in result.unreadable_items[:30]]
    lines += ["", f"読み取れなかった項目：{result.unread_listed}（問い合わせ文の案があるもの {result.unread_with_question}）"]
    lines.append("")
    if result.ok:
        lines.append("結果：形が合い、重要な項目はすべて値か「要確認」で埋まり、出典のない値は0件です。")
    else:
        lines.append("結果：まだ足りないところがあります（上の一覧）。")
    return "\n".join(lines) + "\n"


def merge_report(case: str, merged: MergeResult, verified: urakadori.Result, rel: str) -> str:
    lines = [f"章ごとの読み取りを、1つの制度データにまとめました（案件：{case}、制度データの公募回：{merged.data_round}）。", ""]
    lines.append(f"- まとめた章：{len(merged.chapters)}")
    for name, keys in merged.chapters:
        lines.append(f"  - {name}：{'・'.join(keys) if keys else '（項目なし）'}")
    if merged.skipped:
        lines.append(f"- 使わなかった結果：{'、'.join(merged.skipped)}")
    if merged.not_read:
        lines.append(f"- どの章でも読み取っていない項目（「読み取れなかった項目」に入れました）：{'・'.join(merged.not_read)}")
    for c in merged.conflicts:
        lines.append(f"- {c}")
    for d in merged.duplicates:
        lines.append(f"- 同じ名前の件が2つ以上あります（章をまたいで重ねて読んでいないか確かめる）：{d}")
    lines.append(f"- 裏取りし直した値：{verified.checked}（出典つき値 {verified.values}：{_states_line(verified.states)}）")
    if verified.downgraded or verified.conflicts_flagged:
        lines += ["", "裏取りで外れた値（要確認にしました）：", "", "| 場所 | 理由 |", "|---|---|"]
        for f in verified.downgraded + verified.conflicts_flagged:
            lines.append(f"| {f.where} | {'。'.join(f.problems)} |")
    lines.append(f"- 置き場所：{rel}")
    return "\n".join(lines) + "\n"


__all__ = [
    "IMPORTANT", "CheckResult", "DataMissing", "ImportantItem", "MergeError", "MergeResult", "check", "check_report",
    "data_round", "load_data", "make_stage_folders", "merge", "merge_and_save", "merge_report", "seido_path",
]
