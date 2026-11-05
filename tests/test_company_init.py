"""会社のフォルダを作る道具（TASKS S5・S5b、DESIGN 4.5・4.7・10章）。

道具（skills/kiroku/scripts/init_company.py）を、Claude が Bash で動かすのと同じ形で動かして確かめる。
- 一度に用意するもの：目印、フォルダの形（4.5）、版の履歴（送り先のない Git）、.claude/settings.json（4.7）
- 結果として、どの段階にも共通の決まりの短い文を返す（4.7）
- もう一度動かしたときは、足りないものだけを補う。すでにある設定は残して足す
- だめなときは何も書かない。途中で失敗したら、書いたものを戻す
- 会社のフォルダの外（プラグインの場所、HOME など）を変えない
- 通信を断っても、準備なしに用意する（dulwich はプラグインに同梱している）
- ホームのフォルダとディスクの根は断る。前からある設定は断り、新しいフォルダで始めて書類は取り込むよう案内する（S5b）
- 同期されるフォルダを見分けて知らせ、版の持ち方を選んでもらう。同期の形はまだ選べないと伝える（S5b）
- 版の履歴は、利用者の全体の除外の指定（と、ほかの Git の設定）を読まない（S5b）
送り先（リモート）の設定0件は test_T0_8.py で確かめる。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest

from lib import common_rules, company_init

# DESIGN 4.5 の会社のフォルダの形（ここでは、道具の定数を使わずに書き写す）
EXPECTED_FOLDERS = [
    "入れ口",
    "原本",
    "原本/登記・名簿",
    "原本/決算・税",
    "原本/見積・契約・請求",
    "原本/役所からの通知",
    "原本/会社の資料",
    "原本/写真・カタログ",
    "案件",
    "記録",
]


def contents(folder) -> dict:
    """名前と中身だけ（更新時刻は見ない）。"""
    return {
        str(p.relative_to(folder)): ("dir" if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(folder.rglob("*"))
    }


def settings_of(folder) -> dict:
    return json.loads((folder / ".claude" / "settings.json").read_text(encoding="utf-8"))


# ---- 一度に用意するもの ----


def test_creates_everything_at_once(tmp_path) -> None:
    env = ct.Env(tmp_path)
    folder = env.folder()
    out = ct.ok(env.run(folder))

    assert "会社のフォルダを用意しました" in out
    # 目印
    assert (folder / ".hojokin").is_dir()
    assert json.loads((folder / ".hojokin" / "設定.json").read_text(encoding="utf-8")) == {}
    # フォルダの形
    for name in EXPECTED_FOLDERS:
        assert (folder / name).is_dir(), name
    # 段階のフォルダと「見るだけ」は、ここでは作らない（案件を作るときと、見たいときに作る）
    assert list((folder / "案件").iterdir()) == []
    assert not (folder / "見るだけ").exists()
    # 版の履歴と設定
    assert (folder / ".git").is_dir()
    assert (folder / ".claude" / "settings.json").is_file()
    assert (folder / ".gitignore").is_file()
    # 用意した後は、履歴に残していない変更がない
    assert ct.changed(folder) == []


def test_marker_is_recognized_by_lib(tmp_path) -> None:
    """hooks とスクリプトが使う目印の確かめ（lib/company.py）が、作ったフォルダを会社のフォルダとみなす。"""
    from lib import company, dates

    env = ct.Env(tmp_path)
    folder = env.folder()
    assert company.company_folder(folder) is None
    ct.ok(env.run(folder))
    assert company.company_folder(folder) == folder
    assert company.load_settings(folder) == {}
    assert dates.substituted_today(folder) is None


# ---- .claude/settings.json（DESIGN 4.7） ----


def rule_regex(pattern: str) -> re.Pattern:
    """Edit(...) の中のパスの書き方（gitignore と同じ）を正規表現にする。先頭の / は会社のフォルダ。"""
    assert pattern.startswith("/"), pattern
    out = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("/**/", i):
            out += "/(?:.*/)?"
            i += 4
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out += "/.*"
            i += 3
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + "$")


def denied(rules: list, rel: str) -> bool:
    paths = [r[len("Edit("):-1] for r in rules if r.startswith("Edit(")]
    return any(rule_regex(p).match("/" + rel) for p in paths)


DENIED_PATHS = [
    "原本/決算・税/2025-05-31_決算書_第12期.pdf",
    "原本/見積・契約・請求/2026-10-20_見積書_〇〇機械.pdf",
    "案件/2026_省力化（一般型）第9回/公式資料/公募要領.pdf",
    "記録/審査役の結果/E3-0001.json",
    ".hojokin/設定.json",
    ".hojokin/一時/画面入力の許可.json",
    ".claude/settings.json",
    ".git/config",
    "財務モデル.xlsx",
    "補助金の候補.docx",
    "案件/2026_省力化（一般型）第9回/1_申請/申請書/その1.docx",
    "案件/2026_省力化（一般型）第9回/1_申請/申請書/その3.xlsx",
    "案件/2026_省力化（一般型）第9回/1_申請/申請書/入力シート.xlsx",
    "入れ口/古い様式.doc",
    "入れ口/古い表.xls",
    "入れ口/マクロ付き.xlsm",
]
ALLOWED_PATHS = [
    "記録/会社の記録.json",
    "記録/作業の記録.json",
    "入れ口/メモ.txt",
    "案件/2026_省力化（一般型）第9回/メモ.md",
    "今の状態.html",
]


def test_settings_follow_design_4_7(tmp_path) -> None:
    env = ct.Env(tmp_path)
    folder = env.folder()
    ct.ok(env.run(folder))
    permissions = settings_of(folder)["permissions"]

    # 会社のフォルダの外：block の2つ
    assert permissions["blockReadsOutsideWorkingDirectories"] is True
    assert permissions["blockWritesOutsideWorkingDirectories"] is True
    # 規則の deny：組み込みの Edit で、原本、公式資料、審査役の結果、.hojokin/、.claude/、.git/、Word・Excel を書き換えない
    deny = permissions["deny"]
    assert all(r.startswith("Edit(/") for r in deny), deny
    for rel in DENIED_PATHS:
        assert denied(deny, rel), rel
    for rel in ALLOWED_PATHS:
        assert not denied(deny, rel), rel
    # 読むことは止めない（原本も読めないと、書類を確かめられない）
    assert not any(r.startswith("Read(") for r in deny)
    # 規則の allow：Web 検索と、公的なサイト（go.jp、lg.jp）と持続化の公式サイトの取得だけ。下のドメインにも当たる書き方にする
    assert permissions["allow"] == ["WebSearch", "WebFetch(domain:*.go.jp)", "WebFetch(domain:*.lg.jp)",
                                    "WebFetch(domain:*.jizokukahojokin.info)"]
    # この区分のほかは書かない
    assert set(settings_of(folder)) == {"permissions"}


def test_rule_regex_reads_patterns_like_gitignore() -> None:
    """読み方そのものの確かめ：/**/ は0段のフォルダにも当たり、* はフォルダの区切りを越えない。"""
    assert rule_regex("/**/*.docx").match("/計画書.docx")
    assert rule_regex("/**/*.docx").match("/a/b/計画書.docx")
    assert not rule_regex("/原本/*").match("/原本/a/b.pdf")
    assert rule_regex("/原本/**").match("/原本/a/b.pdf")
    assert not rule_regex("/原本/**").match("/原本その2/a.pdf")


def test_existing_settings_are_kept_in_company_folder(tmp_path) -> None:
    """目印があるフォルダで足りないものを補うときは、すでにある設定を残して、決まりの分を足す。"""
    env = ct.Env(tmp_path)
    folder = env.folder()
    (folder / ".hojokin").mkdir()
    (folder / ".claude").mkdir()
    mine = {
        "env": {"EXAMPLE": "1"},
        "permissions": {
            "allow": ["Bash(ls:*)", "WebSearch"],
            "deny": ["Read(/秘密/**)"],
            "blockWritesOutsideWorkingDirectories": False,
        },
    }
    (folder / ".claude" / "settings.json").write_text(json.dumps(mine, ensure_ascii=False), encoding="utf-8")
    ct.ok(env.run(folder))

    settings = settings_of(folder)
    assert settings["env"] == {"EXAMPLE": "1"}
    permissions = settings["permissions"]
    assert permissions["allow"][:2] == ["Bash(ls:*)", "WebSearch"]
    assert permissions["allow"].count("WebSearch") == 1
    assert "WebFetch(domain:*.go.jp)" in permissions["allow"]
    assert permissions["deny"][0] == "Read(/秘密/**)"
    assert all(r in permissions["deny"] for r in company_init.DENY_RULES)
    # 守りを弱める値は、決まりの値で上書きする
    assert permissions["blockWritesOutsideWorkingDirectories"] is True
    assert permissions["blockReadsOutsideWorkingDirectories"] is True


# ---- .gitignore と版の履歴 ----

IGNORED = [
    ".hojokin/一時/画面入力の許可.json",
    ".hojokin/一時/部品の控え.json",
    "見るだけ/計画書_提出版.docx",
    ".claude/settings.local.json",
    "~$画書.docx",
    "案件/~$その1.docx",
    "~WRL0001.tmp",
    ".~lock.財務モデル.xlsx#",
    ".DS_Store",
    "原本/.DS_Store",
    "Thumbs.db",
    "desktop.ini",
]
TRACKED = [
    ".hojokin/設定.json",
    "記録/会社の記録.json",
    "原本/決算・税/2025-05-31_決算書_第12期.pdf",
    "財務モデル.xlsx",
]


def test_gitignore_keeps_temporary_files_out_of_history(tmp_path) -> None:
    env = ct.Env(tmp_path)
    folder = env.folder()
    ct.ok(env.run(folder))
    for rel in IGNORED + TRACKED:
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("試し", encoding="utf-8")
    seen = ct.changed(folder)
    for rel in IGNORED:
        assert rel not in seen, rel
    # 設定.json は最初の版に入っていて変わっていない。ほかは増えたものとして見える
    assert ".hojokin/設定.json" not in seen
    for rel in TRACKED[1:]:
        assert rel in seen, rel


def test_first_versions_name_who(tmp_path) -> None:
    """前からあったファイルは「社長」、用意したものは「ツール」の版にする。作者と記録者は利用者の設定を使わない。"""
    env = ct.Env(tmp_path)
    folder = env.folder()
    (folder / "原本").mkdir()
    (folder / "原本" / "見積書.pdf").write_bytes(b"%PDF-1.4 mitsumori")
    (folder / "メモ.txt").write_text("前からある", encoding="utf-8")
    (folder / ".DS_Store").write_bytes(b"\0")
    ct.ok(env.run(folder))

    log = ct.git_log(folder)
    assert len(log) == 2
    tool, owner = log
    assert owner["author"] == owner["committer"] == "社長 <owner@hojokin.invalid>"
    assert owner["files"] == ["メモ.txt", "原本/見積書.pdf"]
    assert owner["message"].startswith("会社のフォルダにする前からあったファイル")
    assert tool["author"] == tool["committer"] == "ツール <tool@hojokin.invalid>"
    assert tool["files"] == [".claude/settings.json", ".gitignore", ".hojokin/設定.json"]
    assert tool["message"].startswith("会社のフォルダを用意した")


def test_empty_folder_has_one_version(tmp_path) -> None:
    env = ct.Env(tmp_path)
    folder = env.folder()
    ct.ok(env.run(folder))
    log = ct.git_log(folder)
    assert [row["author"] for row in log] == ["ツール <tool@hojokin.invalid>"]


# ---- もう一度動かしたとき ----


def test_running_again_changes_nothing(tmp_path) -> None:
    env = ct.Env(tmp_path)
    folder = env.folder()
    ct.ok(env.run(folder))
    before = contents(folder)
    out = ct.ok(env.run(folder))
    assert "すでに会社のフォルダです" in out
    assert "足りないものはありませんでした" in out
    assert common_rules.TEXT in out
    # 名前と中身は同じ（.git/index は、dulwich が中身を変えずに書き直すので、更新時刻は見ない）
    assert contents(folder) == before
    assert len(ct.git_log(folder)) == 1


def test_running_again_fills_what_is_missing(tmp_path) -> None:
    env = ct.Env(tmp_path)
    folder = env.folder()
    ct.ok(env.run(folder))
    (folder / "入れ口").rmdir()
    settings = settings_of(folder)
    settings["permissions"]["deny"].remove("Edit(/原本/**)")
    (folder / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    # 社長が置いたファイル（まだ版にしていない）は、道具の版に入れない
    (folder / "記録" / "社長のメモ.txt").write_text("あとで版にする", encoding="utf-8")

    out = ct.ok(env.run(folder))
    assert "足りなかったものを補いました" in out
    assert (folder / "入れ口").is_dir()
    assert "Edit(/原本/**)" in settings_of(folder)["permissions"]["deny"]
    log = ct.git_log(folder)
    assert len(log) == 2
    assert log[0]["author"].startswith("ツール") and log[0]["files"] == [".claude/settings.json"]
    assert ct.changed(folder) == ["記録/社長のメモ.txt"]


def test_marker_without_the_rest_is_completed(tmp_path) -> None:
    """目印だけがある（手で作ったなど）フォルダでも、足りないものを用意する。"""
    env = ct.Env(tmp_path)
    folder = env.folder()
    (folder / ".hojokin").mkdir()
    out = ct.ok(env.run(folder))
    assert "すでに会社のフォルダです" in out
    for name in EXPECTED_FOLDERS + [".git", ".claude"]:
        assert (folder / name).is_dir(), name
    assert settings_of(folder)["permissions"]["blockReadsOutsideWorkingDirectories"] is True


# ---- だめなとき・失敗したとき ----


LOCAL_WEAKENING = {
    "フックを止める": {"disableAllHooks": True},
    "外を読む": {"permissions": {"blockReadsOutsideWorkingDirectories": False}},
    "外に書く": {"permissions": {"blockWritesOutsideWorkingDirectories": False}},
    "作業フォルダを足す": {"permissions": {"additionalDirectories": ["~/"]}},
    "確認をすべて外す": {"permissions": {"defaultMode": "bypassPermissions"}},
}


def _prepare(folder, case: str) -> None:
    if case == "目印と同じ名前のファイル":
        (folder / ".hojokin").write_text("", encoding="utf-8")
    elif case == "原本という名前のファイル":
        (folder / "原本").write_text("", encoding="utf-8")
    elif case == "前からある.gitignore":
        (folder / ".gitignore").write_text("*.pdf\n", encoding="utf-8")
    elif case == "前からある.git":
        # 送り先のない .git（送り先のあるものは test_T0_8.py）
        ct.py_json("from dulwich import porcelain\nporcelain.init(sys.argv[1])\nprint(1)", str(folder))
    elif case == "前からある設定":
        (folder / ".claude").mkdir()
        (folder / ".claude" / "settings.json").write_text('{"disableAllHooks": true}', encoding="utf-8")
    elif case in LOCAL_WEAKENING:
        (folder / ".claude").mkdir()
        (folder / ".claude" / "settings.local.json").write_text(json.dumps(LOCAL_WEAKENING[case]), encoding="utf-8")
    elif case in ("読めない設定", "形の違う設定", "読めない.gitignore"):
        # 目印があるフォルダで補うときに、すでにあるものを読めない
        (folder / ".hojokin").mkdir()
        if case == "読めない.gitignore":
            (folder / ".gitignore").write_bytes("見るだけ/\n".encode("shift_jis"))
        else:
            (folder / ".claude").mkdir()
            text = "{ 書きかけ" if case == "読めない設定" else '{"permissions": {"deny": "Edit(/a)"}}'
            (folder / ".claude" / "settings.json").write_text(text, encoding="utf-8")
    else:
        raise AssertionError(case)


@pytest.mark.parametrize(
    "case",
    ["目印と同じ名前のファイル", "原本という名前のファイル", "前からある.gitignore", "前からある.git", "前からある設定"]
    + list(LOCAL_WEAKENING)
    + ["読めない設定", "形の違う設定", "読めない.gitignore"],
)
def test_refuses_without_writing(tmp_path, case) -> None:
    """目印のないフォルダに、前からある .git・.gitignore・設定があるとき（決まりが気づかないうちに外れないよう）や、
    すでにあるものを読めないときは、何も書かずに断る。"""
    env = ct.Env(tmp_path)
    folder = env.folder()
    (folder / "メモ.txt").write_text("前からある", encoding="utf-8")
    _prepare(folder, case)
    before = hr.snapshot(folder)
    outside = env.outside()

    r = env.run(folder)
    out = r.stdout.decode("utf-8")
    assert r.returncode == 2, out
    assert "会社のフォルダにできませんでした。何も変えていません。" in out
    assert_new_folder_guide(out)
    assert hr.snapshot(folder) == before
    assert env.outside() == outside


def assert_new_folder_guide(out: str) -> None:
    """断ったときの案内（DESIGN 4.7）：新しいフォルダを作ってそこで始め、元の書類は場所を伝えてもらって取り込む。"""
    assert "新しい空のフォルダを作り" in out and "Claude を開き直して" in out
    assert "場所を伝えてもらえば取り込みます" in out and "元のファイルは動かしません" in out


def test_local_settings_with_only_permissions_are_accepted(tmp_path) -> None:
    """「次から聞かない」で Claude Code が作る settings.local.json（許可の規則だけ）は、断らずに残す。"""
    env = ct.Env(tmp_path)
    folder = env.folder()
    (folder / ".claude").mkdir()
    local = '{"permissions": {"allow": ["WebFetch(domain:www.jgrants-portal.go.jp)"]}}'
    (folder / ".claude" / "settings.local.json").write_text(local, encoding="utf-8")
    ct.ok(env.run(folder))
    assert (folder / ".claude" / "settings.local.json").read_text(encoding="utf-8") == local
    # 社長ごとの設定なので、版の履歴には入れない
    assert all(".claude/settings.local.json" not in row["files"] for row in ct.git_log(folder))


ROLLBACK_CODE = """
from pathlib import Path
from lib import company_init, history

