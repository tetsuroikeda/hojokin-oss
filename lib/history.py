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
    版の履歴に書く処理は、どれも locked() の中で1つずつ動かす（途中で止まった処理の錠を片付けられるように）。
    """
    with locked(folder):
        return _commit(folder, message, who, paths)


def _commit(folder: Path, message: str, who: str, paths: Optional[Sequence[Path]]) -> Optional[bytes]:
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
# hook の見張り（hooks/run.sh。開いたとき・送ったときは25秒、応答の終わりは55秒）に止められないよう、
# 1回の場面で使う時間に上限（budget）を設ける（DESIGN 5章「補助プログラムが動かないときは止める」の備え）。
# - 上限までに残しきれないファイルは、次の場面に回す。回したファイルは `.hojokin/一時/版の記録/残り.json` に、
#   回した場面のだれ・理由を控え、次の場面ではその控えのだれ・理由で先に残す（社長が入れた写真を、次の応答の
#   終わりに「ツール」として残さないため）。
# - 中身は1MB ごとに読みながら印（ハッシュ）を計算し、そのまま .git に書く（大きなファイルでも、全部をメモリに
#   読まない）。上限を過ぎたら、そのファイルの途中でもやめて次の場面に回す。1MB 以上のファイルは圧縮しない
#   （写真・PDF・Word はもともと圧縮されていて、圧縮すると10倍ほど遅くなるため。git でもそのまま読める）。
# - 大きすぎるファイル（LARGE_FILE_BYTES を超えるもの）と、上限で途中までしか読めないことが続いたファイルは、
#   版に残さず、開いたときに Claude に知らせる（hooks/version_hooks.py）。
# - それでも見張りに止められたとき（遅いディスクなど）に備え、版の錠に動いている処理の番号（pid）を書く。
#   錠を持つ処理がもう動いていなければ、すぐに錠を外し、dulwich が残した錠（`.git/index.lock`、
#   `.git/objects/xx/….lock` など）と書きかけのファイルも片付けてから残す。
#
# 1つのファイルやフォルダを読めないとき（権限がない、読む途中で失敗した）と、比べた後に消えたときは、
# そのファイルだけを飛ばし、ほかのファイルは残す（場面ごと止めない）。
# - 読めないものは、版に残さず（消したことにもしない）、開いたときに Claude に知らせる。最初に見つけた場面の
#   だれ・理由を `残り.json` に控え、読めるようになったら、その控えのだれ・理由で残す。
# - 比べた後に消えたものは、次の場面で比べ直す。
# - .git の側（中身や記録を書く所）の失敗は、これまでどおり場面ごと止める（hooks/version_hooks.py が控えて知らせる）。
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
import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import stat as stat_mode  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import unicodedata  # noqa: E402
import zlib  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from typing import Dict, Iterator, Set, Tuple  # noqa: E402

from dulwich.index import ConflictedIndexEntry, IndexEntry, cleanup_mode  # noqa: E402
from dulwich.object_store import tree_lookup_path  # noqa: E402
from dulwich.objects import Blob, Commit  # noqa: E402

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
# 錠を持つ処理の番号が読めないときに、古い残りとみなすまでの秒数（hook は長くても55秒で止められる）
LOCK_STALE_SECONDS = 120.0
# 錠を持つ処理がまだ動いているように見えても、dulwich・git の錠がこの秒数より古ければ残りとみなす
# （手で動かした git が、いま書いているところの錠は消さない）
LEFTOVER_SECONDS = 60.0
# 書きかけの中身を置く名前（.git/objects/ の直下。書き終えたら、印の名前に移す）
TMP_OBJECT_PREFIX = "hojokin-tmp-"
# 次の場面に回したファイルの控え（だれ・理由）。その場限りの置き場なので、版の履歴に入れない
STATE_DIR = f"{company.MARKER_DIR}/{company.TEMP_DIR}/版の記録"
LEFTOVER_FILE = "残り.json"
# 1つのファイルの大きさの上限。超えるものは版に残さず、開いたときに知らせる（仮。TASKS M0a の質問）
LARGE_FILE_BYTES = 2 * 1024 ** 3
# これより大きいファイルは圧縮しない
STORE_ONLY_BYTES = 1024 ** 2
# 残せるかを前もって見積もるときの速さ（遅めのパソコンを見込む。この Mac では 800MB/秒ほど出た）
ESTIMATED_BYTES_PER_SECOND = 100 * 1024 ** 2
# 上限で途中までしか読めないことがこの回数続いたファイルは、大きすぎるものとして扱う
MAX_ABORTS = 2
CHUNK_BYTES = 1024 ** 2
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
    unsure: bool = False  # 時間の上限で、中身が変わったかを比べきれなかった（次の場面で比べる）
    entry: Optional[IndexEntry] = None  # 残すときの記録（中身を書いた後）
    unreadable: bool = False  # 読めなかった（権限がないなど）。版に残さず、知らせる


@dataclass
class Result:
    """1回の場面で版を残した結果。"""

    recorded: List[Change] = field(default_factory=list)  # 版に残したもの（前の場面から回したものを含む）
    mine: List[Change] = field(default_factory=list)  # この場面のだれ・理由に当たるもの（残した・回した）
    deferred: List[Change] = field(default_factory=list)  # 時間の上限で、次の場面に回したもの
    too_large: List[Change] = field(default_factory=list)  # 大きすぎて、版に残さないもの
    known_dirs: Set[str] = field(default_factory=set)  # この場面より前の版にあったフォルダ
    unreadable: List[Change] = field(default_factory=list)  # 読めなくて、版に残さないファイル
    unreadable_dirs: List[str] = field(default_factory=list)  # 中を読めないフォルダ（会社のフォルダからの場所）


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


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # Windows の os.kill は、合図0でも処理を止めてしまうので使わない（古さだけで判断する）
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # 調べることを許されないとき（ほかの利用者の処理など）は、動いているとみなす
        return True
    return True


def _lock_state(path: Path) -> Tuple[Optional[str], Optional[bool]]:
    """錠の中身と、途中で止まった処理の残りか。錠がもうなければ (None, None)。"""
    try:
        st = path.stat()
        text = path.read_bytes().decode("ascii", "replace").strip()
    except FileNotFoundError:
        return None, None
    except OSError:
        return "", False
    if time.time() - st.st_mtime > LOCK_STALE_SECONDS:
        return text, True
    if text.isdigit():
        return text, not _pid_alive(int(text))
    return text, False


def _git_leftovers(gdir: Path) -> List[Path]:
    """dulwich（と git）が書いている間だけ置く錠と、書きかけの中身の一覧。"""
    found = [gdir / name for name in ("index.lock", "HEAD.lock", "packed-refs.lock", "config.lock")]
    refs = gdir / "refs"
    for dirpath, _dirnames, filenames in os.walk(str(refs)):
        found += [Path(dirpath) / name for name in filenames if name.endswith(".lock")]
    objects = gdir / "objects"
    try:
        entries = list(os.scandir(str(objects)))
    except OSError:
        entries = []
    for entry in entries:
        if entry.name.startswith(TMP_OBJECT_PREFIX):
            found.append(Path(entry.path))
        elif len(entry.name) == 2 and entry.is_dir(follow_symlinks=False):
            try:
                found += [Path(e.path) for e in os.scandir(entry.path) if e.name.endswith(".lock")]
            except OSError:
                continue
    return found


def clear_leftovers(folder: Path, min_age: float = LEFTOVER_SECONDS) -> List[str]:
    """途中で止まった処理が .git に残した錠と書きかけの中身を消す。消したものの場所（.git から）を返す。

    版の錠（locked）を持っている間だけ呼ぶ。版の履歴に書く処理はどれも版の錠の中で動くので、
    ここにある錠は、止められた処理の残り。手で動かした git の錠を消さないよう、min_age より新しいものは残す
    （錠を持っていた処理がもう動いていないと分かったときは、0 で呼ぶ）。
    """
    gdir = git_dir(folder)
    now = time.time()
    removed = []
    for path in _git_leftovers(gdir):
        try:
            if now - os.lstat(str(path)).st_mtime < min_age:
                continue
            os.unlink(str(path))
        except OSError:
            continue
        removed.append(path.relative_to(gdir).as_posix())
    return removed


@contextlib.contextmanager
def locked(folder: Path) -> Iterator[None]:
    """同じ会社のフォルダで、版を残す処理を1つずつにする（2つのセッションの hook が重なったとき）。

    錠（.git/hojokin-record.lock）には、持っている処理の番号（pid）を書く。その処理がもう動いていなければ
    （hook の見張りに止められたときなど）、すぐに外し、その処理が残した dulwich の錠も片付ける。
    """
    path = git_dir(folder) / LOCK_NAME
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    holder_gone = False
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            break
        except FileExistsError:
            text, stale = _lock_state(path)
            if stale is None:
                continue
            if stale:
                # 途中で止まった処理の残り。ほかの処理が先に取り直していないかを、中身で確かめてから外す
                again, _ = _lock_state(path)
                if again == text:
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
                holder_gone = True
                continue
            if time.monotonic() > deadline:
                raise HistoryBusy("ほかの処理が版を残しているところです")
            time.sleep(0.05)
    try:
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        clear_leftovers(folder, 0.0 if holder_gone else LEFTOVER_SECONDS)
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


def _vanished(error: OSError) -> bool:
    """そのファイル（か、途中のフォルダ）がもうないときの失敗か。"""
    return isinstance(error, (FileNotFoundError, NotADirectoryError))


class _UnreadableDir(OSError):
    """中を読めないフォルダ（権限がないなど。その中の .gitignore を読めないときを含む）。path は会社のフォルダから。"""

    def __init__(self, path: str, error: OSError) -> None:
        super().__init__(error.errno, f"フォルダを読めません（{path or '.'}）: {error.strerror}")
        self.path = path.rstrip("/")


class _WalkIgnore(IgnoreFilterManager):
    """作業のファイルを数えるときだけ使う除外の判定。.gitignore を読めないフォルダを、読めないフォルダとして返す
    （dulwich は、ない以外の失敗をそのまま上げるため、そのままでは1つのフォルダで場面ごと止まる）。"""

    def _load_path(self, path: str):
        try:
            return super()._load_path(path)
        except OSError as error:
            raise _UnreadableDir(path, error) from error


def _work_files(folder: Path, repo: Repo) -> Tuple[Dict[str, str], List[str]]:
    """作業のファイルの一覧（NFC の場所 → 実際の場所）と、中を読めないフォルダの一覧（NFC の場所）。
    .gitignore にあるものと、履歴に入れない場所は除く。会社のフォルダそのものを読めなければ、場面ごと止める。"""
    ignore = _WalkIgnore.from_repo(repo)
    root = str(folder)
    found: Dict[str, str] = {}
    unreadable: List[str] = []

    def walk_error(error: OSError) -> None:
        where = error.filename if isinstance(error.filename, str) else ""
        rel = os.path.relpath(where, root) if where else "."
        if rel == "." or rel.startswith(".."):
            raise error
        unreadable.append(nfc(rel).replace(os.sep, "/"))

    for dirpath, dirnames, filenames in os.walk(root, onerror=walk_error):
        keep = []
        for name in sorted(dirnames):
            rel = _rel(dirpath, root, name)
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                # 別名のフォルダは、Git と同じく、別名そのものを1つのファイルとして扱う（先はたどらない）
                if not ignore.is_ignored(rel):
                    found.setdefault(rel, full)
                continue
            if _skipped_dir(rel):
                continue
            try:
                ignored = ignore.is_ignored(rel + "/")
            except _UnreadableDir as error:
                if error.path != rel:
                    raise  # 上のフォルダ（会社のフォルダそのものなど）の失敗
                unreadable.append(rel)
                continue
            if ignored:
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            rel = _rel(dirpath, root, name)
            if ignore.is_ignored(rel):
                continue
            found.setdefault(rel, os.path.join(dirpath, name))
    return found, unreadable


def _exists_exactly(folder: Path, rel: str) -> Optional[str]:
    """その名前のファイルが（大文字と小文字・濁点の形を区別して）あれば、実際の場所を返す。なければ None。
    途中のフォルダを読めなければ _UnreadableDir（あるかどうか分からないので、消したことにしない）。"""
    parts = rel.split("/")
    current = str(folder)
    for i, part in enumerate(parts):
        try:
            names = os.listdir(current)
        except OSError as error:
            if _vanished(error):
                return None
            raise _UnreadableDir("/".join(parts[:i]), error) from error
        match = next((n for n in names if nfc(n) == part), None)
        if match is None:
            return None
        current = os.path.join(current, match)
    return current if not os.path.isdir(current) or os.path.islink(current) else None


def _under(rel: str, dirs: Sequence[str]) -> bool:
    return any(rel.startswith(d + "/") for d in dirs)


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


def _past(deadline: Optional[float]) -> bool:
    return deadline is not None and time.monotonic() > deadline


def _fits(size: int, deadline: Optional[float]) -> bool:
    """その大きさのファイルを、上限までに書き終えられそうか（見積もり）。"""
    return deadline is None or time.monotonic() + size / ESTIMATED_BYTES_PER_SECOND <= deadline


def _link_blob(fs_path: str) -> Blob:
    """別名（シンボリックリンク）は、Git と同じく、指す先の名前を中身にする。"""
    return Blob.from_string(os.readlink(os.fsencode(fs_path)))


def _hash_file(fs_path: str, st: os.stat_result, deadline: Optional[float]) -> Optional[bytes]:
    """中身の印（Git の blob の40桁）。時間の上限を過ぎたら None。読む間に大きさが変わったら空。"""
    if stat_mode.S_ISLNK(st.st_mode):
        return _link_blob(fs_path).id
    sha = hashlib.sha1(b"blob %d\x00" % st.st_size)
    total = 0
    with open(fs_path, "rb") as f:
        while True:
            if _past(deadline):
                return None
            chunk = f.read(CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            sha.update(chunk)
    if total != st.st_size:
        return b""
    return sha.hexdigest().encode("ascii")


WROTE = "書いた"
OUT_OF_TIME = "時間切れ"
CHANGING = "書き換え中"
VANISHED = "消えた"
UNREADABLE = "読めない"


def _write_blob(repo: Repo, fs_path: str, deadline: Optional[float]) -> Tuple[str, Optional[os.stat_result], bytes]:
    """作業のファイルの中身を .git に書く。(結果, 読んだときの状態, 印) を返す。

    1MB ごとに読みながら印を計算して書きかけのファイルに書き、終わったら印の名前に移す（全部をメモリに読まない。
    止められても、書きかけのファイルが残るだけで、ほかの錠は残らない）。時間の上限を過ぎたら、途中でやめる。
    作業のファイルを読む所の失敗は、結果（消えた・読めない）で返す（そのファイルだけを飛ばすため）。
    .git に書く所の失敗は、そのまま上げる（場面ごと止める）。
    """
    try:
        st = os.lstat(fs_path)
        if stat_mode.S_ISLNK(st.st_mode):
            blob = _link_blob(fs_path)
        else:
            # 書きかけのファイルを作る前に開く（読めないときに、書きかけを残さない）
            src = open(fs_path, "rb")
    except OSError as error:
        return (VANISHED if _vanished(error) else UNREADABLE), None, b""
    if stat_mode.S_ISLNK(st.st_mode):
        repo.object_store.add_object(blob)
        return WROTE, st, blob.id
    with src:
        objects = os.path.join(repo.controldir(), "objects")
        level = 0 if st.st_size >= STORE_ONLY_BYTES else -1
        fd, tmp = tempfile.mkstemp(prefix=TMP_OBJECT_PREFIX, dir=objects)
        try:
            header = b"blob %d\x00" % st.st_size
            sha = hashlib.sha1(header)
            packer = zlib.compressobj(level)
            total = 0
            with os.fdopen(fd, "wb") as out:
                out.write(packer.compress(header))
                while total <= st.st_size:
                    if _past(deadline):
                        return OUT_OF_TIME, st, b""
                    try:
                        chunk = src.read(CHUNK_BYTES)
                    except OSError:
                        return UNREADABLE, st, b""  # 読む途中の失敗（ディスクの不具合、同期の途中など）
                    if not chunk:
                        break
                    total += len(chunk)
                    sha.update(chunk)
                    out.write(packer.compress(chunk))
                out.write(packer.flush())
            if total != st.st_size:
                return CHANGING, st, b""
            hexsha = sha.hexdigest()
            final_dir = os.path.join(objects, hexsha[:2])
            final = os.path.join(final_dir, hexsha[2:])
            if not os.path.exists(final):
                os.makedirs(final_dir, exist_ok=True)
                os.chmod(tmp, 0o444)
                os.replace(tmp, final)
            return WROTE, st, hexsha.encode("ascii")
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)


def _same_as_entry(fs_path: str, entry: IndexEntry,
                   deadline: Optional[float] = None) -> Tuple[Optional[bool], Optional[IndexEntry]]:
    """作業のファイルが履歴の中身と同じか。同じで、時刻などだけが違うときは、書き直した記録を返す。

    時間の上限で比べきれなかったときは (None, None)。
    """
    st = os.lstat(fs_path)
    if cleanup_mode(st.st_mode) != entry.mode or (st.st_size & 0xFFFFFFFF) != entry.size:
        return False, None
    if _time_ns(entry.mtime) == st.st_mtime_ns and _time_ns(entry.ctime) == st.st_ctime_ns:
        return True, None
    sha = _hash_file(fs_path, st, deadline)
    if sha is None:
        return None, None
    if sha != entry.sha:
        return False, None
    return True, _entry_from_stat(st, entry.sha)


def _compare(folder: Path, repo: Repo, index,
             deadline: Optional[float] = None) -> Tuple[List[Change], Dict[bytes, IndexEntry], List[str]]:
    """最後の版（index）と作業のファイルを比べる。変わったものと、書き直すだけの記録と、中を読めないフォルダを返す。

    時間の上限で中身を比べきれなかったものは、変えたもの（unsure）として返す。
    読めないもの（履歴にあって、中を読めないフォルダの中にあるものを含む）は、変えたかどうか分からないもの
    （unreadable）として返す（消したことにはしない）。比べる間に消えたものは返さない（次の場面で比べ直す）。
    """
    files, unreadable_dirs = _work_files(folder, repo)
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
            if _under(name, unreadable_dirs):
                changes.append(Change(name, MODIFIED, index_key=key, unreadable=True))
                continue
            try:
                fs_path = None if _under_skipped_dir(name) else _exists_exactly(folder, name)
            except _UnreadableDir:
                changes.append(Change(name, MODIFIED, index_key=key, unreadable=True))
                continue
            if fs_path is None:
                changes.append(Change(name, DELETED, index_key=key))
                continue
        if isinstance(entry, ConflictedIndexEntry):
            changes.append(Change(name, MODIFIED, fs_path=fs_path, index_key=key))
            continue
        try:
            same, fresh = _same_as_entry(fs_path, entry, deadline)
        except OSError as error:
            # 作業のファイルを読む所の失敗だけ（.git には書かない）
            if not _vanished(error):
                changes.append(Change(name, MODIFIED, fs_path=fs_path, index_key=key, unreadable=True))
            continue
        if same is None:
            changes.append(Change(name, MODIFIED, fs_path=fs_path, index_key=key, unsure=True))
        elif not same:
            changes.append(Change(name, MODIFIED, fs_path=fs_path, index_key=key))
        elif fresh is not None:
            refresh[key] = fresh
    return changes, refresh, unreadable_dirs


def pending_changes(folder: Path) -> List[Change]:
    """最後の版から変わったファイル（読むだけ。何も書かない）。読めないファイルも含む（unreadable）。"""
    repo = Repo(str(folder))
    try:
        changes, _, _ = _compare(folder, repo, repo.open_index())
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


def _leftover_path(folder: Path) -> Path:
    return Path(folder) / STATE_DIR / LEFTOVER_FILE


def load_leftovers(folder: Path) -> Dict[str, dict]:
    """次の場面に回したファイルの控え（場所 → だれ・理由、途中でやめた回数）。読めなければ空。"""
    try:
        value = json.loads(_leftover_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    documents = value.get("書類") if isinstance(value, dict) else None
    if not isinstance(documents, dict):
        return {}
    return {nfc(path): note for path, note in documents.items()
            if isinstance(note, dict) and note.get("だれ") in IDENTITIES and isinstance(note.get("理由"), str)}


def _save_leftovers(folder: Path, leftovers: Dict[str, dict]) -> None:
    path = _leftover_path(folder)
    if not leftovers:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"書類": leftovers}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _dirs_of(index) -> Set[str]:
    """履歴にあるファイルを含むフォルダの一覧（会社のフォルダからの場所。NFC）。"""
    dirs: Set[str] = set()
    for key, _entry in index.items():
        parts = nfc(key.decode("utf-8", "surrogateescape")).split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    return dirs


def _groups(changes: List[Change], leftovers: Dict[str, dict], who: str,
            reason: str) -> List[Tuple[str, str, List[Change], bool]]:
    """(だれ, 理由, 変わったもの, 前の場面から回したものか) の一覧。前の場面から回したものを先にする。"""
    earlier: Dict[Tuple[str, str], List[Change]] = {}
    current: List[Change] = []
    for ch in changes:
        note = leftovers.get(ch.path)
        if note is None:
            current.append(ch)
        else:
            earlier.setdefault((note["だれ"], note["理由"]), []).append(ch)
    groups = [(w, r, items, True) for (w, r), items in earlier.items()]
    groups.append((who, reason, current, False))
    return groups


def _size(ch: Change) -> int:
    if ch.kind == DELETED or ch.fs_path is None:
        return -1
    try:
        return os.lstat(ch.fs_path).st_size
    except OSError:
        return -1


def _commit_changes(repo: Repo, index, who: str, reason: str, moment: datetime,
                    done: List[Change]) -> List[Change]:
    """中身を書いた変更を、1件の版に残す。中身が最後の版と同じなら、記録だけをそろえて空を返す。"""
    for ch in done:
        if ch.index_key is not None and ch.index_key in index:
            del index[ch.index_key]
        if ch.kind != DELETED:
            # 履歴の中の名前は NFC にそろえる
            index[ch.path.encode("utf-8")] = ch.entry
    tree = index.commit(repo.object_store)
    parent = repo.refs[b"HEAD"] if has_commits(repo) else None
    if parent is not None and repo[parent].tree == tree:
        # 中身は最後の版と同じ（前に途中で止まった処理の残りなど）
        return []
    identity = IDENTITIES[who].encode("utf-8")
    commit_obj = Commit()
    commit_obj.tree = tree
    commit_obj.parents = [parent] if parent is not None else []
    commit_obj.author = commit_obj.committer = identity
    commit_obj.author_time = commit_obj.commit_time = int(moment.timestamp())
    commit_obj.author_timezone = commit_obj.commit_timezone = 9 * 3600
    commit_obj.message = format_message(who, reason, done).encode("utf-8")
    repo.object_store.add_object(commit_obj)
    if not repo.refs.set_if_equals(b"HEAD", parent, commit_obj.id):
        raise HistoryBusy("ほかの処理が、同じときに版を残しました")
    return done


def record_scene(folder: Path, who: str, reason: str, when: Optional[datetime] = None,
                 budget: Optional[float] = None) -> Result:
    """最後の版から変わったファイルを、だれ・理由を付けて版に残す（1つの場面の分）。

    - when は版の日時（今日の日付の差し替えを含む。dates.now）。渡さなければ今の日本時間。
    - budget は、この呼び出しで使ってよい秒数。過ぎたら、残しきれないファイルを次の場面に回す（上の説明）。
      渡さなければ、上限なしで全部を残す。
    - 前の場面から回したファイルは、その場面のだれ・理由で先に残す（版が2件になることがある）。
    """
    if who not in IDENTITIES:
        raise ValueError(f"だれ（{who}）が分かりません")
    deadline = None if budget is None else time.monotonic() + budget
    moment = (when or datetime.now(timezone.utc)).astimezone(JST)
    result = Result()
    with locked(folder):
        repo = Repo(str(folder))
        try:
            index = repo.open_index()
            result.known_dirs = _dirs_of(index)
            changes, refresh, result.unreadable_dirs = _compare(folder, repo, index, deadline)
            for key, entry in refresh.items():
                index[key] = entry
            wrote = bool(refresh)
            leftovers = load_leftovers(folder)
            kept: Dict[str, dict] = {}
            for g_who, g_reason, items, earlier in _groups(changes, leftovers, who, reason):
                done: List[Change] = []
                deferred: List[Change] = []
                skipped: List[Change] = []  # 読めなかったもの

                def skip(ch: Change, note: dict) -> None:
                    # 版に残さず、最初に見つけた場面のだれ・理由を控える（読めるようになったら、それで残す）
                    ch.unreadable = True
                    skipped.append(ch)
                    result.unreadable.append(ch)
                    kept[ch.path] = note

                for ch in sorted(items, key=lambda c: (c.kind != DELETED, _size(c), c.path)):
                    if ch.kind == DELETED:
                        done.append(ch)
                        continue
                    note: dict = {"だれ": g_who, "理由": g_reason}
                    if ch.unreadable or ch.fs_path is None:
                        skip(ch, note)
                        continue
                    try:
                        st = os.lstat(ch.fs_path)
                    except OSError as error:
                        if not _vanished(error):
                            skip(ch, note)
                        continue  # 比べた後に消えた。次の場面で比べ直す
                    if not (stat_mode.S_ISREG(st.st_mode) or stat_mode.S_ISLNK(st.st_mode)):
                        continue  # ファイルでないもの（名前付きの管など）は残さない
                    before = leftovers.get(ch.path) or {}
                    aborts = before.get("止めた回数", 0) if before.get("大きさ") == st.st_size else 0
                    if not isinstance(aborts, int):
                        aborts = 0
                    if aborts:
                        note.update({"大きさ": st.st_size, "止めた回数": aborts})
                    if st.st_size > LARGE_FILE_BYTES or aborts >= MAX_ABORTS:
                        result.too_large.append(ch)
                        if aborts:
                            kept[ch.path] = note  # 途中でやめた回数を覚えておく（大きさが変わったら、また試す）
                        continue
                    if not ch.unsure and _fits(st.st_size, deadline):
                        status, written, sha = _write_blob(repo, ch.fs_path, deadline)
                        if status == WROTE:
                            ch.entry = _entry_from_stat(written, sha)
                            done.append(ch)
                            continue
                        if status == VANISHED:
                            continue  # 比べた後に消えた。次の場面で比べ直す
                        if status == UNREADABLE:
                            skip(ch, {"だれ": g_who, "理由": g_reason})
                            continue
                        if status == OUT_OF_TIME:
                            note.update({"大きさ": st.st_size, "止めた回数": aborts + 1})
                    deferred.append(ch)
                    kept[ch.path] = note
                recorded: List[Change] = []
                if done:
                    recorded = _commit_changes(repo, index, g_who, g_reason, moment, done)
                    wrote = True
                result.recorded += recorded
                result.deferred += deferred
                if not earlier:
                    # 版の名前の確かめ（Stop）には、読めなかったものも入れる
                    result.mine = recorded + deferred + skipped
            if wrote:
                index.write()
            if kept != leftovers:
                _save_leftovers(folder, kept)
            return result
        finally:
            repo.close()


def record(folder: Path, who: str, reason: str, when: Optional[datetime] = None,
           budget: Optional[float] = None) -> List[Change]:
    """record_scene と同じ。残したものの一覧を返す（なければ空）。"""
    return record_scene(folder, who, reason, when=when, budget=budget).recorded


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
