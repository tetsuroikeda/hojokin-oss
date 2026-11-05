"""T6-4 見込みと確定（SPEC F6「見込みと確定」、DESIGN 4.5・4.7・6章。TASKS K1）。

合格ライン（SPEC T6-4）：採択発表の予定だけがある状態で期限を作り、架空の採択の通知（F14）を入れて作り直すと、
初めは交付申請の期限が「見込み」で示され、通知の日付から計算し直した期限が「確定」で示される。

材料
- 制度データ：省力化 第8回の正解（testdata/正解/省力化_第8回.json）の手続きの段階と書類に、第9回の締切（仮）と
  採択発表の予定（2027年4月中旬。予定）を「決まった期日」として足したもの。第9回の採択発表の予定は公表されていないので、
  D13 の仮の採択発表日（2027-04-16）を含む旬に置いた（K1 で決めた。testdata/期限/正解.json の「見込みのとき」）。
- 通知：testdata/期限/材料/通知/ の採択の通知と交付決定通知書（D13。架空）。
- 期待する日付：testdata/期限/正解.json の「期限」（省力化（一般型）第9回）。

通知の原本から日付を読むのは Claude、社長に確かめてから「確定」にするのは採択後の切り替えの道具（DESIGN 6章・4.7）。
このテストでは、Claude の読み取りの代わりに PDF の文字から日付を拾って正解と照らし、社長が「その日付でよい」と答えた後に
道具（lib/stage_switch.switch。skills/junbi/scripts/stage_switch.py と同じ関数）へ渡す。
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
from conftest import REPO_ROOT
from lib import deadlines, doc_text, event_ledger, stage_switch, status_view

CASE = "2026_省力化（一般型）第9回"
MATERIAL = REPO_ROOT / "testdata" / "期限"
NOTICES = MATERIAL / "材料" / "通知"
ADOPTION_PDF = "省力化_第9回_採択の通知.pdf"
DECISION_PDF = "省力化_第9回_交付決定通知書.pdf"
ANSWER = json.loads((MATERIAL / "正解.json").read_text(encoding="utf-8"))
EXPECTED = {e["名前"]: e for e in ANSWER["期限"]["省力化（一般型）第9回"]}
NOTICE_DATES = {n["ファイル"]: n["日付"] for n in ANSWER["通知"]}
KOFU = "交付申請の期限"
JISSHI = "補助事業の実施（契約・納品・検収・支払い）の期限"  # 正解の段階の名前のまま


def _sv(value, note=None):
    node = {"値": value, "出典": [{"資料": "スケジュール"}], "根拠の文": "（テスト用の値。資料の文は写していない）",
            "状態": "確認済み"}
    if note:
        node["注記"] = note
    return node


def seido_9() -> dict:
    """第8回の正解に、第9回の締切（仮）と採択発表の予定を足した制度データ。"""
    data = json.loads((REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json").read_text(encoding="utf-8"))
    data["決まった期日"] = list(data.get("決まった期日") or []) + [
        {"名前": "第9回 締切", "日時": _sv({"日時": "2026-12-25T17:00+09:00"}), "注記": "予定"},
        {"名前": "第9回 採択発表", "日時": _sv({"年月": "2027-04", "旬": "中旬"}), "注記": "予定"},
    ]
    return data


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


def set_settings(folder: Path, **values) -> None:
    path = folder / ".hojokin" / "設定.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update(values)
    _write_json(path, data)


@pytest.fixture
def folder(tmp_path) -> Path:
    """申請を出した後（1_申請 に提出版がある）の第9回の案件。近い締切は60日（採択発表の後の交付申請が入るように）。"""
    folder = tmp_path / "試しの会社"
    (folder / ".hojokin").mkdir(parents=True)
    set_settings(folder, 今日の日付="2027-04-12", 近い締切の日数=60)
    listed = {"案件": CASE, "制度": {"名前": "中小企業省力化投資補助金", "略称": "省力化", "枠": "一般型", "種類": "補助金",
                                   "公募回": "第9回"},
              "案件の回": "第9回", "資料": [{"id": "要領8", "名前": "公募要領", "公募回": "第8回"}]}
    _write_json(folder / "記録" / "資料の本文" / CASE / "資料の一覧.json", listed)
    _write_json(folder / "記録" / "制度データ" / "省力化_第8回.json", seido_9())
    for sub in ("申請書", "添付する書類"):
        (folder / "案件" / CASE / "1_申請" / sub).mkdir(parents=True, exist_ok=True)
    _write_json(folder / "記録" / "提出版.json", {"提出版": [
        {"案件": CASE, "段階": "1_申請", "日時": "2026-12-20T10:00:00+09:00", "版": "0" * 40, "番号": 1, "ファイル": []}]})
    return folder


def task_of(ov: deadlines.Overview, what: str) -> deadlines.Task:
    found = [t for c in ov.cases for t in c.tasks if t.case == CASE and t.what == what]
    assert len(found) == 1, [t.what for c in ov.cases for t in c.tasks]
    return found[0]


def brief_line(text: str, what: str) -> str:
    (line,) = [x for x in text.splitlines() if f"｜{CASE}｜{what}" in x]
    return line


def read_notice_date(pdf: Path) -> str:
    """通知の PDF の文字から、日付（2027年4月16日 の形）を拾う（Claude の読み取りの代わり）。"""
    text = "".join(doc_text.pdf_pages(pdf))
    found = re.findall(r"(20[0-9]{2})年\s*([0-9]{1,2})月\s*([0-9]{1,2})日", text)
    assert found, "通知に日付がありません"
    y, m, d = found[0]
    return date(int(y), int(m), int(d)).isoformat()


def put_notice(folder: Path, pdf_name: str, day: str) -> str:
    rel = f"原本/役所からの通知/{day}_{pdf_name.split('_', 2)[2]}"
    (folder / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(NOTICES / pdf_name, folder / rel)
    return rel


def test_estimate_before_the_notice_then_confirmed_from_its_date(folder) -> None:
    # 1. 採択発表の予定（2027年4月中旬）だけがある：交付申請の期限は、予定から出した「見込み」
    ov = deadlines.build(folder)
    kofu = task_of(ov, KOFU)
    assert kofu.due.estimate is True and kofu.due.confirmed is False
    assert (kofu.due.first, kofu.due.last) == (date(2027, 6, 11), date(2027, 6, 20))
    assert kofu.due.state_word == "見込み"
    assert "（見込み）" in kofu.due.label() and "（確定）" not in kofu.due.label()
    text = status_view.deadline_text(ov)
    assert "（見込み）" in brief_line(text, KOFU)
    page = status_view.render_page(ov, "試しの会社")
    assert re.search(rf"<td>{re.escape(CASE)}</td><td>{KOFU}</td><td>見込み</td>", page)
    # 補助事業の実施の期限（交付決定から17か月と採択発表から19か月の早いほう）も、まだ見込み
    assert task_of(ov, JISSHI).due.estimate is True

    # 2. 採択の通知が届いた。日付を読み、社長に確かめて、道具が期限の台帳の出来事を「確定」にする
    day = read_notice_date(NOTICES / ADOPTION_PDF)
    assert day == NOTICE_DATES[f"通知/{ADOPTION_PDF}"] == "2027-04-16"
    set_settings(folder, 今日の日付="2027-04-19")
    rel = put_notice(folder, ADOPTION_PDF, day)
    out = stage_switch.switch(folder, CASE, events=[f"採択発表={day}"], source=rel)
    assert out.target_folder == "2_交付申請"
    ledger = event_ledger.load(folder)
    assert ledger["出来事"] == [{"案件": CASE, "名前": "採択発表", "日付": "2027-04-16", "状態": "確定", "出典": rel,
                                "記録した日": "2027-04-19"}]

    # 3. 作り直すと、通知の日付から計算し直した交付申請の期限が「確定」で示される
    ov = deadlines.build(folder)
    kofu = task_of(ov, KOFU)
    want = EXPECTED[KOFU]
    assert kofu.due.first == kofu.due.last == date.fromisoformat(want["日付"]) == date(2027, 6, 16)
    assert kofu.due.estimate is False and kofu.due.confirmed is True and kofu.due.state_word == "確定"
    assert kofu.due.label() == "2027年6月16日（水）（確定）"
    assert any("採択発表 2027年4月16日（金）（確定。出典：" + rel in b for b in kofu.due.basis), kofu.due.basis
    text = status_view.deadline_text(ov)
    line = brief_line(text, KOFU)
    assert "2027年6月16日（水）（確定）（あと58日）" in line and "見込み" not in line.split("｜")[0]
    page = status_view.render_page(ov, "試しの会社")
    assert re.search(rf"<td>{re.escape(CASE)}</td><td>{KOFU}</td><td>確定</td>", page)
    # 交付決定はまだなので、補助事業の実施は「遅くとも」採択発表から19か月（上限だけ確定）
    jisshi = task_of(ov, JISSHI)
    assert jisshi.due.bound is True and jisshi.due.first == date(2028, 11, 16)
    # 正解では、実施の期間が「資料で食い違い」（交付申請の手引き6 は第6回版）なので【要確認】が付く
    assert jisshi.due.label() == "【要確認】遅くとも 2028年11月16日（木）（確定）"


def test_decision_notice_confirms_the_completion_deadline(folder) -> None:
    """交付決定通知書の日付を入れると、補助事業の完了期限が、2つの式の早いほう（採択発表から19か月）の確定になる。"""
    set_settings(folder, 今日の日付="2027-04-19")
    adoption = read_notice_date(NOTICES / ADOPTION_PDF)
    stage_switch.switch(folder, CASE, events=[f"採択発表={adoption}"], source=put_notice(folder, ADOPTION_PDF, adoption))
    set_settings(folder, 今日の日付="2027-06-28")
    decision = read_notice_date(NOTICES / DECISION_PDF)
    assert decision == NOTICE_DATES[f"通知/{DECISION_PDF}"] == "2027-06-25"
    rel = put_notice(folder, DECISION_PDF, decision)
    stage_switch.switch(folder, CASE, stage="2_交付申請", events=[f"交付決定={decision}"], source=rel)
    ov = deadlines.build(folder)
    want = EXPECTED["補助事業の完了期限（補助事業完了期限日）"]
    jisshi = task_of(ov, JISSHI)
    assert jisshi.due.first == jisshi.due.last == date.fromisoformat(want["日付"])
    assert jisshi.due.bound is False and jisshi.due.confirmed is True
    assert jisshi.due.label() == "【要確認】2028年11月16日（木）（確定）"
    names = {e["名前"]: e["状態"] for e in event_ledger.load(folder)["出来事"]}
    assert names == {"採択発表": "確定", "交付決定": "確定"}


def test_ledger_estimate_is_not_shown_as_confirmed(folder) -> None:
    """台帳の出来事が「見込み」なら、そこから出した期限も見込み（確定と示さない）。"""
    event_ledger.write(folder, {"出来事": [{"案件": CASE, "名前": "採択発表", "日付": "2027-04-16", "状態": "見込み",
                                           "出典": "社長の答え", "記録した日": "2027-04-12"}]})
    kofu = task_of(deadlines.build(folder), KOFU)
    assert kofu.due.first == date(2027, 6, 16)
    assert kofu.due.estimate is True and kofu.due.confirmed is False
    assert kofu.due.label().endswith("（見込み）")
