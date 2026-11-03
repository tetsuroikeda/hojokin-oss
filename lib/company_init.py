"""会社のフォルダを作る（DESIGN 4.5・4.7、TASKS S5）。

社長の了承を得てから、道具（skills/kiroku/scripts/init_company.py）が呼ぶ。次を一度に用意する。
1. フォルダの形（4.5）：入れ口・原本と6つの区分・案件・記録。
   段階のフォルダは、案件を作るときに制度データの手続きの段階から作る（M2a）。
2. `.claude/settings.json`（4.7）：外を読み書きさせない設定、書き換えを止める規則（deny）、道具の許可（allow）。
   すでにあれば、ほかの設定を残したまま足す。
3. 版の履歴（送り先のない Git）と .gitignore。前からあったファイルは「社長」、用意したものは「ツール」の版にする。
4. 目印（`.hojokin/`）：最後に作る。目印の中の設定.json も履歴に入れ、履歴から戻しても目印が残るようにする。

書く前に、読むだけで確かめる（送り先のある .git、読めない設定など）。だめなら何も書かない。
書いている途中で失敗したら、書いたものを戻す（目印だけ・設定だけが残り、決まりが中途半端に効かないように）。
もう一度動かしたときは、足りないものだけを補う。

版の履歴は dulwich を使うので、init() は venv の python から動かす（lib/runtime.py）。
それ以外（定数、設定の組み立て、事前の確かめ）は、標準のライブラリだけで使える。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from lib import common_rules, company

INBOX_DIR = "入れ口"
ORIGINALS_DIR = "原本"
ORIGINAL_KINDS = ("登記・名簿", "決算・税", "見積・契約・請求", "役所からの通知", "会社の資料", "写真・カタログ")
CASES_DIR = "案件"
RECORDS_DIR = "記録"
VIEW_DIR = "見るだけ"
FOLDERS = (INBOX_DIR, ORIGINALS_DIR) + tuple(f"{ORIGINALS_DIR}/{k}" for k in ORIGINAL_KINDS) + (CASES_DIR, RECORDS_DIR)

CLAUDE_SETTINGS = ".claude/settings.json"
GITIGNORE = ".gitignore"
MARKER_SETTINGS = f"{company.MARKER_DIR}/{company.SETTINGS_FILE}"

# 組み込みの Edit（Write・NotebookEdit も含めて止まる）で書き換えさせないもの（4.7、5章）。
# 先頭の「/」は、Claude Code を開いたフォルダ（会社のフォルダ）から。日本語のフォルダ名でも効く（実験 E6）。
DENY_RULES = (
    f"Edit(/{ORIGINALS_DIR}/**)",
    f"Edit(/{CASES_DIR}/**/公式資料/**)",
    f"Edit(/{RECORDS_DIR}/審査役の結果/**)",
    f"Edit(/{company.MARKER_DIR}/**)",
    "Edit(/.claude/**)",
    "Edit(/.git/**)",
    "Edit(/**/*.docx)",
    "Edit(/**/*.doc)",
    "Edit(/**/*.xlsx)",
    "Edit(/**/*.xlsm)",
    "Edit(/**/*.xls)",
)
# 確認なしにするもの（4.7）。Web 検索と、公的なサイトの取得。
# `domain:go.jp` は go.jp だけに当たるので、下のドメインは `*.` で書く（公式文書）。
ALLOW_RULES = (
    "WebSearch",
    "WebFetch(domain:*.go.jp)",
    "WebFetch(domain:*.lg.jp)",
)
BLOCK_KEYS = ("blockReadsOutsideWorkingDirectories", "blockWritesOutsideWorkingDirectories")

GITIGNORE_LINES = (
    "# hojokin：版の履歴に入れないもの",
    f"/{company.MARKER_DIR}/{company.TEMP_DIR}/",
    f"/{VIEW_DIR}/",
    "/.claude/settings.local.json",
    "# Word・Excel・LibreOffice が、開いている間だけ作るファイル",
    "~$*",
    "~*.tmp",
    ".~lock.*#",
    "# パソコンが自動で作るファイル",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
)

INIT_MESSAGE = "会社のフォルダを用意した\n\n社長の了承を得て、目印・フォルダの形・設定・版の履歴を用意した。\n"
EXISTING_MESSAGE = "会社のフォルダにする前からあったファイル\n\n会社のフォルダを用意したときに、フォルダにあったファイルを残した。\n"


class Refused(Exception):
    """会社のフォルダにできない。何も書いていない。"""

    def __init__(self, reasons: List[str]) -> None:
        super().__init__("\n".join(reasons))
        self.reasons = reasons


@dataclass
class InitResult:
    folder: Path
    already: bool
    added: List[str] = field(default_factory=list)
    existing_files: int = 0
    commits: List[str] = field(default_factory=list)


# ---- 設定と .gitignore の組み立て（標準のライブラリだけ） ----


def _union(current: list, extra: Tuple[str, ...]) -> list:
    return list(current) + [x for x in extra if x not in current]


def merged_settings(existing: Optional[dict]) -> dict:
    """会社のフォルダの `.claude/settings.json` の中身。すでにある設定は残し、決まりの分を足す。"""
    settings = dict(existing or {})
    permissions = dict(settings.get("permissions") or {})
    for key in BLOCK_KEYS:
        permissions[key] = True
    permissions["deny"] = _union(permissions.get("deny") or [], DENY_RULES)
    permissions["allow"] = _union(permissions.get("allow") or [], ALLOW_RULES)
    settings["permissions"] = permissions
    return settings


def merged_gitignore(existing: str) -> str:
    """会社のフォルダの .gitignore の中身。すでにある行は残し、足りない行を後ろに足す。"""
    if not existing.strip():
        return "\n".join(GITIGNORE_LINES) + "\n"
    have = {line.strip() for line in existing.splitlines()}
    missing = [line for line in GITIGNORE_LINES if not line.startswith("#") and line not in have]
    if not missing:
        return existing
    text = existing if existing.endswith("\n") else existing + "\n"
    return text + "\n" + "\n".join((GITIGNORE_LINES[0],) + tuple(missing)) + "\n"


def _read_settings(path: Path) -> Optional[dict]:
    """すでにある `.claude/settings.json`。ないときは None。形が読めなければ ValueError。"""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"{CLAUDE_SETTINGS} が JSON として読めません（{e}）") from e
    if not isinstance(data, dict):
        raise ValueError(f"{CLAUDE_SETTINGS} の中身が {{ }} で囲んだ形ではありません")
    permissions = data.get("permissions")
    if permissions is None:
        return data
    if not isinstance(permissions, dict):
        raise ValueError(f"{CLAUDE_SETTINGS} の permissions が {{ }} で囲んだ形ではありません")
    for key in ("deny", "allow"):
        value = permissions.get(key)
        if value is not None and not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
            raise ValueError(f"{CLAUDE_SETTINGS} の permissions.{key} が、文字の一覧の形ではありません")
    return data


# ---- 書く前の確かめ（読むだけ） ----


def check(folder: Path, remotes_of: Optional[Callable[[Path], List[str]]] = None) -> List[str]:
    """会社のフォルダにできない理由の一覧。空なら作ってよい。何も書かない。

    remotes_of は、すでにある .git の送り先の設定を数える関数（venv の中では lib.history を使う）。
    """
    reasons = []
    if not folder.is_dir():
        return [f"フォルダがありません：{folder}"]
    for name in (company.MARKER_DIR, ".claude", ".git") + FOLDERS:
        path = folder / name
        if path.exists() and not path.is_dir():
            reasons.append(f"「{name}」という名前のファイルがあり、同じ名前のフォルダを作れません。")
    for name in (CLAUDE_SETTINGS, GITIGNORE, MARKER_SETTINGS):
        path = folder / name
        if path.is_dir():
            reasons.append(f"「{name}」という名前のフォルダがあり、同じ名前のファイルを作れません。")
    try:
        _read_settings(folder / CLAUDE_SETTINGS)
    except (OSError, ValueError) as e:
        reasons.append(f"すでにある設定を読めないため、書き足せません：{e}")
    gitignore = folder / GITIGNORE
    if gitignore.is_file():
        try:
            gitignore.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            reasons.append(f"すでにある {GITIGNORE} を読めないため、書き足せません（{e}）")
    if (folder / ".git").is_dir() and remotes_of is not None:
        try:
            found = remotes_of(folder)
        except Exception as e:  # dulwich が読めない .git
            reasons.append(f"すでにある版の履歴（.git）を読めません（{e}）")
        else:
            if found:
                reasons.append(
                    "すでにある版の履歴（.git）に、送り先（リモート）の設定があります："
                    + "、".join(found)
                    + "。会社のフォルダの履歴はインターネットに送らない決まりなので、このフォルダは使えません。"
                )
    return reasons


# ---- 用意する（venv の python から） ----


class _Undo:
    """書いている途中で失敗したときに、書いたものを戻すための控え。"""

    def __init__(self) -> None:
        self._actions: List[Callable[[], None]] = []

    def file(self, path: Path) -> None:
        before = path.read_bytes() if path.exists() else None

        def restore() -> None:
            if before is None:
                if path.exists():
                    path.unlink()
            else:
                path.write_bytes(before)

        self._actions.append(restore)

    def dir(self, path: Path) -> None:
        self._actions.append(lambda: path.rmdir() if path.is_dir() and not any(path.iterdir()) else None)

    def tree(self, path: Path) -> None:
        self._actions.append(lambda: shutil.rmtree(path, ignore_errors=True))

    def run(self) -> None:
        for action in reversed(self._actions):
            try:
                action()
            except OSError:
                pass


def _make_dir(path: Path, undo: _Undo, added: List[str], name: str) -> None:
    if path.is_dir():
        return
    path.mkdir()
    undo.dir(path)
    added.append(name + "/")


def _write_text(path: Path, text: str, undo: _Undo, added: List[str], name: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    undo.file(path)
    path.write_text(text, encoding="utf-8")
    added.append(name)


def init(folder: Path) -> InitResult:
    """会社のフォルダを用意する。できないときは Refused（何も書いていない）。"""
    from lib import history  # dulwich は venv にだけある

    folder = folder.resolve()
    reasons = check(folder, remotes_of=_remotes_of)
    if reasons:
        raise Refused(reasons)

    result = InitResult(folder=folder, already=company.is_company_folder(folder))
    undo = _Undo()
    try:
        # .gitignore を先に書き、前からあったファイルを見分けるときに、履歴に入れないものを除く
        gitignore = folder / GITIGNORE
        current = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        _write_text(gitignore, merged_gitignore(current), undo, result.added, GITIGNORE)

        if not (folder / ".git").exists():
            undo.tree(folder / ".git")
            result.added.append(".git/（版の履歴。送り先なし）")
        repo = history.open_or_init(folder)
        try:
            fresh = not history.has_commits(repo)
        finally:
            repo.close()
        if fresh:
            # 前からあったファイルは、社長が置いたものとして残す（.gitignore だけは、用意したものの版に入れる）
            existing = [p for p in history.changed_paths(folder) if p != GITIGNORE]
            if existing:
                history.commit(folder, EXISTING_MESSAGE, history.OWNER, paths=[folder / p for p in existing])
                result.existing_files = len(existing)
                result.commits.append(f"前からあったファイル {len(existing)} 件（社長）")

        for name in FOLDERS:
            _make_dir(folder / name, undo, result.added, name)

        claude_dir = folder / ".claude"
        _make_dir(claude_dir, undo, result.added, ".claude")
        settings_file = folder / CLAUDE_SETTINGS
        settings = merged_settings(_read_settings(settings_file))
        _write_text(settings_file, json.dumps(settings, ensure_ascii=False, indent=2) + "\n", undo, result.added,
                    CLAUDE_SETTINGS)

        # 目印は最後に作る
        marker = folder / company.MARKER_DIR
        if not marker.is_dir():
            marker.mkdir()
            undo.tree(marker)
            result.added.append(company.MARKER_DIR + "/（会社のフォルダの目印）")
        marker_settings = folder / MARKER_SETTINGS
        if not marker_settings.exists():
            _write_text(marker_settings, "{}\n", undo, result.added, MARKER_SETTINGS)

        made = history.commit(folder, INIT_MESSAGE, history.TOOL,
                              paths=[gitignore, settings_file, marker_settings])
        if made is not None:
            result.commits.append("用意したもの（ツール）")
    except BaseException:
        undo.run()
        raise
    return result


def _remotes_of(folder: Path) -> List[str]:
    """すでにある .git の送り先の設定（check() は .git があるときだけ呼ぶ）。"""
    from lib import history

    repo = history.open_or_init(folder)
    try:
        return history.remotes(repo)
    finally:
        repo.close()


# ---- 結果の文 ----

SETTINGS_SUMMARY = (
    "ファイルの道具は会社のフォルダの外を読み書きしない。原本・公式資料・審査役の結果・目印・設定・履歴と、"
    "Word・Excel のファイルを書き換えない。Web 検索と公的なサイト（go.jp・lg.jp）の取得は確認なしにする"
)


def report(result: InitResult) -> str:
    """道具の出力。作ったものと、どの段階にも共通の決まりの短い文（初めて使うセッションに渡す）。"""
    lines = []
    if result.already:
        lines.append(f"このフォルダは、すでに会社のフォルダです（{result.folder}）。")
        if result.added:
            lines.append("足りなかったものを補いました：" + "、".join(result.added))
        else:
            lines.append("足りないものはありませんでした。")
    else:
        kinds = "、".join(ORIGINAL_KINDS)
        lines += [
            f"会社のフォルダを用意しました（{result.folder}）。",
            "",
            "用意したもの：",
            f"- 目印：{company.MARKER_DIR}/",
            f"- フォルダ：{INBOX_DIR}/、{ORIGINALS_DIR}/（{kinds} の6つの区分）、{CASES_DIR}/、{RECORDS_DIR}/",
            f"- 設定：{CLAUDE_SETTINGS}（{SETTINGS_SUMMARY}）。"
            "Claude Code をこのフォルダで開いていれば、この設定は今のセッションからすぐ効きます。",
            "- 版の履歴：.git/（送り先なし）。" + ("残した版：" + "、".join(result.commits) if result.commits else ""),
            "",
            "社長に伝えること：",
            f"- 受け取った書類は「{INBOX_DIR}」フォルダに入れてください（ほかの場所でもかまいません）。"
            f"ツールが「{ORIGINALS_DIR}」に整理します。",
            "- 書類の版は、このパソコンの中だけに残し、インターネットには送りません。"
            "前の版を見たいときや戻したいときは、頼んでください。",
            "- デスクトップアプリのモードの選択で「auto」を選ぶと、会社のフォルダの中の読み取りと書き込みで、"
            "確認を求められなくなります。",
        ]
    lines += ["", common_rules.TEXT]
    return "\n".join(lines).rstrip() + "\n"


def refusal(folder: Path, reasons: List[str]) -> str:
    lines = [f"このフォルダ（{folder}）は、会社のフォルダにできませんでした。何も変えていません。", "", "理由："]
    lines += [f"- {r}" for r in reasons]
    lines += ["", "社長に理由を伝え、会社のフォルダにする別の新しいフォルダで Claude を開き直すよう案内してください。"]
    return "\n".join(lines) + "\n"
