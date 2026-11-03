"""会社のフォルダの版の履歴（SPEC 共通の要件「書類の版の管理」、DESIGN 5章・10章）。

- Python だけで動く Git（dulwich）で、会社のフォルダの .git に残す。git のコマンドは使わない（実験 E5）。
- 送り先（リモート）は持たせない。送る・取ってくる機能（push・fetch・pull・clone、送り先を足すこと）は、
  ここにも、ほかのどこにも作らない（DESIGN 5章「履歴を外に送らない」）。
- だれが変えたかは、作者の名前（ツール・社長）で残す。利用者の Git の設定（名前、署名など）は使わない。

dulwich はプラグインに同梱している（lib/vendor/。Python だけの形）。通信も venv の準備もなしに、
/usr/bin/python3（3.9）で動く。プラグインの場所に __pycache__ を書かないよう、python3 は -B で動かす。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence

# 同梱の dulwich を読み込む。社長のパソコンに別の版が入っていても同梱の版を使うよう、先頭に入れる
VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

from dulwich import porcelain  # noqa: E402
from dulwich.repo import Repo  # noqa: E402

TOOL = "ツール"
OWNER = "社長"
IDENTITIES = {
    TOOL: "ツール <tool@hojokin.invalid>",
    OWNER: "社長 <owner@hojokin.invalid>",
}


def git_dir(folder: Path) -> Path:
    return folder / ".git"


def open_or_init(folder: Path) -> Repo:
    """会社のフォルダの履歴を開く。なければ作る（送り先は持たない）。"""
    if git_dir(folder).exists():
        return Repo(str(folder))
    return porcelain.init(str(folder))


def remotes(repo: Repo) -> List[str]:
    """履歴にある、送り先にかかわる設定の一覧。0件でなければならない。

    .git/config の、送り先そのもの（[remote "…"]）、送り先の既定（remote.pushDefault）、
    ブランチの送り先（branch.<名前>.remote・pushRemote）、ほかの設定ファイルの読み込み（include・includeIf）。
    git が今も送り先として読む、古い形のファイル（.git/remotes/・.git/branches/ の中）も数える。
    """
    found = []
    config = repo.get_config()
    for section in config.sections():
        if not section:
            continue
        kind = section[0].decode("utf-8", "replace").lower()
        name = section[1].decode("utf-8", "replace") if len(section) > 1 else ""
        if kind == "remote":
            found.append(f"remote {name}".strip())
        elif kind in ("include", "includeif"):
            label = f"{kind} {name}".strip()
            found.append(f"{label}（ほかの設定ファイルの読み込み）")
        elif kind == "branch":
            for key, _value in config.items(section):
                if key.decode("utf-8", "replace").lower() in ("remote", "pushremote"):
                    found.append(f"branch {name} の {key.decode('utf-8', 'replace')}")
    for old in ("remotes", "branches"):
        folder = Path(repo.controldir()) / old
        if folder.is_dir():
            found += [f".git/{old}/{p.name}" for p in sorted(folder.iterdir()) if p.is_file()]
    return found


def has_commits(repo: Repo) -> bool:
    try:
        repo.head()
    except KeyError:
        return False
    return True


def tracked_paths(repo: Repo) -> List[str]:
    return sorted(p.decode("utf-8") if isinstance(p, bytes) else p for p in porcelain.ls_files(repo))


def commit(folder: Path, message: str, who: str, paths: Optional[Sequence[Path]] = None) -> Optional[bytes]:
    """変わったファイルを、だれが変えたかを付けて1件の版に残す。変わったものがなければ None。

    paths を渡したときは、そのファイルだけを加える（ほかの変更は、だれが変えたかを後で見分けるため残す）。
    渡さないときは、増えたファイルと変わったファイルをすべて加える。.gitignore にあるものは加えない。
    """
    identity = IDENTITIES[who].encode("utf-8")
    repo = Repo(str(folder))
    try:
        if paths is None:
            porcelain.add(repo)
        else:
            existing = [str(p) for p in paths if Path(p).exists()]
            if existing:
                porcelain.add(repo, paths=existing)
        status = porcelain.status(repo, untracked_files="no")
        if not any(status.staged.values()):
            return None
        return porcelain.commit(
            repo,
            message=message.encode("utf-8"),
            author=identity,
            committer=identity,
            # 利用者の Git の設定（署名、commit の前の処理）に左右されないようにする
            sign=False,
            no_verify=True,
        )
    finally:
        repo.close()


def changed_paths(folder: Path) -> List[str]:
    """最後の版から変わったファイル（増えた・変わった・消えた）。.gitignore にあるものは除く。"""
    repo = Repo(str(folder))
    try:
        status = porcelain.status(repo, untracked_files="all")
    finally:
        repo.close()
    names = [p for paths in status.staged.values() for p in paths] + list(status.unstaged) + list(status.untracked)
    return sorted({os.fsdecode(p) if isinstance(p, bytes) else p for p in names})
