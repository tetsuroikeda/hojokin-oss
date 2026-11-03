"""T0-8 履歴を外に送らない。

SPEC：会社のフォルダの Git の設定を見る。合格ライン：送り先（リモート）の設定0件。

会社のフォルダを作る道具（S5）で作った会社のフォルダの .git/config を、3通りで読む。
- 設定のファイルの文字を、そのまま読む（区分と項目の名前）
- dulwich（道具と同じ読み方）
- git のコマンド（あれば）
送り先そのもの（[remote "…"]、remote.pushDefault）と、送り先を指す項目（branch.<名前>.remote など、
名前に remote を含む項目）が0件であることを確かめる。もう一度動かした後も、前からあったファイルを残した後も同じ。
通信を断って作ったとき（eval の中や、通信できないパソコンで初めて使うとき）も同じ。
すでに送り先のある .git があるフォルダは、会社のフォルダにしない（そのまま使うと、送り先が残るため）。
同期されるフォルダ（Google ドライブなど）には、経営者が版の持ち方を選ぶまで履歴を作らない（S5b）。
①②③の段と同意の記録（②の期限の一覧、③の GitHub）は K4 で足す。
DESIGN 5章「版の操作はスクリプトで行い、送る機能を持たせない」も、コードを読んで確かめる（同梱の dulwich の中は除く）。
"""

from __future__ import annotations

import re
import shutil
import subprocess

import company_tool as ct
import hook_runner as hr
import pytest
import test_vendor as tv

SECTION = re.compile(r'^\s*\[\s*([A-Za-z0-9.-]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\]')
KEY = re.compile(r"^\s*([A-Za-z][A-Za-z0-9-]*)\s*(?:=|$)")


def remote_settings_in_text(text: str) -> list:
    """設定のファイルの文字から、送り先にかかわる区分と項目を拾う。"""
    found = []
    section = ""
    for line in text.splitlines():
        line = line.split("#", 1)[0].split(";", 1)[0]
        m = SECTION.match(line)
        if m:
            name = m.group(1).lower()
            # [remote.origin] のような古い書き方も、remote の区分として数える。
            # ほかの設定ファイルの読み込み（include・includeIf）は、その先に送り先があるかもしれないので数える
            section = name
            if name == "remote" or name.startswith("remote.") or name in ("include", "includeif"):
                found.append(line.strip())
            continue
        k = KEY.match(line)
        if k and "remote" in k.group(1).lower():
            found.append(f"{section}.{k.group(1)}")
    return found


def test_text_reader_finds_remotes() -> None:
    """読み方そのものの確かめ：送り先の書き方をどれも拾う。"""
    text = (
        "[core]\n\tbare = false\n"
        '[remote "origin"]\n\turl = https://example.invalid/a.git\n'
        "[remote]\n\tpushDefault = origin\n"
        '[branch "master"]\n\tremote = origin\n\tpushRemote = origin\n'
        "[remote.old]\n\turl = x\n"
    )
    # [remote "origin"]、[remote]（pushDefault の区分）、branch の remote と pushRemote、[remote.old]
    assert len(remote_settings_in_text(text)) == 5
    assert len(remote_settings_in_text('[include]\n\tpath = ~/a\n[includeIf "gitdir:~/x/"]\n\tpath = b\n')) == 2
    assert remote_settings_in_text("[core]\n\tbare = false\n\tlogallrefupdates = true\n") == []


REMOTES_CODE = """
from pathlib import Path
from lib import history
repo = history.open_or_init(Path(sys.argv[1]))
config = repo.get_config()
sections = [[p.decode("utf-8") for p in s] for s in config.sections()]
print(json.dumps({"remotes": history.remotes(repo), "sections": sections}, ensure_ascii=False))
"""


