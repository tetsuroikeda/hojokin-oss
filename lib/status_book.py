"""今の状態の画面と Excel の中身（工程表・書類ごとの状態・申請書の進み具合・長い期限）を、1つの組み立てから作る
（SPEC F6「今の状態」・T6-2、DESIGN 4.6。TASKS B27）。

画面（lib/status_view.py の render_page）と Excel（今の状態.xlsx）は、どちらもここの行から作るので、同じ値が入る。

- 工程表：案件ごとに、期限の日付が出せる手続きの段階を横の帯で並べる（帯は、前の段階の期限の次の日から、その段階の期限まで。
  いちばん前の段階は期限の日だけ）。繰り返しの報告（効果報告）は、回ごとに提出期間の帯にする。列は月ごと。期限の月に印（◆）、
  今日の月の列に今日の線。複数の案件を1つの表に並べる。外の部品（ライブラリや外のサイト）は読まない。
- 書類：原本（書類の台帳の原本。案件をまたいで1か所）、写し（書類の台帳の写し。元の原本と、その原本より新しい原本があるか）、
  申請書（段階のフォルダの「申請書」の中のファイル）。場所、提出版（その書類が入ったいちばん新しい提出版）、最後に変えた日
  （原本は整理した日、写しは作った日、申請書はファイルを最後に保存した日）。
- 申請書の進み具合：制度データの様式の項目ごとに、まだ・下書き・仮の印あり・確かめ中・完成。完成の記録に案件と段階があれば
  完成、審査役に渡したものの控えがあれば確かめ中、ほかは計画書の Word の項目の文（lib/kakunin.py と同じ読み方）で決める。
  文字数と上限も添える。
- 長い期限：繰り返しの報告の回ごとの期限（5年先まで）を、年ごとに。

hook からも呼ぶので、標準のライブラリだけを使う（同梱の openpyxl・dulwich を読み込まない）。/usr/bin/python3（3.9）で動く。
どの部分も、読めないものがあれば、その部分だけ空にしてわけを添える（画面全体は作る）。
"""

from __future__ import annotations

import json
import os
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lib import dates, deadlines, places  # noqa: F401（dates は工程表の今日の文に使う）

BOOK_NAME = "今の状態.xlsx"
JST = timezone(timedelta(hours=9))
APPLICATION_DIR = "申請書"
ORIGINAL = "原本"
COPY = "写し"
FORM_DOC = "申請書"
NOT_YET, DRAFT, PROVISIONAL, CHECKING, DONE = "まだ", "下書き", "仮の印あり", "確かめ中", "完成"
MONTHS_MAX = 84  # 工程表の列の数の上限（7年分）
COMPLETION_FILE = "記録/完成の記録.json"  # lib/kakunin.py の COMPLETION_REL と同じ
HANDOFF_DIR = "記録/審査に渡すもの"
DEFECTS_FILE = "記録/不備の一覧.json"


def nfc(text) -> str:
    return unicodedata.normalize("NFC", str(text or ""))


# ---- 書類 ----


@dataclass
class DocItem:
    form: str  # 原本・写し・申請書
    kind: str  # 書類の種類（写しは書類の名前、申請書はファイルの名前）
    case: str  # 案件（原本は空。案件をまたいで1か所）
    stage: str
    place: str
    changed: str  # 最後に変えた日（YYYY-MM-DD）
    submitted: str = ""  # 入っている、いちばん新しい提出版（「1_申請 1回目（2026-12-20）」）
    source: str = ""  # 写しの元の原本の場所
    newer: str = ""  # 元の原本より新しい原本の場所（あれば、写しを作り直す）


def _day(text) -> str:
    return str(text or "")[:10]


def _mtime_day(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, JST).date().isoformat()
    except OSError:
        return ""


