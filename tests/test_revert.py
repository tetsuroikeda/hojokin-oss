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
import os
from pathlib import Path

import company_tool as ct
import pytest
import version_tool as vt
from test_T0_6 import (COPY, RECORD, SONO1, blob, edit_three_times, refused, run_tool, submissions, submit,
                       working_files)


@pytest.fixture(params=vt.FORMS)
def company(request, tmp_path) -> vt.Company:
    """Git の形と、版のファイルの形（同期されるフォルダの形。TASKS M0c）の両方。"""
    return vt.Company(tmp_path, form=request.param)


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


def test_submission_record_is_not_reverted(company) -> None:
    """提出版の記録（記録/提出版.json）は戻さない。戻すと、記録した提出版が消えるため。
    壊れたときだけ、直すために戻せる。"""
    edit_three_times(company)
    submit(company)
    company.say("差し戻しに合わせて、写しを作り直して")
    company.write(COPY, blob("pdf", 9))
    assert company.stop() is None
    submit(company, "直して出し直しました")
    count = len(company.versions())
    # 提出の直後に「1つ前に戻して」と言われ、提出版の記録の版を戻そうとしても、戻さない
    company.say("1つ前に戻して")
    for args in (("--document", "提出版.json", "--back", "1"), ("--document", RECORD, "--back", "2")):
        out = refused(run_tool(company, "revert", *args, "--reason", "1つ前に戻して"))
        assert "戻せません" in out and "show-submitted" in out
    assert company.stop() is None
    assert len(company.versions()) == count
    assert [e["番号"] for e in submissions(company)] == [1, 2]
    ct.ok(run_tool(company, "show-submitted", "--number", "2"))

    # 手で書き換えて壊れたときは、直すために前の版に戻せる
    record = company.folder / RECORD
    good = record.read_bytes()
    company.write(RECORD, "{ 壊れた")
    company.say("提出版の一覧を手で直そうとしたら壊れました")
    assert company.log(RECORD)[0]["だれ"] == "社長"
    out = refused(run_tool(company, "show-submitted"))
    assert "JSON として読めません" in out
    ct.ok(run_tool(company, "revert", "--document", RECORD, "--back", "1", "--reason", "壊れる前に戻して"))
    assert record.read_bytes() == good
    assert [e["番号"] for e in submissions(company)] == [1, 2]
    ct.ok(run_tool(company, "show-submitted", "--number", "2"))


# ---- 別名を通って、会社のフォルダの外を書き換えない（DESIGN 5章「会社のフォルダの外に書かない」） ----


def tree(folder: Path) -> dict:
    """フォルダの中のすべて（場所 → 中身。フォルダと別名は None）。別名はたどらない。"""
    found = {}
    for dirpath, dirnames, filenames in os.walk(str(folder)):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            found[str(path.relative_to(folder))] = None if path.is_dir() or path.is_symlink() else path.read_bytes()
    return found


@pytest.mark.slow
@pytest.mark.parametrize("where", ["申請書", "案件のフォルダ", "書類そのもの"])
def test_revert_does_not_write_through_a_link(company, where) -> None:
    """申請書/ や 案件/<案件>/（か、書類そのもの）が外を指す別名なら、戻さずに断る。外のファイルは変わらず、版も増えない。"""
    edit_three_times(company)
    first = company.log(SONO1)[-1]["版"]
    outside = company.env.folder("外のフォルダ")
    if where == "書類そのもの":
        target = outside / "その1.docx"
        target.write_bytes(blob("docx", 3))
        (company.folder / SONO1).unlink()
        (company.folder / SONO1).symlink_to(target)
        link = SONO1
    else:
        link = vt.APPLICATION if where == "申請書" else vt.CASE_DIR
        place = company.folder / link
        moved = outside / "移した中身"
        place.rename(moved)
        place.symlink_to(moved, target_is_directory=True)
    company.say("申請書のフォルダを置き換えました")
    assert company.stop() is None
    count = len(company.versions())
    outside_before = tree(outside)
    assert blob("docx", 3) in outside_before.values()
    company.say("最初の版に戻して")
    out = refused(run_tool(company, "revert", "--document", SONO1, "--version", first, "--reason", "最初の版に戻して"))
    assert "戻せません" in out and "別名" in out and link in out, out
    assert "戻しました" not in out
    # 外のファイルは書き換わらず（最初の版の中身はどこにも書かれない）、版も増えない
    assert tree(outside) == outside_before
    assert blob("docx", 1) not in tree(outside).values()
    assert company.stop() is None
    assert len(company.versions()) == count
    assert (company.folder / link).is_symlink()