def assert_no_remote(folder) -> None:
    config = folder / ".git" / "config"
    assert config.is_file()
    # 1. 文字のまま。git が今も送り先として読む古い形のファイル（.git/remotes/・.git/branches/）もない
    assert remote_settings_in_text(config.read_text(encoding="utf-8")) == []
    for old in ("remotes", "branches"):
        d = folder / ".git" / old
        assert not d.exists() or [p for p in d.iterdir()] == [], old
    # 2. dulwich
    seen = ct.py_json(REMOTES_CODE, str(folder))
    assert seen["remotes"] == []
    assert all(s[0].lower() != "remote" for s in seen["sections"]), seen["sections"]
    # 3. git のコマンド（あれば）。利用者の設定を混ぜず、このフォルダの設定だけを見る
    git = shutil.which("git")
    if git:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(folder.parent), "GIT_CONFIG_NOSYSTEM": "1"}
        r = subprocess.run([git, "-C", str(folder), "remote", "-v"], capture_output=True, env=env)
        assert r.returncode == 0 and r.stdout == b"", r
        r = subprocess.run([git, "config", "--file", str(config), "--list"], capture_output=True, env=env)
        assert r.returncode == 0, r
        assert [line for line in r.stdout.decode("utf-8").splitlines() if "remote" in line.lower()] == []


def test_no_remote_in_new_company_folder(tmp_path) -> None:
    env = ct.Env(tmp_path)
    folder = env.folder()
    (folder / "決算書_2025年度.pdf").write_bytes(b"%PDF-1.4 dummy")
    ct.ok(env.run(folder))
    assert_no_remote(folder)
    # 前からあったファイルの版（社長）と、用意したものの版（ツール）
    assert len(ct.git_log(folder)) == 2


def test_no_remote_when_made_offline(tmp_path) -> None:
    """通信を断って作っても（eval の中や、通信できないパソコンで初めて使うとき）、同じく送り先0件の履歴ができる。"""
    env = ct.Env(tmp_path)
    folder = env.folder()
    (folder / "決算書_2025年度.pdf").write_bytes(b"%PDF-1.4 dummy")
    ct.ok(env.run(folder, offline=True))
    assert_no_remote(folder)
    assert len(ct.git_log(folder)) == 2
    # もう一度動かしても（通信を断ったまま）、送り先は増えない
    assert "すでに会社のフォルダです" in ct.ok(env.run(folder, offline=True))
    assert_no_remote(folder)


def test_no_remote_after_running_again(tmp_path) -> None:
    env = ct.Env(tmp_path)
    folder = env.folder()
    ct.ok(env.run(folder))
    (folder / "入れ口").rmdir()
    out = ct.ok(env.run(folder))
    assert "すでに会社のフォルダです" in out
    assert_no_remote(folder)


@pytest.mark.parametrize("place", [
    "Library/CloudStorage/GoogleDrive-taro@example.com/マイドライブ/山田製作所",
    "Library/Mobile Documents/com~apple~CloudDocs/山田製作所",
    "Dropbox/山田製作所",
])
def test_no_history_is_made_in_synced_folder(tmp_path, place) -> None:
    """同期されるフォルダ（中身がクラウドに上がる）には、経営者が選ぶまで版の履歴を作らない（S5b）。
    同期されるフォルダの形（版をファイルで残す）ができるまで、そこに Git の形の履歴を置いて上げてしまわない。"""
    env = ct.Env(tmp_path)
    folder = env.home / place
    folder.mkdir(parents=True)
    (folder / "決算書_2025年度.pdf").write_bytes(b"%PDF-1.4 dummy")
    before = hr.snapshot(folder)
    r = env.run(folder)
    out = r.stdout.decode("utf-8")
    assert r.returncode == 2, out
    assert "同期されています" in out and "何も変えていません" in out
    assert not (folder / ".git").exists()
    assert hr.snapshot(folder) == before


SET_REMOTE_CODE = """
import os
from dulwich import porcelain
repo = porcelain.init(sys.argv[1])
config = repo.get_config()
kind = sys.argv[2]
url = b"https://example.invalid/company.git"
if kind == "remote":
    config.set((b"remote", b"origin"), b"url", url)
elif kind == "pushDefault":
    config.set((b"remote",), b"pushDefault", b"origin")
elif kind == "branch":
    config.set((b"branch", b"master"), b"remote", b"origin")
elif kind == "include":
    config.set((b"include",), b"path", "../送り先の設定".encode("utf-8"))
elif kind in ("remotes", "branches"):
    # git が今も送り先として読む、古い形のファイル
    os.makedirs(os.path.join(repo.controldir(), kind), exist_ok=True)
    with open(os.path.join(repo.controldir(), kind, "origin"), "wb") as f:
        f.write(b"URL: " + url + b"\\n" if kind == "remotes" else url + b"\\n")
config.write_to_path()
print("{}")
"""