def _read_json(folder: Path, rel: str):
    if places.first_link(folder, rel) is not None:
        return None
    path = places.actual(folder, rel)
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _submitted_by_file(folder: Path) -> Dict[str, str]:
    entries, _problem = deadlines._submissions(folder)
    latest: Dict[str, Tuple[Tuple, str]] = {}
    for e in entries:
        key = (str(e.get("日時") or ""), e.get("番号") if isinstance(e.get("番号"), int) else 0)
        label = f"{nfc(e.get('段階'))} {key[1]}回目（{_day(e.get('日時'))}）"
        for f in e.get("ファイル") or []:
            if isinstance(f, dict) and isinstance(f.get("書類"), str):
                place = nfc(f["書類"])
                if place not in latest or latest[place][0] <= key:
                    latest[place] = (key, label)
    return {k: v[1] for k, v in latest.items()}


def _newer(originals: List[dict], src: dict) -> str:
    """同じ区分・種類・相手先で、元の原本より日付の新しい原本の場所（lib/utsushi.py の newer_original と同じ決め方）。"""
    base = next((o for o in originals if o.get("id") == src.get("id")), None) or src
    key = (nfc(base.get("区分")), nfc(base.get("種類")), nfc(base.get("相手先")))
    found = [o for o in originals if (nfc(o.get("区分")), nfc(o.get("種類")), nfc(o.get("相手先"))) == key
             and o.get("id") != base.get("id") and str(o.get("日付") or "") > str(base.get("日付") or "")]
    return nfc(max(found, key=lambda o: str(o.get("日付") or ""))["場所"]) if found else ""


def documents(folder: Path, ov: deadlines.Overview) -> Tuple[List[DocItem], str]:
    """書類ごとの状態（原本・写し・申請書）と、読めなかったわけ。"""
    folder = Path(folder)
    sent = _submitted_by_file(folder)
    items: List[DocItem] = []
    problem = ""
    try:
        from lib import seiri
        ledger = seiri.load_ledger(folder)
    except Exception as error:
        ledger, problem = {}, f"書類の台帳を読めないため、原本と写しを並べていません（{error}）"
    originals = [o for o in ledger.get("原本") or [] if isinstance(o, dict) and isinstance(o.get("場所"), str)]
    for o in originals:
        items.append(DocItem(form=ORIGINAL, kind=nfc(o.get("種類")), case="", stage="", place=nfc(o["場所"]),
                             changed=_day(o.get("整理した日時")) or _day(o.get("日付")), submitted=sent.get(nfc(o["場所"]), "")))
    for c in ledger.get("写し") or []:
        if not isinstance(c, dict) or not isinstance(c.get("場所"), str):
            continue
        sources = [s for s in c.get("元の原本") or [] if isinstance(s, dict)]
        newer = [n for n in (_newer(originals, s) for s in sources) if n]
        items.append(DocItem(form=COPY, kind=nfc(c.get("書類")), case=nfc(c.get("案件")), stage=nfc(c.get("段階")),
                             place=nfc(c["場所"]), changed=_day(c.get("作った日時")), submitted=sent.get(nfc(c["場所"]), ""),
                             source="、".join(nfc(s.get("場所")) for s in sources), newer="、".join(newer)))
    for case in ov.cases:
        base = folder / deadlines.CASES_DIR / case.name
        for row in case.stages:
            if not row.folder:
                continue
            stage_dirs = [row.folder] + [deadlines.year_folder(row.folder, y.number) for y in row.years]
            for stage in stage_dirs:
                rel = f"{deadlines.CASES_DIR}/{case.name}/{stage}/{APPLICATION_DIR}"
                path = places.actual(folder, rel)
                if path is None or not path.is_dir() or not places.is_inside(folder, path):
                    continue
                for p in sorted(path.rglob("*")):
                    if not p.is_file() or p.name.startswith((".", "~")) or not places.is_inside(folder, p):
                        continue
                    place = nfc(p.relative_to(folder).as_posix())
                    items.append(DocItem(form=FORM_DOC, kind=nfc(p.name), case=case.name, stage=stage, place=place,
                                         changed=_mtime_day(p), submitted=sent.get(place, "")))
    return items, problem


# ---- 申請書の進み具合 ----


@dataclass
class FormItem:
    case: str
    stage: str
    form: str
    item: str
    state: str
    chars: int = 0
    limit: str = ""


def _forms_of(data: dict) -> List[dict]:
    forms = data.get("様式") if isinstance(data, dict) else None
    return [f for f in forms if isinstance(f, dict)] if isinstance(forms, list) else []


