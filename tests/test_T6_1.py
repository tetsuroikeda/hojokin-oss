"""T6-1 開いたときの表示（SPEC F6、DESIGN 4.6・4.7 の3と5・4.2。TASKS M3）。

合格ライン（SPEC T6-1）：今日の日付と案件の状態を固定して作ると、期限切れが一番上に分かれ、続いて期待する作業が
締切順に並ぶ。近い締切には、設定した日数の内のものだけが入る。
M3 で確かめるのは、近い締切がはじめの値（30日）の部分。日数を変える設定と期限の台帳は K1 で足す。

材料は、このファイルの中の架空の制度データ3つ（tests の外の場所も、公式資料も使わない）。今日は 2027-03-01（月）に
差し替え、3つの案件を次の状態に固定する。
- A「2026_試し補助（一般型）第3回」：1_申請 の段階（提出していない）。申請の締切は過ぎた（期限切れ）。
  今日が締切の手続き、採択発表の予定（決まった期日）から出す見込みの期限（7日以内）、早いほうの一部が分からない
  期限（遅くとも30日後。近い締切に入る境目）、日付をまだ出せない効果報告がある。前の回（第2回）の締切は使わない。
- B「2027_試し助成第5回」：制度データは前の回（第4回）の資料から作ったもの。段階の期限は第4回の締切（過ぎた日）だが、
  決まった期日に第5回の締切（3月下旬・予定）があるので、そちらを使う。回のない締切の名前の日付も使わない。
  31日後の期限（近い締切に入らない境目）と、過ぎた届け出がある。
- C「2025_試し補助（一般型）第1回」：2_交付申請 の段階で、交付申請の提出版を記録した。前の段階と交付申請の期限は
  出さない。次の段階（事業の実施）の期限が近い。
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

import company_tool as ct
import pytest
import version_tool as vt
from lib import common_rules, deadlines, status_view

TODAY = "2027-03-01"
CASE_A = "2026_試し補助（一般型）第3回"
CASE_B = "2027_試し助成第5回"
CASE_C = "2025_試し補助（一般型）第1回"
PAGE = "今の状態.html"


def _sv(value, source="要領", page=None, state="確認済み", note=None):
    """出典つきの値。"""
    src = {"資料": source}
    if page is not None:
        src["ページ"] = page
    node = {"値": value, "出典": [src], "根拠の文": "（架空の資料の文）", "状態": state}
    if note:
        node["注記"] = note
    return node


def _fixed_date(text):
    return {"種類": "決まった日付", "日時": text}


SEIDO_A = {
    "スキーマの版": 1,
    "制度": {"名前": "試し補助金", "枠": "一般型", "種類": "補助金", "公募回": "第3回"},
    "決まった期日": [
        {"名前": "第2回 公募締切日", "日時": _sv({"日時": "2027-03-02T17:00+09:00"}, "スケジュール")},
        {"名前": "第3回 採択発表日", "日時": _sv({"日時": "2027-02-05"}, "スケジュール"), "注記": "予定"},
    ],
    "書類": [
        {"名前": "履歴事項全部証明書", "区分": "必須", "発行元": "役所", "手続き": ["申請"], "内容": _sv("法人")},
        {"名前": "納税証明書（その2）", "区分": "必須", "発行元": "役所", "手続き": ["申請"], "内容": _sv("直近")},
        {"名前": "事業計画書（その1）", "区分": "必須", "発行元": "自社", "手続き": ["申請"], "内容": _sv("計画")},
        {"名前": "見積書", "区分": "必須", "発行元": "外部機関", "手続き": ["交付申請"], "内容": _sv("相見積")},
        {"名前": "会社案内", "区分": "任意", "発行元": "自社", "手続き": ["申請"], "内容": _sv("任意")},
    ],
    "様式": [{"名前": "【参考様式】事業計画書（その1）"}],
    "手続きの段階": [
        {"id": "申請", "順番": 1, "名前": "申請", "フォルダ": "1_申請",
         "期限": _sv(_fixed_date("2027-02-26T17:00+09:00"), page=4),
         "様式": ["【参考様式】事業計画書（その1）"],
         "注意": [_sv("締切の期限までに申請がなかったときは、次の回に申請する", page=5),
                  _sv("電子申請で出す", page=6)]},
        {"id": "追加提出", "順番": 2, "名前": "書類の追加提出", "期限": _sv(_fixed_date("2027-03-01"), page=7)},
        {"id": "採択発表", "順番": 3, "名前": "採択発表", "始まる条件": _sv("後日")},
        {"id": "交付申請", "順番": 4, "名前": "交付申請", "フォルダ": "2_交付申請",
         "期限": _sv({"種類": "出来事からの期間", "出来事": "採択発表日", "期間": {"数": 1, "単位": "か月"}}, page=8)},
        {"id": "実績報告", "順番": 5, "名前": "実績報告", "フォルダ": "3_実績報告",
         "期限": _sv({"種類": "早いほう", "期限": [
             {"種類": "出来事からの期間", "出来事": "補助事業の完了", "期間": {"数": 30, "単位": "日"}},
             _fixed_date("2027-03-31")]}, page=9)},
        {"id": "効果報告", "順番": 6, "名前": "効果報告", "フォルダ": "4_効果報告",
         "期限": _sv({"種類": "繰り返し", "回数": 3, "間隔": {"数": 1, "単位": "年"},
                      "提出期間": {"始まりの月": 4, "長さ": {"数": 3, "単位": "か月"}}}, page=10)},
    ],
}

SEIDO_B = {
    "スキーマの版": 1,
    "制度": {"名前": "試し助成金", "種類": "助成金", "公募回": "第4回"},
    "決まった期日": [
        {"名前": "公募締切日", "日時": _sv({"日時": "2027-03-03T17:00+09:00"}, "スケジュール")},
        {"名前": "第5回 公募締切日", "日時": _sv({"年月": "2027-03", "旬": "下旬"}, "スケジュール"), "注記": "予定"},
    ],
    "手続きの段階": [
        {"id": "申請", "順番": 1, "名前": "申請", "フォルダ": "1_申請",
         "期限": _sv(_fixed_date("2027-01-15T17:00+09:00"), "要領4", page=3)},
        {"id": "見積書等の提出", "順番": 2, "名前": "見積書等の提出", "期限": _sv(_fixed_date("2027-04-01"), "要領4", page=4)},
        {"id": "届け出", "順番": 3, "名前": "事前の届け出", "期限": _sv(_fixed_date("2027-02-01"), "要領4", page=5),
         "注意": [_sv("届け出は電子申請で出す", "要領4", page=5)]},
    ],
}

SEIDO_C = {
    "スキーマの版": 1,
    "制度": {"名前": "試し補助金", "枠": "一般型", "種類": "補助金", "公募回": "第1回"},
    "決まった期日": [],
    "手続きの段階": [
        {"id": "申請", "順番": 1, "名前": "申請", "フォルダ": "1_申請", "期限": _sv(_fixed_date("2025-12-01"))},
        {"id": "交付申請", "順番": 2, "名前": "交付申請", "フォルダ": "2_交付申請",
         "期限": _sv(_fixed_date("2027-02-10"))},
        {"id": "実施", "順番": 3, "名前": "事業の実施", "期限": _sv(_fixed_date("2027-03-10"), page=12)},
        {"id": "実績報告", "順番": 4, "名前": "実績報告", "フォルダ": "3_実績報告",
         "期限": _sv(_fixed_date("2027-06-30"))},
    ],
}

# 期待する並び（案件、期限の名前）。それぞれの中は締切順
EXPECTED = {
    deadlines.OVERDUE: [(CASE_B, "事前の届け出の期限"), (CASE_A, "申請の期限")],
    deadlines.TODAY: [(CASE_A, "書類の追加提出の期限")],
    deadlines.NEAR: [(CASE_A, "交付申請の期限"), (CASE_C, "事業の実施の期限"), (CASE_B, "申請の期限"),
                     (CASE_A, "実績報告の期限")],
    deadlines.LATE: [],
}
LATER = [(CASE_B, "見積書等の提出の期限"), (CASE_C, "実績報告の期限")]
UNDATED = [(CASE_A, "効果報告の期限")]


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


def _case(folder: Path, case: str, short: str, seido: dict, case_round: str, doc_round: str, frame: str,
          stages: list) -> None:
    listed = {"案件": case,
              "制度": {"名前": seido["制度"]["名前"], "略称": short, "種類": seido["制度"]["種類"], "公募回": case_round},
              "案件の回": case_round,
              "資料": [{"id": f"要領{doc_round}", "名前": "公募要領", "公募回": f"第{doc_round}回"}]}
    if frame:
        listed["制度"]["枠"] = frame
    _write_json(folder / "記録" / "資料の本文" / case / "資料の一覧.json", listed)
    _write_json(folder / "記録" / "制度データ" / f"{short}_第{doc_round}回.json", seido)
    for stage in stages:
        for sub in ("申請書", "添付する書類"):
            (folder / "案件" / case / stage / sub).mkdir(parents=True, exist_ok=True)


def set_today(folder: Path, today: str = TODAY) -> None:
    path = folder / ".hojokin" / "設定.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["今日の日付"] = today
    _write_json(path, data)


def make_cases(folder: Path) -> None:
    """3つの案件を、決まった状態で置く。"""
    set_today(folder)
    _case(folder, CASE_A, "試し補助", SEIDO_A, "第3回", "3", "一般型", ["1_申請"])
    _case(folder, CASE_B, "試し助成", SEIDO_B, "第5回", "4", "", ["1_申請"])
    _case(folder, CASE_C, "試し補助", SEIDO_C, "第1回", "1", "一般型", ["1_申請", "2_交付申請"])
    _write_json(folder / "記録" / "提出版.json", {"提出版": [
        {"案件": CASE_C, "段階": "2_交付申請", "日時": "2027-02-09T10:00:00+09:00", "版": "0" * 40, "番号": 1,
         "ファイル": []}]})


def plain_folder(tmp_path: Path) -> Path:
    """道具で作らない、目印だけの会社のフォルダ（hook を通さずに、組み立ての道具を直接確かめる）。"""
    folder = tmp_path / "試しの会社"
    (folder / ".hojokin").mkdir(parents=True)
    return folder


# ---- 渡す文を読み分ける ----

HEADS = {deadlines.OVERDUE: "### 期限切れ", deadlines.TODAY: "### 今日やること",
         deadlines.NEAR: "### 近い締切（30日以内）", deadlines.LATE: "### 遅れている作業"}


def sections(text: str) -> dict:
    """期限と作業の部分を、見出しごとの行に分ける。"""
    block = text[text.index(status_view.BRIEF_HEAD):]
    block = block[: block.index("## hojokin：どの段階にも共通の決まり")]
    found, current = {"頭": []}, "頭"
    for line in block.splitlines():
        if line.startswith("### "):
            current = line
            found[current] = []
        elif line.strip():
            found[current].append(line)
    return found


def items(lines: list) -> list:
    """「- 締切（あと何日）｜案件｜期限の名前。メモ」の行から、（案件、期限の名前）。"""
    out = []
    for line in lines:
        if not line.startswith("- ") or "｜" not in line:
            continue
        _head, case, rest = line[2:].split("｜", 2)
        out.append((case, rest.split("。", 1)[0]))
    return out


def line_of(lines: list, case: str, what: str) -> str:
    (line,) = [x for x in lines if f"｜{case}｜{what}" in x]
    return line


def assert_expected_order(text: str) -> None:
    sec = sections(text)
    order = [k for k in sec if k.startswith("### ")]
    # 期限切れが一番上に分かれ、続いて今日やること・近い締切・遅れている作業
    assert order[:4] == [HEADS[g] for g in deadlines.GROUPS], order
    assert items(sec["頭"]) == [], "期限切れより前に作業が並んでいる"
    for group in deadlines.GROUPS:
        assert items(sec[HEADS[group]]) == EXPECTED[group], group
    return sec


# ---- 開いたとき（hook を Claude Code と同じ形で動かす） ----


@pytest.fixture
def company(tmp_path):
    c = vt.Company(tmp_path)
    make_cases(c.folder)
    return c


def test_session_start_lists_overdue_first_then_tasks_by_deadline(company) -> None:
    """期限切れが一番上に分かれ、続いて期待する作業が締切順に並ぶ。近い締切には30日以内のものだけが入る。"""
    out = company.start_raw("startup")
    text = vt.start_context(out)
    sec = assert_expected_order(text)

    near = sec[HEADS[deadlines.NEAR]]
    # 近い締切：境目の30日（遅くとも 3月31日）は入り、31日（4月1日）は入らない
    assert "あと30日" in line_of(near, CASE_A, "実績報告の期限")
    assert "遅くとも 2027年3月31日（水）" in line_of(near, CASE_A, "実績報告の期限")
    days = [int(m) for m in re.findall(r"あと([0-9]+)日", "\n".join(near))]
    assert days and all(0 < d <= 30 for d in days), days
    assert "2027年4月1日" not in "\n".join(near)
    assert "30日より先の期限が2件、日付がまだ出せない期限が1件" in text

    # 7日以内は強める（あと4日の見込みの交付申請）。あと9日には付けない
    kofu = line_of(near, CASE_A, "交付申請の期限")
    assert "2027年3月5日（金）（見込み）（あと4日）【7日以内】" in kofu
    assert "【7日以内】" not in line_of(near, CASE_C, "事業の実施の期限")
    # 日が決まっていない第5回の締切は、旬のはじめの日で並べ、見込みと示す
    assert "2027年3月下旬（日はまだ決まっていません）（見込み）（あと20日）" in line_of(near, CASE_B, "申請の期限")

    overdue = sec[HEADS[deadlines.OVERDUE]]
    line_a = line_of(overdue, CASE_A, "申請の期限")
    assert "2027年2月26日（金）17:00（3日過ぎています）" in line_a
    # 期限切れには、制度データにある手を出典つきで添える。手がなければ、そう書く
    assert "過ぎたときの手：締切の期限までに申請がなかったときは、次の回に申請する（要領 p.5）" in line_a
    assert "過ぎたときの手が資料に見当たりません" in line_of(overdue, CASE_B, "事前の届け出の期限")
    # 今の段階の作業には、集める必須の書類のうち見当たらないものを添える（様式で作る書類と任意の書類は数えない）
    assert "見当たらないもの 2件（履歴事項全部証明書、納税証明書（その2））" in line_a
    assert "今日まで" in line_of(sec[HEADS[deadlines.TODAY]], CASE_A, "書類の追加提出の期限")

    # 前の回の日付と、済んだ段階の期限は出さない
    for absent in ("2027年3月2日", "2027年3月3日", "2027年1月15日", "2027年2月10日", "2025年12月1日"):
        assert absent not in text, absent
    # 今日の日付（差し替え）と、近い締切の日数を示す
    assert "今日：2027年3月1日（月）（日付を差し替えています）" in text
    assert "近い締切は30日以内" in text


def test_session_start_passes_common_rules_within_limits(company) -> None:
    """どの段階にも共通の決まりの短い文（1,200字まで）を添え、渡す情報は全体で10,000字以内。"""
    text = vt.start_context(company.start_raw("startup"))
    assert len(common_rules.TEXT) <= common_rules.MAX_CHARS == 1200
    assert common_rules.TEXT.rstrip() in text
    assert text.index(status_view.BRIEF_HEAD) < text.index("## hojokin：どの段階にも共通の決まり")
    assert len(text) <= 10000
    # どの開き方でも渡す（compact の後は、前の情報が文脈から消えるため）
    for source in ("resume", "clear", "compact"):
        again = vt.start_context(company.start_raw(source))
        assert common_rules.TEXT.rstrip() in again and status_view.BRIEF_HEAD in again, source


def test_status_page_shows_the_same_lists(company) -> None:
    """今の状態.html を作り直し、同じ分け方・同じ並びで示す。外の部品を読まない。版の履歴には入れない。"""
    company.start_raw("startup")
    page = (company.folder / PAGE).read_text(encoding="utf-8")
    assert "<title>今の状態｜" in page
    rows = page_sections(page)
    for group in deadlines.GROUPS:
        assert rows[status_view._group_title(group, 30)] == EXPECTED[group], group
    assert rows["30日より先の期限"] == LATER
    assert rows["日付がまだ出せない期限"] == UNDATED
    for outside in ("http://", "https://", "<script", "<link", "src="):
        assert outside not in page, outside
    # 案件ごとの今の段階
    assert "今の段階：申請" in page and "今の段階：交付申請（提出済み）" in page
    # 中身が同じなら書き直さない。版の履歴（.gitignore）にも入れない
    before = os.stat(company.folder / PAGE).st_mtime_ns
    company.start_raw("resume")
    assert os.stat(company.folder / PAGE).st_mtime_ns == before
    assert PAGE not in ct.changed(company.folder)
    company.say("次に進めて")
    assert all(r["書類"] != PAGE for r in company.log())
    assert PAGE not in company.tracked()


def page_sections(page: str) -> dict:
    """画面の見出し（h3）ごとの、表の行の（案件、期限の名前）。"""
    found = {}
    parts = re.split(r"<h3>(.*?)</h3>", page)
    for title, body in zip(parts[1::2], parts[2::2]):
        rows = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body):
            cells = re.findall(r"<td>(.*?)</td>", row)
            if len(cells) == 7:
                rows.append((cells[2], cells[3]))
            elif len(cells) == 4 and title == "日付がまだ出せない期限":
                rows.append((cells[0], cells[1]))
        found[title] = rows
    return found


# ---- 組み立ての道具（hook を通さずに直接） ----


def test_build_matches_the_hook_and_marks_estimates(tmp_path) -> None:
    folder = plain_folder(tmp_path)
    make_cases(folder)
    ov = deadlines.build(folder)
    assert ov.today == date(2027, 3, 1) and ov.near_days == deadlines.NEAR_DAYS == 30
    for group in deadlines.GROUPS:
        assert [(t.case, t.what) for t in ov.groups[group]] == EXPECTED[group], group
    assert [(t.case, t.what) for t in ov.later] == LATER
    assert [(t.case, t.what) for t in ov.undated] == UNDATED
    # 期限切れの後に続く作業（今日やること・近い締切・遅れている作業）は、案件をまたいで締切順
    following = [t.due.first for g in deadlines.GROUPS[1:] for t in ov.groups[g]]
    assert following == sorted(following) and len(following) == 5
    overdue = [t.due.last for t in ov.groups[deadlines.OVERDUE]]
    assert overdue == sorted(overdue) and all(d < ov.today for d in overdue)
    near = {t.what: t for t in ov.groups[deadlines.NEAR] if t.case == CASE_A}
    assert near["交付申請の期限"].due.estimate is True  # 採択発表の予定から出した
    assert near["実績報告の期限"].due.bound is True  # 完了の日が分からないので「遅くとも」
    assert "決算の月が分かってから" in ov.undated[0].due.label()
    case_c = next(c for c in ov.cases if c.name == CASE_C)
    assert case_c.current == "交付申請" and case_c.submitted
    assert [r.state for r in case_c.stages] == ["済み", "済み", "これから", "これから"]


def test_documents_found_in_ledger_or_attachments_are_not_listed(tmp_path) -> None:
    """書類の台帳にある種類と、添付する書類にある書類は「見当たらない」に数えない。"""
    folder = plain_folder(tmp_path)
    make_cases(folder)
    _write_json(folder / "記録" / "書類の台帳.json", {"説明": "試し", "確かめ済み": [], "原本": [
        {"id": "原本-0001", "場所": "原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf", "種類": "履歴事項全部証明書"}]})
    ov = deadlines.build(folder)
    task = next(t for t in ov.groups[deadlines.OVERDUE] if t.case == CASE_A)
    assert any("見当たらないもの 1件（納税証明書（その2））" in n for n in task.notes), task.notes
    attach = folder / "案件" / CASE_A / "1_申請" / "添付する書類" / "納税証明書（その2）.pdf"
    attach.write_bytes(b"%PDF-1.4 test")
    ov = deadlines.build(folder)
    task = next(t for t in ov.groups[deadlines.OVERDUE] if t.case == CASE_A)
    assert not any("見当たらない" in n for n in task.notes), task.notes
    states = {d.name: d.state for d in next(c for c in ov.cases if c.name == CASE_A).documents}
    assert states == {"履歴事項全部証明書": "台帳にあり", "納税証明書（その2）": "添付する書類にあり",
                      "事業計画書（その1）": "様式で作る（申請書）"}


def test_near_window_edges() -> None:
    """近い締切は、今日から30日以内。今日は「今日やること」、過ぎたものは「期限切れ」、31日からは入らない。"""
    today = date(2027, 3, 1)

    def task(day: int, what: str) -> deadlines.Task:
        d = date.fromordinal(today.toordinal() + day)
        return deadlines.Task(case="案件", order=1, stage="段階", what=what, due=deadlines.Due(first=d, last=d))

    tasks = [task(31, "31日"), task(30, "30日"), task(1, "1日"), task(0, "0日"), task(-1, "-1日")]
    groups, later, undated = deadlines.classify(tasks, today)
    assert [t.what for t in groups[deadlines.OVERDUE]] == ["-1日"]
    assert [t.what for t in groups[deadlines.TODAY]] == ["0日"]
    assert [t.what for t in groups[deadlines.NEAR]] == ["1日", "30日"]
    assert [t.what for t in later] == ["31日"] and undated == []


def test_ten_day_span_is_near_from_its_first_day_and_overdue_after_its_last_day() -> None:
    """日が決まっていない「下旬」は、はじめの日で近いかを決め、終わりの日を過ぎてから期限切れにする。"""
    first, last, label = deadlines.month_span("2027-02", "下旬")
    assert (first, last, label) == (date(2027, 2, 21), date(2027, 2, 28), "2027年2月下旬")
    due = deadlines.Due(first=first, last=last, span=label, estimate=True)
    t = deadlines.Task(case="案件", order=1, stage="申請", what="申請の期限", due=due)
    for today, group in ((date(2027, 2, 1), deadlines.NEAR), (date(2027, 2, 25), deadlines.NEAR),
                         (date(2027, 2, 28), deadlines.NEAR), (date(2027, 3, 1), deadlines.OVERDUE)):
        groups, _later, _undated = deadlines.classify([t], today)
        assert groups[group] == [t], today
    assert due.days_text(date(2027, 2, 25)) == "今がその時期です"
    assert due.label() == "2027年2月下旬（日はまだ決まっていません）（見込み）"


def test_tasks_with_start_dates_go_to_today_or_late() -> None:
    """始める日（K1・K2 の期限の台帳が持つ）を過ぎて済んでいない作業は「遅れている作業」、今日なら「今日やること」。"""
    today = date(2027, 3, 1)
    due = deadlines.Due(first=date(2027, 4, 30), last=date(2027, 4, 30))
    late = deadlines.Task(case="案件", order=1, stage="申請", what="依頼", due=due, start=date(2027, 2, 20))
    now = deadlines.Task(case="案件", order=1, stage="申請", what="取得", due=due, start=today)
    groups, later, _undated = deadlines.classify([late, now], today)
    assert groups[deadlines.LATE] == [late] and groups[deadlines.TODAY] == [now] and later == []


def test_months_are_added_to_the_same_day_or_the_month_end() -> None:
    assert deadlines.add_period(date(2027, 4, 16), {"数": 2, "単位": "か月"}) == date(2027, 6, 16)
    assert deadlines.add_period(date(2027, 1, 31), {"数": 1, "単位": "か月"}) == date(2027, 2, 28)
    assert deadlines.add_period(date(2028, 1, 31), {"数": 1, "単位": "か月"}) == date(2028, 2, 29)
    assert deadlines.add_period(date(2027, 6, 25), {"数": 17, "単位": "か月"}) == date(2028, 11, 25)
    assert deadlines.add_period(date(2028, 2, 29), {"数": 1, "単位": "年"}) == date(2029, 2, 28)
    assert deadlines.add_period(date(2027, 3, 1), {"数": 30, "単位": "日"}) == date(2027, 3, 31)
    assert deadlines.add_period(date(2027, 3, 1), {"数": 1, "単位": "週"}) is None


# ---- 案件がないとき・組み立てられないとき ----


def test_folder_without_cases_gets_rules_and_no_page(tmp_path) -> None:
    folder = plain_folder(tmp_path)
    out = status_view.session_start(folder, None)
    text = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "案件はまだありません" in text and common_rules.TEXT.rstrip() in text
    assert not (folder / PAGE).exists()


def test_broken_settings_still_pass_the_rules(tmp_path) -> None:
    """今日の日付の差し替えが読めなくても、決まりの文は渡し、わけを添える（hook を落とさない）。"""
    folder = plain_folder(tmp_path)
    (folder / ".hojokin" / "設定.json").write_text("{壊れた", encoding="utf-8")
    text = status_view.session_start(folder, None)["hookSpecificOutput"]["additionalContext"]
    assert "期限と作業を組み立てられませんでした" in text
    assert common_rules.TEXT.rstrip() in text


def test_case_without_seido_data_is_told(tmp_path) -> None:
    folder = plain_folder(tmp_path)
    set_today(folder)
    (folder / "案件" / "2027_試し補助（一般型）第9回" / "公式資料").mkdir(parents=True)
    text = status_view.session_start(folder, None)["hookSpecificOutput"]["additionalContext"]
    assert "### 組み立てられなかったもの" in text
    assert "2027_試し補助（一般型）第9回：制度データを読めないため" in text
    assert (folder / PAGE).is_file()


def test_page_is_not_written_through_a_link(tmp_path) -> None:
    """今の状態.html が別名（シンボリックリンク）なら、別名の先（会社のフォルダの外）に書かない。"""
    folder = plain_folder(tmp_path)
    make_cases(folder)
    outside = tmp_path / "外の画面.html"
    outside.write_text("外", encoding="utf-8")
    os.symlink(str(outside), str(folder / PAGE))
    text = status_view.session_start(folder, None)["hookSpecificOutput"]["additionalContext"]
    assert outside.read_text(encoding="utf-8") == "外"
    assert "別名（シンボリックリンク）" in text and "今の状態.html を作り直していません" in text


def test_submissions_through_a_link_are_not_read(tmp_path) -> None:
    """提出版の一覧が別名なら、別名の先（会社のフォルダの外）を読まない（済んだ段階にしない）。"""
    folder = plain_folder(tmp_path)
    make_cases(folder)
    outside = tmp_path / "外の提出版.json"
    _write_json(outside, {"提出版": [{"案件": CASE_A, "段階": "1_申請", "日時": "2027-02-20T10:00:00+09:00",
                                      "版": "0" * 40, "番号": 1, "ファイル": []}]})
    (folder / "記録" / "提出版.json").unlink()
    os.symlink(str(outside), str(folder / "記録" / "提出版.json"))
    ov = deadlines.build(folder)
    assert (CASE_A, "申請の期限") in [(t.case, t.what) for t in ov.groups[deadlines.OVERDUE]]
    assert any("別名（シンボリックリンク）のため、提出版の一覧" in p for p in ov.problems), ov.problems


def test_long_other_notes_are_cut_to_keep_the_rules(tmp_path) -> None:
    """ほかの処理の情報が長くても、全体を10,000字以内にし、期限と決まりの文は削らない。"""
    folder = plain_folder(tmp_path)
    make_cases(folder)
    long_note = "長い知らせ。" * 3000
    out = status_view.session_start(folder, {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                                     "additionalContext": long_note}})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert len(text) <= status_view.MAX_CONTEXT
    assert "10,000字を超えるため、ここで切りました" in text
    assert common_rules.TEXT.rstrip() in text
    assert_expected_order(text)
