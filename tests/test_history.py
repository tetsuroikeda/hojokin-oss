"""版の記録（TASKS M0a。SPEC 共通の要件「書類の版の管理」、DESIGN 5章「版を自動で残す」、10章「書類の版」）。

- ツールが変えた分は、Stop（応答の終わり）で「ツール」として残す。理由は、その応答のもとになった社長の依頼の文。
- 社長が手で変えた分は、UserPromptSubmit（送ったとき）と SessionStart（開いたとき）で「社長」として残す。
  理由は「社長が手で変更」。
- 履歴の1件ごとに、日時・書類・理由・だれ・案件・段階が付く（書類ごとに読み返せる）。
- 書類ごとにファイルは1つのまま、前の版の中身を履歴から取り出せる。
- 履歴に入れないもの（.gitignore と、その場限りの置き場）は残さない。濁点の分かれた名前は1文字の形で残す。
- 送り先は持たないまま。利用者の Git の設定と全体の除外の指定は読まない。
- Git の形の履歴（.git）がない会社のフォルダでは、何も書かない。
- hook の見張り（開いたとき・送ったときは25秒）に止められないよう、1回の場面で使う時間に上限を設ける。
  残しきれない分は次の場面に回し、回した場面のだれ・理由で残す。大きすぎるファイルは残さず、開いたときに伝える。
- 見張りに止められて .git に錠が残っても、次の場面で片付けて残す。版を残す処理が落ちても hook は落とさず、
  「Python が動かない」の案内ではなく、版の記録が止まったことを開いたときに伝える。

hook は hooks.json のコマンドから、Claude Code と同じ入力で動かす（tests/version_tool.py）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import unicodedata
from datetime import datetime, timedelta, timezone

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt

JST = timezone(timedelta(hours=9))
SONO1 = f"{vt.APPLICATION}/その1.md"
OWNER_REASON = "社長が手で変更"
# 版を残す秒数を短くする（テストのため。長くはできない）
SHORT_BUDGET = {"HOJOKIN_RECORD_SECONDS": "1"}
# 見積もり（100MB/秒）では1秒の上限に収まらない大きさ（中身は0。読むのはすぐ終わる）
BIG_BYTES = 160 * 1024 * 1024
PYTHON_MISSING = ("補助プログラム（Python）が動かない", "xcode-select")


@pytest.fixture
def company(tmp_path) -> vt.Company:
    return vt.Company(tmp_path)


def newest(company: vt.Company, n: int = 1) -> list:
    """新しい順の履歴（書類ごと）の先頭 n 件の版にある記録。"""
    records = company.log()
    versions = []
    for r in records:
        if r["版"] not in versions:
            versions.append(r["版"])
    keep = set(versions[:n])
    return [r for r in records if r["版"] in keep]


def assert_jst_now(record: dict) -> None:
    when = datetime.fromisoformat(record["日時"])
    assert when.utcoffset() == timedelta(hours=9), record
    assert abs(datetime.now(JST) - when) < timedelta(minutes=5), record


# ---- ツールが変えた分（Stop） ----

def test_tool_changes_are_recorded_at_stop_with_the_request(company) -> None:
    """応答の中で変わったファイルを、応答の終わりに「ツール」として、依頼の文を理由にして残す。"""
    before = len(company.versions())
    assert company.say("計画書のその1を書いて") is None
    company.write(SONO1, "一版目")
    company.write("記録/会社の記録.json", "{}")
    assert company.stop() is None

    versions = company.versions()
    assert len(versions) == before + 1
    assert versions[0]["author"] == "ツール <tool@hojokin.invalid>"
    assert versions[0]["files"] == sorted([SONO1, "記録/会社の記録.json"])

    records = newest(company)
    assert {r["書類"] for r in records} == {SONO1, "記録/会社の記録.json"}
    for r in records:
        assert r["だれ"] == "ツール"
        assert r["理由"] == "計画書のその1を書いて"
        assert r["変更"] == "足した"
        assert_jst_now(r)
    by_doc = {r["書類"]: r for r in records}
    assert (by_doc[SONO1]["案件"], by_doc[SONO1]["段階"]) == (vt.CASE, vt.STAGE)
    assert (by_doc["記録/会社の記録.json"]["案件"], by_doc["記録/会社の記録.json"]["段階"]) == ("", "")
    # 版のメッセージにも、書類・理由・だれ・案件・段階が人の読める形で入る
    message = versions[0]["message"]
    for line in ("理由: 計画書のその1を書いて", "だれ: ツール", f"書類: {SONO1}", "変更: 足した",
                 f"案件: {vt.CASE}", f"段階: {vt.STAGE}", "書類: 記録/会社の記録.json", "案件: —", "段階: —"):
        assert line in message.splitlines(), (line, message)
    assert company.pending() == []


def test_stage_of_effect_report_years_and_case_level_files(company) -> None:
    """段階は「1_申請」の形のフォルダ。効果報告の年のフォルダは年まで含める。案件の直下は段階なし。"""
    company.say("効果報告の書類を用意して")
    company.write(f"案件/{vt.CASE}/4_効果報告/1年目/申請書/効果報告.md", "x")
    company.write(f"案件/{vt.CASE}/概要と流れ.md", "x")
    company.write(f"案件/{vt.CASE}/2_交付申請/添付する書類/見積書の写し.txt", "x")
    company.stop()
    by_doc = {r["書類"]: (r["案件"], r["段階"]) for r in newest(company)}
    assert by_doc == {
        f"案件/{vt.CASE}/4_効果報告/1年目/申請書/効果報告.md": (vt.CASE, "4_効果報告/1年目"),
        f"案件/{vt.CASE}/概要と流れ.md": (vt.CASE, ""),
        f"案件/{vt.CASE}/2_交付申請/添付する書類/見積書の写し.txt": (vt.CASE, "2_交付申請"),
    }


def test_reason_is_one_line_and_cut(company) -> None:
    """依頼の文は、1行にそろえ、100字で切って理由にする。"""
    prompt = "次の差し戻しの文に合わせて直して\n\n" + "経費の内訳が見積書と合っていません。" * 12
    company.say(prompt)
    company.write(SONO1, "直した")
    company.stop()
    (record,) = newest(company)
    reason = record["理由"]
    assert "\n" not in reason
    assert len(reason) == 100 and reason.endswith("…")
    assert reason.startswith("次の差し戻しの文に合わせて直して 経費の内訳が見積書と合っていません。")


def test_stop_without_a_saved_request_uses_a_fixed_reason(company) -> None:
    """依頼の文を控えられなかったとき（目印のないフォルダで始めた最初のセッションなど）は、決まった文にする。"""
    company.write(SONO1, "x")
    company.stop()
    (record,) = newest(company)
    assert record["だれ"] == "ツール"
    assert record["理由"] == "Claude の作業（依頼の文を控えられなかった）"


def test_request_is_kept_per_session(company) -> None:
    """依頼の文はセッションごとに控え、別のセッションの依頼を理由にしない。"""
    company.say("Aの依頼", session="A")
    company.say("Bの依頼", session="B")
    company.write(SONO1, "A が書いた")
    company.stop(session="A")
    (record,) = newest(company)
    assert record["理由"] == "Aの依頼"


# ---- 社長が手で変えた分（UserPromptSubmit・SessionStart） ----

def test_owner_changes_are_recorded_when_the_owner_sends(company) -> None:
    """社長が手で変えた分は、送ったときに、依頼の前に「社長」として残す（ツールの分と混ぜない）。"""
    company.say("その1を書いて")
    company.write(SONO1, "ツールが書いた")
    company.stop()
    # 社長が Word などで手で直した
    company.write(SONO1, "社長が直した")
    company.write("入れ口/見積書.pdf", b"%PDF-1.4 owner")
    company.say("次に進めて")
    records = newest(company)
    assert {r["書類"] for r in records} == {SONO1, "入れ口/見積書.pdf"}
    for r in records:
        assert r["だれ"] == "社長"
        assert r["理由"] == OWNER_REASON
        assert_jst_now(r)
    assert {r["書類"]: r["変更"] for r in records} == {SONO1: "変えた", "入れ口/見積書.pdf": "足した"}
    assert company.versions()[0]["author"] == "社長 <owner@hojokin.invalid>"
    # 応答の中で何も変えなければ、応答の終わりに版は増えない
    count = len(company.versions())
    assert company.stop() is None
    assert len(company.versions()) == count


def test_owner_changes_while_closed_are_recorded_at_session_start(company) -> None:
    """閉じている間に手で変えた分は、開いたとき（startup・resume・clear）に「社長」として残す。"""
    for source in ("startup", "resume", "clear"):
        company.write(SONO1, f"閉じている間に直した（{source}）")
        assert company.start(source) is None
        (record,) = newest(company)
        assert (record["書類"], record["だれ"], record["理由"]) == (SONO1, "社長", OWNER_REASON), source
        assert company.content(record["版"], SONO1) == f"閉じている間に直した（{source}）"


def test_compact_does_not_record(company) -> None:
    """compact で開き直したときは残さない（応答の途中のツールの分を社長の分にしないため）。次に送ったときに残る。"""
    company.write(SONO1, "x")
    count = len(company.versions())
    company.start("compact")
    assert len(company.versions()) == count
    company.say("続けて")
    (record,) = newest(company)
    assert record["だれ"] == "社長"


def test_interrupted_response_is_recorded_as_tool(company) -> None:
    """応答を途中で止めて次を送ったときは、それまでに変わった分を、前の依頼のツールの分として残す（仮）。"""
    company.say("その1を書いて")
    company.write(SONO1, "途中まで書いた")
    # 応答の終わり（Stop）が来ないまま、次の発言
    company.say("やっぱり別の書き方で")
    (record,) = newest(company)
    assert record["だれ"] == "ツール"
    assert record["理由"] == "その1を書いて（応答が途中で止まったため、次の発言のときに残した）"
    company.write(SONO1, "別の書き方")
    company.stop()
    (record,) = newest(company)
    assert (record["だれ"], record["理由"]) == ("ツール", "やっぱり別の書き方で")


def test_deleted_and_renamed_files_are_recorded(company) -> None:
    """消したファイルと名前を変えたファイルも残す。"""
    company.say("2つ書いて")
    company.write(SONO1, "その1")
    company.write(f"{vt.APPLICATION}/メモ.md", "メモ")
    company.stop()
    (company.folder / SONO1).unlink()
    (company.folder / vt.APPLICATION / "メモ.md").rename(company.folder / vt.APPLICATION / "打ち合わせのメモ.md")
    company.say("確かめて")
    changes = {r["書類"]: (r["変更"], r["だれ"]) for r in newest(company)}
    assert changes == {
        SONO1: ("消した", "社長"),
        f"{vt.APPLICATION}/メモ.md": ("消した", "社長"),
        f"{vt.APPLICATION}/打ち合わせのメモ.md": ("足した", "社長"),
    }
    assert company.pending() == []
    assert SONO1 not in company.tracked()


def test_case_only_rename_is_recorded(company) -> None:
    """大文字と小文字だけを変えた名前も、変えたこととして残す（Mac のファイルの仕組みは区別しないため）。"""
    company.write("記録/Plan.md", "x")
    company.say("確かめて")
    os.rename(company.folder / "記録" / "Plan.md", company.folder / "記録" / "plan.md")
    company.say("もう一度")
    changes = {r["書類"]: r["変更"] for r in newest(company)}
    assert changes == {"記録/Plan.md": "消した", "記録/plan.md": "足した"}
    assert "記録/plan.md" in company.tracked() and "記録/Plan.md" not in company.tracked()


def test_nothing_changed_makes_no_version(company) -> None:
    count = len(company.versions())
    company.start()
    company.say("今の状態を教えて")
    company.stop()
    company.say("ありがとう")
    company.stop()
    assert len(company.versions()) == count


def test_touch_without_change_makes_no_version(company) -> None:
    """中身が同じなら、更新時刻だけが変わっても版を増やさない。"""
    company.write(SONO1, "x")
    company.say("残して")
    count = len(company.versions())
    later = time.time() + 10
    os.utime(company.folder / SONO1, (later, later))
    company.say("もう一度")
    company.stop()
    assert len(company.versions()) == count


# ---- 版の中身（T0-6 の形。提出版は M0b） ----

def test_three_edits_give_three_records_and_contents(company) -> None:
    """同じ書類を3回直すと、書類ごとにファイルは1つのまま、履歴3件に日時・書類・理由・だれが付き、中身を取り出せる。"""
    company.say("その1を書いて")
    company.write(SONO1, "一版目（ツール）")
    company.stop()
    company.write(SONO1, "二版目（社長）")
    company.say("社長の直しを生かして、効果の段を書いて")
    company.write(SONO1, "三版目（ツール）")
    company.stop()

    records = company.log(SONO1)
    assert [(r["だれ"], r["理由"], r["変更"]) for r in records] == [
        ("ツール", "社長の直しを生かして、効果の段を書いて", "変えた"),
        ("社長", OWNER_REASON, "変えた"),
        ("ツール", "その1を書いて", "足した"),
    ]
    for r in records:
        assert r["書類"] == SONO1 and (r["案件"], r["段階"]) == (vt.CASE, vt.STAGE)
        assert_jst_now(r)
    assert [company.content(r["版"], SONO1) for r in records] == ["三版目（ツール）", "二版目（社長）", "一版目（ツール）"]
    # 書類ごとにファイルは1つ
    assert sorted(p.name for p in (company.folder / vt.APPLICATION).iterdir()) == ["その1.md"]


# ---- 履歴に入れないもの・名前の形・設定 ----

def test_ignored_and_temporary_files_are_not_recorded(company) -> None:
    """.gitignore にあるもの（見るだけ/、開いている間だけのファイル、.DS_Store）と、その場限りの置き場は残さない。"""
    company.say("見るだけに出して")
    company.write("見るだけ/その1_前の版.docx", b"old")
    company.write(f"{vt.APPLICATION}/~$その1.docx", b"lock")
    company.write(f"{vt.APPLICATION}/.DS_Store", b"x")
    company.write(".hojokin/一時/画面入力/s/許可.json", "{}")
    company.write(SONO1, "残すもの")
    company.stop()
    (record,) = newest(company)
    assert record["書類"] == SONO1
    tracked = company.tracked()
    assert not [p for p in tracked if p.startswith(("見るだけ/", ".hojokin/一時/")) or "~$" in p or ".DS_Store" in p]
    # 依頼の文の控えは、その場限りの置き場にある
    assert list((company.folder / ".hojokin" / "一時" / "版の記録").glob("*.json"))


def test_temporary_place_is_not_recorded_even_without_gitignore(company) -> None:
    """.gitignore が消えても、プラグインのその場限りの置き場（.hojokin/一時/）は残さない。"""
    (company.folder / ".gitignore").unlink()
    company.say("続けて")
    company.write(".hojokin/一時/画面入力/s/許可.json", "{}")
    company.stop()
    assert not [p for p in company.tracked() if p.startswith(".hojokin/一時/")]


def test_nfd_names_are_recorded_as_nfc(company) -> None:
    """濁点が分かれた名前（Finder などで作られる NFD）は、1文字の形（NFC）にそろえて残す。"""
    name = "データの一覧.md"
    nfd = unicodedata.normalize("NFD", name)
    assert nfd != name
    company.say("一覧を作って")
    company.write(f"{vt.APPLICATION}/{nfd}", "一版目")
    company.stop()
    (record,) = newest(company)
    assert record["書類"] == f"{vt.APPLICATION}/{name}"
    assert f"{vt.APPLICATION}/{name}" in company.tracked()
    # 作業のファイルの名前はそのまま（NFD）。直しても同じ書類として残る
    assert nfd in os.listdir(company.folder / vt.APPLICATION)
    company.write(f"{vt.APPLICATION}/{nfd}", "二版目")
    company.say("確かめて")
    (record,) = newest(company)
    assert (record["書類"], record["変更"]) == (f"{vt.APPLICATION}/{name}", "変えた")
    assert company.pending() == []
    assert [r["変更"] for r in company.log(f"{vt.APPLICATION}/{name}")] == ["変えた", "足した"]


def test_nfd_names_from_before_are_renamed_to_nfc_when_changed(tmp_path) -> None:
    """会社のフォルダにする前からあった NFD の名前は、変わったときに NFC の名前にして残す（同じ書類の「変えた」1件）。"""
    name = "ガイドブック.txt"
    nfd = unicodedata.normalize("NFD", name)

    def before(folder):
        (folder / nfd).write_text("前から", encoding="utf-8")

    company = vt.Company(tmp_path, before_init=before)
    company.write(nfd, "直した")
    company.say("確かめて")
    (record,) = newest(company)
    assert (record["書類"], record["変更"], record["だれ"]) == (name, "変えた", "社長")
    assert name in company.tracked() and nfd not in company.tracked()
    assert company.pending() == []


def test_user_git_settings_do_not_drop_documents(company) -> None:
    """利用者の全体の除外の指定（*.pdf など）と Git の設定は読まない。書類が黙って履歴から抜けない。"""
    git_config = company.env.home / ".config" / "git"
    git_config.mkdir(parents=True)
    (git_config / "ignore").write_text("*.pdf\n*.docx\n", encoding="utf-8")
    (company.env.home / ".gitconfig").write_text(
        "[core]\n\texcludesFile = ~/.config/git/ignore\n\tautocrlf = true\n[user]\n\tname = someone\n",
        encoding="utf-8")
    company.say("見積書を入れて")
    company.write("入れ口/見積書.pdf", b"%PDF-1.4\r\nx\n")
    company.write(f"{vt.APPLICATION}/その1.docx", b"PK\x03\x04 docx")
    company.stop()
    docs = {r["書類"]: r["だれ"] for r in newest(company)}
    assert docs == {"入れ口/見積書.pdf": "ツール", f"{vt.APPLICATION}/その1.docx": "ツール"}
    assert company.versions()[0]["author"] == "ツール <tool@hojokin.invalid>"


def test_dates_follow_the_substituted_today(company) -> None:
    """今日の日付を差し替えていれば、版の日時もその日付にする（日本時間）。"""
    company.write(".hojokin/設定.json", '{"今日の日付": "2027-03-01"}\n')
    company.say("交付申請に進めて")
    (record,) = newest(company)
    assert record["書類"] == ".hojokin/設定.json" and record["だれ"] == "社長"
    company.write(SONO1, "x")
    company.stop()
    (record,) = newest(company)
    when = datetime.fromisoformat(record["日時"])
    assert when.date().isoformat() == "2027-03-01"
    assert when.utcoffset() == timedelta(hours=9)


def test_remotes_stay_zero(company) -> None:
    """版を残しても、送り先は0件のまま。"""
    company.say("書いて")
    company.write(SONO1, "x")
    company.stop()
    remotes = ct.py_json("repo = history.open_or_init(__import__('pathlib').Path(sys.argv[1]))\n"
                         "print(json.dumps(history.remotes(repo)))", str(company.folder))
    assert remotes == []


def test_many_files_are_recorded_well_within_the_watch(company) -> None:
    """資料の本文のように一度に多くのファイルが増えても、Stop の見張り（55秒）より十分早く残す。"""
    company.say("公募要領を取って、ページごとの文字にして")
    for i in range(300):
        company.write(f"記録/資料の本文/{vt.CASE}/要領8/p{i:03d}.txt", f"ページ {i}\n" * 50)
    company.write(f"案件/{vt.CASE}/公式資料/公募要領_第8回.pdf", os.urandom(5 * 1024 * 1024))
    start = time.monotonic()
    company.stop()
    assert time.monotonic() - start < 15
    assert len(newest(company)) == 301
    # 変わっていなければ、読まずに済ませる（2回目は早い）
    start = time.monotonic()
    company.say("ありがとう")
    assert time.monotonic() - start < 5
    assert len(newest(company)) == 301


def test_real_git_reads_the_history(company) -> None:
    """dulwich で残した履歴を、本物の git でも壊れずに読める（手元に git があるときだけ）。"""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git がありません")
    company.say("書いて")
    company.write(SONO1, "x")
    company.write("記録/会社の記録.json", "{}")
    company.stop()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(company.env.home), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull}
    for args in (["fsck", "--no-progress"], ["status", "--porcelain"]):
        r = subprocess.run([git, *args], cwd=company.folder, env=env, capture_output=True, timeout=60)
        assert r.returncode == 0, r.stderr.decode("utf-8")
        assert r.stdout.decode("utf-8").strip() == "", (args, r.stdout.decode("utf-8"))
    r = subprocess.run([git, "-c", "core.quotepath=off", "log", "-1", "--format=%an%n%B"], cwd=company.folder,
                       env=env, capture_output=True, timeout=60)
    assert r.returncode == 0
    text = r.stdout.decode("utf-8")
    assert text.startswith("ツール\n") and f"書類: {SONO1}" in text


# ---- 見張りの中で残す（時間の上限、大きなファイル、止められた後、落ちたとき） ----

def sparse(company: vt.Company, rel: str, size: int):
    """中身が0の大きなファイル（ディスクはほとんど使わない）。"""
    path = company.folder / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)
    return path


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def dead_pid() -> int:
    """もう動いていない処理の番号。"""
    p = subprocess.Popen(["/usr/bin/true"])
    p.wait()
    return p.pid


def fsck(company: vt.Company) -> None:
    """本物の git で、履歴が壊れていないかを確かめる（手元に git があるときだけ）。"""
    git = shutil.which("git")
    if git is None:
        return
    env = {"PATH": "/usr/bin:/bin", "HOME": str(company.env.home), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull}
    r = subprocess.run([git, "fsck", "--no-progress", "--strict"], cwd=company.folder, env=env, capture_output=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8")


def test_photos_in_bulk_are_recorded_well_within_the_watch(company) -> None:
    """写真をまとめて入れたように、大きなファイルが多くても、送ったときの見張り（25秒）より十分早く残す。"""
    for i in range(50):
        company.write(f"入れ口/写真/IMG_{i:04d}.jpg", os.urandom(4 * 1024 * 1024))
    start = time.monotonic()
    assert company.say("写真を入れた") is None
    assert time.monotonic() - start < 10
    assert len(newest(company)) == 50
    assert company.pending() == []
    fsck(company)


def test_leftover_locks_of_a_stopped_hook_are_cleared(company) -> None:
    """見張りに止められた hook が .git に残した錠（版の錠、dulwich の錠、書きかけの中身）は、次の場面で片付けて残す。

    版の錠を持っていた処理がもう動いていなければ、120秒を待たずにすぐ外す。同じ中身の錠が残っていても残せる。
    """
    data = b"photo-" * 2000
    company.write("入れ口/写真/IMG_0001.jpg", data)
    git = company.folder / ".git"
    sha = blob_id(data)
    (git / "objects" / sha[:2]).mkdir(exist_ok=True)
    for path in (git / "objects" / sha[:2] / f"{sha[2:]}.lock", git / "index.lock", git / "refs" / "heads" / "master.lock",
                 git / "objects" / "hojokin-tmp-abc123"):
        path.write_bytes(b"")
    (git / "hojokin-record.lock").write_text(f"{dead_pid()}\n", encoding="ascii")
    assert len(vt.git_leftovers(company.folder)) == 5
    start = time.monotonic()
    assert company.say("写真を入れた") is None
    assert time.monotonic() - start < 4
    (record,) = newest(company)
    assert (record["書類"], record["だれ"], record["理由"]) == ("入れ口/写真/IMG_0001.jpg", "社長", OWNER_REASON)
    assert vt.git_leftovers(company.folder) == []
    output = company.start()
    assert output is None, output
    company.write(SONO1, "x")
    assert company.stop() is None
    assert newest(company)[0]["書類"] == SONO1
    fsck(company)


def test_record_recovers_after_the_watch_kills_it(company) -> None:
    """見張りが本当に止めても（kill -9）、次の場面で錠を片付け、残っていたものをすべて残す。"""
    for i in range(12000):
        company.write(f"記録/資料の本文/{vt.CASE}/要領8/p{i:05d}.txt", f"ページ {i}\n" * 20)
    context = vt.start_context(company.start(env={"HOJOKIN_WATCH_SECONDS": "1"}))
    assert "補助プログラム（Python）が時間内に終わらなかった" in context, context
    assert company.pending() != []
    start = time.monotonic()
    assert company.say("続けて") is None
    assert time.monotonic() - start < 20
    assert company.pending() == []
    assert vt.git_leftovers(company.folder) == []
    assert len([r for r in company.log() if r["書類"].startswith("記録/資料の本文/")]) == 12000
    assert company.start() is None
    fsck(company)


def test_lock_of_a_running_process_is_respected(company) -> None:
    """版の錠を持つ処理がまだ動いていれば、待って、何も書かずに次の場面に回す（何も伝えない）。古すぎる錠は外す。"""
    company.write(SONO1, "x")
    lock = company.folder / ".git" / "hojokin-record.lock"
    lock.write_text(f"{os.getpid()}\n", encoding="ascii")
    count = len(company.versions())
    assert company.say("書いて") is None
    assert len(company.versions()) == count and lock.exists()
    old = time.time() - 600
    os.utime(lock, (old, old))
    assert company.say("もう一度") is None
    (record,) = newest(company)
    assert record["書類"] == SONO1
    assert not lock.exists()


def test_owner_files_left_for_later_are_recorded_as_the_owner(company) -> None:
    """時間の上限で残しきれなかった社長のファイルは、次の場面（応答の終わり）でも「社長」として残す。"""
    sparse(company, "入れ口/動画.mp4", BIG_BYTES)
    company.write("入れ口/メモ.txt", "社長のメモ")
    assert company.say("動画を入れた", env=SHORT_BUDGET) is None
    (record,) = newest(company)
    assert (record["書類"], record["だれ"]) == ("入れ口/メモ.txt", "社長")
    assert company.pending() == [["入れ口/動画.mp4", "足した"]]
    company.write(SONO1, "ツールが書いた")
    assert company.stop() is None
    by_doc = {r["書類"]: (r["だれ"], r["理由"]) for r in newest(company, 2)}
    assert by_doc == {"入れ口/動画.mp4": ("社長", OWNER_REASON), SONO1: ("ツール", "動画を入れた")}
    assert company.pending() == []
    assert not (company.folder / ".hojokin" / "一時" / "版の記録" / "残り.json").exists()


def test_tool_files_left_for_later_keep_the_request(company) -> None:
    """応答の終わりに残しきれなかったツールのファイルは、次に送ったときに「ツール」と前の依頼で残す。
    残しきれなくても、版の名前のファイルは伝える。"""
    company.say("動画を書き出して")
    sparse(company, "記録/紹介動画_最終.mp4", BIG_BYTES)
    company.write(SONO1, "x")
    output = company.stop(env=SHORT_BUDGET)
    assert output["decision"] == "block"
    assert "記録/紹介動画_最終.mp4（「最終」）" in output["reason"]
    (record,) = newest(company)
    assert (record["書類"], record["だれ"]) == (SONO1, "ツール")
    company.write("入れ口/メモ.txt", "社長のメモ")
    company.say("ありがとう")
    by_doc = {r["書類"]: (r["だれ"], r["理由"]) for r in newest(company, 2)}
    assert by_doc == {"記録/紹介動画_最終.mp4": ("ツール", "動画を書き出して"), "入れ口/メモ.txt": ("社長", OWNER_REASON)}
    assert company.pending() == []


def test_session_start_tells_files_left_for_later(company) -> None:
    """開いたときに残しきれなかったファイルがあれば、件数を伝える。次の場面で残す。"""
    sparse(company, "入れ口/動画.mp4", BIG_BYTES)
    context = vt.start_context(company.start(env=SHORT_BUDGET))
    assert "1件はまだ版の履歴に残していません" in context, context
    assert not any(word in context for word in PYTHON_MISSING)
    assert company.start() is None
    (record,) = newest(company)
    assert (record["書類"], record["だれ"]) == ("入れ口/動画.mp4", "社長")


def test_too_large_files_are_not_recorded_and_told(company) -> None:
    """大きすぎるファイル（2GB を超えるもの）は版に残さず、開いたときに伝える。ツールの分にも、版の名前の確かめにも入れない。"""
    sparse(company, "入れ口/撮影データ_最終.mov", 2 * 1024 ** 3 + 1)
    company.write("入れ口/メモ.txt", "x")
    start = time.monotonic()
    context = vt.start_context(company.start())
    assert time.monotonic() - start < 5
    assert "大きすぎるため" in context and "入れ口/撮影データ_最終.mov" in context, context
    (record,) = newest(company)
    assert record["書類"] == "入れ口/メモ.txt"
    assert "入れ口/撮影データ_最終.mov" not in company.tracked()
    sparse(company, "記録/書き出し_v2.mov", 2 * 1024 ** 3 + 1)
    company.say("見て")
    assert company.stop() is None
    assert "記録/書き出し_v2.mov" in vt.start_context(company.start())


def test_files_cut_off_twice_are_treated_as_too_large(company) -> None:
    """時間の上限でファイルの途中までしか読めないことが2回続いたら、大きすぎるものとして伝える（遅いディスクなどで、
    毎回の場面の時間を使い切らないため）。大きさが変わったら、また試す。"""
    # 会社のフォルダを作ったときの記録（時刻）をそろえておく（小さな上限では、比べることも次に回すため）
    assert company.start() is None
    company.write("入れ口/動画.mov", b"x" * (3 * 1024 * 1024))
    code = ("from pathlib import Path\n"
            "history._fits = lambda size, deadline: True  # 見積もりでは収まり、書く途中で上限を過ぎたことにする\n"
            "r = history.record_scene(Path(sys.argv[1]), history.OWNER, history.OWNER_REASON, budget=0.000001)\n"
            "print(json.dumps([len(r.recorded), len(r.deferred), len(r.too_large)]))")
    assert ct.py_json(code, str(company.folder)) == [0, 1, 0]
    assert vt.git_leftovers(company.folder) == []
    leftovers = json.loads((company.folder / ".hojokin/一時/版の記録/残り.json").read_text(encoding="utf-8"))
    assert leftovers == {"書類": {"入れ口/動画.mov": {"だれ": "社長", "理由": OWNER_REASON, "大きさ": 3 * 1024 * 1024,
                                                    "止めた回数": 1}}}
    assert ct.py_json(code, str(company.folder)) == [0, 1, 0]
    assert ct.py_json(code, str(company.folder)) == [0, 0, 1]
    context = vt.start_context(company.start())
    assert "大きすぎるため" in context and "入れ口/動画.mov" in context
    assert company.pending() == [["入れ口/動画.mov", "足した"]]
    company.write("入れ口/動画.mov", b"y" * (3 * 1024 * 1024 + 1))
    assert company.start() is None
    (record,) = newest(company)
    assert (record["書類"], record["だれ"]) == ("入れ口/動画.mov", "社長")


def test_writing_stops_midway_at_the_deadline(company) -> None:
    """中身を書く途中で時間の上限を過ぎたら、やめて、書きかけのファイルも錠も残さない。"""
    company.write("入れ口/a.bin", b"x" * (3 * 1024 * 1024))
    code = ("import time\nfrom dulwich.repo import Repo\n"
            "repo = Repo(sys.argv[1])\n"
            "status, _st, sha = history._write_blob(repo, sys.argv[2], time.monotonic() - 1)\n"
            "print(json.dumps([status, sha.decode('ascii')], ensure_ascii=False))")
    assert ct.py_json(code, str(company.folder), str(company.folder / "入れ口" / "a.bin")) == ["時間切れ", ""]
    assert vt.git_leftovers(company.folder) == []


def test_record_failure_is_told_at_session_start_not_as_python_missing(company) -> None:
    """版を残す処理が落ちても hook は落とさず（書き込みの守りも続く）、開いたときに版の記録が止まったことを伝える。
    「Python が動かない」の案内にはしない。次に残せたら、知らせは消える。"""
    company.write(SONO1, "x")
    objects = company.folder / ".git" / "objects"
    objects.chmod(0o500)
    try:
        context = vt.start_context(company.start())
        assert "版の記録が止まっています" in context and "開いたとき" in context and "PermissionError" in context, context
        assert not any(word in context for word in PYTHON_MISSING), context
        assert company.say("書いて") is None
        company.write(f"{vt.APPLICATION}/その1_v2.md", "x")
        assert company.stop() is None
        assert company.pre("Write", {"file_path": str(company.folder / vt.APPLICATION / "その1_v3.md"),
                                     "content": "x"}) is not None
        context = vt.start_context(company.start())
        assert "版の記録が止まっています" in context and "開いたとき" in context
    finally:
        objects.chmod(0o755)
    assert company.say("直した") is None
    assert company.pending() == []
    assert company.start() is None


# ---- .git のない会社のフォルダ ----

def test_folder_without_git_is_left_untouched(tmp_path) -> None:
    """目印はあるが Git の形の履歴がないフォルダでは、何も書かない（.git を作らない）。"""
    folder = tmp_path / "試しの会社"
    (folder / ".hojokin").mkdir(parents=True)
    (folder / "計画.md").write_text("x", encoding="utf-8")
    home = tmp_path / "home"
    data = tmp_path / "plugin-data"
    home.mkdir()
    data.mkdir()
    plugin = hr.copy_plugin(tmp_path / "plugin")
    path = hr.make_bin(tmp_path / "bin", "本物", tmp_path / "python-ran")
    before = hr.snapshot(folder)
    base = {"session_id": "s", "transcript_path": str(home / "t.jsonl"), "cwd": str(folder)}
    for event, payload in (("SessionStart", {"source": "startup"}), ("UserPromptSubmit", {"prompt": "書いて"}),
                           ("Stop", {"stop_hook_active": False})):
        (command,) = hr.hook_commands(event)
        r = hr.run(command, {**base, "hook_event_name": event, **payload}, plugin=plugin, folder=folder,
                   path=path, home=home, data=data)
        assert (r.returncode, r.stdout, r.stderr) == (0, b"", b""), (event, r)
    assert hr.snapshot(folder) == before
    assert not (folder / ".git").exists()
    assert (tmp_path / "python-ran").exists()