def _item_texts(folder: Path, case: str, stage: str, data: dict) -> Dict[str, str]:
    """申請書の Word の、様式の項目ごとの文（lib/kakunin.py と同じ読み方）。読めなければ空。"""
    try:
        from lib import kakunin
        files = kakunin.application_files(folder, case, stage)
    except Exception:
        return {}
    texts: Dict[str, str] = {}
    for rel, path in files.items():
        suffix = Path(rel).suffix.lower()
        if suffix not in (".docx", ".xlsx"):
            continue
        try:
            found, _cells = kakunin._texts_of(path.read_bytes(), rel, suffix, data)
        except Exception:
            continue
        for key, text in found.items():
            texts[nfc(key)] = texts.get(nfc(key), "") + text
    return texts


def forms(folder: Path, ov: deadlines.Overview) -> List[FormItem]:
    """案件の、申請書を作る段階（今の段階と、申請書のある段階）の、様式の項目ごとの進み具合。"""
    folder = Path(folder)
    out: List[FormItem] = []
    done = _read_json(folder, COMPLETION_FILE)
    done_list = done.get("記録") if isinstance(done, dict) else done
    completed = {(nfc(d.get("案件")), nfc(d.get("段階"))) for d in done_list or [] if isinstance(d, dict)} \
        if isinstance(done_list, list) else set()
    handoff = _read_json(folder, f"{HANDOFF_DIR}/控え.json")
    checking = (nfc(handoff.get("案件")), nfc(handoff.get("段階"))) if isinstance(handoff, dict) else None
    for case in ov.cases:
        if case.problem:
            continue
        try:
            from lib import seido_data
            _path, data = seido_data.load_data(folder, case.name)
        except Exception:
            continue
        # 様式の項目を持つのは申請の段階なので、進み具合は申請の段階（いちばん前の、フォルダのある段階）のもの（仮）
        stage = next((r.folder for r in case.stages if r.folder), "")
        if not stage:
            continue
        texts = _item_texts(folder, case.name, stage, data)
        try:
            from lib import kakunin
            limits = kakunin._limits(data)
        except Exception:
            limits = {}
        for form in _forms_of(data):
            for item in form.get("項目") or []:
                if not isinstance(item, dict) or not isinstance(item.get("名前"), str):
                    continue
                name = nfc(item["名前"])
                text = texts.get(name, "")
                chars = sum(1 for ch in text if not ch.isspace())
                if (case.name, stage) in completed:
                    state = DONE
                elif checking == (case.name, stage) and text:
                    state = CHECKING
                elif not text.strip():
                    state = NOT_YET
                else:
                    try:
                        from lib import kakunin
                        state = PROVISIONAL if kakunin.marks(text) else DRAFT
                    except Exception:
                        state = DRAFT
                limit = limits.get(name)
                out.append(FormItem(case=case.name, stage=stage, form=nfc(form.get("名前")), item=name, state=state,
                                    chars=chars, limit=f"{limit[1]}字（{limit[0]}）" if limit else ""))
    return out


# ---- 長い期限と工程表 ----


@dataclass
class YearLine:
    case: str
    stage: str
    number: int
    label: str
    state: str  # 提出済み・次に出す回・これから
    due: deadlines.Due


def long_deadlines(ov: deadlines.Overview) -> List[YearLine]:
    out = []
    for case in ov.cases:
        for row in case.stages:
            for y in row.years:
                state = "提出済み" if y.submitted else ("次に出す回" if y.number == row.next_year else "これから")
                out.append(YearLine(case=case.name, stage=row.name, number=y.number, label=y.due.label(), state=state,
                                    due=y.due))
    return out


@dataclass
class Bar:
    case: str
    label: str  # 段階の名前（効果報告は「… 1年目」）
    start: date
    end: date
    due_label: str
    state: str  # 済み・今・これから・提出済み など


def _month(day: date) -> Tuple[int, int]:
    return day.year, day.month


