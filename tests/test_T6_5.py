"""T6-5 取り直しの時期（SPEC F6「書類の取り直しの時期」、DESIGN 4.5・6章。TASKS K1）。

合格ライン（SPEC T6-5）：「発行から3か月以内」の証明書と、決算日をまたぐ日付で作ると、締切に間に合う取得の期間が、
いちばん早い日と遅い日で示される。決算日を過ぎると、期の入れ替わりが示される。

材料（どれも架空。D2a・D13）
- 履歴事項全部証明書（testdata/デモの会社/書類/。発行 2026-10-22）
- 納税証明書（その2）の2通（testdata/期限/材料/納税証明書/。決算日の前の 2027-03-10 と、申告の後の 2027-06-07）
- 期待する値：testdata/期限/正解.json の「決算日をまたぐ書類（T6-5）」（決算の月は3月。回答表 A-10）
制度データは、このファイルの中の小さな架空のもの（取得の決まりと期数の欄だけを持つ）。
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from conftest import REPO_ROOT
from lib import deadlines, status_view

CASE = "2026_試し補助（一般型）第9回"
ANSWER = json.loads((REPO_ROOT / "testdata" / "期限" / "正解.json").read_text(encoding="utf-8"))["決算日をまたぐ書類（T6-5）"]
TOUKI = REPO_ROOT / "testdata" / "デモの会社" / "書類" / "履歴事項全部証明書.pdf"
TAX_DIR = REPO_ROOT / "testdata" / "期限" / "材料" / "納税証明書"
TAX_MARCH = TAX_DIR / "納税証明書_その2_2027年3月.pdf"
TAX_JUNE = TAX_DIR / "納税証明書_その2_2027年6月.pdf"
TOUKI_NAME = "履歴事項全部証明書"
TAX_NAME = "納税証明書（その2）"


def _sv(value, page=27):
    return {"値": value, "出典": [{"資料": "要領", "ページ": page}], "根拠の文": "（テスト用の値。資料の文は写していない）",
            "状態": "確認済み"}


def seido(deadline: str, touki_rule: dict) -> dict:
    return {
        "スキーマの版": 1,
        "制度": {"名前": "試し補助金", "枠": "一般型", "種類": "補助金", "公募回": "第9回"},
        "決まった期日": [],
        "書類": [
            dict({"名前": TOUKI_NAME, "区分": "必須", "発行元": "役所", "手続き": ["申請"], "内容": _sv("法人")}, **touki_rule),
            {"名前": TAX_NAME, "区分": "必須", "発行元": "役所", "手続き": ["申請"], "期数": _sv(3), "内容": _sv("直近3期分")},
            {"名前": "会社案内", "区分": "任意", "発行元": "自社", "手続き": ["申請"], "期数": _sv(1), "内容": _sv("任意")},
        ],
        "手続きの段階": [
            {"id": "申請", "順番": 1, "名前": "申請", "フォルダ": "1_申請",
             "期限": _sv({"種類": "決まった日付", "日時": deadline}, 4)},
            {"id": "交付申請", "順番": 2, "名前": "交付申請", "フォルダ": "2_交付申請",
             "期限": _sv({"種類": "出来事からの期間", "出来事": "採択発表", "期間": {"数": 2, "単位": "か月"}}, 8)},
        ],
    }


PERIOD_RULE = {"取得の決まり": _sv({"数": 3, "単位": "か月"})}  # スキーマの「取得の決まり」（期間の形）
TEXT_RULE = {"有効期限": _sv("応募申請日に発行から3か月以内")}  # 取得の決まりがなく、有効期限の文だけのとき（正解 第8回の形）


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


def make_folder(tmp_path: Path, today: str, deadline: str, touki_rule: dict = PERIOD_RULE,
                closing: str = "3月") -> Path:
    folder = tmp_path / "試しの会社"
    (folder / ".hojokin").mkdir(parents=True, exist_ok=True)
    _write_json(folder / ".hojokin" / "設定.json", {"今日の日付": today})
    listed = {"案件": CASE, "制度": {"名前": "試し補助金", "略称": "試し補助", "枠": "一般型", "種類": "補助金", "公募回": "第9回"},
              "案件の回": "第9回", "資料": [{"id": "要領", "名前": "公募要領", "公募回": "第9回"}]}
    _write_json(folder / "記録" / "資料の本文" / CASE / "資料の一覧.json", listed)
    _write_json(folder / "記録" / "制度データ" / "試し補助_第9回.json", seido(deadline, touki_rule))
    for sub in ("申請書", "添付する書類"):
        (folder / "案件" / CASE / "1_申請" / sub).mkdir(parents=True, exist_ok=True)
    facts = []
    if closing:
        facts.append({"id": "事実-0001", "種類": "事実", "名前": "決算の月", "値": closing, "変わりうる": False,
                      "出典": {"種類": "社長の発言", "発言": "決算は3月です", "日付": "2026-11-05"},
                      "覚えた日": "2026-11-05", "最後に確かめた日": "2026-11-05", "状態": "有効"})
    _write_json(folder / "記録" / "会社の記録.json", {"スキーマの版": 1, "項目": facts})
    _write_json(folder / "記録" / "書類の台帳.json", {"説明": "試し", "確かめ済み": [], "原本": []})
    return folder


def add_original(folder: Path, src: Path, kind: str, day: str, area: str) -> str:
    """原本を置き、書類の台帳に1件足す（書類を整理する道具が残すのと同じ欄：種類・日付・場所）。"""
    rel = f"原本/{area}/{day}_{kind}.pdf"
    (folder / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, folder / rel)
    path = folder / "記録" / "書類の台帳.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    number = len(ledger["原本"]) + 1
    ledger["原本"].append({"id": f"原本-{number:04d}", "場所": rel, "区分": area, "種類": kind, "日付": day})
    _write_json(path, ledger)
    return rel


def reacquire(ov: deadlines.Overview, name: str = TOUKI_NAME) -> deadlines.Task:
    found = [t for c in ov.cases for t in c.tasks if t.kind == deadlines.REACQUIRE and t.doc == name]
    assert len(found) == 1, [(t.kind, t.what) for c in ov.cases for t in c.tasks]
    return found[0]


def case_notes(ov: deadlines.Overview) -> str:
    (case,) = ov.cases
    return "\n".join(case.notes)


# ---- 取得の期間（いちばん早い日と遅い日） ----


@pytest.mark.parametrize("rule", [PERIOD_RULE, TEXT_RULE], ids=["取得の決まり", "有効期限の文"])
def test_window_for_three_month_certificate(tmp_path, rule) -> None:
    """「発行から3か月以内」の証明書の、締切に間に合う取得の期間を、いちばん早い日と遅い日で示す。"""
    want = ANSWER["履歴事項全部証明書"]["例"]
    folder = make_folder(tmp_path, "2026-11-16", want["応募申請日"] + "T17:00+09:00", rule)
    ov = deadlines.build(folder)
    task = reacquire(ov)
    period = want["取得の期間"]
    assert task.due.first == date.fromisoformat(period["いちばん早い日"]) == date(2026, 9, 25)
    assert task.due.last == date.fromisoformat(period["いちばん遅い日"]) == date(2026, 12, 25)
    label = "取る期間 2026年9月25日（金）〜2026年12月25日（金）"
    assert task.due.label() == label
    assert task.due.days_text(ov.today) == "今が取る期間です（あと39日）"
    assert not task.done and "まだこの書類の原本がありません" in "。".join(task.notes)
    # 開いたときの文にも、同じ期間が並ぶ（今が取る期間なので、近い締切に入る）
    near = [t for t in ov.groups[deadlines.NEAR] if t.kind == deadlines.REACQUIRE]
    assert near == [task]
    text = status_view.deadline_text(ov)
    assert f"{label}（今が取る期間です（あと39日））｜{CASE}｜{TOUKI_NAME}を取る（申請に出す）" in text
    # 画面にも並ぶ
    page = status_view.render_page(ov, "試しの会社")
    assert label in page and f"{TOUKI_NAME}を取る（申請に出す）" in page
    # 期数のある任意の書類（会社案内）は、取り直しにも期の入れ替わりにも入れない
    assert "会社案内" not in text


def test_certificate_inside_the_window_is_done(tmp_path) -> None:
    """D2a の証明書（発行 2026-10-22）は期間の内なので、済んだものに並ぶ。期間より前の日付なら取り直しを促す。"""
    want = ANSWER["履歴事項全部証明書"]["例"]["D2a の証明書"]
    folder = make_folder(tmp_path, "2026-11-16", "2026-12-25T17:00+09:00")
    add_original(folder, TOUKI, TOUKI_NAME, want["発行日"], "登記・名簿")
    ov = deadlines.build(folder)
    task = reacquire(ov)
    assert want["期間の内か"] is True and task.done
    assert task in ov.done and all(task not in g for g in ov.groups.values())
    assert "今ある原本（2026年10月22日（木）の日付。" in "。".join(task.notes)
    assert "取る期間の内の原本がある書類）が1件" in status_view.deadline_text(ov)

    old = make_folder(tmp_path / "前", "2026-11-16", "2026-12-25T17:00+09:00")
    add_original(old, TOUKI, TOUKI_NAME, "2026-08-01", "登記・名簿")
    task = reacquire(deadlines.build(old))
    assert not task.done
    assert "今ある原本（2026年8月1日（土）の日付）は取る期間より前のものなので、取る期間の内に取り直します" in task.notes


def test_window_moves_with_the_deadline_estimate(tmp_path) -> None:
    """締切が見込み（出来事の日付がまだ）なら、取る期間も見込み。締切の日付が出せなければ、取る期間も出さない。"""
    folder = make_folder(tmp_path, "2026-11-16", "2026-12-25T17:00+09:00")
    data = seido("2026-12-25T17:00+09:00", PERIOD_RULE)
    data["書類"][0]["手続き"] = ["交付申請"]
    data["決まった期日"] = [{"名前": "第9回 採択発表日", "日時": _sv({"日時": "2027-04-16"}), "注記": "予定"}]
    _write_json(folder / "記録" / "制度データ" / "試し補助_第9回.json", data)
    task = reacquire(deadlines.build(folder))
    assert (task.due.first, task.due.last) == (date(2027, 3, 16), date(2027, 6, 16))
    assert task.due.estimate and task.due.label().endswith("（見込み）")
    data["決まった期日"] = []
    _write_json(folder / "記録" / "制度データ" / "試し補助_第9回.json", data)
    ov = deadlines.build(folder)
    assert not [t for c in ov.cases for t in c.tasks if t.kind == deadlines.REACQUIRE]


# ---- 決算日をまたぐとき（期の入れ替わり） ----


def test_period_switch_is_shown_after_the_closing_day(tmp_path) -> None:
    """決算日（2027-03-31）の前に取った納税証明書は、決算日を過ぎると期の入れ替わりが示される。"""
    example = {e["応募申請日"]: e for e in ANSWER["納税証明書（その2）"]["例"]}["2027-06-14"]
    closing = ANSWER["第19期"]["決算日"]
    assert closing == "2027-03-31"
    march = ANSWER["納税証明書（その2）"]["材料"][0]
    assert march["発行日"] == "2027-03-10"

    # 決算日の前（2027-03-20）：まだ過ぎていない。締切までに決算日を迎えることだけを知らせる
    before = make_folder(tmp_path / "前", "2027-03-20", example["応募申請日"])
    add_original(before, TAX_MARCH, TAX_NAME, march["発行日"], "決算・税")
    notes = case_notes(deadlines.build(before))
    assert "決算日（2027年3月31日（水））を過ぎました" not in notes
    assert "申請の締切（2027年6月14日（月））までに決算日（2027年3月31日（水））を迎えます" in notes
    assert "期の入れ替わり" in notes and "申告の前に取った納税証明書（その2）は使えなくなります" in notes

    # 決算日の後（2027-04-05）：期の入れ替わりが示され、3月に取った証明書は直近の期に足りなくなると知らせる
    after = make_folder(tmp_path / "後", "2027-04-05", example["応募申請日"])
    add_original(after, TAX_MARCH, TAX_NAME, march["発行日"], "決算・税")
    ov = deadlines.build(after)
    notes = case_notes(ov)
    assert "決算日（2027年3月31日（水））を過ぎました。この決算の申告をした後は、直近の期が入れ替わります（期の入れ替わり）" in notes
    assert "納税証明書（その2）は申告の後に取ったもので出してください" in notes
    assert "今ある原本の 納税証明書（その2）（2027年3月10日（水）の日付） は決算日より前に取ったもの" in notes
    # 開いたときの文の「書類について」に出る（申請の締切は30日より先でも、知らせは並ぶ）
    text = status_view.deadline_text(ov)
    assert "### 書類について" in text and "を過ぎました。この決算の申告をした後は" in text


def test_period_switch_after_new_certificate_and_without_closing_month(tmp_path) -> None:
    """申告の後に取り直した証明書（2027-06-07）があれば、取り直しを促さず、直近の期が入っているかを確かめるよう伝える。
    決算の月が会社の記録になければ、確かめていないことを知らせる（推測で決めない）。"""
    june = ANSWER["納税証明書（その2）"]["材料"][1]
    folder = make_folder(tmp_path, "2027-06-08", "2027-06-14")
    add_original(folder, TAX_MARCH, TAX_NAME, "2027-03-10", "決算・税")
    add_original(folder, TAX_JUNE, TAX_NAME, june["発行日"], "決算・税")
    notes = case_notes(deadlines.build(folder))
    assert "を過ぎました" not in notes
    assert "今ある原本の 納税証明書（その2）（2027年6月7日（月）の日付） は、決算日（2027年3月31日（水））の後に取ったもの" in notes

    unknown = make_folder(tmp_path / "決算の月なし", "2027-04-05", "2027-06-14", closing="")
    notes = case_notes(deadlines.build(unknown))
    assert "決算の月が会社の記録にないため、決算日をまたぐときの期の入れ替わり（納税証明書（その2））は確かめていません" in notes


def test_submission_before_tax_filing_keeps_the_march_certificate_usable(tmp_path) -> None:
    """応募申請日が申告の前（2027-05-14）でも、決算日を過ぎたことは知らせる（申告をしたかで直近の期が変わるため）。"""
    example = {e["応募申請日"]: e for e in ANSWER["納税証明書（その2）"]["例"]}["2027-05-14"]
    assert example["使う証明書"].endswith("2027年3月.pdf")
    folder = make_folder(tmp_path, "2027-04-05", example["応募申請日"])
    add_original(folder, TAX_MARCH, TAX_NAME, "2027-03-10", "決算・税")
    notes = case_notes(deadlines.build(folder))
    assert "申請の締切（2027年5月14日（金））までに申告をするなら" in notes
