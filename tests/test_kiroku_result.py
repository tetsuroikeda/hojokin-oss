"""過去の申請と採否、受けた指摘を会社の記録に残す（TASKS B6、SPEC F13「最初に会社の資料と過去の書類から学ぶ」、DESIGN 10章）。

- kiroku の記録の道具の add-result で、不採択の通知と、不採択の後の相談で受けた指摘のメモを出典にして、
  申請と採否（案件・結果・指摘された審査項目・受けた指摘・通知の日・覚えた日）を残す。形はスキーマに合う。
- 同じ案件・同じ結果は2回足さない。不採択で指摘も審査項目もないものは断る（記録は変えない）。
- 書く前の取り出し（relevant_records.py）の「前の申請で受けた指摘」に出る（次の申請書で応える記述を入れるため）。
"""

from __future__ import annotations

from pathlib import Path

import company_tool as ct
from test_kiroku_min import RECORD, RELEVANT, company, record, refused, run  # noqa: F401（company は fixture）

NOTICE = "原本/役所からの通知/2025-10-28_採択結果の通知.pdf"
CASE = "2025_ものづくり補助金 20次締切"
COMMENT = "1. 効果の根拠を工程ごとに示す 2. ミスを防ぐ仕組みを書く 3. 浮いた人手の使い道を書く"


def put_notice(c) -> None:
    path = c.folder / NOTICE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 test")


def add(c, *extra: str):
    return run(c, RECORD, "add-result", "--case", CASE, "--result", "不採択", "--notice-date", "2025-10-28",
               "--source", "原本", "--file", NOTICE, *extra)


def test_a_rejection_and_its_feedback_are_kept(company) -> None:  # noqa: F811
    put_notice(company)
    out = ct.ok(add(company, "--pointed", "計画面", "--pointed", "技術面", "--comment", COMMENT))
    assert "覚えました" in out and "採否-0001" in out
    items = [it for it in record(company)["項目"] if it["種類"] == "申請と採否"]
    assert len(items) == 1
    item = items[0]
    assert item["結果"] == "不採択" and item["指摘された審査項目"] == ["計画面", "技術面"]
    assert item["審査コメント"] == COMMENT and item["通知の日"] == "2025-10-28"
    assert item["出典"] == {"種類": "原本", "ファイル": NOTICE} and item["覚えた日"]
    assert "もう覚えています" in ct.ok(add(company, "--comment", "別の書き方"))
    assert len([it for it in record(company)["項目"] if it["種類"] == "申請と採否"]) == 1
    shown = ct.ok(run(company, RELEVANT, "--item", "計画"))
    assert "前の申請で受けた指摘" in shown and "効果の根拠" in shown


def test_a_rejection_without_any_feedback_is_refused(company) -> None:  # noqa: F811
    put_notice(company)
    out = refused(add(company))
    assert "--comment" in out
    assert not (company.folder / "記録" / "会社の記録.json").exists() or \
        not [it for it in record(company)["項目"] if it["種類"] == "申請と採否"]
    assert "外" in refused(run(company, RECORD, "add-result", "--case", CASE, "--result", "不採択", "--comment", "x",
                               "--notice-date", "2025-10-28", "--source", "原本", "--file", str(Path("/tmp") / "x.pdf")))