def _months(first: date, last: date) -> List[Tuple[int, int]]:
    out = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month) and len(out) < MONTHS_MAX:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def bars(ov: deadlines.Overview) -> List[Bar]:
    out = []
    for case in ov.cases:
        previous: Optional[date] = None
        for row in case.stages:
            if row.years:
                for y in row.years:
                    state = "提出済み" if y.submitted else ("次に出す回" if y.number == row.next_year else "これから")
                    out.append(Bar(case=case.name, label=f"{row.name} {y.number}{deadlines.YEAR_WORD}", start=y.due.first,
                                   end=y.due.last, due_label=y.due.label(), state=state))
                continue
            d = row.due
            if d is None or not d.dated:
                continue
            start = previous + timedelta(days=1) if previous is not None and previous < d.last else d.first
            out.append(Bar(case=case.name, label=row.name, start=min(start, d.first), end=d.last, due_label=d.label(),
                           state=row.state))
            previous = d.last
    return out


def gantt(ov: deadlines.Overview) -> Tuple[List[Tuple[int, int]], List[Bar]]:
    """工程表の月の列と帯。帯がなければ（[], []）。"""
    found = bars(ov)
    if not found:
        return [], []
    first = min([b.start for b in found] + [ov.today])
    last = max([b.end for b in found] + [ov.today])
    return _months(first, last), found


def cells(months: List[Tuple[int, int]], bar: Bar, today: date) -> List[str]:
    """帯の1行の、月ごとの印（"" 空・"bar" 帯・"mark" 期限の月）。"""
    out = []
    for ym in months:
        if ym == _month(bar.end):
            out.append("mark")
        elif _month(bar.start) <= ym < _month(bar.end):
            out.append("bar")
        else:
            out.append("")
    return out


# ---- 不備 ----


def defects(folder: Path) -> List[dict]:
    data = _read_json(Path(folder), DEFECTS_FILE)
    return [i for i in data.get("不備") or [] if isinstance(i, dict)] if isinstance(data, dict) else []


# ---- Excel ----


def _task_rows(ov: deadlines.Overview) -> List[Tuple[str, deadlines.Task]]:
    rows = []
    for group in deadlines.GROUPS:
        rows += [(group, t) for t in ov.groups.get(group) or []]
    rows += [(f"{ov.near_days}日より先", t) for t in ov.later]
    rows += [("日付がまだ出せない", t) for t in ov.undated]
    rows += [("済んだもの", t) for t in ov.done]
    return rows


TASK_HEAD = ["分け方", "締切", "あと何日", "案件", "期限の名前", "見込みか確定か", "だれがするか", "依頼の状態", "出典", "メモ"]
DOC_HEAD = ["原本か写しか", "書類", "案件", "段階", "場所", "提出版", "最後に変えた日", "写しの元の原本", "元の原本より新しい原本"]
FORM_HEAD = ["案件", "段階", "様式", "項目", "進み具合", "文字数", "上限"]
YEAR_HEAD = ["案件", "手続き", "回", "期限", "状態"]


def task_values(group: str, t: deadlines.Task, today: date) -> List[str]:
    memo = [n for n in t.notes]
    if t.start is not None:
        memo.insert(0, f"始める日：{t.start_label()}")
    return [group, t.due.label(), t.due.days_text(today) if not t.done else "", t.case, t.what, t.due.state_word,
            t.who or "—", t.state or "—", "、".join(t.due.sources), "。".join(memo)]


def doc_values(d: DocItem) -> List[str]:
    return [d.form, d.kind, d.case or "（案件をまたぐ）", d.stage or "—", d.place, d.submitted or "—", d.changed or "—",
            d.source or "—", d.newer or "—"]


def form_values(f: FormItem) -> List[object]:
    return [f.case, f.stage, f.form, f.item, f.state, f.chars, f.limit or "—"]


def year_values(y: YearLine) -> List[str]:
    return [y.case, y.stage, f"{y.number}{deadlines.YEAR_WORD}", y.label, y.state]


