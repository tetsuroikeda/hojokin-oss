"""会社のフォルダの版の履歴（SPEC 共通の要件「書類の版の管理」、DESIGN 5章・10章）。

- Python だけで動く Git（dulwich）で、会社のフォルダの .git に残す。git のコマンドは使わない（実験 E5）。
- 送り先（リモート）は持たせない。送る・取ってくる機能（push・fetch・pull・clone、送り先を足すこと）は、
  ここにも、ほかのどこにも作らない（DESIGN 5章「履歴を外に送らない」）。
- だれが変えたかは、作者の名前（ツール・社長）で残す。利用者の Git の設定（名前、署名、改行の扱いなど）と、
  全体の除外の指定（~/.config/git/ignore、core.excludesFile）は読まない（DESIGN 10章。下の差し替え）。

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
from dulwich.config import StackedConfig  # noqa: E402
from dulwich.ignore import IgnoreFilterManager  # noqa: E402
from dulwich.repo import Repo  # noqa: E402

DEFAULT_BRANCH = b"master"


# ---- 利用者の Git の設定と、全体の除外の指定を読まない（DESIGN 10章） ----
#
# dulwich は、そのままでは次を読む。
# - 利用者の Git の設定（~/.gitconfig、$XDG_CONFIG_HOME/git/config、GIT_CONFIG_GLOBAL、/etc/gitconfig）。
#   core.autocrlf（改行を書き換えて残す）、core.excludesFile（全体の除外の指定の場所）などが、版の中身に効く。
# - 全体の除外の指定（core.excludesFile、なければ ~/.config/git/ignore）と、.git/info/exclude。
#   社長のパソコンに「*.pdf」のような行があると、書類が黙って履歴から抜ける。
# 同梱の dulwich は書き換えない（wheel のまま。tests/test_vendor.py）ので、ここで振る舞いを差し替える。
# このプラグインで dulwich を使うのは会社のフォルダの履歴だけなので、クラスごと差し替えてよい。


def _local_config_stack(self: Repo) -> StackedConfig:
    """会社のフォルダの .git/config だけを読む設定（利用者とパソコン全体の Git の設定は読まない）。"""
    local = self.get_config()
    return StackedConfig([local], writable=local)


def _ignore_from_repo(cls, repo: Repo) -> IgnoreFilterManager:
    """版の履歴に入れないものは、会社のフォルダの .gitignore だけで決める。"""
    ignorecase = repo.get_config().get_boolean((b"core",), b"ignorecase", False)
    return cls(repo.path, [], ignorecase)


Repo.get_config_stack = _local_config_stack  # type: ignore[method-assign]
IgnoreFilterManager.from_repo = classmethod(_ignore_from_repo)  # type: ignore[method-assign]

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
    # ブランチの名前も、利用者の設定（init.defaultBranch）によらず決める
    return Repo.init(str(folder), default_branch=DEFAULT_BRANCH)


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


# ---- 版の記録（TASKS M0a。DESIGN 5章「版を自動で残す」、10章「書類の版」） ----
#
# hook（SessionStart・UserPromptSubmit・Stop）が、最後の版から変わったファイルをまとめて1件の版に残す。
# - だれ（ツール・社長）と理由は版ごとに、書類・変更・案件・段階は書類ごとに、版のメッセージに書く（下の形）。
#   履歴を読むとき（log）は、書類ごとの1件に分けて返す（T0-6「履歴3件に日時・書類・理由・だれ」）。
# - 版の日時は、日本時間で残す。今日の日付を差し替えていれば、その日付にする（呼ぶ側が when で渡す）。
# - ファイルの名前は、濁点が分かれた形（Finder などで作られる NFD）を1文字の形（NFC）にそろえて残す（実験 E5）。
#   作業のファイルの名前そのものは変えない（原本の置き場に移すときにそろえるのは、書類を整理するスクリプト）。
# - 変わったかどうかは、ファイルの大きさ・更新時刻・状態の変わった時刻が前と同じなら読まずに同じとみなし、
#   違えば中身のハッシュで比べる（Word・PDF が多くても、応答のたびに全部を読まないため）。
# - 履歴に入れないものは、会社のフォルダの .gitignore で決める。.git と、このプラグインのその場限りの置き場
#   （.hojokin/一時/）は、.gitignore がなくても入れない。
#
# 版のメッセージの形（人が git で読んでも分かり、M0b・M0c の道具が読み返せる形）：
#
#   ツール：その1.docx ほか1件
#
#   理由: 計画書のその1を書いて
#   だれ: ツール
#
#   書類: 案件/2026_省力化（一般型）第9回/1_申請/申請書/その1.docx
#   変更: 変えた
#   案件: 2026_省力化（一般型）第9回
#   段階: 1_申請
#
#   書類: 記録/会社の記録.json
#   変更: 足した
#   案件: —
#   段階: —

import contextlib  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
import unicodedata  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from typing import Dict, Iterator, Tuple  # noqa: E402

from dulwich.index import ConflictedIndexEntry, IndexEntry, blob_from_path_and_stat, cleanup_mode  # noqa: E402
from dulwich.object_store import tree_lookup_path  # noqa: E402
from dulwich.objects import Commit  # noqa: E402

from lib import case_folder, company  # noqa: E402

ADDED = "足した"
MODIFIED = "変えた"
DELETED = "消した"
OWNER_REASON = "社長が手で変更"
NOT_APPLICABLE = "—"
# 理由（社長の依頼の文）は1行にそろえ、この字数で切る（仮。TASKS M0a の質問）
REASON_MAX_CHARS = 100
JST = timezone(timedelta(hours=9), "JST")
# 履歴に入れない場所（.gitignore がなくても）
ALWAYS_SKIPPED_DIRS = (".git", f"{company.MARKER_DIR}/{company.TEMP_DIR}")
LOCK_NAME = "hojokin-record.lock"
LOCK_WAIT_SECONDS = 5.0
LOCK_STALE_SECONDS = 120.0
YEAR_DIR = re.compile(r"^[0-9]+年目$")
_TREE_KIND = {"add": ADDED, "modify": MODIFIED, "delete": DELETED}


class HistoryBusy(Exception):
    """ほかの処理が、同じ会社のフォルダの版を残しているところ。"""


@dataclass
class Change:
    """最後の版から変わったファイル1つ。path は会社のフォルダからの場所（NFC、区切りは「/」）。"""

    path: str
    kind: str
    fs_path: Optional[str] = None  # 作業のファイルの実際の場所（足した・変えた）
    index_key: Optional[bytes] = None  # 履歴の中の名前（変えた・消した。NFD のこともある）


@dataclass
class Record:
    """履歴の1件（書類ごと）。version は版の印（40桁）。"""

    version: str
    time: datetime
    document: str
    change: str
    reason: str
    who: str
    case: str
    stage: str

    def as_dict(self) -> dict:
        return {
            "版": self.version,
            "日時": self.time.isoformat(),
            "書類": self.document,
            "変更": self.change,
            "理由": self.reason,
            "だれ": self.who,
            "案件": self.case,
            "段階": self.stage,
        }


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def enabled(folder: Path) -> bool:
    """会社のフォルダに Git の形の版の履歴があるか（ないときは、hook は何も書かない）。"""
    return git_dir(folder).is_dir()


def case_and_stage(path: str) -> Tuple[str, str]:
    """書類の場所から、案件と段階を出す。`案件/<案件>/<段階>/…` の形でなければ空。

    段階は「1_申請」の形のフォルダ。効果報告の年のフォルダ（「4_効果報告/1年目」）は、年まで含める。
    """
    parts = nfc(path).split("/")
    if len(parts) < 3 or parts[0] != case_folder.CASES_DIR:
        return "", ""
    case = parts[1]
    stage = ""
    if len(parts) >= 4 and case_folder.STAGE_NAME.match(parts[2]):
        stage = parts[2]
        if len(parts) >= 5 and YEAR_DIR.match(parts[3]):
            stage = f"{parts[2]}/{parts[3]}"
    return case, stage


def one_line(text: str, limit: Optional[int] = None) -> str:
    """改行と続く空白を1つの空白にそろえる。limit を超えたら切って「…」を付ける。"""
    line = " ".join(nfc(str(text)).split())
    if limit is not None and len(line) > limit:
        line = line[: limit - 1] + "…"
    return line


@contextlib.contextmanager
def locked(folder: Path) -> Iterator[None]:
    """同じ会社のフォルダで、版を残す処理を1つずつにする（2つのセッションの hook が重なったとき）。"""
    path = git_dir(folder) / LOCK_NAME
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            break
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > LOCK_STALE_SECONDS:
                # 途中で止まった処理の残り
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
                continue
            if time.monotonic() > deadline:
                raise HistoryBusy("ほかの処理が版を残しているところです")
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def _rel(dirpath: str, root: str, name: str) -> str:
    rel_dir = os.path.relpath(dirpath, root)
    rel_dir = "" if rel_dir == "." else nfc(rel_dir).replace(os.sep, "/")
    return f"{rel_dir}/{nfc(name)}" if rel_dir else nfc(name)


def _skipped_dir(rel: str) -> bool:
    return rel in ALWAYS_SKIPPED_DIRS or rel.rsplit("/", 1)[-1] == ".git"


def _under_skipped_dir(rel: str) -> bool:
    parts = rel.split("/")
    return any(_skipped_dir("/".join(parts[:i])) for i in range(1, len(parts)))


def _work_files(folder: Path, repo: Repo) -> Dict[str, str]:
    """作業のファイルの一覧（NFC の場所 → 実際の場所）。.gitignore にあるものと、履歴に入れない場所は除く。"""
    ignore = IgnoreFilterManager.from_repo(repo)
    root = str(folder)
    found: Dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        keep = []
        for name in sorted(dirnames):
            rel = _rel(dirpath, root, name)
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                # 別名のフォルダは、Git と同じく、別名そのものを1つのファイルとして扱う（先はたどらない）
                if not ignore.is_ignored(rel):
                    found.setdefault(rel, full)
                continue
            if _skipped_dir(rel) or ignore.is_ignored(rel + "/"):
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            rel = _rel(dirpath, root, name)
            if ignore.is_ignored(rel):
                continue
            found.setdefault(rel, os.path.join(dirpath, name))
    return found


def _exists_exactly(folder: Path, rel: str) -> Optional[str]:
    """その名前のファイルが（大文字と小文字・濁点の形を区別して）あれば、実際の場所を返す。"""
    parts = rel.split("/")
    current = str(folder)
    for part in parts:
        try:
            names = os.listdir(current)
        except OSError:
            return None
        match = next((n for n in names if nfc(n) == part), None)
        if match is None:
            return None
        current = os.path.join(current, match)
    return current if not os.path.isdir(current) or os.path.islink(current) else None


def _time_ns(value) -> Optional[int]:
    if isinstance(value, tuple):
        return value[0] * 1_000_000_000 + value[1]
    if isinstance(value, int):
        return value * 1_000_000_000
    return None  # 小数で残した時刻は、ナノ秒まで合わないので比べない


def _entry_from_stat(st: os.stat_result, sha: bytes) -> IndexEntry:
    return IndexEntry(
        ctime=(st.st_ctime_ns // 1_000_000_000, st.st_ctime_ns % 1_000_000_000),
        mtime=(st.st_mtime_ns // 1_000_000_000, st.st_mtime_ns % 1_000_000_000),
        dev=st.st_dev & 0xFFFFFFFF,
        ino=st.st_ino & 0xFFFFFFFF,
        mode=cleanup_mode(st.st_mode),
        uid=st.st_uid & 0xFFFFFFFF,
        gid=st.st_gid & 0xFFFFFFFF,
        size=st.st_size & 0xFFFFFFFF,
        sha=sha,
    )


def _same_as_entry(fs_path: str, entry: IndexEntry) -> Tuple[bool, Optional[IndexEntry]]:
    """作業のファイルが履歴の中身と同じか。同じで、時刻などだけが違うときは、書き直した記録を返す。"""
    st = os.lstat(fs_path)
    if cleanup_mode(st.st_mode) != entry.mode or (st.st_size & 0xFFFFFFFF) != entry.size:
        return False, None
    if _time_ns(entry.mtime) == st.st_mtime_ns and _time_ns(entry.ctime) == st.st_ctime_ns:
        return True, None
    blob = blob_from_path_and_stat(os.fsencode(fs_path), st)
    if blob.id != entry.sha:
        return False, None
    return True, _entry_from_stat(st, entry.sha)


def _compare(folder: Path, repo: Repo, index) -> Tuple[List[Change], Dict[bytes, IndexEntry]]:
    """最後の版（index）と作業のファイルを比べる。変わったものと、書き直すだけの記録を返す。"""
    files = _work_files(folder, repo)
    tracked: Dict[str, Tuple[bytes, object]] = {}
    for key, entry in index.items():
        tracked.setdefault(nfc(key.decode("utf-8", "surrogateescape")), (key, entry))
    changes: List[Change] = []
    refresh: Dict[bytes, IndexEntry] = {}
    for name in sorted(set(files) | set(tracked)):
        fs_path = files.get(name)
        if name not in tracked:
            changes.append(Change(name, ADDED, fs_path=fs_path))
            continue
        key, entry = tracked[name]
        if fs_path is None:
            # 履歴にあって一覧にないもの。.gitignore に後から足されたものは、Git と同じく続けて見る
            fs_path = None if _under_skipped_dir(name) else _exists_exactly(folder, name)
            if fs_path is None:
                changes.append(Change(name, DELETED, index_key=key))
                continue
        if isinstance(entry, ConflictedIndexEntry):
            changes.append(Change(name, MODIFIED, fs_path=fs_path, index_key=key))
            continue
        same, fresh = _same_as_entry(fs_path, entry)
        if not same:
            changes.append(Change(name, MODIFIED, fs_path=fs_path, index_key=key))
        elif fresh is not None:
            refresh[key] = fresh
    return changes, refresh


def pending_changes(folder: Path) -> List[Change]:
    """最後の版から変わったファイル（読むだけ。何も書かない）。"""
    repo = Repo(str(folder))
    try:
        changes, _ = _compare(folder, repo, repo.open_index())
    finally:
        repo.close()
    return changes


def format_message(who: str, reason: str, changes: Sequence[Change]) -> str:
    """版のメッセージ（上の形）。"""
    first = changes[0].path.rsplit("/", 1)[-1]
    subject = f"{who}：{first}" + (f" ほか{len(changes) - 1}件" if len(changes) > 1 else "")
    lines = [subject, "", f"理由: {one_line(reason, REASON_MAX_CHARS)}", f"だれ: {who}", ""]
    for ch in changes:
        case, stage = case_and_stage(ch.path)
        lines += [
            f"書類: {one_line(ch.path)}",
            f"変更: {ch.kind}",
            f"案件: {case or NOT_APPLICABLE}",
            f"段階: {stage or NOT_APPLICABLE}",
            "",
        ]
    return "\n".join(lines)


def parse_message(text: str) -> Tuple[str, Dict[str, str], Dict[str, Dict[str, str]]]:
    """版のメッセージを読む。(件名, 版の項目（理由・だれ）, 書類ごとの項目) を返す。"""
    lines = text.splitlines()
    subject = lines[0] if lines else ""
    header: Dict[str, str] = {}
    documents: Dict[str, Dict[str, str]] = {}
    current: Optional[Dict[str, str]] = None
    for line in lines[1:]:
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        if key == "書類":
            current = {}
            documents[nfc(value)] = current
        elif current is not None:
            current[key] = "" if value == NOT_APPLICABLE else value
        elif key in ("理由", "だれ"):
            header[key] = value
    return subject, header, documents


def record(folder: Path, who: str, reason: str, when: Optional[datetime] = None) -> List[Change]:
    """最後の版から変わったファイルを、だれ・理由を付けて1件の版に残す。残したものの一覧を返す（なければ空）。

    when は版の日時（今日の日付の差し替えを含む。dates.now）。渡さなければ今の日本時間。
    """
    identity = IDENTITIES[who].encode("utf-8")
    moment = (when or datetime.now(timezone.utc)).astimezone(JST)
    with locked(folder):
        repo = Repo(str(folder))
        try:
            index = repo.open_index()
            changes, refresh = _compare(folder, repo, index)
            for key, entry in refresh.items():
                index[key] = entry
            if changes:
                for ch in changes:
                    if ch.index_key is not None and ch.index_key in index:
                        del index[ch.index_key]
                    if ch.kind == DELETED:
                        continue
                    st = os.lstat(ch.fs_path)
                    blob = blob_from_path_and_stat(os.fsencode(ch.fs_path), st)
                    repo.object_store.add_object(blob)
                    # 履歴の中の名前は NFC にそろえる
                    index[ch.path.encode("utf-8")] = _entry_from_stat(st, blob.id)
                tree = index.commit(repo.object_store)
                parent = repo.refs[b"HEAD"] if has_commits(repo) else None
                if parent is not None and repo[parent].tree == tree:
                    # 中身は最後の版と同じ（前に途中で止まった処理の残りなど）。記録だけをそろえる
                    changes = []
                else:
                    commit_obj = Commit()
                    commit_obj.tree = tree
                    commit_obj.parents = [parent] if parent is not None else []
                    commit_obj.author = commit_obj.committer = identity
                    commit_obj.author_time = commit_obj.commit_time = int(moment.timestamp())
                    commit_obj.author_timezone = commit_obj.commit_timezone = 9 * 3600
                    commit_obj.message = format_message(who, reason, changes).encode("utf-8")
                    repo.object_store.add_object(commit_obj)
                    if not repo.refs.set_if_equals(b"HEAD", parent, commit_obj.id):
                        raise HistoryBusy("ほかの処理が、同じときに版を残しました")
            if changes or refresh:
                index.write()
            return changes
        finally:
            repo.close()


def _who_from_author(author: bytes) -> str:
    """作者の名前（ツール・社長）。"""
    return author.decode("utf-8", "replace").split(" <", 1)[0]


def log(folder: Path, document: Optional[str] = None, limit: Optional[int] = None) -> List[Record]:
    """履歴を、書類ごとの1件にして新しい順に返す。document を渡すと、その書類の分だけ。

    M0a より前の版（会社のフォルダを用意したときの版など。メッセージに書類ごとの項目がない）は、
    件名を理由とし、案件と段階は場所から出す。
    """
    target = nfc(document) if document is not None else None
    records: List[Record] = []
    repo = Repo(str(folder))
    try:
        if not has_commits(repo):
            return []
        for entry in repo.get_walker():
            c = entry.commit
            subject, header, documents = parse_message(c.message.decode("utf-8", "replace"))
            who = header.get("だれ") or _who_from_author(c.author)
            reason = header.get("理由") or subject
            when = datetime.fromtimestamp(c.author_time, timezone(timedelta(seconds=c.author_timezone))).astimezone(JST)
            kinds: Dict[str, List[str]] = {}
            for ch in entry.changes():
                # 消したときは new が、足したときは old が空（None か、中が None の形）
                new_path = getattr(ch.new, "path", None)
                raw = new_path if new_path is not None else ch.old.path
                kinds.setdefault(nfc(raw.decode("utf-8", "surrogateescape")), []).append(ch.type)
            for path in sorted(kinds):
                if target is not None and path != target:
                    continue
                meta = documents.get(path, {})
                types = kinds[path]
                # 名前の形を NFC にそろえたときは、消したと足したが同じ書類に並ぶ
                default_kind = MODIFIED if len(types) > 1 else _TREE_KIND.get(types[0], MODIFIED)
                case, stage = case_and_stage(path)
                records.append(Record(
                    version=c.id.decode("ascii"),
                    time=when,
                    document=path,
                    change=meta.get("変更") or default_kind,
                    reason=reason,
                    who=who,
                    case=meta.get("案件", case),
                    stage=meta.get("段階", stage),
                ))
                if limit is not None and len(records) >= limit:
                    return records
    finally:
        repo.close()
    return records


def content_at(folder: Path, version: str, document: str) -> Optional[bytes]:
    """その版の、その書類の中身。その版になければ None。"""
    repo = Repo(str(folder))
    try:
        commit_obj = repo[version.encode("ascii")]
        for form in ("NFC", "NFD"):
            path = unicodedata.normalize(form, document).encode("utf-8")
            try:
                _mode, sha = tree_lookup_path(repo.__getitem__, commit_obj.tree, path)
            except KeyError:
                continue
            return repo[sha].data
        return None
    finally:
        repo.close()