@pytest.mark.parametrize("kind", ["remote", "pushDefault", "branch", "include", "remotes", "branches"])
def test_existing_git_with_remote_is_refused(tmp_path, kind) -> None:
    """送り先のある .git があるフォルダは、会社のフォルダにしない。何も書かない。"""
    env = ct.Env(tmp_path)
    folder = env.folder()
    (folder / "メモ.txt").write_text("前からあるファイル", encoding="utf-8")
    ct.py_json(SET_REMOTE_CODE, str(folder), kind)
    before = hr.snapshot(folder)
    outside = env.outside()

    r = env.run(folder)
    out = r.stdout.decode("utf-8")
    assert r.returncode == 2, out
    assert "送り先" in out and "何も変えていません" in out
    assert hr.snapshot(folder) == before
    assert env.outside() == outside
    assert not (folder / ".hojokin").exists()


# 送る・取ってくる・送り先を足す機能。会社のフォルダの版を扱うコードに、1つもあってはならない
# （公式資料の取得など、版と関係のない取得の関数を拾わないよう、dulwich の呼び出しと git のコマンドに絞る）
SENDING = r"(push|pull|fetch|clone|ls_remote|remote_add|submodule_add|get_transport_and_path)"
SEND_CALLS = re.compile(
    rf"porcelain\.{SENDING}\b"
    # dulwich の通信の部分と、コマンドの入口（cli.py・__main__.py。git と同じく push などができる）
    r"|dulwich\.(client|cli)\b"
    rf"|from\s+dulwich(\.porcelain)?\s+import\s+[^\n]*\b(client|cli|{SENDING[1:-1]})\b"
    r"""|-m["',\s]+dulwich\b"""
    r"""|\bgit["',\s]+(push|pull|fetch|clone|remote)\b"""
)


def test_send_pattern_catches_calls() -> None:
    """探し方そのものの確かめ。"""
    for line in ('porcelain.push(repo, "origin")', "from dulwich.client import get_transport_and_path",
                 'subprocess.run(["git", "push"])', "os.system('git remote add origin x')",
                 "from dulwich import cli", "dulwich.cli.main(['push'])",
                 'subprocess.run([sys.executable, "-m", "dulwich", "push"])', "python3 -m dulwich push"):
        assert SEND_CALLS.search(line), line
    for line in ("def fetch(url):", "公式資料を fetch_official(url) で取る", "# git のコマンドは使わない"):
        assert not SEND_CALLS.search(line), line


def test_history_code_has_no_sending() -> None:
    """このプラグインのコードが、送る機能を呼ばない。

    同梱したライブラリ（lib/vendor/。dulwich そのもの）は見ない。dulwich は送る機能も持つが、それを呼ぶのは
    このプラグインのコードだけで、そこを見れば足りる（venv に入れていたときも、dulwich の中は見ていなかった）。
    lib/vendor/ に自前のコードが紛れていないこと（wheel のままであること）は、下の test_bundled_code_is_the_wheel で見る。
    """
    vendor = hr.REPO_ROOT / "lib" / "vendor"
    files = sorted(
        p
        for p in set(hr.REPO_ROOT.glob("lib/**/*.py"))
        | set(hr.REPO_ROOT.glob("skills/*/scripts/**/*.py"))
        | set(hr.REPO_ROOT.glob("hooks/**/*.py"))
        if vendor not in p.parents
    )
    assert any(p.name == "history.py" for p in files)
    assert any(p.name == "init_company.py" for p in files)
    hits = []
    for path in files:
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if SEND_CALLS.search(line):
                hits.append(f"{path.relative_to(hr.REPO_ROOT)}:{no}: {line.strip()}")
    assert hits == []


def test_bundled_code_is_the_wheel() -> None:
    """上の検査から lib/vendor/ を外せるのは、中身が PyPI の wheel のままだから（詳しい確かめは test_vendor.py）。"""
    for name in tv.PACKAGES:
        tv.test_files_match_wheel_record(name)
    tv.test_nothing_else_is_added()
