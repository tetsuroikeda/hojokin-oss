"""会社のフォルダを作る道具（TASKS S5、DESIGN 4.5・4.7）。

道具（skills/kiroku/scripts/init_company.py）を、Claude が Bash で動かすのと同じ形で動かして確かめる。
- 一度に用意するもの：目印、フォルダの形（4.5）、版の履歴（送り先のない Git）、.claude/settings.json（4.7）
- 結果として、どの段階にも共通の決まりの短い文を返す（4.7）
- もう一度動かしたときは、足りないものだけを補う。すでにある設定は残して足す
- だめなときは何も書かない。途中で失敗したら、書いたものを戻す
- 会社のフォルダの外（プラグインの場所、HOME など）を変えない
送り先（リモート）の設定0件は test_T0_8.py で確かめる。
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess

import company_tool as ct
import hook_runner as hr
import pytest
from company_tool import plugin_data  # noqa: F401（fixture）

from lib import common_rules, company_init, runtime

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


def test_creates_everything_at_once(tmp_path, plugin_data) -> None:  # noqa: F811
    env = ct.Env(tmp_path, plugin_data)
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
    assert ct.changed(plugin_data, folder) == []


def test_marker_is_recognized_by_lib(tmp_path, plugin_data) -> None:  # noqa: F811
    """hooks とスクリプトが使う目印の確かめ（lib/company.py）が、作ったフォルダを会社のフォルダとみなす。"""
    from lib import company, dates

    env = ct.Env(tmp_path, plugin_data)
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


def test_settings_follow_design_4_7(tmp_path, plugin_data) -> None:  # noqa: F811
    env = ct.Env(tmp_path, plugin_data)
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
    # 規則の allow：Web 検索と、公的なサイト（go.jp、lg.jp）の取得だけ。下のドメインにも当たる書き方にする
    assert permissions["allow"] == ["WebSearch", "WebFetch(domain:*.go.jp)", "WebFetch(domain:*.lg.jp)"]
    # この区分のほかは書かない
    assert set(settings_of(folder)) == {"permissions"}


def test_rule_regex_reads_patterns_like_gitignore() -> None:
    """読み方そのものの確かめ：/**/ は0段のフォルダにも当たり、* はフォルダの区切りを越えない。"""
    assert rule_regex("/**/*.docx").match("/計画書.docx")
    assert rule_regex("/**/*.docx").match("/a/b/計画書.docx")
    assert not rule_regex("/原本/*").match("/原本/a/b.pdf")
    assert rule_regex("/原本/**").match("/原本/a/b.pdf")
    assert not rule_regex("/原本/**").match("/原本その2/a.pdf")


def test_existing_settings_are_kept_in_company_folder(tmp_path, plugin_data) -> None:  # noqa: F811
    """目印があるフォルダで足りないものを補うときは、すでにある設定を残して、決まりの分を足す。"""
    env = ct.Env(tmp_path, plugin_data)
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


def test_gitignore_keeps_temporary_files_out_of_history(tmp_path, plugin_data) -> None:  # noqa: F811
    env = ct.Env(tmp_path, plugin_data)
    folder = env.folder()
    ct.ok(env.run(folder))
    for rel in IGNORED + TRACKED:
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("試し", encoding="utf-8")
    seen = ct.changed(plugin_data, folder)
    for rel in IGNORED:
        assert rel not in seen, rel
    # 設定.json は最初の版に入っていて変わっていない。ほかは増えたものとして見える
    assert ".hojokin/設定.json" not in seen
    for rel in TRACKED[1:]:
        assert rel in seen, rel


def test_first_versions_name_who(tmp_path, plugin_data) -> None:  # noqa: F811
    """前からあったファイルは「社長」、用意したものは「ツール」の版にする。作者と記録者は利用者の設定を使わない。"""
    env = ct.Env(tmp_path, plugin_data)
    folder = env.folder()
    (folder / "原本").mkdir()
    (folder / "原本" / "見積書.pdf").write_bytes(b"%PDF-1.4 mitsumori")
    (folder / "メモ.txt").write_text("前からある", encoding="utf-8")
    (folder / ".DS_Store").write_bytes(b"\0")
    ct.ok(env.run(folder))

    log = ct.git_log(plugin_data, folder)
    assert len(log) == 2
    tool, owner = log
    assert owner["author"] == owner["committer"] == "社長 <owner@hojokin.invalid>"
    assert owner["files"] == ["メモ.txt", "原本/見積書.pdf"]
    assert owner["message"].startswith("会社のフォルダにする前からあったファイル")
    assert tool["author"] == tool["committer"] == "ツール <tool@hojokin.invalid>"
    assert tool["files"] == [".claude/settings.json", ".gitignore", ".hojokin/設定.json"]
    assert tool["message"].startswith("会社のフォルダを用意した")


def test_empty_folder_has_one_version(tmp_path, plugin_data) -> None:  # noqa: F811
    env = ct.Env(tmp_path, plugin_data)
    folder = env.folder()
    ct.ok(env.run(folder))
    log = ct.git_log(plugin_data, folder)
    assert [row["author"] for row in log] == ["ツール <tool@hojokin.invalid>"]


# ---- もう一度動かしたとき ----


def test_running_again_changes_nothing(tmp_path, plugin_data) -> None:  # noqa: F811
    env = ct.Env(tmp_path, plugin_data)
    folder = env.folder()
    ct.ok(env.run(folder))
    before = contents(folder)
    out = ct.ok(env.run(folder))
    assert "すでに会社のフォルダです" in out
    assert "足りないものはありませんでした" in out
    assert common_rules.TEXT in out
    # 名前と中身は同じ（.git/index は、dulwich が中身を変えずに書き直すので、更新時刻は見ない）
    assert contents(folder) == before
    assert len(ct.git_log(plugin_data, folder)) == 1


def test_running_again_fills_what_is_missing(tmp_path, plugin_data) -> None:  # noqa: F811
    env = ct.Env(tmp_path, plugin_data)
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
    log = ct.git_log(plugin_data, folder)
    assert len(log) == 2
    assert log[0]["author"].startswith("ツール") and log[0]["files"] == [".claude/settings.json"]
    assert ct.changed(plugin_data, folder) == ["記録/社長のメモ.txt"]


def test_marker_without_the_rest_is_completed(tmp_path, plugin_data) -> None:  # noqa: F811
    """目印だけがある（手で作ったなど）フォルダでも、足りないものを用意する。"""
    env = ct.Env(tmp_path, plugin_data)
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


def _prepare(folder, case: str, data) -> None:
    if case == "目印と同じ名前のファイル":
        (folder / ".hojokin").write_text("", encoding="utf-8")
    elif case == "原本という名前のファイル":
        (folder / "原本").write_text("", encoding="utf-8")
    elif case == "前からある.gitignore":
        (folder / ".gitignore").write_text("*.pdf\n", encoding="utf-8")
    elif case == "前からある.git":
        # 送り先のない .git（送り先のあるものは test_T0_8.py）
        ct.venv_json(data, "from dulwich import porcelain\nporcelain.init(sys.argv[1])\nprint(1)", str(folder))
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
def test_refuses_without_writing(tmp_path, plugin_data, case) -> None:  # noqa: F811
    """目印のないフォルダに、前からある .git・.gitignore・設定があるとき（決まりが気づかないうちに外れないよう）や、
    すでにあるものを読めないときは、何も書かずに断る。"""
    env = ct.Env(tmp_path, plugin_data)
    folder = env.folder()
    (folder / "メモ.txt").write_text("前からある", encoding="utf-8")
    _prepare(folder, case, plugin_data)
    before = hr.snapshot(folder)
    outside = env.outside()

    r = env.run(folder)
    out = r.stdout.decode("utf-8")
    assert r.returncode == 2, out
    assert "会社のフォルダにできませんでした。何も変えていません。" in out
    assert hr.snapshot(folder) == before
    assert env.outside() == outside


def test_local_settings_with_only_permissions_are_accepted(tmp_path, plugin_data) -> None:  # noqa: F811
    """「次から聞かない」で Claude Code が作る settings.local.json（許可の規則だけ）は、断らずに残す。"""
    env = ct.Env(tmp_path, plugin_data)
    folder = env.folder()
    (folder / ".claude").mkdir()
    local = '{"permissions": {"allow": ["WebFetch(domain:www.jgrants-portal.go.jp)"]}}'
    (folder / ".claude" / "settings.local.json").write_text(local, encoding="utf-8")
    ct.ok(env.run(folder))
    assert (folder / ".claude" / "settings.local.json").read_text(encoding="utf-8") == local
    # 社長ごとの設定なので、版の履歴には入れない
    assert all(".claude/settings.local.json" not in row["files"] for row in ct.git_log(plugin_data, folder))


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


def test_failure_on_the_way_undoes_everything(tmp_path, plugin_data) -> None:  # noqa: F811
    """最後の版を残すときに失敗したら、目印・設定・フォルダ・履歴を戻し、前からあったものは元のまま。"""
    env = ct.Env(tmp_path, plugin_data)
    folder = env.folder()
    (folder / "メモ.txt").write_text("前からある", encoding="utf-8")
    (folder / "原本").mkdir()
    (folder / "原本" / "見積書.pdf").write_bytes(b"%PDF")
    before = contents(folder)

    assert ct.venv_json(plugin_data, ROLLBACK_CODE, str(folder)) == "失敗した"
    assert contents(folder) == before
    assert not (folder / ".hojokin").exists()


# ---- 結果の文 ----


def test_output_returns_common_rules(tmp_path, plugin_data) -> None:  # noqa: F811
    """初めて使うセッションに、どの段階にも共通の決まりの短い文（1,200字ほど）を返す。"""
    env = ct.Env(tmp_path, plugin_data)
    folder = env.folder()
    out = ct.ok(env.run(folder))
    assert common_rules.TEXT in out
    for heading in ("聞き方", "決めつけずに確かめる", "記録に残すか", "説明"):
        assert heading in common_rules.TEXT, heading
    assert "3つまで" in common_rules.TEXT
    # 質問と仮の印の書き方（DESIGN 6章）。Stop hook が質問の記録を残すのは、この形から
    for form in ("【質問】", "（理由：", "AskUserQuestion", "【仮：", "【空欄："):
        assert form in common_rules.TEXT, form
    # 開いたときに渡す情報（10,000字以内）を圧迫しない長さ
    assert len(common_rules.TEXT) <= 1500
    # 社長に伝えること：書類の入れ方、履歴をパソコンの外に送らないこと、auto モードの案内（4.7）
    assert "入れ口" in out and "インターネットには送りません" in out and "auto" in out


# ---- 会社のフォルダの外、引数と場所 ----


def test_nothing_outside_changes(tmp_path, plugin_data) -> None:  # noqa: F811
    """プラグインの写し（__pycache__ を書かない）、HOME、一時ファイルの置き場、今いるフォルダ、隣のフォルダは変わらない。"""
    env = ct.Env(tmp_path, plugin_data)
    folder = env.folder()
    neighbor = env.folder("隣の会社")
    (neighbor / "書類.pdf").write_bytes(b"%PDF")
    before = env.outside()
    neighbor_before = hr.snapshot(neighbor)
    stamp = (runtime.venv_dir(plugin_data) / runtime.STAMP_FILE).read_bytes()
    ct.ok(env.run(folder))
    assert env.outside() == before
    assert hr.snapshot(neighbor) == neighbor_before
    assert (runtime.venv_dir(plugin_data) / runtime.STAMP_FILE).read_bytes() == stamp


def test_without_data_dir_writes_nothing(tmp_path, plugin_data) -> None:  # noqa: F811
    env = ct.Env(tmp_path, plugin_data)
    folder = env.folder()
    r = env.run(args=["--folder", str(folder)])
    out = r.stdout.decode("utf-8")
    assert r.returncode == 1, out
    assert "CLAUDE_PLUGIN_DATA" in out and "何も変えていません" in out
    assert list(folder.iterdir()) == []


def test_folder_defaults(tmp_path, plugin_data) -> None:  # noqa: F811
    """--folder がなければ CLAUDE_PROJECT_DIR、それもなければ今いるフォルダ。データの置き場も環境変数で受け付ける。"""
    env = ct.Env(tmp_path, plugin_data)
    by_cwd = env.folder("今いるフォルダ")
    ct.ok(env.run(args=["--data-dir", str(plugin_data)], cwd=by_cwd))
    assert (by_cwd / ".hojokin").is_dir()

    by_env = env.folder("開いたフォルダ")
    ct.ok(env.run(args=[], extra_env={"CLAUDE_PLUGIN_DATA": str(plugin_data), "CLAUDE_PROJECT_DIR": str(by_env)}))
    assert (by_env / ".hojokin").is_dir()
    assert not (env.cwd / ".hojokin").exists()


# ---- 補助プログラムの準備（通信する。開発用の Stop hook では流さない） ----


@pytest.mark.slow
def test_setup_failure_writes_nothing(tmp_path, plugin_data) -> None:  # noqa: F811
    """ライブラリを入れられないとき（通信できないなど）は、分かる文で止まり、会社のフォルダに何も書かない。"""
    env = ct.Env(tmp_path, plugin_data)
    folder = env.folder()
    data = tmp_path / "空のデータの置き場"
    r = env.run(folder, data=data, extra_env={"PIP_NO_INDEX": "1"}, timeout=300)
    out = r.stdout.decode("utf-8")
    assert r.returncode == 1, out
    assert "インターネット" in out and "何も変えていません" in out
    assert list(folder.iterdir()) == []
    # 次に動いたときに入れ直せるよう、入れ終わった印は残さない
    assert not (runtime.venv_dir(data) / runtime.STAMP_FILE).exists()


@pytest.mark.slow
def test_broken_venv_is_rebuilt(tmp_path, plugin_data) -> None:  # noqa: F811
    """venv が動かなくなっていたら（開発ツールの更新など）、作り直してから会社のフォルダを用意する。uv も git も使わない。"""
    env = ct.Env(tmp_path, plugin_data)
    folder = env.folder()
    data = tmp_path / "データの置き場"
    broken = runtime.venv_python(data)
    broken.parent.mkdir(parents=True)
    broken.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    broken.chmod(0o755)

    out = ct.ok(env.run(folder, data=data, timeout=600))
    assert "会社のフォルダを用意しました" in out
    assert (runtime.venv_dir(data) / runtime.STAMP_FILE).read_text(encoding="utf-8") == "\n".join(
        runtime.REQUIREMENTS) + "\n"
    code = "from importlib.metadata import version; print(version('dulwich'))"
    r = subprocess.run([str(runtime.venv_python(data)), "-B", "-c", code], capture_output=True)
    assert r.stdout.decode().strip() == "0.24.10"