real = history.commit

def fail_on_tool(folder, message, who, paths=None):
    if who == history.TOOL:
        raise RuntimeError("試しの失敗")
    return real(folder, message, who, paths)

history.commit = fail_on_tool
try:
    company_init.init(Path(sys.argv[1]))
except RuntimeError:
    print(json.dumps("失敗した"))
else:
    print(json.dumps("失敗しなかった"))
"""


def test_failure_on_the_way_undoes_everything(tmp_path) -> None:
    """最後の版を残すときに失敗したら、目印・設定・フォルダ・履歴を戻し、前からあったものは元のまま。"""
    env = ct.Env(tmp_path)
    folder = env.folder()
    (folder / "メモ.txt").write_text("前からある", encoding="utf-8")
    (folder / "原本").mkdir()
    (folder / "原本" / "見積書.pdf").write_bytes(b"%PDF")
    before = contents(folder)

    assert ct.py_json(ROLLBACK_CODE, str(folder)) == "失敗した"
    assert contents(folder) == before
    assert not (folder / ".hojokin").exists()


# ---- 結果の文 ----


def test_output_returns_common_rules(tmp_path) -> None:
    """初めて使うセッションに、どの段階にも共通の決まりの短い文（1,200字ほど）を返す。"""
    env = ct.Env(tmp_path)
    folder = env.folder()
    out = ct.ok(env.run(folder))
    assert common_rules.TEXT in out
    for heading in ("聞き方", "決めつけずに確かめる", "記録に残すか", "説明"):
        assert heading in common_rules.TEXT, heading
    assert "3つまで" in common_rules.TEXT
    # 質問と仮の印の書き方（DESIGN 6章）。Stop hook が質問の記録を残すのは、この形から
    for form in ("【質問】", "（理由：", "AskUserQuestion", "【仮：", "【空欄："):
        assert form in common_rules.TEXT, form
    # 計算と日付は道具で行うこと（DESIGN 4.2・6章）、画面入力は /hojokin:nyuryoku を案内すること（DESIGN 4.2）
    assert "計算と日付" in common_rules.TEXT and "道具（スクリプト）で出す" in common_rules.TEXT
    assert "今日の日付" in common_rules.TEXT and "期限" in common_rules.TEXT
    assert "`/hojokin:nyuryoku` を呼んでもらうよう案内する" in common_rules.TEXT
    assert "自分では画面の操作を始めない" in common_rules.TEXT
    # 1,200字まで（DESIGN 4.2）。開いたときに渡す情報（10,000字以内）を圧迫しない長さ
    assert common_rules.MAX_CHARS == 1200
    assert len(common_rules.TEXT) <= 1200
    # 社長に伝えること：書類の入れ方、履歴をパソコンの外に送らないこと、auto モードの案内（4.7）
    assert "入れ口" in out and "インターネットには送りません" in out and "auto" in out


# ---- 会社のフォルダの外、引数と場所 ----


def test_nothing_outside_changes(tmp_path) -> None:
    """プラグインの写し（同梱の dulwich にも __pycache__ を書かない）、HOME、一時ファイルの置き場、今いるフォルダ、
    隣のフォルダは変わらない。"""
    env = ct.Env(tmp_path)
    folder = env.folder()
    neighbor = env.folder("隣の会社")
    (neighbor / "書類.pdf").write_bytes(b"%PDF")
    before = env.outside()
    neighbor_before = hr.snapshot(neighbor)
    ct.ok(env.run(folder))
    assert env.outside() == before
    assert hr.snapshot(neighbor) == neighbor_before
    assert not list(env.plugin.rglob("__pycache__"))


def test_plugin_data_is_not_used(tmp_path) -> None:
    """プラグインのデータの置き場は使わない。前の呼び方（--data-dir）で、まだない置き場を渡しても、作らずに用意する。"""
    env = ct.Env(tmp_path)
    folder = env.folder()
    data = tmp_path / "まだないデータの置き場"
    ct.ok(env.run(args=["--data-dir", str(data), "--folder", str(folder)]))
    assert (folder / ".hojokin").is_dir()
    assert not data.exists()


def test_folder_defaults(tmp_path) -> None:
    """--folder がなければ CLAUDE_PROJECT_DIR、それもなければ今いるフォルダ。"""
    env = ct.Env(tmp_path)
    by_cwd = env.folder("今いるフォルダ")
    ct.ok(env.run(args=[], cwd=by_cwd))
    assert (by_cwd / ".hojokin").is_dir()

    by_env = env.folder("開いたフォルダ")
    ct.ok(env.run(args=[], extra_env={"CLAUDE_PROJECT_DIR": str(by_env)}))
    assert (by_env / ".hojokin").is_dir()
    assert not (env.cwd / ".hojokin").exists()


# ---- 補助プログラム（同梱の dulwich）と通信 ----


def test_offline_prefix_blocks_network() -> None:
    """通信の断ち方そのものの確かめ：断たなければつながる手元の口（127.0.0.1）にも、つながらない。"""
    prefix = ct.offline_prefix()
    code = "import socket, sys\nsocket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=5).close()"
    with socket.socket() as server:
        try:
            server.bind(("127.0.0.1", 0))
        except OSError:
            pytest.skip("テストを流す所の通信が、すでに断たれています")
        server.listen()
        port = str(server.getsockname()[1])
        r = subprocess.run([hr.real_python(), "-I", "-B", "-c", code, port], capture_output=True, timeout=30)
        assert r.returncode == 0, r.stderr.decode("utf-8")
        r = subprocess.run([*prefix, hr.real_python(), "-I", "-B", "-c", code, port], capture_output=True, timeout=30)
        assert r.returncode != 0
        assert b"Operation not permitted" in r.stderr


def test_creates_everything_offline(tmp_path) -> None:
    """通信を断っても（eval の中や、通信できないパソコンで初めて使うとき）、準備なしに一度に用意する。"""
    env = ct.Env(tmp_path)
    folder = env.folder()
    (folder / "決算書_2025年度.pdf").write_bytes(b"%PDF-1.4 dummy")
    before = env.outside()
    out = ct.ok(env.run(folder, offline=True))
    assert "会社のフォルダを用意しました" in out
    assert common_rules.TEXT in out
    for name in EXPECTED_FOLDERS + [".hojokin", ".git", ".claude"]:
        assert (folder / name).is_dir(), name
    assert settings_of(folder)["permissions"]["blockReadsOutsideWorkingDirectories"] is True
    log = ct.git_log(folder)
    assert [row["author"] for row in log] == ["ツール <tool@hojokin.invalid>", "社長 <owner@hojokin.invalid>"]
    assert ct.changed(folder) == []
    assert env.outside() == before


@pytest.mark.parametrize(
    "missing, said",
    [
        # すべて欠けている：何か書く前に読み込めない
        ("dulwich", "何も変えていません"),
        # 版を残した後に初めて読み込むモジュール（worktree.py の commit の中）だけが欠けている：書きかけたものを戻す
        ("dulwich/gc.py", "書きかけたものを元に戻しました"),
    ],
)
def test_missing_bundled_library_leaves_nothing(tmp_path, missing, said) -> None:
    """同梱の dulwich が欠けていたら（壊れたプラグインなど）、分かる文で止まり、会社のフォルダにも外にも何も残さない。"""
    env = ct.Env(tmp_path)
    target = env.plugin / "lib" / "vendor" / missing
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    folder = env.folder()
    (folder / "メモ.txt").write_text("前からある", encoding="utf-8")
    before = hr.snapshot(folder)
    outside = env.outside()
    # 利用者の site-packages にある dulwich で動いてしまわないようにする
    r = env.run(folder, extra_env={"PYTHONNOUSERSITE": "1"})
    out = r.stdout.decode("utf-8")
    assert r.returncode == 1, out
    assert r.stderr == b"", r.stderr.decode("utf-8")
    assert said in out and "入れ直して" in out
    assert hr.snapshot(folder) == before
    assert env.outside() == outside


# ---- ホームのフォルダとディスクの根（DESIGN 4.7、TASKS S5b） ----


def assert_refused(env, folder, *, said: str, snapshot_of=None) -> str:
    """道具が終了コード2で断り、何も書かないこと。出力を返す。"""
    watched = snapshot_of or [folder]
    before = hr.snapshot(*watched)
    outside = env.outside()
    r = env.run(folder)
    out = r.stdout.decode("utf-8")
    assert r.returncode == 2, out
    assert r.stderr == b"", r.stderr.decode("utf-8")
    assert "会社のフォルダにできませんでした。何も変えていません。" in out
    assert said in out, out
    assert hr.snapshot(*watched) == before
    assert env.outside() == outside
    return out


def test_refuses_home_folder(tmp_path) -> None:
    """ホームのフォルダは、会社のフォルダにしない。新しいフォルダで始め、書類は取り込むよう案内する。"""
    env = ct.Env(tmp_path)
    (env.home / "決算書.pdf").write_bytes(b"%PDF")
    out = assert_refused(env, env.home, said="ホームのフォルダです")
    assert_new_folder_guide(out)
    assert not (env.home / ".hojokin").exists() and not (env.home / ".git").exists()


def test_refuses_home_folder_even_with_marker(tmp_path) -> None:
    """目印があっても（手で作ったなど）、ホームのフォルダには何も補わない。"""
    env = ct.Env(tmp_path)
    (env.home / ".hojokin").mkdir()
    assert_refused(env, env.home, said="ホームのフォルダです")
    assert not (env.home / ".git").exists() and not (env.home / ".claude").exists()


def test_refuses_folder_that_contains_home(tmp_path) -> None:
    """ホームのフォルダを含むフォルダ（/Users など）も、中のものがすべて対象になるので断る。"""
    env = ct.Env(tmp_path)
    out = assert_refused(env, tmp_path, said="ホームのフォルダ", snapshot_of=[tmp_path])
    assert "含んでいます" in out
    assert not (tmp_path / ".hojokin").exists()


def test_disk_root_is_refused() -> None:
    """ディスクの根（「/」と、ほかのディスクのつなぎ目）は断る。本物の「/」では道具を動かさず、確かめだけを見る。"""
    from lib import sync_folder

    for root in [Path("/")] + [p for p in (Path("/dev"), Path("/System/Volumes/Data")) if os.path.ismount(str(p))]:
        reason = sync_folder.not_allowed_reason(root)
        assert reason and "ディスクの一番上のフォルダ" in reason, root
        assert company_init.check(root) == [reason]


def test_folders_inside_home_are_allowed(tmp_path, monkeypatch) -> None:
    """ホームの下のふつうのフォルダは、ホームの扱いにしない。"""
    from lib import sync_folder

    home = tmp_path / "home"
    (home / "書類" / "山田製作所").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    assert sync_folder.not_allowed_reason(home / "書類" / "山田製作所") is None
    assert sync_folder.not_allowed_reason(home / "書類") is None
    assert sync_folder.not_allowed_reason(home) is not None


# ---- 同期されるフォルダ（DESIGN 4.7・10章、TASKS S5b） ----

SYNCED_PLACES = [
    ("Library/CloudStorage/GoogleDrive-taro@example.com/マイドライブ/山田製作所", "Google ドライブ"),
    ("Library/CloudStorage/OneDrive-個人用/山田製作所", "OneDrive"),
    ("Library/CloudStorage/Dropbox/山田製作所", "Dropbox"),
    ("Library/CloudStorage/Box-Box/山田製作所", "Box"),
    ("Library/Mobile Documents/com~apple~CloudDocs/山田製作所", "iCloud Drive"),
    # 前からの形（ホームの直下）
    ("Dropbox (個人)/山田製作所", "Dropbox"),
    ("Google Drive/山田製作所", "Google ドライブ"),
    ("OneDrive - 架空商事/山田製作所", "OneDrive"),
]


def assert_sync_choice(out: str, service: str) -> None:
    """同期されるフォルダのときの案内：サービスを伝え、版の持ち方を経営者に選んでもらう（同期の形は今は選べない）。"""
    assert f"{service}で同期されています" in out
    assert "選んでもらってください" in out
    assert "1. パソコンの中だけに置く（勧める案）" in out and "同期されない場所に新しい空のフォルダ" in out
    assert "場所を伝えてもらえば取り込む" in out
    assert f"2. このまま{service}に置く" in out and "今は選べない" in out


@pytest.mark.parametrize("place, service", SYNCED_PLACES)
def test_synced_folder_is_refused_with_choice(tmp_path, place, service) -> None:
    """同期されるフォルダを見分けて知らせ、何も書かずに、版の持ち方を選んでもらう問いを返す。"""
    env = ct.Env(tmp_path)
    folder = env.home / place
    folder.mkdir(parents=True)
    (folder / "決算書.pdf").write_bytes(b"%PDF")
    out = assert_refused(env, folder, said="版の持ち方を先に選んでもらいます")
    assert_sync_choice(out, service)
    for name in (".hojokin", ".git", ".claude", ".gitignore", "入れ口"):
        assert not (folder / name).exists(), name


@pytest.mark.parametrize("marker, is_dir", [(".dropbox", False), (".dropbox.cache", True)])
def test_synced_folder_found_by_root_marker(tmp_path, marker, is_dir) -> None:
    """場所を変えた Dropbox（根に .dropbox のファイルか、.dropbox.cache のフォルダがある）も、
    同期されるフォルダとして見分ける。"""
    env = ct.Env(tmp_path)
    root = tmp_path / "外付けのディスク" / "共有の箱"
    folder = root / "山田製作所"
    folder.mkdir(parents=True)
    if is_dir:
        (root / marker).mkdir()
    else:
        (root / marker).write_text("{}", encoding="utf-8")
    out = assert_refused(env, folder, said="Dropboxで同期されています")
    assert_sync_choice(out, "Dropbox")


@pytest.mark.parametrize("layout", ["settings_folder", "file_and_cache"])
def test_dropbox_settings_in_home_do_not_make_home_synced(tmp_path, monkeypatch, layout) -> None:
    """Dropbox のアプリは、自分の設定を ~/.dropbox/（フォルダ）に置く。これがあっても、ホームの下の
    ふつうのフォルダは同期されるフォルダとみなさず、会社のフォルダを用意する。
    目印はホームより下だけで探すので、ホームに .dropbox のファイルや .dropbox.cache があっても同じ。"""
    from lib import sync_folder

    env = ct.Env(tmp_path)
    if layout == "settings_folder":
        (env.home / ".dropbox").mkdir()
        (env.home / ".dropbox" / "info.json").write_text('{"personal": {"path": "/somewhere/Dropbox"}}',
                                                         encoding="utf-8")
    else:
        (env.home / ".dropbox").write_text("{}", encoding="utf-8")
        (env.home / ".dropbox.cache").mkdir()
    folder = env.home / "書類" / "山田製作所"
    folder.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(env.home))
    assert sync_folder.synced(folder, icloud_desktop=set) is None
    assert sync_folder.synced(env.home / "書類", icloud_desktop=set) is None
    out = ct.ok(env.run(folder))
    assert "会社のフォルダを用意しました" in out
    assert (folder / ".hojokin").is_dir() and (folder / ".git").is_dir()


def case_insensitive_disk(path: Path) -> bool:
    """path のあるディスクが、大文字と小文字を区別しないか（Mac の標準のディスクは区別しない）。"""
    return path.exists() and Path(str(path).swapcase()).exists()


def test_case_variants_of_synced_folder_are_found(tmp_path, monkeypatch) -> None:
    """大文字と小文字を変えた道筋（~/library/cloudstorage/… など）でも、同期されるフォルダと見分けて断る。"""
    from lib import sync_folder

    env = ct.Env(tmp_path)
    rest = ("GoogleDrive-a@example.com", "マイドライブ", "会社")
    real = env.home.joinpath("Library", "CloudStorage", *rest)
    real.mkdir(parents=True)
    if not case_insensitive_disk(real):
        pytest.skip("大文字と小文字を区別するディスクです")
    monkeypatch.setenv("HOME", str(env.home))
    variants = [
        env.home.joinpath("library", "cloudstorage", *rest),
        env.home.joinpath("LIBRARY", "CloudStorage", *rest),
        env.home.joinpath("Library", "CLOUDSTORAGE", "googledrive-a@example.com", "マイドライブ", "会社"),
    ]
    for variant in variants:
        assert variant.exists(), variant
        found = sync_folder.synced(variant, icloud_desktop=set)
        assert found is not None and found.service == "Google ドライブ", variant
    out = assert_refused(env, variants[0], said="Google ドライブで同期されています")
    assert_sync_choice(out, "Google ドライブ")
    assert not (real / ".git").exists() and not (real / ".hojokin").exists()

    # iCloud の「デスクトップと書類」と、前からの形（ホームの直下）も、大文字と小文字を変えて見分ける
    (env.home / "Desktop" / "会社").mkdir(parents=True)
    (env.home / "Dropbox" / "会社").mkdir(parents=True)
    assert sync_folder.synced(env.home / "desktop" / "会社", icloud_desktop=lambda: {"Desktop"}) is not None
    assert sync_folder.synced(env.home / "DROPBOX" / "会社", icloud_desktop=set).service == "Dropbox"


def test_case_variants_of_home_are_refused(tmp_path, monkeypatch) -> None:
    """大文字と小文字を変えた道筋でも、ホームのフォルダとそれを含むフォルダを断る。"""
    from lib import sync_folder

    env = ct.Env(tmp_path)
    if not case_insensitive_disk(env.home):
        pytest.skip("大文字と小文字を区別するディスクです")
    upper_home = Path(str(env.home).upper())
    out = assert_refused(env, upper_home, said="ホームのフォルダです")
    assert_new_folder_guide(out)
    assert not (env.home / ".hojokin").exists() and not (env.home / ".git").exists()
    out = assert_refused(env, Path(str(tmp_path).swapcase()), said="ホームのフォルダ", snapshot_of=[tmp_path])
    assert "含んでいます" in out

    monkeypatch.setenv("HOME", str(env.home))
    for variant in (upper_home, env.home.parent / env.home.name.upper(), Path(str(env.home).lower())):
        reason = sync_folder.not_allowed_reason(variant)
        assert reason and "ホームのフォルダです" in reason, variant
    # この Mac の本当のホーム（利用者の登録から）も、書き方を変えて断る。読むだけで、何も書かない
    import pwd

    real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if case_insensitive_disk(real_home):
        for variant in (Path(str(real_home).lower()), Path(str(real_home).upper())):
            reason = sync_folder.not_allowed_reason(variant)
            assert reason and "ホームのフォルダです" in reason, variant
        reason = sync_folder.not_allowed_reason(Path(str(real_home.parent).upper()))
        assert reason and "含んでいます" in reason


@pytest.mark.parametrize("place", ["Boxes/山田製作所", "Documents/山田製作所", "Library/Application Support/山田製作所"])
def test_folders_with_similar_names_are_not_synced(tmp_path, place) -> None:
    """同期と関係のない場所は、同期されるフォルダとみなさずに用意する。"""
    from lib import sync_folder

    env = ct.Env(tmp_path)
    folder = env.home / place
    folder.mkdir(parents=True)
    assert sync_folder.synced(folder, icloud_desktop=set) is None
    if not place.startswith("Documents/"):
        # Documents は、この Mac の「デスクトップと書類」の設定を読むので、道具では動かさない（下のテストで差し替えて見る）
        assert "会社のフォルダを用意しました" in ct.ok(env.run(folder))


def test_icloud_desktop_and_documents(tmp_path, monkeypatch) -> None:
    """iCloud の「デスクトップと書類」が入っているときだけ、~/Desktop・~/Documents の下を同期されるとみなす。"""
    from lib import sync_folder

    home = tmp_path / "home"
    desk = home / "Desktop" / "山田製作所"
    docs = home / "Documents" / "山田製作所"
    for d in (desk, docs):
        d.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    assert sync_folder.synced(desk, icloud_desktop=set) is None
    found = sync_folder.synced(desk, icloud_desktop=lambda: {"Desktop"})
    assert found == sync_folder.Synced("iCloud Drive（デスクトップと書類）", home.resolve() / "Desktop")
    assert sync_folder.synced(docs, icloud_desktop=lambda: {"Desktop"}) is None
    assert sync_folder.synced(docs, icloud_desktop=lambda: {"Desktop", "Documents"}) is not None


def test_icloud_desktop_reader_reads_finder_setting() -> None:
    """Finder の設定の読み方：この Mac の今の設定を、/usr/bin/defaults と同じに読む（読めなければ空）。"""
    from lib import sync_folder

    names = sync_folder.icloud_desktop_synced()
    assert names <= {"Desktop", "Documents"}
    if sys.platform != "darwin":
        assert names == set()
        return
    for key, name in sync_folder.ICLOUD_DESKTOP_KEYS:
        r = subprocess.run(["/usr/bin/defaults", "read", "com.apple.finder", key], capture_output=True, timeout=10)
        assert (name in names) == (r.returncode == 0 and r.stdout.strip() == b"1"), key


def test_company_folder_moved_into_synced_folder_is_refused(tmp_path) -> None:
    """Git の形の会社のフォルダ（目印と .git がある）が後から同期されるフォルダに移されていたら、
    経営者が同期の形を選んでいないので、何も書き足さずに断り、版の持ち方を選んでもらう。
    同期されない場所へフォルダごと戻せば、そのまま使える。
    （仮の形。補って注意を添える形・注意だけの形と、どれにするかは作者の決定待ち）"""
    env = ct.Env(tmp_path)
    first = env.folder()
    ct.ok(env.run(first))
    folder = env.home / "Library" / "CloudStorage" / "Dropbox" / "山田製作所"
    folder.parent.mkdir(parents=True)
    shutil.move(str(first), str(folder))
    (folder / "入れ口").rmdir()

    out = assert_refused(env, folder, said="Dropboxで同期されています")
    assert_sync_choice(out, "Dropbox")
    assert "何も書き足しません" in out and "同期されない場所へフォルダごと移せば" in out
    assert not (folder / "入れ口").exists()

    back = tmp_path / "戻した会社"
    shutil.move(str(folder), str(back))
    out = ct.ok(env.run(back))
    assert "足りなかったものを補いました" in out and (back / "入れ口").is_dir()


def test_marker_without_history_in_synced_folder_is_refused(tmp_path) -> None:
    """同期されるフォルダで、目印だけがあって版の履歴（.git）がないときは、新しく .git を作らずに断る。"""
    env = ct.Env(tmp_path)
    folder = env.home / "Library" / "CloudStorage" / "GoogleDrive-taro@example.com" / "マイドライブ" / "山田製作所"
    (folder / ".hojokin").mkdir(parents=True)
    out = assert_refused(env, folder, said="Google ドライブで同期されています")
    assert_sync_choice(out, "Google ドライブ")
    assert not (folder / ".git").exists()


# ---- 版の履歴は、利用者の全体の除外の指定を読まない（DESIGN 10章、TASKS S5b） ----

# 社長のパソコンにありそうな、書類に当たる除外の行
GLOBAL_IGNORE = "*.pdf\n原本/\n*.xlsx\n*.docx\nメモ*\n"
EXISTING_DOCS = {
    "決算書_2025年度.pdf": b"%PDF-1.4 kessan",
    "原本/見積書.pdf": b"%PDF-1.4 mitsumori",
    "財務モデル.xlsx": b"PK\x03\x04 xlsx",
    "計画書.docx": b"PK\x03\x04 docx",
    # 改行が CRLF の文字のファイル。利用者の core.autocrlf で書き換えられずに、そのまま残る
    "メモ.csv": "日付,内容\r\n2026-11-03,見積を受け取った\r\n".encode("utf-8"),
}

BLOB_CODE = """
from dulwich.repo import Repo
repo = Repo(sys.argv[1])
tree = repo[repo[repo.head()].tree]
mode, sha = tree.lookup_path(repo.object_store.__getitem__, sys.argv[2].encode("utf-8"))
print(json.dumps({"head": repo.refs.read_ref(b"HEAD").decode("utf-8"), "blob": list(repo[sha].data)}))
"""
CHANGED_CODE = ("from pathlib import Path\n"
                "print(json.dumps(history.changed_paths(Path(sys.argv[1])), ensure_ascii=False))")


def _user_git_settings(env, kind: str) -> dict:
    """利用者の Git の設定と全体の除外の指定を、差し替えた HOME などに置く。道具に渡す環境変数を返す。"""
    home = env.home
    if kind == "core.excludesFile":
        (home / "全体の除外").write_text(GLOBAL_IGNORE, encoding="utf-8")
        (home / ".gitconfig").write_text(
            "[core]\n\texcludesFile = ~/全体の除外\n\tautocrlf = true\n[init]\n\tdefaultBranch = main\n",
            encoding="utf-8")
        return {}
    if kind == "~/.config/git/ignore":
        (home / ".config" / "git").mkdir(parents=True)
        (home / ".config" / "git" / "ignore").write_text(GLOBAL_IGNORE, encoding="utf-8")
        (home / ".config" / "git" / "config").write_text("[core]\n\tautocrlf = true\n", encoding="utf-8")
        return {}
    if kind == "XDG_CONFIG_HOME":
        xdg = env.root / "xdg"
        (xdg / "git").mkdir(parents=True)
        (xdg / "git" / "ignore").write_text(GLOBAL_IGNORE, encoding="utf-8")
        return {"XDG_CONFIG_HOME": str(xdg)}
    if kind == "GIT_CONFIG_GLOBAL":
        (env.root / "除外2").write_text(GLOBAL_IGNORE, encoding="utf-8")
        config = env.root / "利用者の設定"
        config.write_text(f"[core]\n\texcludesFile = {env.root / '除外2'}\n\tautocrlf = true\n", encoding="utf-8")
        return {"GIT_CONFIG_GLOBAL": str(config)}
    raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["core.excludesFile", "~/.config/git/ignore", "XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL"])
def test_history_ignores_global_excludes(tmp_path, kind) -> None:
    """利用者の全体の除外の指定に書類に当たる行があっても、書類は黙って履歴から抜けない。
    利用者の Git の設定（改行の書き換え、ブランチの名前）にも左右されない。"""
    env = ct.Env(tmp_path)
    extra = _user_git_settings(env, kind)
    run_env = {"HOME": str(env.home), **extra}
    folder = env.folder()
    for rel, data in EXISTING_DOCS.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(data)

    # 材料が効いていることの確かめ：git のコマンドなら、利用者の設定でこれらを履歴から外す
    git = shutil.which("git")
    if git:
        probe = env.root / "確かめ"
        probe.mkdir()
        subprocess.run([git, "init", "-q", str(probe)], check=True, capture_output=True,
                       env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", **run_env})
        for rel in EXISTING_DOCS:
            r = subprocess.run([git, "-C", str(probe), "check-ignore", "-q", "--no-index", rel], capture_output=True,
                               env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", **run_env})
            assert r.returncode == 0, (rel, r.stderr)
        shutil.rmtree(probe)

    ct.ok(env.run(folder, extra_env=extra))
    tool, owner = ct.git_log(folder)
    assert owner["author"].startswith("社長")
    assert owner["files"] == sorted(EXISTING_DOCS)
    # 同じ設定のまま読んでも、残していない変更はない。増やした書類も、変更として見える
    assert ct.py_json(CHANGED_CODE, str(folder), env=run_env) == []
    (folder / "原本" / "請求書.pdf").write_bytes(b"%PDF-1.4 seikyu")
    (folder / "経費明細.xlsx").write_bytes(b"PK\x03\x04")
    assert ct.py_json(CHANGED_CODE, str(folder), env=run_env) == ["原本/請求書.pdf", "経費明細.xlsx"]
    # 改行は書き換えずに残し、ブランチの名前は利用者の init.defaultBranch によらない
    seen = ct.py_json(BLOB_CODE, str(folder), "メモ.csv", env=run_env)
    assert bytes(seen["blob"]) == EXISTING_DOCS["メモ.csv"]
    assert seen["head"] == "ref: refs/heads/master"