def book(folder: Path, ov: deadlines.Overview) -> bytes:
    """今の状態.xlsx のバイト列（シートは「締切」「工程表」「作業」「書類」「不備」「申請書」「変更の履歴」）。"""
    from lib import xlsx_min as x

    folder = Path(folder)
    today = ov.today
    head = lambda values: [(v, x.HEAD) for v in values]  # noqa: E731
    deadline_rows: List[list] = [head(TASK_HEAD)]
    deadline_rows += [task_values(g, t, today) for g, t in _task_rows(ov)]
    years = long_deadlines(ov)
    if years:
        deadline_rows += [[], [("長い期限（効果報告など、年ごと）", x.HEAD)], head(YEAR_HEAD)]
        deadline_rows += [year_values(y) for y in years]

    months, found = gantt(ov)
    gantt_rows: List[list] = [head(["案件", "手続き", "期限", "状態"] + [f"{y}年{m}月" for y, m in months])]
    today_col = _month(today)
    gantt_rows.append(["", "", f"今日：{dates.format_date(today)}", ""]
                      + [("▼今日", x.TODAY) if ym == today_col else "" for ym in months])
    for b in found:
        marks = cells(months, b, today)
        gantt_rows.append([b.case, b.label, b.due_label, b.state]
                          + [("◆", x.MARK) if m == "mark" else (("", x.BAR) if m == "bar" else
                                                                 (("", x.TODAY) if months[i] == today_col else ""))
                             for i, m in enumerate(marks)])
    if not found:
        gantt_rows.append(["期限の日付が出せる手続きの段階がまだありません"])

    work_rows: List[list] = [head(TASK_HEAD)]
    work_rows += [task_values(g, t, today) for g, t in _task_rows(ov)
                  if t.kind in (deadlines.REQUEST, "証拠", "義務")]
    for case in ov.cases:
        for e in case.evidence:
            work_rows.append(["経費ごとの証拠", "", "", case.name, f"{e.expense}（{e.partner or '相手先不明'}）", "", "社長",
                              "そろった" if not e.missing else "まだ", "", "まだ：" + ("、".join(e.missing) or "なし")])
    items, problem = documents(folder, ov)
    doc_rows: List[list] = [head(DOC_HEAD)] + [doc_values(d) for d in items]
    if problem:
        doc_rows.append([problem])
    defect_rows: List[list] = [head(["重さ", "種類", "書類", "直し方", "直したか"])]
    defect_rows += [[i.get("重さ", ""), i.get("種類", ""), i.get("書類", ""), i.get("直し方", ""),
                     "直した" if i.get("直した") else "まだ"] for i in defects(folder)]
    form_rows: List[list] = [head(FORM_HEAD)] + [form_values(f) for f in forms(folder, ov)]
    change_rows = [head(["いつ", "何を", "だれが"]),
                   ["最近の変更は、kiroku の道具（「前の版を見せて」）で見られます。この表には入れていません（仮）"]]
    sheets = [("締切", deadline_rows, [14, 34, 16, 26, 34, 12, 20, 12, 24, 60]),
              ("工程表", gantt_rows, [26, 30, 34, 10] + [5] * len(months)),
              ("作業", work_rows, [14, 34, 16, 26, 34, 12, 20, 12, 24, 60]),
              ("書類", doc_rows, [10, 28, 26, 16, 60, 24, 14, 50, 50]),
              ("不備", defect_rows, [8, 30, 40, 60, 10]),
              ("申請書", form_rows, [26, 12, 30, 50, 12, 8, 20]),
              ("変更の履歴", change_rows, [20, 60, 10])]
    return x.book_bytes(sheets)


def write_book(folder: Path, ov: deadlines.Overview) -> Optional[str]:
    """今の状態.xlsx を書く。中身が同じなら書き直さない。書けなかったときは、そのわけ。"""
    from lib import place_text

    folder = Path(folder)
    problem = place_text.write_problem(folder, BOOK_NAME, f"{BOOK_NAME} を作り直していません")
    if problem:
        return problem
    data = book(folder, ov)
    path = places.actual(folder, BOOK_NAME, partial=True)
    tmp = None
    try:
        if os.path.lexists(str(path)):
            if not path.is_file():
                return f"{BOOK_NAME} がファイルでないため、作り直していません"
            if path.read_bytes() == data:
                return None
        tmp = path.with_name(f"~{BOOK_NAME}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(str(tmp), str(path))
        tmp = None
    except OSError as error:
        return f"{BOOK_NAME} を書けませんでした（{error}）"
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
    return None
