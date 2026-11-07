"""新しい版・新しい公募回の資料が出たときの、変わったページと、制度データの差（F7。DESIGN 9.2）。

- 変わったページ：前と後の資料の本文（`記録/資料の本文/<案件>/<資料の id>/`）を、資料の全体の行の並びで比べる。
  頁の番号のずれ（同じ文が次のページに送られた）と、目次の頁の番号だけの違いは「変わっていない」にする。
  変わった行が当たるページ（後の資料の印刷されたページ）と、前のページから後のページへの対応を出す。
- 引き継ぎ：変わったページに当たらない章の読み取りは、出典の資料と頁を後の資料に付け替え、後の本文で裏取りし直す。
- 制度データの差：前と後の制度データを項目ごとに比べ、足した・消えた・値が変わった項目を、前と後の値と出典で出す。
  前と後は別の読み取りなので、名前のある件は、件名の形が同じ件と、件名と中身の近さで組にした件どうしで比べる
  （lib/seido_data.pair_items。近さで組にした件は「件名が変わった件」に出す）。件ごと足した・消えた件と、区分ごとの同じ変化は
  1件にまとめ、数が同じで言い回しだけが違う値は別に出す（11/6 のリハーサルで、第8回と第9回の差が 783 件になり使えなかった）。
  自社の申請のどこに影響するかを、会社のフォルダの中身（期限の台帳・書類の台帳・会社の記録・申請書）と照らして出す。

会社のフォルダの中だけを読む・書く（lib/places.py。DESIGN 5章）。/usr/bin/python3（3.9）で動く書き方にする。
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib import case_folder, doc_text, place_text, seido_data, urakadori

RECORDS_DIR = "記録"
TEXT_DIR = "資料の本文"

_SPACES = re.compile(r"[\s​‌‍﻿]+")
_LEADER = re.compile(r"(?:[.．・…‥⋯·]{2,}|[.．・…‥⋯·](?=\d+$))")
_TOC_TAIL = re.compile(r"(?:[.．・…‥⋯·]{2,})\d{1,3}$")
_ONLY_NUMBER = re.compile(r"^[-‐－]?\d{1,3}[-‐－]?$")


class KaiteiError(ValueError):
    """何もしていない（資料の本文がない、会社のフォルダの外を指す など）。"""


# ---- 行の形をそろえる ----


def norm_line(line: str) -> str:
    """比べるための行の形。NFKC、空白を除く、目次の点線と頁の番号を除く。頁の番号だけの行は空にする。"""
    text = _SPACES.sub("", unicodedata.normalize("NFKC", line))
    if _ONLY_NUMBER.match(text):
        return ""
    if _TOC_TAIL.search(text):
        text = _TOC_TAIL.sub("", text)
    return _LEADER.sub("", text)


@dataclass
class DocLines:
    doc_id: str
    kind: str
    lines: List[str] = field(default_factory=list)      # 形をそろえた行
    raw: List[str] = field(default_factory=list)        # 元の行（変わった行を見せるため）
    pages: List[Optional[int]] = field(default_factory=list)  # 行ごとの印刷されたページ（ページのない資料は None）
    page_list: List[Optional[int]] = field(default_factory=list)


def _text_root(company: Path, case: str) -> Path:
    return company / RECORDS_DIR / TEXT_DIR / case_folder.safe_name(case)


def _inside(company: Path, path: Path, what: str) -> None:
    problem = place_text.read_problem(company, path, what)
    if problem:
        raise KaiteiError(problem)


def load_doc(company: Path, case: str, doc_id: str) -> DocLines:
    """資料の本文を、ページつきの行の並びにする。"""
    doc_dir = _text_root(company, case) / doc_id
    _inside(company, doc_dir, f"資料の本文（{doc_id}）")
    if not (doc_dir / doc_text.INDEX_FILE).is_file():
        raise KaiteiError(f"資料「{doc_id}」の本文がありません（{doc_dir.relative_to(company).as_posix()}/）。"
                          "先に公式資料を取ってください")
    _inside(company, doc_dir / doc_text.INDEX_FILE, f"資料の本文（{doc_id}）のページの対応")
    index = doc_text.load_index(doc_dir)
    out = DocLines(doc_id, str(index.get("種類") or ""))
    for info in index.get("ページ", []):
        _inside(company, doc_dir / info["ファイル"], f"資料の本文（{doc_id}）")
        page = info.get("印刷されたページ") if out.kind == "PDF" else None
        out.page_list.append(page)
        for raw in doc_text.read_page(doc_dir, info).splitlines():
            line = norm_line(raw)
            if line:
                out.lines.append(line)
                out.raw.append(raw.strip())
                out.pages.append(page)
    return out


# ---- 変わったページ ----


@dataclass
class Change:
    kind: str                 # 足した・消した・変えた
    old_page: Optional[int]
    new_page: Optional[int]
    old_lines: List[str]
    new_lines: List[str]


@dataclass
class PageDiff:
    old_id: str
    new_id: str
    kind: str
    changes: List[Change] = field(default_factory=list)
    page_map: Dict[int, int] = field(default_factory=dict)   # 前の印刷されたページ → 後の印刷されたページ
    changed_new_pages: List[int] = field(default_factory=list)
    changed_old_pages: List[int] = field(default_factory=list)
    same: bool = False


def _majority(votes: Dict[int, Counter]) -> Dict[int, int]:
    return {k: c.most_common(1)[0][0] for k, c in votes.items() if c}


def compare_docs(old: DocLines, new: DocLines) -> PageDiff:
    """前と後の資料の行の並びを比べる。行の順が同じで中身も同じ所は、ページがずれても変わっていない。"""
    out = PageDiff(old.doc_id, new.doc_id, new.kind)
    matcher = difflib.SequenceMatcher(None, old.lines, new.lines, autojunk=False)
    votes: Dict[int, Counter] = {}
    changed_new, changed_old = set(), set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                op, np_ = old.pages[i1 + k], new.pages[j1 + k]
                if op is not None and np_ is not None:
                    votes.setdefault(op, Counter())[np_] += 1
            continue
        # 変わった所：行の塊を、後のページ（なければ前のページ）ごとに分けて残す
        old_page = old.pages[i1] if i1 < i2 else (old.pages[i1 - 1] if i1 > 0 else None)
        new_page = new.pages[j1] if j1 < j2 else (new.pages[j1 - 1] if j1 > 0 else (new.pages[0] if new.pages else None))
        kind = {"replace": "変えた", "delete": "消した", "insert": "足した"}[tag]
        out.changes.append(Change(kind, old_page, new_page, old.raw[i1:i2], new.raw[j1:j2]))
        for k in range(j1, j2):
            if new.pages[k] is not None:
                changed_new.add(new.pages[k])
        if j1 == j2 and new_page is not None:
            changed_new.add(new_page)
        for k in range(i1, i2):
            if old.pages[k] is not None:
                changed_old.add(old.pages[k])
        if i1 == i2 and old_page is not None:
            changed_old.add(old_page)
    out.page_map = _majority(votes)
    # 行が1つも同じでない前のページは、前後のページの対応から近い所を当てる
    known = sorted(out.page_map)
    for page in old.page_list:
        if page is None or page in out.page_map:
            continue
        before = [p for p in known if p < page]
        after = [p for p in known if p > page]
        if before:
            out.page_map[page] = out.page_map[before[-1]] + (page - before[-1])
        elif after:
            out.page_map[page] = max(1, out.page_map[after[0]] - (after[0] - page))
    out.changed_new_pages = sorted(changed_new)
    out.changed_old_pages = sorted(changed_old)
    out.same = not out.changes
    return out


# ---- 前の回の資料と、今の資料の組 ----


def load_listed(company: Path, case: str) -> Dict:
    path = _text_root(company, case) / "資料の一覧.json"
    _inside(company, path, "案件の資料の一覧")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise KaiteiError(f"案件の資料の一覧（{path.relative_to(company).as_posix()}）が読めません（{type(e).__name__}）。"
                          "先に公式資料を取ってください") from e
    if not isinstance(data, dict) or not isinstance(data.get("資料"), list):
        raise KaiteiError("案件の資料の一覧の形が違います。公式資料を取り直してください")
    return data


def doc_pairs(listed: Dict) -> Dict[str, str]:
    """前の回の資料の id → 同じ名前の、今の資料の id（資料を取り直して、回が変わったもの）。"""
    now = {d.get("名前"): d.get("id") for d in listed.get("資料") or [] if isinstance(d, dict)}
    out = {}
    for d in listed.get("前の回の資料") or []:
        if isinstance(d, dict) and d.get("名前") in now and now[d["名前"]] != d.get("id"):
            out[str(d["id"])] = str(now[d["名前"]])
    return out


def page_diffs(company: Path, case: str, pairs: Dict[str, str]) -> Dict[str, PageDiff]:
    return {old: compare_docs(load_doc(company, case, old), load_doc(company, case, new)) for old, new in pairs.items()}


# ---- 章の読み取りの、変わったページへの当たり ----


def reading_files(company: Path, case: str) -> List[Path]:
    base = urakadori.seido_dir(company) / urakadori.READING_DIR / case_folder.safe_name(case)
    _inside(company, base, "章ごとの読み取りの結果")
    if not base.is_dir():
        raise KaiteiError(f"章ごとの読み取りの結果（{base.relative_to(company).as_posix()}/）がありません")
    files = []
    for path in sorted(base.glob("*.json")):
        _inside(company, path, "章ごとの読み取りの結果")
        files.append(path)
    return files


def _load_json(company: Path, path: Path) -> Dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise KaiteiError(f"{path.relative_to(company).as_posix()} が読めません（{type(e).__name__}）") from e
    if not isinstance(data, dict) or not isinstance(data.get("読み取り"), dict) or not isinstance(data.get("制度データ"), dict):
        raise KaiteiError(f"{path.relative_to(company).as_posix()} の形が違います（「読み取り」と「制度データ」がありません）")
    return data


def _source_pages(source: Dict) -> List[int]:
    page = source.get("ページ")
    if not isinstance(page, int):
        return []
    end = source.get("終わりのページ") if isinstance(source.get("終わりのページ"), int) else page
    return list(range(page, max(page, end) + 1))


def chapter_hits(chapter: Dict, diffs: Dict[str, PageDiff]) -> List[int]:
    """章が読んだページのうち、変わったページ（前の資料の印刷されたページ）。"""
    hits = set()
    for s in chapter["読み取り"].get("読んだページ") or []:
        if isinstance(s, dict) and s.get("資料") in diffs:
            hits.update(p for p in _source_pages(s) if p in diffs[s["資料"]].changed_old_pages)
    return sorted(hits)


# ---- 引き継ぎ：出典を今の資料に付け替える ----


def _map_page(page: int, diff: PageDiff) -> int:
    return diff.page_map.get(page, page)


def _evidence_on(texts: urakadori.Texts, source: Dict, sentence: str) -> bool:
    parts = urakadori.fragments(sentence or "")
    if not parts:
        return False
    got, lost = texts.pages(source)
    return bool(got) and not lost and all(any(p in t for _l, t in got) for p in parts)


def _repoint(source: Dict, pairs: Dict[str, str], diffs: Dict[str, PageDiff],
             texts: Optional[urakadori.Texts], sentence: Optional[str]) -> Dict:
    old_id = source.get("資料")
    if old_id not in pairs:
        return source
    out = dict(source, 資料=pairs[old_id])
    diff = diffs.get(old_id)
    if diff is None or not isinstance(source.get("ページ"), int):
        return out
    out["ページ"] = _map_page(source["ページ"], diff)
    if isinstance(source.get("終わりのページ"), int):
        out["終わりのページ"] = max(out["ページ"], _map_page(source["終わりのページ"], diff))
    if texts is None or sentence is None or _evidence_on(texts, out, sentence):
        return out
    # 境目で次のページに送られた文は、前後のページも見る（見つからなければ、そのまま。裏取りで要確認になる）
    for shift in (-1, 1):
        trial = dict(out, ページ=max(1, out["ページ"] + shift))
        if "終わりのページ" in out:
            trial["終わりのページ"] = max(trial["ページ"], out["終わりのページ"] + shift)
        if _evidence_on(texts, trial, sentence):
            return trial
    return out


def repoint_chapter(chapter: Dict, pairs: Dict[str, str], diffs: Dict[str, PageDiff],
                    texts: Optional[urakadori.Texts]) -> int:
    """章の出典と読んだページを、前の回の資料から今の資料に付け替える（その場で直す）。付け替えた出典の数を返す。"""
    count = [0]

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("出典"), list):
                new = [_repoint(s, pairs, diffs, texts, node.get("根拠の文")) if isinstance(s, dict) else s
                       for s in node["出典"]]
                count[0] += sum(1 for a, b in zip(node["出典"], new) if a != b)
                node["出典"] = new
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(chapter["制度データ"])
    pages = []
    for s in chapter["読み取り"].get("読んだページ") or []:
        moved = _repoint(s, pairs, diffs, None, None) if isinstance(s, dict) else s
        if moved not in pages:
            pages.append(moved)
    chapter["読み取り"]["読んだページ"] = pages
    return count[0]


@dataclass
class CarryResult:
    chapter: str
    hits: List[int]
    moved: int
    result: urakadori.Result
    broken: List[urakadori.Finding] = field(default_factory=list)   # 前の回では外れていなかったのに、今の資料で外れた値
    still: List[urakadori.Finding] = field(default_factory=list)    # 前の回の資料でも要確認だった値


def _states(part: Dict) -> Dict[str, str]:
    """出典つき値の場所（社長に分かる書き方）→ 状態。"""
    out: Dict[str, str] = {}

    def visit(node: Any, path: List[Any]) -> None:
        if urakadori._is_sourced_value(node):
            out[urakadori.readable(path, part)] = node["状態"]
            return
        if isinstance(node, dict):
            for key, value in node.items():
                visit(value, path + [key])
        elif isinstance(node, list):
            for i, value in enumerate(node):
                visit(value, path + [i])

    visit(part, [])
    return out


def _write_chapter(company: Path, case: str, chapter: Dict) -> Tuple[urakadori.Result, Dict]:
    """章の結果を、裏取りの道具（lib/urakadori.run）に通して置く。前の結果のファイルは、付け替えた形にしてから渡す
    （run は前の結果の読んだページを残すので、前の回の資料の頁が残らないように）。"""
    data = {"読み取り": chapter["読み取り"], "制度データ": chapter["制度データ"]}
    if chapter.get("メモ"):
        data["メモ"] = chapter["メモ"]
    errors = urakadori.shape_errors(data)
    if errors:
        raise urakadori.InputError(errors)
    out = urakadori.chapter_out_path(company, case, data)
    urakadori._check_place(company, out)
    out.write_text(json.dumps(dict(data, 裏取り={}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return urakadori.run(company, case, data)


CARRY_MEMO = "前の回の資料（{old}）の読み取りを引き継ぎ、出典を今の資料（{new}）に付け替えた（道具。変わったページに当たる値は読み直す）"


def carry(company: Path, case: str) -> Tuple[Dict[str, PageDiff], List[CarryResult]]:
    """全部の章の読み取りの出典を、今の資料に付け替え、今の資料の本文で裏取りし直して置く。"""
    listed = load_listed(company, case)
    pairs = doc_pairs(listed)
    if not pairs:
        raise KaiteiError("前の回の資料がありません（資料の一覧の「前の回の資料」が空）。付け替えるものはありません")
    diffs = page_diffs(company, case, pairs)
    texts = urakadori.Texts(company, case)
    texts.check_inside(texts.root)
    memo = CARRY_MEMO.format(old="・".join(pairs), new="・".join(pairs.values()))
    out = []
    for path in reading_files(company, case):
        chapter = _load_json(company, path)
        before = _states(chapter["制度データ"])
        hits = chapter_hits(chapter, diffs)
        moved = repoint_chapter(chapter, pairs, diffs, texts)
        if moved == 0 and not any(s.get("資料") in pairs for s in chapter["読み取り"]["読んだページ"] if isinstance(s, dict)):
            continue  # 前の回の資料を使っていない章（もう付け替えた章）
        notes = [m for m in chapter.get("メモ") or [] if isinstance(m, str)]
        if memo not in notes:
            notes.append(memo)
        chapter["メモ"] = notes
        result, _saved = _write_chapter(company, case, chapter)
        done = CarryResult(str(chapter["読み取り"]["章"]), hits, moved, result)
        for f in result.downgraded:
            (done.still if before.get(f.where) == urakadori.CHECK else done.broken).append(f)
        out.append(done)
    return diffs, out


# ---- 読み直した件だけを、章に差し替える ----


@dataclass
class ApplyResult:
    chapter: str
    replaced: List[str] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    result: Optional[urakadori.Result] = None


def apply_items(company: Path, case: str, data: Any) -> ApplyResult:
    """読み取り役が読み直した件（変わったページの件だけ）を、同じ章の結果に差し替える。

    data：{"読み取り": {"章", "読んだページ"}, "制度データ": {項目: [件…] か {…}}, "消す件": {項目: [名前…]}, "メモ": […]}
    一覧の項目は、件の名前（名前・区分・項目・id）で同じ件を差し替え、ない件は足す。一覧でない項目は、項目ごと差し替える。
    """
    if not isinstance(data, dict) or not isinstance(data.get("読み取り"), dict) or not isinstance(data.get("制度データ"), dict):
        raise urakadori.InputError(["（全体）：「読み取り」（章・読んだページ）と「制度データ」（読み直した件）を渡してください"])
    name = data["読み取り"].get("章")
    probe = {"読み取り": {"章": name, "読んだページ": [], "回目": 1}, "制度データ": {}}
    path = urakadori.chapter_out_path(company, case, probe) if isinstance(name, str) and name else None
    if path is None or not path.is_file():
        raise urakadori.InputError([f"読み取り.章：「{name}」の前の結果がありません（章の名前を、前の結果のとおりにしてください）"])
    _inside(company, path, "章ごとの読み取りの結果")
    chapter = _load_json(company, path)
    out = ApplyResult(str(name))
    part = chapter["制度データ"]
    for key, value in data["制度データ"].items():
        current = part.get(key)
        if isinstance(current, list) and isinstance(value, list):
            for item in value:
                item_name = urakadori._item_name(item)
                at = next((i for i, x in enumerate(current) if item_name and urakadori._item_name(x) == item_name), None)
                if at is None:
                    current.append(item)
                    out.added.append(f"{key}「{item_name or '名前のない件'}」")
                else:
                    current[at] = item
                    out.replaced.append(f"{key}「{item_name}」")
        else:
            part[key] = value
            out.replaced.append(key)
    for key, names in (data.get("消す件") or {}).items():
        current = part.get(key)
        for item_name in names or []:
            at = next((i for i, x in enumerate(current or []) if urakadori._item_name(x) == item_name), None)
            if at is None:
                out.missing.append(f"{key}「{item_name}」")
            else:
                del current[at]
                out.removed.append(f"{key}「{item_name}」")
    pages = list(chapter["読み取り"].get("読んだページ") or [])
    for p in data["読み取り"].get("読んだページ") or []:
        if p not in pages:
            pages.append(p)
    chapter["読み取り"]["読んだページ"] = pages
    notes = [m for m in chapter.get("メモ") or [] if isinstance(m, str)]
    for m in data.get("メモ") or []:
        if isinstance(m, str) and m not in notes:
            notes.append(m)
    chapter["メモ"] = notes
    out.result, _saved = _write_chapter(company, case, chapter)
    return out


def reread_list(diffs: Dict[str, PageDiff], carried: List[CarryResult], company: Path, case: str) -> List[Dict]:
    """章ごとに、読み直す値（今の資料で外れた値と、変わったページにある要確認の値）と、今の資料の変わったページ。"""
    out = []
    by_name = {}
    for path in reading_files(company, case):
        chapter = _load_json(company, path)
        by_name[str(chapter["読み取り"]["章"])] = chapter
    for c in carried:
        chapter = by_name.get(c.chapter)
        pages: Dict[str, List[int]] = {}
        if chapter is not None:
            for s in chapter["読み取り"].get("読んだページ") or []:
                if not isinstance(s, dict):
                    continue
                old = next((o for o, d in diffs.items() if d.new_id == s.get("資料")), None)
                if old is None:
                    continue
                hit = [p for p in _source_pages(s) if p in diffs[old].changed_new_pages]
                if hit:
                    pages.setdefault(diffs[old].new_id, [])
                    pages[diffs[old].new_id] += [p for p in hit if p not in pages[diffs[old].new_id]]
        on_changed = []
        for f in c.still:
            m = re.findall(r"（([^（）]+)）にありません", "".join(f.problems))
            if any(any(f"{doc} p.{p}" in "".join(m) for p in ps) for doc, ps in pages.items()):
                on_changed.append(f)
        values = [f.where for f in c.broken + on_changed]
        if values or pages:
            out.append({"章": c.chapter, "変わったページ": {k: sorted(v) for k, v in pages.items()}, "読み直す値": values})
    return out


# ---- 制度データの差 ----


SKIP_KEYS = ("スキーマの版", "制度", "資料", "読み取れなかった項目")

# 項目ごとの、自社の申請で影響するもの（会社のフォルダの中の場所と、見直すこと）
IMPACT = {
    "補助額": [("案件/{case}/概要と流れ.docx", "補助額の見込み"), ("財務モデル.xlsx", "補助金の額"),
             ("案件/{case}/1_申請/申請書/入力シート.xlsx", "申請画面の補助金の額の欄")],
    "数値の要件": [("財務モデル.xlsx", "計画の数値と、要件を満たすかの確かめ"), ("案件/{case}/1_申請/申請書/その1・2.docx", "数値の目標の書き方"),
               ("案件/{case}/概要と流れ.docx", "要件の判定"), ("記録/会社の記録.json", "従業員・賃金の事実")],
    "数値でない要件": [("案件/{case}/概要と流れ.docx", "要件の判定"), ("記録/会社の記録.json", "当てはまるかを確かめる事実")],
    "補助の対象になる経費": [("原本/見積・契約・請求", "見積書の経費の区分"), ("案件/{case}/1_申請/申請書/入力シート.xlsx", "経費の明細")],
    "補助の対象にならない経費": [("原本/見積・契約・請求", "見積書に対象外の経費がないか"),
                       ("案件/{case}/1_申請/申請書/入力シート.xlsx", "経費の明細"), ("財務モデル.xlsx", "投資額")],
    "決まった期日": [("記録/期限の台帳.json", "締切と期日"), ("今の状態.html", "期限の表示")],
    "手続きの段階": [("記録/期限の台帳.json", "出来事の日付から決まる期限"), ("今の状態.html", "期限の表示"),
                ("案件/{case}/概要と流れ.docx", "流れと期限")],
    "書類": [("記録/書類の台帳.json", "そろえる書類"), ("案件/{case}/1_申請/添付する書類", "添付する書類"),
           ("案件/{case}/概要と流れ.docx", "必要書類の一覧")],
    "様式": [("案件/{case}/1_申請/申請書", "様式で作る書類")],
    "審査の段階": [("案件/{case}/概要と流れ.docx", "流れ")],
    "審査項目": [("案件/{case}/1_申請/申請書/その1・2.docx", "審査項目に応える書き方")],
    "加点": [("案件/{case}/概要と流れ.docx", "加点の判定"), ("案件/{case}/1_申請/申請書/その1・2.docx", "加点に関わる書き方"),
           ("記録/会社の記録.json", "加点の証拠になる事実")],
    "してはいけないこと": [("案件/{case}/概要と流れ.docx", "注意すること")],
    "申請画面": [("案件/{case}/1_申請/申請書/入力シート.xlsx", "申請画面の欄")],
    "提出するファイルの決まり": [("案件/{case}/1_申請/申請書", "提出するファイルの形")],
    "資料どうしの食い違い": [("案件/{case}/概要と流れ.docx", "資料で分からなかったこと")],
    "地域による違い": [("記録/会社の記録.json", "所在地")],
    "支援者の欄": [("案件/{case}/1_申請/申請書/入力シート.xlsx", "支援者の欄")],
}


@dataclass
class ValueChange:
    kind: str            # 値が変わった・足した・消えた・状態が変わった
    where: str
    key: str             # いちばん上の項目
    old: Optional[Dict]
    new: Optional[Dict]
    page_ok: bool = True
    entry: str = ""      # 件ごと足した・消えたときの、その件の場所（報告では、件ごとに1つにまとめる）


@dataclass
class Rename:
    """前と後で件名が違い、件名と中身の近さで同じ件として比べた件（lib/seido_data.pair_items）。"""
    key: str
    old: str             # 前の件の場所
    new: str             # 後の件の場所
    score: str           # 近さ（件名 0.70・中身 0.19）


def _leaves(node: Any, path: List[Any]) -> List[Tuple[List[Any], Dict]]:
    """node の中の出典つき値の（道、出典つき値）。"""
    out: List[Tuple[List[Any], Dict]] = []
    if urakadori._is_sourced_value(node):
        return [(path, node)]
    if isinstance(node, dict):
        for k, v in node.items():
            out += _leaves(v, path + [k])
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _leaves(v, path + [i])
    return out


WORDING = "言い回しが変わった"


# 決まった言葉を選ぶ欄（言い回しではなく、中身の違い）
CHOICE_KEYS = {"種類", "何の上限", "税", "比べ方", "単位", "旬", "区分", "出来事"}


def _has_words(value: str) -> bool:
    """文の言葉（数字を除いて4字以上の文字）か。金額・割合・日付だけの文字は、言い回しの違いにしない。"""
    return len(re.sub(r"\d", "", seido_data.name_form(value))) >= 4


def only_wording(a: Any, b: Any, key: Optional[str] = None) -> bool:
    """2つの値の違いが、文の言い回しだけか：違う所がどれも文の言葉の欄（決まった言葉を選ぶ欄でない）で、
    欄の組み立ても同じ。数が同じかは、呼ぶ側で見る。"""
    if _same_value(a, b):
        return True
    if isinstance(a, str) and isinstance(b, str):
        return key not in CHOICE_KEYS and _has_words(a) and _has_words(b)
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(only_wording(a[k], b[k], k) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(only_wording(x, y, key) for x, y in zip(a, b))
    return False


def _named(items: List[Any]) -> bool:
    return any(urakadori._item_name(x) for x in items)


def _conflict_values(entry: Dict) -> List[Dict]:
    return [dict(item, 状態=item.get("状態", "資料で食い違い")) for item in entry.get("値") or [] if isinstance(item, dict)]


def _same_value(a: Any, b: Any) -> bool:
    return json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)


def _kinds(company: Path, case: str) -> Dict[str, str]:
    """資料の id → 種類（PDF・HTML など。本文がなければ空）。"""
    root = _text_root(company, case)
    out = {}
    if root.is_dir():
        for d in root.iterdir():
            index = d / doc_text.INDEX_FILE
            if index.is_file() and not place_text.read_problem(company, index, "ページの対応"):
                out[d.name] = str(doc_text.load_index(d).get("種類") or "")
    return out


def _has_page(value: Optional[Dict], kinds: Dict[str, str]) -> bool:
    """出典があり、PDF の出典にはどれもページがある（HTML・Word・Excel はページの番号がないので、資料だけでよい）。"""
    if not value:
        return False
    sources = [s for s in value.get("出典") or [] if isinstance(s, dict)]
    if not sources:
        return False
    return all(isinstance(s.get("ページ"), int) or kinds.get(str(s.get("資料")), "PDF") not in ("PDF", "") for s in sources)


def top_key(where: str) -> str:
    """値の場所（社長に分かる書き方）の、いちばん上の項目（「数値の要件」のように「の」を含む名前もある）。"""
    props = sorted(urakadori.load_schema()["properties"], key=len, reverse=True)
    return next((k for k in props if where.startswith(k)), re.split(r"[「の]", where, 1)[0])


def diff_data(old: Dict, new: Dict, kinds: Dict[str, str], renames: Optional[List[Rename]] = None) -> List[ValueChange]:
    """前と後の制度データの、出典つき値ごとの差。

    名前のある件の一覧（補助額・書類・数値の要件 など。件の中の特例や画面も）は、件名の形が同じ件を組にし、
    残りを件名と中身の近さで組にしてから（lib/seido_data.pair_items）、組の中の値を比べる。
    近さで組にした件は renames に入れる（報告で「件名が変わった件」として出す。黙って同じ件にしない）。
    組にならない件は、件ごと足した・消えたにする（件の中の値ごとの差には分けない）。
    前と後は別の読み取りなので、件名の言い回しが違うだけで、件の値が全部「消えた」と「足した」に出ないようにする
    （11/6 のリハーサル：第8回と第9回の差が 783 件になり、使えなかった）。
    """
    out: List[ValueChange] = []
    renames = renames if renames is not None else []

    def leaf(x: Optional[Dict], y: Optional[Dict], pa: List[Any], pb: List[Any], key: str, where: str = "") -> None:
        if x is not None and y is not None:
            where = where or urakadori.readable(pb, new)
            if _same_value(x.get("値"), y.get("値")):
                if x.get("状態") != y.get("状態"):
                    out.append(ValueChange("状態が変わった", where, key, x, y, True))
                return
            kind = "値が変わった"
            if (x.get("値") is not None and y.get("値") is not None
                    and urakadori.UNREADABLE not in (x.get("状態"), y.get("状態"))
                    and only_wording(x.get("値"), y.get("値"))
                    and seido_data.numbers_in(x.get("値")) == seido_data.numbers_in(y.get("値"))):
                kind = WORDING  # 数（金額・割合・日付も）は同じで、文の言い回しだけが違う
            change = ValueChange(kind, where, key, x, y)
            # 読み取れないになった値は出典を持たない。前も読み取れないだったときだけ、ページがなくてよい
            change.page_ok = _has_page(y, kinds) or (y.get("状態") == urakadori.UNREADABLE and x.get("状態") == urakadori.UNREADABLE)
        elif y is not None:
            change = ValueChange("足した", where or urakadori.readable(pb, new), key, None, y)
            change.page_ok = _has_page(y, kinds)
        elif x is not None:
            change = ValueChange("消えた", where or urakadori.readable(pa, old), key, x, None)
            change.page_ok = _has_page(x, kinds)  # 消えた値は、前の資料のどこにあったかを示す
        else:
            return
        out.append(change)

    def whole(node: Any, path: List[Any], root: Dict, gone: bool, key: str) -> None:
        """件ごと消えた（gone）・足した件の、中の値の全部。"""
        label = urakadori.readable(path, root)
        for p, v in _leaves(node, path):
            before = len(out)
            leaf(v if gone else None, None if gone else v, p, p, key)
            for c in out[before:]:
                c.where = urakadori.readable(p, root)
                c.entry = label

    def one_side(node: Any, path: List[Any], root: Dict, gone: bool, key: str) -> None:
        if isinstance(node, list) and _named(node):
            for i, item in enumerate(node):
                whole(item, path + [i], root, gone, key)
            return
        for p, v in _leaves(node, path):
            leaf(v if gone else None, None if gone else v, p, p, key, urakadori.readable(p, root))

    def walk(a: Any, b: Any, pa: List[Any], pb: List[Any], key: str) -> None:
        sa, sb = urakadori._is_sourced_value(a), urakadori._is_sourced_value(b)
        if sa and sb:
            leaf(a, b, pa, pb, key)
            return
        if isinstance(a, dict) and isinstance(b, dict) and not sa and not sb:
            for k in list(a) + [k for k in b if k not in a]:
                if not pa and k in SKIP_KEYS + ("資料どうしの食い違い",):
                    continue
                if not pa and (not a.get(k)) != (not b.get(k)):
                    # 項目ごと、片方の回にしかない（前の回では読んでいない項目など）：項目で1つにまとめる
                    whole(a.get(k) or b.get(k), [k], old if a.get(k) else new, bool(a.get(k)), k)
                    continue
                walk(a.get(k), b.get(k), pa + [k], pb + [k], key or k)
            return
        if isinstance(a, list) and isinstance(b, list):
            if _named(a) or _named(b):
                pairs = seido_data.pair_items(
                    [(urakadori._item_name(x) or "", seido_data.content_text(x)) for x in a],
                    [(urakadori._item_name(x) or "", seido_data.content_text(x)) for x in b])
                for p in pairs:
                    if p.near:
                        renames.append(Rename(key, urakadori.readable(pa + [p.old], old),
                                              urakadori.readable(pb + [p.new], new), p.label()))
                    walk(a[p.old], b[p.new], pa + [p.old], pb + [p.new], key)
                for i in sorted(set(range(len(a))) - {p.old for p in pairs}):
                    whole(a[i], pa + [i], old, True, key)
                for j in sorted(set(range(len(b))) - {p.new for p in pairs}):
                    whole(b[j], pb + [j], new, False, key)
            else:
                for i in range(max(len(a), len(b))):
                    walk(a[i] if i < len(a) else None, b[i] if i < len(b) else None, pa + [i], pb + [i], key)
            return
        one_side(a, pa, old, True, key)
        one_side(b, pb, new, False, key)

    walk(old, new, [], [], "")
    # 資料どうしの食い違い：項目の名前で組にし、組の中の値を順に比べる
    ca = [e for e in old.get("資料どうしの食い違い") or [] if isinstance(e, dict)]
    cb = [e for e in new.get("資料どうしの食い違い") or [] if isinstance(e, dict)]
    key = "資料どうしの食い違い"
    pairs = seido_data.pair_items([(e.get("項目") or "", "") for e in ca], [(e.get("項目") or "", "") for e in cb])
    for p in pairs:
        ea, eb = ca[p.old], cb[p.new]
        if p.near:
            renames.append(Rename(key, f"{key}「{ea.get('項目')}」", f"{key}「{eb.get('項目')}」", p.label()))
        va, vb = _conflict_values(ea), _conflict_values(eb)
        for j in range(max(len(va), len(vb))):
            leaf(va[j] if j < len(va) else None, vb[j] if j < len(vb) else None, [], [], key,
                 f"{key}「{eb.get('項目')}」の{j + 1}つ目の値")
    for gone, entries, used in ((True, ca, {p.old for p in pairs}), (False, cb, {p.new for p in pairs})):
        for i, e in enumerate(entries):
            if i in used:
                continue
            before = len(out)
            for j, v in enumerate(_conflict_values(e)):
                leaf(v if gone else None, None if gone else v, [], [], key, f"{key}「{e.get('項目')}」の{j + 1}つ目の値")
            for c in out[before:]:
                c.entry = f"{key}「{e.get('項目')}」"
    return out


def doc_label(data: Dict) -> Dict[str, str]:
    return {str(d.get("id")): f"{d.get('名前')}（{d.get('公募回')}）" for d in data.get("資料") or [] if isinstance(d, dict)}


def sources_text(value: Optional[Dict], labels: Dict[str, str]) -> str:
    if not value:
        return "（なし）"
    parts = []
    for s in value.get("出典") or []:
        if not isinstance(s, dict):
            continue
        name = labels.get(str(s.get("資料")), str(s.get("資料")))
        if isinstance(s.get("ページ"), int):
            end = s.get("終わりのページ")
            parts.append(f"{name} p.{s['ページ']}" + (f"–{end}" if isinstance(end, int) and end != s["ページ"] else ""))
        else:
            parts.append(f"{name}（ページの番号のない資料）")
    return "、".join(parts) or "（出典なし）"


def value_text(value: Optional[Dict], limit: int = 160) -> str:
    if value is None:
        return "（なし）"
    v = value.get("値")
    if v is None:
        text = f"読み取れない（{value.get('理由') or '理由なし'}）"
    elif isinstance(v, (dict, list)):
        text = _period_words(v) or json.dumps(v, ensure_ascii=False)
    else:
        text = str(v)
    if value.get("状態") and value.get("状態") != urakadori.CONFIRMED and v is not None:
        text += f"〔{value['状態']}〕"
    return text if len(text) <= limit else text[:limit] + "…"


def _period_words(v: Any) -> str:
    """期限・期間・日時の値を、短い言葉にする（ほかの形は空）。"""
    if isinstance(v, dict):
        if "数" in v and "単位" in v and len(v) == 2:
            return f"{v['数']}{v['単位']}"
        if "日時" in v and len(v) == 1:
            return str(v["日時"])
        if "年月" in v:
            return f"{v['年月']}{v.get('旬') or ''}"
        if v.get("種類") == "出来事からの期間" and isinstance(v.get("期間"), dict):
            return f"{v.get('出来事')}から{_period_words(v['期間'])}"
        if v.get("種類") in ("早いほう", "遅いほう") and isinstance(v.get("期限"), list):
            inner = [_period_words(x) or json.dumps(x, ensure_ascii=False) for x in v["期限"]]
            return f"{'・'.join(inner)}の{v['種類']}"
    return ""


def _period_strings(v: Any) -> List[str]:
    """値の中の期間（「17か月」など）の文字。申請書の中で探すため。"""
    out: List[str] = []
    if isinstance(v, dict):
        if "数" in v and "単位" in v:
            out.append(f"{v['数']}{v['単位']}")
        for x in v.values():
            out += _period_strings(x)
    elif isinstance(v, list):
        for x in v:
            out += _period_strings(x)
    return out


def _doc_texts(company: Path, case: str) -> Dict[str, str]:
    """会社が作った申請書（案件のフォルダの Word・Excel と、財務モデル）の文字。公式資料は除く。"""
    out = {}
    paths = list((company / "案件" / case_folder.safe_name(case)).rglob("*")) + [company / "財務モデル.xlsx"]
    for path in paths:
        if not path.is_file() or "公式資料" in path.parts or path.suffix not in (".docx", ".xlsx"):
            continue
        if place_text.read_problem(company, path, "申請書"):
            continue
        try:
            if path.suffix == ".docx":
                text = doc_text.word_text(path)
            else:
                text = "\n".join(t for _n, t in doc_text.excel_sheets(path))
        except Exception:  # 壊れたファイルは見ない（影響の一覧に出さないだけ）
            continue
        out[path.relative_to(company).as_posix()] = _SPACES.sub("", unicodedata.normalize("NFKC", text))
    return out


def impact(company: Path, case: str, changes: List[ValueChange]) -> List[Dict]:
    """変わった項目が、自社の申請のどこに影響するか（会社のフォルダにあるものだけ）。"""
    out: List[Dict] = []
    keys = []
    for c in changes:
        if c.kind != "状態が変わった" and c.key not in keys:
            keys.append(c.key)
    for key in keys:
        for place, what in IMPACT.get(key, []):
            rel = place.format(case=case_folder.safe_name(case))
            if (company / rel).exists():
                out.append({"項目": key, "場所": rel, "見直すこと": what})
    # 前の値の期間（「17か月」など）が、会社の作った申請書に書いてあれば、その場所を示す
    texts = _doc_texts(company, case)
    seen = set()
    for c in changes:
        if c.kind != "値が変わった" or not c.old:
            continue
        olds = set(_period_strings(c.old.get("値"))) - set(_period_strings((c.new or {}).get("値")))
        for word in sorted(olds):
            for rel, text in texts.items():
                if word in text and (rel, word) not in seen:
                    seen.add((rel, word))
                    out.append({"項目": c.where, "場所": rel, "見直すこと": f"前の値「{word}」が書いてある"})
    # 期限の台帳の出来事（手続きの段階の期限が変わると、その出来事から決まる期限が変わる）
    if any(c.key in ("手続きの段階", "決まった期日") for c in changes if c.kind != "状態が変わった"):
        ledger = company / RECORDS_DIR / "期限の台帳.json"
        if ledger.is_file() and not place_text.read_problem(company, ledger, "期限の台帳"):
            try:
                events = json.loads(ledger.read_text(encoding="utf-8")).get("出来事") or []
            except (OSError, ValueError, AttributeError):
                events = []
            for e in events:
                if isinstance(e, dict) and e.get("案件") == case:
                    out.append({"項目": "期限の台帳", "場所": "記録/期限の台帳.json",
                                "見直すこと": f"出来事「{e.get('名前')}」（{e.get('日付')}）から決まる期限を、新しい制度データで出し直す"})
    return out


_FIRST_NAME = re.compile(r"「[^「」]*」")


def _signature(kind: str, cs: List[ValueChange]) -> Any:
    """同じ変化かを見る印：種類、いちばん上の件名を除いた場所（「補助額の特例「X」の条件」）、値の前後。"""
    def values(c: ValueChange) -> str:
        return json.dumps([(c.old or {}).get("値"), (c.new or {}).get("値")], ensure_ascii=False, sort_keys=True)

    def place(where: str) -> str:
        return _FIRST_NAME.sub("", where, count=1)

    if len(cs) == 1 and not cs[0].entry:
        return (kind, place(cs[0].where), values(cs[0]))
    entry = cs[0].entry
    return (kind, place(entry), tuple((c.where[len(entry):], values(c)) for c in cs))


@dataclass
class DiffResult:
    old_file: str
    new_file: str
    old_round: str
    new_round: str
    docs: List[str]
    changes: List[ValueChange]
    impacts: List[Dict]
    labels_old: Dict[str, str] = field(default_factory=dict)
    labels_new: Dict[str, str] = field(default_factory=dict)
    renames: List[Rename] = field(default_factory=list)

    @property
    def missing_pages(self) -> List[ValueChange]:
        return [c for c in self.changes if not c.page_ok]

    def grouped(self) -> List[Tuple[str, List[ValueChange], List[str], bool]]:
        """報告の1件ずつ（種類、値の差、同じ変化のほかの場所、どれにも出典のページがあるか）。区分ごとに同じ特例が
        あるときなど、件名の最後と値の前後がまったく同じ変化は、1件にまとめて、ほかの場所を並べる。"""
        out: List[Tuple[str, List[ValueChange], List[str], bool]] = []
        at: Dict[Any, int] = {}
        for kind, cs in self.items():
            sig = _signature(kind, cs)
            ok = all(c.page_ok for c in cs)
            if sig in at:
                k, first, others, was_ok = out[at[sig]]
                out[at[sig]] = (k, first, others + [cs[0].entry or cs[0].where], was_ok and ok)
                continue
            at[sig] = len(out)
            out.append((kind, cs, [], ok))
        return out

    def items(self) -> List[Tuple[str, List[ValueChange]]]:
        """報告の1件ずつ（種類、値の差）。件ごと足した・消えた件は、中の値をまとめて1件にする。"""
        out: List[Tuple[str, List[ValueChange]]] = []
        at: Dict[Tuple[str, str], int] = {}
        for c in self.changes:
            if c.kind == "状態が変わった":
                continue
            if not c.entry:
                out.append((c.kind, [c]))
                continue
            group = (c.kind, c.entry)
            if group not in at:
                at[group] = len(out)
                out.append((f"{'項目' if c.entry == c.key else '件'}ごと{c.kind}", []))
            out[at[group]][1].append(c)
        return out


def load_seido(company: Path, rel: str) -> Dict:
    path = company / rel
    _inside(company, path, f"制度データ（{rel}）")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise KaiteiError(f"制度データ（{rel}）が読めません（{type(e).__name__}）") from e
    if not urakadori.is_full(data):
        raise KaiteiError(f"制度データ（{rel}）の形が違います（「スキーマの版」がありません）")
    return data


def seido_files(company: Path, abbreviation: str) -> List[str]:
    base = urakadori.seido_dir(company)
    _inside(company, base, "制度データ")
    files = sorted(base.glob(f"{case_folder.safe_name(abbreviation)}_第*回.json"),
                   key=lambda p: int(re.search(r"第(\d+)回", p.name).group(1)) if re.search(r"第(\d+)回", p.name) else 0)
    return [p.relative_to(company).as_posix() for p in files]


def compare_seido(company: Path, case: str, old_rel: Optional[str] = None, new_rel: Optional[str] = None) -> DiffResult:
    """前と後の制度データを比べる。渡さなければ、その制度のいちばん新しい2つの回。"""
    listed = load_listed(company, case)
    abbreviation = str((listed.get("制度") or {}).get("略称") or "")
    if not (old_rel and new_rel):
        files = seido_files(company, abbreviation)
        if len(files) < 2:
            raise KaiteiError(f"比べる制度データが2つありません（{'・'.join(files) or 'なし'}）。新しい回の制度データを先にまとめてください")
        old_rel, new_rel = old_rel or files[-2], new_rel or files[-1]
    old, new = load_seido(company, old_rel), load_seido(company, new_rel)
    kinds = _kinds(company, case)
    renames: List[Rename] = []
    changes = diff_data(old, new, kinds, renames)
    la, lb = doc_label(old), doc_label(new)
    docs = []
    for i, label in lb.items():
        if label not in la.values():
            docs.append(f"使う資料が変わった：{label}" + (f"（前は {la[i]}）" if i in la else ""))
    return DiffResult(old_rel, new_rel, str(old["制度"].get("公募回")), str(new["制度"].get("公募回")), docs, changes,
                      impact(company, case, changes), la, lb, renames)


SHOW_RENAMES = 60      # 報告に並べる「件名が変わった件」の数（ほかは --json で見る）
SHOW_ENTRY_VALUES = 3  # 件ごと足した・消えた件で、報告に並べる値の数


def diff_report(r: DiffResult) -> str:
    labels_old, labels_new = r.labels_old, r.labels_new
    every = r.grouped()
    items = [x for x in every if x[0] != WORDING]
    wording = [x for x in every if x[0] == WORDING]
    lines = [f"制度データの差（前：{r.old_file}〔{r.old_round}〕／後：{r.new_file}〔{r.new_round}〕）", ""]
    lines += [f"- {d}" for d in r.docs]
    if r.renames:
        lines += ["", f"件名が変わった件（前と後で件名が違い、件名と中身の近さで同じ件として比べた）：{len(r.renames)}件。"
                  "組が違っていれば、その章を読み直す（中の値の差は、下の変わった項目に出る）"]
        lines += [f"- {x.old} → {x.new}（近さ：{x.score}）" for x in r.renames[:SHOW_RENAMES]]
        if len(r.renames) > SHOW_RENAMES:
            lines.append(f"- ほかに {len(r.renames) - SHOW_RENAMES} 件（--json の「件名が変わった件」）")
    if not items and not wording:
        lines += ["", "変更なし（値の変わった項目はありません）。"]
    elif not items:
        lines += ["", "変わった項目：0件（数の変わった値・足した値・消えた値はありません。言い回しだけが違う値は下のとおり）。"
                  "出典のページのない変わった項目：0件"]
    else:
        counts = Counter(kind for kind, _cs, _o, _ok in items)
        missing = sum(1 for _k, _cs, _o, ok in items if not ok)
        same = sum(len(o) for _k, _cs, o, _ok in items)
        lines += ["", f"変わった項目：{len(items)}件（" + "・".join(f"{k} {n}件" for k, n in counts.items())
                  + f"）。出典のページのない変わった項目：{missing}件"
                  + (f"。区分ごとなどに同じ変化があるものは1件にまとめた（まとめた場所 {same}か所）" if same else ""), ""]
        for n, (kind, cs, others, ok) in enumerate(items, 1):
            mark = "" if ok else "  ← 出典のページがありません"
            also = ""
            if others:
                shown = "、".join(others[:3]) + (f" ほか{len(others) - 3}か所" if len(others) > 3 else "")
                also = f"\n   （同じ変化がほかに {len(others)}か所：{shown}）"
            if len(cs) == 1:
                c = cs[0]
                whole = ("（項目ごと）" if c.entry == c.key else "（件ごと）") if c.entry else ""
                lines.append(f"{n}. {c.kind}：{c.where}{mark}{whole}{also}")
                if c.old is not None:
                    lines.append(f"   前：{value_text(c.old)}　〔出典：{sources_text(c.old, labels_old)}〕")
                if c.new is not None:
                    lines.append(f"   後：{value_text(c.new)}　〔出典：{sources_text(c.new, labels_new)}〕")
                continue
            lines.append(f"{n}. {kind}：{cs[0].entry}（値 {len(cs)}）{mark}{also}")
            for c in cs[:SHOW_ENTRY_VALUES]:
                value, labels = (c.old, labels_old) if c.old is not None else (c.new, labels_new)
                inner = c.where[len(c.entry):] if c.where.startswith(c.entry) else c.where
                lines.append(f"   - {inner.lstrip('の') or '値'}：{value_text(value, 80)}　〔出典：{sources_text(value, labels)}〕")
            if len(cs) > SHOW_ENTRY_VALUES:
                lines.append(f"   - ほかに {len(cs) - SHOW_ENTRY_VALUES} 値（--json の「変わった項目」）")
    if wording:
        missing = sum(1 for _k, _cs, _o, ok in wording if not ok)
        lines += ["", f"数（金額・割合・日付・人数など）は同じで、文の言い回しだけが違う値：{len(wording)}件"
                  f"（出典のページのない値 {missing}件）。前と後は別の読み取りなので、書き方の違いのことが多い。"
                  "中身が変わっていないかは、前と後の文で確かめる"]
        for _k, cs, others, ok in wording:
            c = cs[0]
            mark = "" if ok else "  ← 出典のページがありません"
            also = f"（同じ変化がほかに {len(others)}か所）" if others else ""
            lines.append(f"- {c.where}{mark}{also}：前「{value_text(c.old, 50)}」／後「{value_text(c.new, 50)}」"
                         f"〔出典：{sources_text(c.new, labels_new)}〕")
    states = [c for c in r.changes if c.kind == "状態が変わった"]
    if states:
        lines += ["", f"値は同じで、状態だけが変わった値：{len(states)}件"]
        lines += [f"- {c.where}：{c.old.get('状態')} → {c.new.get('状態')}" for c in states[:20]]
    lines += ["", "自社の申請で影響するところ："]
    if r.impacts:
        lines += [f"- {i['場所']}：{i['見直すこと']}（{i['項目']}）" for i in r.impacts]
    else:
        lines.append("- ありません")
    return "\n".join(lines) + "\n"


def diff_json(r: DiffResult) -> Dict:
    labels_old, labels_new = r.labels_old, r.labels_new

    def one(c: ValueChange) -> Dict:
        out: Dict[str, Any] = {"種類": c.kind, "場所": c.where, "項目": c.key, "出典のページ": c.page_ok}
        if c.entry:
            out["件ごと"] = c.entry  # 件ごと足した・消えた件の場所
        for side, value, labels in (("前", c.old, labels_old), ("後", c.new, labels_new)):
            if value is not None:
                out[side] = {"値": value.get("値"), "状態": value.get("状態"), "出典": value.get("出典"),
                             "出典の名前": sources_text(value, labels)}
        return out

    return {"前": r.old_file, "後": r.new_file, "前の公募回": r.old_round, "後の公募回": r.new_round, "資料": r.docs,
            "件名が変わった件": [{"項目": x.key, "前": x.old, "後": x.new, "近さ": x.score} for x in r.renames],
            "変わった項目": [one(c) for c in r.changes if c.kind != "状態が変わった"],
            "状態だけ変わった値": [one(c) for c in r.changes if c.kind == "状態が変わった"],
            "影響するところ": r.impacts}
