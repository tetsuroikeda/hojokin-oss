"""前の版に戻す道具（TASKS M0b。SPEC 共通の要件「書類の版の管理」、DESIGN 10章「戻すときは、戻したこと自体を
新しい記録として残す。履歴は書き換えない」）。社長の言葉で動かす振る舞い（T0-9）は B8 の eval で確かめる。

- 戻すと、作業のファイル（1つのまま）が前の版の中身になり、戻したことが新しい版（「ツール」、理由に「…の版に戻した」）
  として残る。前の版はどれも消えない（戻す前の版も取り出せる）。
- 戻す前にまだ版になっていない変更があれば、先に版に残す。
- 原本・公式資料・審査役の結果・設定は戻さない。
- 消した書類も、消す前の版に戻せる。
"""

from __future__ import annotations

import hashlib

import company_tool as ct
import pytest
import version_tool as vt
from test_T0_6 import SONO1, blob, edit_three_times, refused, run_tool, working_files


@pytest.fixture
def company(tmp_path) -> vt.Company:
    return vt.Company(tmp_path)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_revert_restores_previous_version_and_records_it(company) -> None:
    edit_three_times(company)
    files = set(working_files(company.folder))
    company.say("1つ前に戻して")
    out = ct.ok(run_tool(company, "revert", "--document", SONO1, "--back", "1", "--reason", "1つ前に戻して"))
    assert "戻しました" in out
    assert (company.folder / SONO1).read_bytes() == blob("docx", 2)
    assert company.stop() is None
    # ファイルは1つのまま。戻したことが新しい版として残り、前の版は消えない
    assert set(working_files(company.folder)) == files
    records = company.log(SONO1)
    assert len(records) == 4
    latest = records[0]
    assert (latest["だれ"], latest["変更"]) == ("ツール", "変えた")
    assert latest["理由"].startswith("1つ前に戻して（") and latest["理由"].endswith("の版に戻した）")
    assert [r["理由"] for r in records[1:]] == [
        "審査の観点で効果の段を直して、見積書の写しも作り直して", "社長が手で変更",
        "計画書のその1と入力シートを作り、見積書の写しと財務モデルも用意して",
    ]
    # 戻す前の版（3版目）も取り出せる
    ct.ok(run_tool(company, "show", "--document", SONO1, "--version", records[1]["版"]))
    assert list((company.folder / "見るだけ").iterdir())[0].read_bytes() == blob("docx", 3)


def test_pending_changes_are_recorded_before_revert(company) -> None:
    """まだ版になっていない変更（同じ応答の中でツールが直した分）は、先に版に残してから戻す。"""
    edit_three_times(company)
    company.say("やはり社長が直した版に戻して")
    company.write(SONO1, blob("docx", 7))
    second = company.log(SONO1)[1]
    ct.ok(run_tool(company, "revert", "--document", SONO1, "--version", second["版"][:8],
                   "--reason", "やはり社長が直した版に戻して"))
    assert (company.folder / SONO1).read_bytes() == blob("docx", 2)
    records = company.log(SONO1)
    assert [r["理由"] for r in records[:2]] == [
        records[0]["理由"], "やはり社長が直した版に戻して",
    ]
    assert "の版に戻した" in records[0]["理由"]
    assert company.pending() == []


def test_revert_to_same_content_changes_nothing(company) -> None:
    edit_three_times(company)
    count = len(company.versions())
    out = ct.ok(run_tool(company, "revert", "--document", SONO1, "--back", "0"))
    assert "何も変えていません" in out
    assert len(company.versions()) == count


def test_revert_deleted_document(company) -> None:
    """消した書類も、消す前の版に戻せる（書き戻すと、その名前のファイルが1つに戻る）。"""
    edit_three_times(company)
    company.say("その1を消して")
    (company.folder / SONO1).unlink()
    assert company.stop() is None
    assert company.log(SONO1)[0]["変更"] == "消した"
    out = refused(run_tool(company, "show", "--document", SONO1, "--back", "0"))
    assert "消されています" in out
    ct.ok(run_tool(company, "revert", "--document", SONO1, "--back", "1", "--reason", "やはり戻して"))
    assert (company.folder / SONO1).read_bytes() == blob("docx", 3)
    assert company.log(SONO1)[0]["変更"] == "足した"


def test_originals_and_settings_are_not_reverted(company) -> None:
    """原本・公式資料・設定は戻さない（原本と公式資料は入れたときの1版だけを守る。DESIGN 5章）。"""
    original = "原本/見積・契約・請求/2026-10-20_見積書_〇〇機械.pdf"
    official = f"{vt.CASE_DIR}/公式資料/公募要領.pdf"
    company.say("見積書を整理して")
    company.write(original, blob("pdf", 1))
    company.write(official, blob("pdf", 2))
    assert company.stop() is None
    company.write(".hojokin/設定.json", '{"今日の日付": "2027-03-01"}\n')
    company.say("日付を進めた")
    for document in (original, official, ".hojokin/設定.json"):
        out = refused(run_tool(company, "revert", "--document", document, "--back", "1"))
        assert "戻せません" in out, document
    assert (company.folder / original).read_bytes() == blob("pdf", 1)
