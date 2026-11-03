"""T0-6 版の管理（TASKS M0b。SPEC 共通の要件「書類の版の管理」、DESIGN 4.5・8.3・10章）。

SPEC：申請書を3回直し、「提出した」と伝える。
合格ライン：書類ごとにファイルは1つ。履歴3件に日時・書類・理由・だれが付く。
            提出版を取り出すと提出時と同じ中身（写しを含む）。

- 直したときの版は、hook（hooks.json のコマンド）が Claude Code と同じ入力で残す（M0a。tests/version_tool.py）。
- 「提出した」と伝えられたら、Claude が kiroku の道具（skills/kiroku/scripts/versions.py の submit）を、
  Bash で動かすのと同じ形（/usr/bin/python3 -B、CLAUDE_* の環境変数なし、PATH は python3 と sh だけ）で動かす。
- 提出版に入るのは、段階のフォルダ（申請書/ と 添付する書類/）のすべてと、財務モデル.xlsx（DESIGN 8.3）。
- 取り出すと、`見るだけ/` に読み取り専用で出る。作業のファイルは増えも変わりもしない。次に開いたときに片付く。
- 前の版も、同じく `見るだけ/` に出せる。

中身は、Word・Excel・PDF の形に見立てた、文字でないバイトを含む中身にする（1バイトでも違えば分かるように）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt

SCRIPT = Path("skills") / "kiroku" / "scripts" / "versions.py"
JST = timezone(timedelta(hours=9))
STAGE_DIR = f"{vt.CASE_DIR}/{vt.STAGE}"
SONO1 = f"{vt.APPLICATION}/その1.docx"
INPUT = f"{vt.APPLICATION}/入力シート.xlsx"
COPY = f"{STAGE_DIR}/添付する書類/見積書_写し.pdf"
FINANCE = "財務モデル.xlsx"
RECORD = "記録/提出版.json"
OWNER_REASON = "社長が手で変更"
SUBMIT_WORDS = "申請を提出しました"
VIEW = "見るだけ"


def blob(kind: str, n: int) -> bytes:
    """n 版目の中身（文字でないバイト、改行の形の違い、0 を含む）。"""
    heads = {"docx": b"PK\x03\x04", "xlsx": b"PK\x03\x04\x14\x00", "pdf": b"%PDF-1.7\r\n"}
    return heads[kind] + f"{kind} の {n} 版目".encode("utf-8") + b"\r\n\x00\xff\xfe" + bytes([n]) * 64


@pytest.fixture
def company(tmp_path) -> vt.Company:
    return vt.Company(tmp_path)


def run_tool(company: vt.Company, command: str, *args: str, folder: Path = None) -> subprocess.CompletedProcess:
    """kiroku の版の道具を、Claude が Bash で動かすのと同じ形で動かす。"""
    env = {"PATH": company.env.path, "HOME": str(company.env.home), "TMPDIR": str(company.env.tmp)}
    return subprocess.run(
        [hr.real_python(), "-B", str(company.env.plugin / SCRIPT), command,
         "--folder", str(folder or company.folder), *args],
        env=env, cwd=company.env.cwd, capture_output=True, timeout=120,
    )


def refused(r: subprocess.CompletedProcess) -> str:
    out = r.stdout.decode("utf-8")
    assert r.returncode == 2, (r.returncode, out, r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    return out


def working_files(folder: Path) -> dict:
    """作業のファイル（会社のフォルダからの場所 → 中身）。版の履歴とその場限りの置き場は除く。"""
    found = {}
    for path in folder.rglob("*"):
        rel = path.relative_to(folder).as_posix()
        if rel.startswith((".git/", ".hojokin/一時/")) or not path.is_file():
            continue
        found[rel] = path.read_bytes()
    return found


def submission_set(folder: Path) -> dict:
    """提出版に入るはずのもの（段階のフォルダのすべてと、財務モデル.xlsx）の今の中身。"""
    return {p: data for p, data in working_files(folder).items() if p.startswith(STAGE_DIR + "/") or p == FINANCE}


def view_files(folder: Path) -> dict:
    """見るだけ/ の中のファイル（見るだけ/ からの場所 → 中身）。"""
    base = folder / VIEW
    return {p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob("*") if p.is_file()}


def assert_read_only(folder: Path) -> None:
    base = folder / VIEW
    paths = [base] + list(base.rglob("*"))
    assert len(paths) > 1
    for p in paths:
        assert stat.S_IMODE(p.stat().st_mode) & 0o222 == 0, (p, oct(p.stat().st_mode))


def assert_jst_now(record: dict) -> None:
    when = datetime.fromisoformat(record["日時"])
    assert when.utcoffset() == timedelta(hours=9), record
    assert abs(datetime.now(JST) - when) < timedelta(minutes=10), record


def submissions(company: vt.Company) -> list:
    return json.loads((company.folder / RECORD).read_text(encoding="utf-8"))["提出版"]


def tags(company: vt.Company) -> dict:
    code = ("from dulwich.repo import Repo\n"
            "repo = Repo(sys.argv[1])\n"
            "print(json.dumps({'refs/tags/' + k.decode('utf-8'): v.decode('ascii') "
            "for k, v in repo.refs.as_dict(b'refs/tags').items()}, ensure_ascii=False))")
    return ct.py_json(code, str(company.folder))


def edit_three_times(company: vt.Company) -> None:
    """申請書を3回直す（ツール → 社長が手で → ツール）。写しと財務モデルも用意する。"""
    company.say("計画書のその1と入力シートを作り、見積書の写しと財務モデルも用意して")
    company.write(SONO1, blob("docx", 1))
    company.write(INPUT, blob("xlsx", 1))
    company.write(COPY, blob("pdf", 1))
    company.write(FINANCE, blob("xlsx", 101))
    assert company.stop() is None
    company.write(SONO1, blob("docx", 2))
    company.say("その1を手で直しました。確かめてください")
    assert company.stop() is None
    company.say("審査の観点で効果の段を直して、見積書の写しも作り直して")
    company.write(SONO1, blob("docx", 3))
    company.write(COPY, blob("pdf", 2))
    assert company.stop() is None


def submit(company: vt.Company, words: str = SUBMIT_WORDS, *args: str) -> str:
    company.say(words)
    out = ct.ok(run_tool(company, "submit", "--case", vt.CASE, "--stage", vt.STAGE, "--reason", words, *args))
    assert company.stop() is None
    return out


def from_view(view: dict) -> dict:
    """見るだけ/ に出した提出版（1つのフォルダ）を、会社のフォルダからの場所に読み替える。"""
    dirs = {p.split("/", 1)[0] for p in view}
    assert len(dirs) == 1, dirs
    (top,) = dirs
    assert top.startswith("提出版 "), top
    found = {}
    for p, data in view.items():
        rel = p.split("/", 1)[1]
        found[rel if rel == FINANCE else f"{STAGE_DIR}/{rel}"] = data
    return found


# ---- T0-6 の合格ライン ----

def test_T0_6_three_edits_then_submitted_version(company) -> None:
    before = set(working_files(company.folder))
    edit_three_times(company)

    # 「提出した」と伝える
    at_submit = submission_set(company.folder)
    assert set(at_submit) == {SONO1, INPUT, COPY, FINANCE}
    out = submit(company)
    assert "提出版を記録しました" in out
    for path in at_submit:
        assert f"- {path}" in out

    # 書類ごとにファイルは1つ（別の版のファイルが増えていない）
    assert set(working_files(company.folder)) == before | {SONO1, INPUT, COPY, FINANCE, RECORD}
    assert sorted(p.name for p in (company.folder / vt.APPLICATION).iterdir()) == ["その1.docx", "入力シート.xlsx"]
    assert sorted(p.name for p in (company.folder / STAGE_DIR / "添付する書類").iterdir()) == ["見積書_写し.pdf"]

    # 履歴3件に日時・書類・理由・だれが付く（提出しても、その1の履歴は増えない）
    records = company.log(SONO1)
    assert [(r["だれ"], r["理由"], r["変更"]) for r in records] == [
        ("ツール", "審査の観点で効果の段を直して、見積書の写しも作り直して", "変えた"),
        ("社長", OWNER_REASON, "変えた"),
        ("ツール", "計画書のその1と入力シートを作り、見積書の写しと財務モデルも用意して", "足した"),
    ]
    for r in records:
        assert r["書類"] == SONO1
        assert (r["案件"], r["段階"]) == (vt.CASE, vt.STAGE)
        assert_jst_now(r)
    assert [r["日時"] for r in records] == sorted((r["日時"] for r in records), reverse=True)

    # 社長に見せる履歴（道具の出力）にも、3件それぞれの日時・書類・理由・だれが出る
    shown = ct.ok(run_tool(company, "log", "--document", SONO1))
    assert f"{SONO1} の版の履歴（新しい順、3件）" in shown
    lines = [line for line in shown.splitlines() if re.match(r"^[0-9]+\. ", line)]
    assert len(lines) == 3
    for line, r in zip(lines, records):
        when = datetime.fromisoformat(r["日時"])
        assert f"{when.year}年{when.month}月{when.day}日" in line and f"{when.hour}:{when.minute:02d}" in line
        assert f"　{r['だれ']}　" in line and f"理由：{r['理由']}" in line and r["版"][:10] in line

    # 提出版の記録：提出したときの版と、写しを含むファイルごとの中身の印
    (entry,) = submissions(company)
    assert (entry["番号"], entry["案件"], entry["段階"], entry["発言"]) == (1, vt.CASE, vt.STAGE, SUBMIT_WORDS)
    assert re.fullmatch(r"[0-9a-f]{40}", entry["版"])
    assert_jst_now(entry)
    assert {f["書類"]: f["sha256"] for f in entry["ファイル"]} == {
        p: hashlib.sha256(data).hexdigest() for p, data in at_submit.items()
    }
    assert {f["書類"]: f["大きさ"] for f in entry["ファイル"]} == {p: len(d) for p, d in at_submit.items()}
    # Git の印（タグ）が、提出したときの版を指す
    assert tags(company).get(entry["印"]) == entry["版"]
    assert entry["印"].startswith("refs/tags/提出版/")

    # 提出の後も直す（差し戻しへの対応など）。今の中身は提出したときと違う
    company.say("差し戻しに合わせて、その1と写しと財務モデルを直して")
    company.write(SONO1, blob("docx", 4))
    company.write(COPY, blob("pdf", 3))
    company.write(FINANCE, blob("xlsx", 102))
    assert company.stop() is None
    current = working_files(company.folder)
    for path in (SONO1, COPY, FINANCE):
        assert current[path] != at_submit[path]
    versions = len(company.versions())

    # 提出版を取り出すと、提出時と同じ中身（写しと財務モデルを含む。過不足なし）
    company.say("提出したときの申請書を見せて")
    out = ct.ok(run_tool(company, "show-submitted", "--case", vt.CASE, "--stage", vt.STAGE))
    assert "提出したときと同じ中身" in out
    view = view_files(company.folder)
    assert from_view(view) == at_submit
    for p in view:
        assert f"- {VIEW}/{p}" in out
    assert_read_only(company.folder)
    # 作業のファイルは増えも変わりもしない。見るだけ/ は版の履歴に入らない
    assert {p: d for p, d in working_files(company.folder).items() if not p.startswith(VIEW + "/")} == current
    assert company.stop() is None
    assert len(company.versions()) == versions
    assert not [p for p in company.tracked() if p.startswith(VIEW + "/")]

    # 次に開いたときに片付く。片付けた後も、もう一度同じ中身を取り出せる
    company.start()
    assert not (company.folder / VIEW).exists()
    ct.ok(run_tool(company, "show-submitted"))
    assert from_view(view_files(company.folder)) == at_submit
    assert_read_only(company.folder)


# ---- 提出版のそのほかの形 ----

def test_changes_made_in_the_same_response_go_into_the_submitted_version(company) -> None:
    """提出の直前にツールが直した分（まだ版になっていない）も、先に版に残してから提出版に入れる。"""
    edit_three_times(company)
    words = "誤字を直してから出しました"
    company.say(words)
    company.write(SONO1, blob("docx", 5))
    ct.ok(run_tool(company, "submit", "--case", vt.CASE, "--stage", vt.STAGE, "--reason", words))
    (entry,) = submissions(company)
    sha = {f["書類"]: f["sha256"] for f in entry["ファイル"]}
    assert sha[SONO1] == hashlib.sha256(blob("docx", 5)).hexdigest()
    latest = company.log(SONO1)[0]
    assert (latest["だれ"], latest["理由"], latest["版"]) == ("ツール", words, entry["版"])
    # 提出版の記録も、版に残る（記録した版は、提出版の版の次）
    (rec,) = company.log(RECORD)
    assert (rec["だれ"], rec["変更"]) == ("ツール", "足した") and "提出版 1回目を記録" in rec["理由"]
    assert company.pending() == []
    assert company.stop() is None


def test_resubmission_keeps_both_submitted_versions(company) -> None:
    """出し直すと2回目として足す。番号を省けば最新を、番号を付ければその回を取り出せる。"""
    edit_three_times(company)
    first = submission_set(company.folder)
    submit(company)
    company.say("差し戻しに合わせて、写しを作り直して")
    company.write(COPY, blob("pdf", 9))
    assert company.stop() is None
    second = submission_set(company.folder)
    out = submit(company, "直して出し直しました")
    assert "2回目" in out
    assert [e["番号"] for e in submissions(company)] == [1, 2]
    assert len({e["印"] for e in submissions(company)}) == 2

    ct.ok(run_tool(company, "show-submitted"))
    assert from_view(view_files(company.folder)) == second
    company.start()
    ct.ok(run_tool(company, "show-submitted", "--number", "1"))
    assert from_view(view_files(company.folder)) == first

    listed = ct.ok(run_tool(company, "submissions"))
    assert "1回目" in listed and "2回目" in listed and vt.CASE in listed


def test_submitted_time_follows_substituted_today(company) -> None:
    """今日の日付を差し替えていれば、提出版の日時もその日付にする（日本時間）。"""
    company.write(".hojokin/設定.json", '{"今日の日付": "2027-03-01"}\n')
    edit_three_times(company)
    submit(company)
    (entry,) = submissions(company)
    assert entry["日時"].startswith("2027-03-01T") and entry["日時"].endswith("+09:00")
    ct.ok(run_tool(company, "show-submitted"))
    (top,) = {p.split("/", 1)[0] for p in view_files(company.folder)}
    assert "2027年3月1日" in top


def test_submit_refuses_without_documents_or_with_unknown_case(company) -> None:
    """段階のフォルダに書類がないとき、案件・段階が見つからないときは、提出版を記録しない。"""
    (company.folder / vt.APPLICATION).mkdir(parents=True)
    company.write(FINANCE, blob("xlsx", 1))
    company.say("出しました")
    out = refused(run_tool(company, "submit", "--case", vt.CASE, "--stage", vt.STAGE))
    assert "書類がない" in out
    out = refused(run_tool(company, "submit", "--case", "2026_持続化（一般型）第20回", "--stage", vt.STAGE))
    assert vt.CASE in out  # 選べる案件を挙げる
    out = refused(run_tool(company, "submit", "--case", vt.CASE, "--stage", "2_交付申請"))
    assert vt.STAGE in out
    assert not (company.folder / RECORD).exists()
    assert tags(company) == {}
    out = refused(run_tool(company, "show-submitted"))
    assert "提出版がありません" in out


# ---- 版の履歴に残せないものがあるときは、提出版を記録しない ----

EXTRA_DIR = f"{STAGE_DIR}/添付する書類/追加の写し"
EXTRA_COPY = f"{EXTRA_DIR}/納税証明書_写し.pdf"
needs_permissions = pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                                       reason="管理者では、権限を外しても読めてしまう")


def submit_refused(company: vt.Company, words: str = SUBMIT_WORDS) -> str:
    return refused(run_tool(company, "submit", "--case", vt.CASE, "--stage", vt.STAGE, "--reason", words))


def assert_not_recorded(company: vt.Company, out: str, where: str, why: str) -> None:
    """断った出力に場所とわけが出て、提出版の記録も Git の印も残っていない。"""
    assert "提出版を記録していません" in out, out
    assert f"- {where}（{why}）" in out, out
    assert not (company.folder / RECORD).exists()
    assert tags(company) == {}
    out = refused(run_tool(company, "show-submitted"))
    assert "提出版がありません" in out


@needs_permissions
def test_submit_refuses_when_a_folder_in_the_stage_cannot_be_read(company) -> None:
    """段階のフォルダの中に読めないフォルダがあれば、中の写しが黙って抜けないように、提出版を記録しない。
    読めるようにしてから記録し直すと、その写しも入り、取り出すと提出時と同じ中身になる。"""
    edit_three_times(company)
    company.say(SUBMIT_WORDS)
    company.write(EXTRA_COPY, blob("pdf", 7))
    locked_dir = company.folder / EXTRA_DIR
    os.chmod(str(locked_dir), 0)
    try:
        out = submit_refused(company)
    finally:
        os.chmod(str(locked_dir), 0o755)
    assert_not_recorded(company, out, EXTRA_DIR + "/", "中を読めないフォルダ")

    at_submit = submission_set(company.folder)
    assert set(at_submit) == {SONO1, INPUT, COPY, FINANCE, EXTRA_COPY}
    out = submit(company, "読めるようにしたので、もう一度記録して")
    assert f"- {EXTRA_COPY}" in out and "（5件。" in out
    (entry,) = submissions(company)
    assert {f["書類"]: f["sha256"] for f in entry["ファイル"]} == {
        p: hashlib.sha256(data).hexdigest() for p, data in at_submit.items()
    }
    ct.ok(run_tool(company, "show-submitted"))
    assert from_view(view_files(company.folder)) == at_submit


@needs_permissions
def test_submit_refuses_when_a_copy_cannot_be_read(company) -> None:
    """読めない写しがあれば、提出版を記録しない。"""
    edit_three_times(company)
    company.say(SUBMIT_WORDS)
    path = company.write(EXTRA_COPY, blob("pdf", 7))
    os.chmod(str(path), 0)
    try:
        out = submit_refused(company)
    finally:
        os.chmod(str(path), 0o644)
    assert_not_recorded(company, out, EXTRA_COPY, "読めない")


def test_submit_refuses_when_a_copy_is_left_out_by_gitignore(company) -> None:
    """.gitignore に当たる写し・財務モデルは版の履歴に入らないので、黙って抜けないように、提出版を記録しない。"""
    company.say("申請書を作り、写しも用意して")
    company.write(SONO1, blob("docx", 1))
    company.write(COPY, blob("pdf", 1))
    gitignore = company.folder / ".gitignore"
    gitignore.write_text(gitignore.read_text(encoding="utf-8") + "納税証明書*\n/財務モデル.xlsx\n", encoding="utf-8")
    company.write(EXTRA_COPY, blob("pdf", 7))
    company.write(FINANCE, blob("xlsx", 101))
    assert company.stop() is None
    assert EXTRA_COPY not in company.tracked() and FINANCE not in company.tracked()
    out = submit_refused(company)
    assert_not_recorded(company, out, EXTRA_COPY, "版の履歴に入っていない（.gitignore で除かれているなど）")
    assert f"- {FINANCE}（版の履歴に入っていない" in out


def test_temporary_files_do_not_block_submission(company) -> None:
    """Word・Excel が開いている間だけ作るファイルや .DS_Store は、書類でないので、残っていても断らない。
    提出版にも入れない。"""
    edit_three_times(company)
    at_submit = submission_set(company.folder)
    company.write(f"{vt.APPLICATION}/~$その1.docx", b"\x00lock")
    company.write(f"{vt.APPLICATION}/.~lock.入力シート.xlsx#", "lock")
    company.write(f"{STAGE_DIR}/添付する書類/.DS_Store", b"\x00\x00\x00\x01Bud1")
    out = submit(company)
    assert "（4件。" in out
    (entry,) = submissions(company)
    assert {f["書類"] for f in entry["ファイル"]} == set(at_submit)
    ct.ok(run_tool(company, "show-submitted"))
    assert from_view(view_files(company.folder)) == at_submit


def test_tool_does_nothing_outside_company_folder(company) -> None:
    """会社のフォルダでないフォルダでは、どの道具も何もしない（T0-13 の道具の部分）。"""
    plain = company.env.folder("ふつうのフォルダ")
    (plain / "メモ.txt").write_text("会社のフォルダではない", encoding="utf-8")
    before = hr.snapshot(plain, company.env.home, company.env.tmp, company.env.cwd)
    for command, args in (("log", []), ("show", ["--document", "メモ.txt"]), ("submissions", []),
                          ("submit", ["--case", vt.CASE, "--stage", vt.STAGE]), ("show-submitted", []),
                          ("revert", ["--document", "メモ.txt"])):
        out = refused(run_tool(company, command, *args, folder=plain))
        assert "会社のフォルダではありません" in out
    assert hr.snapshot(plain, company.env.home, company.env.tmp, company.env.cwd) == before


# ---- 前の版を見るだけ/ に出す ----

def test_previous_version_goes_to_view_only_folder(company) -> None:
    """前の版を、作業のファイルを増やさずに、見るだけ/ に読み取り専用で出す。版の名前の確かめにも当たらない。"""
    edit_three_times(company)
    versions = len(company.versions())
    before = working_files(company.folder)
    company.say("その1の前の版を見せて")
    out = ct.ok(run_tool(company, "show", "--document", "その1.docx"))  # 名前だけでも、1つに決まればよい
    (name,) = view_files(company.folder)
    assert re.fullmatch(r"その1（[0-9]{4}年[0-9]+月[0-9]+日 [0-9]+時[0-9]{2}分の版）\.docx", name), name
    assert view_files(company.folder)[name] == blob("docx", 2)
    assert f"{VIEW}/{name}" in out and "社長" in out
    assert_read_only(company.folder)
    # 版の印でも選べる。2つ前（1版目）
    first = company.log(SONO1)[2]
    ct.ok(run_tool(company, "show", "--document", SONO1, "--version", first["版"][:10]))
    assert sorted(view_files(company.folder).values()) == sorted([blob("docx", 2), blob("docx", 1)])
    # 作業のファイルと履歴は変わらない（見るだけ/ の名前は、版の名前のファイルとして伝えない）
    assert company.stop() is None
    assert {p: d for p, d in working_files(company.folder).items() if not p.startswith(VIEW + "/")} == before
    assert len(company.versions()) == versions
    # 同じ版をもう一度出しても、ファイルは増えない
    ct.ok(run_tool(company, "show", "--document", SONO1, "--back", "1"))
    assert len(view_files(company.folder)) == 2


def test_view_errors_are_explained(company) -> None:
    edit_three_times(company)
    out = refused(run_tool(company, "show", "--document", "ないもの.docx"))
    assert "版の履歴がありません" in out
    out = refused(run_tool(company, "show", "--document", SONO1, "--back", "3"))
    assert "3 件" in out
    out = refused(run_tool(company, "show", "--document", SONO1, "--version", "zzzz"))
    assert "版の印" in out
    assert not (company.folder / VIEW).exists()


# ---- 次に開いたときに片付ける ----

def test_cleanup_keeps_files_the_tool_did_not_put(company) -> None:
    """片付けで消すのは、ツールが出して中身が変わっていないものだけ。社長が置いたものは残して、Claude に伝える。"""
    edit_three_times(company)
    ct.ok(run_tool(company, "show", "--document", SONO1))
    view = company.folder / VIEW
    os.chmod(str(view), 0o755)
    (view / "社長のメモ.txt").write_text("大事なメモ", encoding="utf-8")
    context = vt.start_context(company.start())
    assert sorted(p.name for p in view.iterdir()) == ["社長のメモ.txt"]
    assert "社長のメモ.txt" in context and "消さずに残しました" in context
    # 残したものは、社長が動かせる（フォルダに書き込める）
    assert stat.S_IMODE(view.stat().st_mode) & 0o200


def test_view_folder_that_is_a_link_is_not_followed(company) -> None:
    """見るだけ/ が会社のフォルダの外を指す別名になっていても、外に書かず、片付けでも外を消さない。"""
    edit_three_times(company)
    outside = company.env.root / "外のフォルダ"
    outside.mkdir()
    (outside / "大事.txt").write_text("外", encoding="utf-8")
    os.symlink(str(outside), str(company.folder / VIEW))
    out = refused(run_tool(company, "show", "--document", SONO1))
    assert "フォルダでない" in out
    refused(run_tool(company, "show-submitted"))
    context = vt.start_context(company.start())
    assert VIEW in context
    assert (company.folder / VIEW).is_symlink()
    assert sorted(p.name for p in outside.iterdir()) == ["大事.txt"]


def test_cleanup_is_not_done_on_compact(company) -> None:
    """同じセッションの途中の compact では片付けない（社長が見ているものを消さない）。"""
    edit_three_times(company)
    ct.ok(run_tool(company, "show", "--document", SONO1))
    assert company.start("compact") is None
    assert len(view_files(company.folder)) == 1
    assert company.start("resume") is None
    assert not (company.folder / VIEW).exists()
