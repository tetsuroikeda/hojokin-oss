"""提出版（SPEC 共通の要件「書類の版の管理」・T0-6、DESIGN 8.3・10章「書類の版」。TASKS M0b）。

担当者が「提出した」と伝えたら、その時点の申請書（添付の写しを含む）を提出版として記録し、
後から同じ中身を取り出せるようにする（実績報告や差し戻しへの対応で照らし合わせるため）。

提出版に入れるもの：
- 段階のフォルダの中のすべて（`案件/<案件>/<段階>/` の 申請書/ と 添付する書類/。計画書・入力シート・写しなど）。
- 会社のフォルダの直下の「財務モデル.xlsx」（あれば）。提出した案件の数字は、提出版に入れた財務モデルで固定し、
  計画書との照合にも使うため（DESIGN 8.3）。

記録の仕方（Git の形。同期されるフォルダの形は M0c で、同じ入口から動かす）：
1. 最後の版から変わったものを、先に版に残す（「ツール」。理由は社長の発言）。提出するものに残しきれないものが
   あれば、提出版を記録しない（取り出しても同じ中身にならないため）。残しきれないものは、版に残す処理の結果
   （読めないファイル・中を読めないフォルダ・大きすぎるもの・次に回したもの）と、残した後もまだ変わっているもので見る。
2. 段階のフォルダを .gitignore を使わずにたどり、そのときの版にないファイルがあれば、提出版を記録しない
   （.gitignore に当たる写しや、読めないフォルダの中の写しが、黙って提出版から抜けないように）。ただし、
   Word・Excel が開いている間だけ作るファイルと、パソコンが自動で作るファイル（プラグインが .gitignore に書くもの。
   lib/company_init.py）は、書類でないので見逃す。財務モデル.xlsx も同じく確かめる。
3. そのときの版の印（40桁）と、提出するファイルごとの場所・大きさ・中身の印（sha256）を、
   `記録/提出版.json`（版の一覧）に足し、その変更も版に残す。
4. Git の印（`refs/tags/提出版/<案件>/<段階>/<番号>`）を、提出したときの版に付ける。名前に使えない文字があれば、
   案件と段階の印（sha256 の先頭）で名前を作る。印を付けられなくても、版の一覧の記録は残す。

同じ案件・段階を出し直したとき（差し戻しの後など）は、番号を1つ増やして足す。前の提出版も残る。
`記録/提出版.json` は、前の版に戻す道具でも戻さない（記録した提出版が消えないように。壊れたか消えたときだけ、
直すために戻せる。lib/past_versions.py）。
取り出すときは、版の一覧にある版から中身を出し、sha256 が記録と同じことを確かめてから、`見るだけ/` に出す
（lib/view_only.py）。作業のファイルは変えない。
"""

from __future__ import annotations

import hashlib
import json
import os
import stat as stat_mode
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from lib import case_folder, company_init, dates, history, view_only

RECORD_FILE = "記録/提出版.json"
FINANCIAL_MODEL = "財務モデル.xlsx"
TAG_PREFIX = "refs/tags/提出版/"
DEFAULT_REASON = "「提出した」と伝えられた"
LIST_KEY = "提出版"

# 版の履歴になくても、提出版から抜けてよいもの（書類でないもの）。プラグインが会社のフォルダの .gitignore に書く行
# （Word・Excel が開いている間だけ作るファイル、パソコンが自動で作るファイルなど）だけにする。
# 社長や Claude が後から .gitignore に足した行は、ここに入らない（当たる写しは、提出版を記録せずに知らせる）。
TEMPORARY_PATTERNS = tuple(line for line in company_init.GITIGNORE_LINES if line and not line.startswith("#"))

# 版の履歴に残せなかったわけ（社長への説明に使う）
UNREADABLE = "読めない"
UNREADABLE_DIR = "中を読めないフォルダ"
TOO_LARGE = "大きすぎる"
DEFERRED = "残しきる前に時間が切れた"
STILL_CHANGING = "版に残す間に変わった"
NOT_IN_HISTORY = "版の履歴に入っていない（.gitignore で除かれているなど）"


class SubmissionError(Exception):
    """提出版を記録・取り出しできない。文は、そのまま社長への説明に使える形にする。"""


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def stage_dir(case: str, stage: str) -> str:
    return f"{case_folder.CASES_DIR}/{nfc(case)}/{nfc(stage)}"


def in_submission(path: str, case: str, stage: str) -> bool:
    """会社のフォルダからの場所（NFC）が、その案件・段階の提出版に入るものか。"""
    return path.startswith(stage_dir(case, stage) + "/") or path == FINANCIAL_MODEL


def _now(folder: Path) -> datetime:
    try:
        return dates.now(folder)
    except ValueError:
        return datetime.now(timezone.utc).astimezone(dates.JST)


# ---- 案件と段階 ----

def _dirs(path: Path) -> List[str]:
    try:
        return sorted(nfc(p.name) for p in path.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []


def cases(folder: Path) -> List[str]:
    return _dirs(Path(folder) / case_folder.CASES_DIR)


def stages(folder: Path, case: str) -> List[str]:
    """案件の段階のフォルダ（「1_申請」の形。効果報告の年のフォルダは「4_効果報告/1年目」の形）。"""
    base = Path(folder) / case_folder.CASES_DIR / case
    found = []
    for name in _dirs(base):
        if not case_folder.STAGE_NAME.match(name):
            continue
        years = [y for y in _dirs(base / name) if history.YEAR_DIR.match(y)]
        found += [f"{name}/{y}" for y in years] if years else [name]
    return found


def choose(folder: Path, case: Optional[str], stage: Optional[str]) -> Tuple[str, str]:
    """案件と段階を決める。省いたときは、1つしかなければそれにする。決められなければ、選べるものを挙げて断る。"""
    all_cases = cases(folder)
    if case is None:
        if len(all_cases) != 1:
            raise SubmissionError("どの案件かを --case で選んでください。案件：" + ("、".join(all_cases) or "（ありません）"))
        case = all_cases[0]
    case = nfc(case).strip()
    if case not in all_cases:
        raise SubmissionError(f"案件「{case}」のフォルダがありません。案件：" + ("、".join(all_cases) or "（ありません）"))
    all_stages = stages(folder, case)
    if stage is None:
        if len(all_stages) != 1:
            raise SubmissionError(f"案件「{case}」のどの段階かを --stage で選んでください。段階："
                                  + ("、".join(all_stages) or "（ありません）"))
        stage = all_stages[0]
    stage = nfc(stage).strip().strip("/")
    if stage not in all_stages:
        raise SubmissionError(f"案件「{case}」に段階「{stage}」のフォルダがありません。段階："
                              + ("、".join(all_stages) or "（ありません）"))
    return case, stage


# ---- 版の一覧（記録/提出版.json） ----

def load(folder: Path) -> List[dict]:
    """記録した提出版の一覧（古い順）。ファイルがなければ空。読めなければ SubmissionError。"""
    path = Path(folder) / RECORD_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as error:
        raise SubmissionError(f"{RECORD_FILE} を読めません（{error}）") from error
    try:
        value = json.loads(text)
    except ValueError as error:
        raise SubmissionError(
            f"{RECORD_FILE} が JSON として読めません（{error}）。版の履歴から前の版に戻してください"
        ) from error
    entries = value.get(LIST_KEY) if isinstance(value, dict) else None
    if not isinstance(entries, list) or not all(_valid(e) for e in entries):
        raise SubmissionError(f"{RECORD_FILE} の形が正しくありません。版の履歴から前の版に戻してください")
    return entries


def _valid(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    if not all(isinstance(entry.get(k), str) for k in ("案件", "段階", "日時", "版")):
        return False
    if not isinstance(entry.get("番号"), int) or not isinstance(entry.get("ファイル"), list):
        return False
    return all(isinstance(f, dict) and isinstance(f.get("書類"), str) and isinstance(f.get("sha256"), str)
               for f in entry["ファイル"])


def _save(folder: Path, entries: List[dict]) -> None:
    path = Path(folder) / RECORD_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    # 「~*.tmp」は .gitignore にあるので、書きかけが版に残らない
    tmp = path.with_name(f"~{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({LIST_KEY: entries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


# ---- 記録する ----

def _tag_name(case: str, stage: str, number: int) -> bytes:
    from dulwich.refs import check_ref_format

    name = f"{TAG_PREFIX}{case}/{stage}/{number}".encode("utf-8")
    if check_ref_format(name):
        return name
    key = hashlib.sha256(f"{case}/{stage}".encode("utf-8")).hexdigest()[:16]
    return f"{TAG_PREFIX}{key}/{number}".encode("utf-8")


def _related_dir(directory: str, base: str) -> bool:
    """中を読めないフォルダが、段階のフォルダ（base）の中か、段階のフォルダそのもの・その上か。"""
    return directory == base or directory.startswith(base + "/") or base.startswith(directory + "/")


def _left_by_scene(folder: Path, result: history.Result, case: str, stage: str) -> Dict[str, str]:
    """版に残す処理（record_scene）で、提出するもののうち残せなかったもの（場所 → わけ）。"""
    base = stage_dir(case, stage)
    left: Dict[str, str] = {}
    for directory in result.unreadable_dirs:
        if _related_dir(directory, base):
            left.setdefault(directory + "/", UNREADABLE_DIR)
    for items, why in ((result.unreadable, UNREADABLE), (result.too_large, TOO_LARGE),
                       (result.deferred, DEFERRED)):
        for ch in items:
            if in_submission(ch.path, case, stage):
                left.setdefault(ch.path, why)
    # 残した後も、まだ変わっているもの（読めない・残す間に書き換えられたなど）
    for ch in history.pending_changes(folder):
        if in_submission(ch.path, case, stage):
            left.setdefault(ch.path, UNREADABLE if ch.unreadable else STILL_CHANGING)
    return left


def _actual(folder: Path, rel: str) -> Optional[str]:
    """会社のフォルダからの場所（NFC）の、実際の場所（名前が NFD のこともある）。なければ None。"""
    current = str(folder)
    for part in rel.split("/"):
        try:
            names = os.listdir(current)
        except OSError:
            return None
        match = next((n for n in names if nfc(n) == part), None)
        if match is None:
            return None
        current = os.path.join(current, match)
    return current


def _outside_history(folder: Path, case: str, stage: str, recorded: Set[str]) -> Dict[str, str]:
    """段階のフォルダ（と 財務モデル.xlsx）にあって、そのときの版にないもの（場所 → わけ）。
    .gitignore は使わずにたどる。書類でないもの（TEMPORARY_PATTERNS に当たるもの）と、.git のフォルダは見逃す。
    別名（シンボリックリンク）は、版の履歴と同じく1つのファイルとして扱い、先はたどらない。"""
    from dulwich.ignore import IgnoreFilter

    temporary = IgnoreFilter(p.encode("utf-8") for p in TEMPORARY_PATTERNS)
    root = str(folder)
    found: Dict[str, str] = {}

    def rel_of(path: str) -> str:
        return nfc(os.path.relpath(path, root)).replace(os.sep, "/")

    def check(full: str, rel: str) -> None:
        if rel in recorded or temporary.is_ignored(rel):
            return
        try:
            st = os.lstat(full)
        except FileNotFoundError:
            return  # たどる間に消えた
        except OSError:
            found[rel] = UNREADABLE
            return
        if stat_mode.S_ISREG(st.st_mode) or stat_mode.S_ISLNK(st.st_mode):
            found[rel] = NOT_IN_HISTORY

    def walk_error(error: OSError) -> None:
        where = error.filename if isinstance(error.filename, str) else ""
        if where and not isinstance(error, (FileNotFoundError, NotADirectoryError)):
            found[rel_of(where) + "/"] = UNREADABLE_DIR

    start = _actual(folder, stage_dir(case, stage))
    if start is not None:
        for dirpath, dirnames, filenames in os.walk(start, onerror=walk_error):
            keep = []
            for name in sorted(dirnames):
                full = os.path.join(dirpath, name)
                rel = rel_of(full)
                if os.path.islink(full):
                    check(full, rel)
                elif nfc(name) != ".git" and not temporary.is_ignored(rel + "/"):
                    keep.append(name)
            dirnames[:] = keep
            for name in filenames:
                full = os.path.join(dirpath, name)
                check(full, rel_of(full))
    model = _actual(folder, FINANCIAL_MODEL)
    if model is not None and (os.path.islink(model) or not os.path.isdir(model)):
        check(model, FINANCIAL_MODEL)
    return found


def _refuse_left(left: Dict[str, str]) -> SubmissionError:
    lines = "\n".join(f"- {path}（{why}）" for path, why in sorted(left.items()))
    return SubmissionError(
        "次のものを版の履歴に残せなかったため、提出版を記録していません（取り出しても、提出したときと同じ中身に"
        "ならないため）。読めるようにする、.gitignore から外すなどしてから、もう一度記録してください：\n" + lines
    )


def record(folder: Path, case: str, stage: str, reason: Optional[str] = None,
           when: Optional[datetime] = None) -> dict:
    """「提出した」と伝えられたときに、提出版を記録する。記録した1件を返す。"""
    from dulwich.object_store import iter_tree_contents
    from dulwich.objects import Blob
    from dulwich.repo import Repo

    folder = Path(folder)
    if not history.enabled(folder):
        raise SubmissionError("この会社のフォルダには版の履歴（Git の形）がないため、提出版を記録できません")
    case, stage = choose(folder, case, stage)
    base = stage_dir(case, stage)
    moment = (when or _now(folder)).astimezone(dates.JST)
    words = history.one_line(reason, history.REASON_MAX_CHARS) if reason and reason.strip() else DEFAULT_REASON
    entries = load(folder)  # 読めなければ、何も残さずに断る

    # 1. 変わったものを先に残す（提出したときの中身を版に入れる）。残せなかったものがあれば断る
    left = _left_by_scene(folder, history.record_scene(folder, history.TOOL, words, when=moment), case, stage)
    if left:
        raise _refuse_left(left)

    # 2. そのときの版から、提出するファイルの一覧と中身の印を作る
    with history.locked(folder):
        repo = Repo(str(folder))
        try:
            if not history.has_commits(repo):
                raise SubmissionError("版の履歴がまだないため、提出版を記録できません")
            head = repo.head()
            files = []
            for item in iter_tree_contents(repo.object_store, repo[head].tree):
                path = nfc(item.path.decode("utf-8", "surrogateescape"))
                if not in_submission(path, case, stage):
                    continue
                blob = repo[item.sha]
                if not isinstance(blob, Blob):
                    continue
                data = blob.data
                files.append({"書類": path, "大きさ": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            # 段階のフォルダにあって、版にないもの（.gitignore に当たる写しなど）があれば断る
            outside = _outside_history(folder, case, stage, {f["書類"] for f in files})
            if outside:
                raise _refuse_left(outside)
            if not any(f["書類"].startswith(base + "/") for f in files):
                raise SubmissionError(f"{base}/ に書類がないため、提出版を記録していません")
            files.sort(key=lambda f: f["書類"])
            number = 1 + max((e["番号"] for e in entries if (e["案件"], e["段階"]) == (case, stage)), default=0)
            tag = _tag_name(case, stage, number)
            try:
                if not repo.refs.add_if_new(tag, head):
                    tag = _tag_name(case, stage, number) + b"-" + head[:7]
                    if not repo.refs.add_if_new(tag, head):
                        tag = b""
            except Exception:  # 印を付けられなくても、版の一覧には残す
                tag = b""
        finally:
            repo.close()

    entry = {
        "番号": number,
        "案件": case,
        "段階": stage,
        "日時": moment.isoformat(timespec="seconds"),
        "版": head.decode("ascii"),
        "印": tag.decode("utf-8"),
        "発言": words,
        "ファイル": files,
    }
    # 3. 版の一覧に足し、その変更も版に残す
    _save(folder, entries + [entry])
    history.record_scene(folder, history.TOOL, f"{words}（提出版 {number}回目を記録）", when=moment)
    return entry


# ---- 取り出す ----

def find(folder: Path, case: Optional[str] = None, stage: Optional[str] = None,
         number: Optional[int] = None) -> dict:
    """記録した提出版の1件。番号を省けば、いちばん新しいもの。"""
    entries = load(folder)
    if not entries:
        raise SubmissionError("記録した提出版がありません")
    matched = [e for e in entries
               if (case is None or e["案件"] == nfc(case).strip())
               and (stage is None or e["段階"] == nfc(stage).strip().strip("/"))]
    if number is not None:
        matched = [e for e in matched if e["番号"] == number]
    if not matched:
        raise SubmissionError("その提出版は記録されていません。記録した提出版：" + "、".join(label(e) for e in entries))
    return max(matched, key=lambda e: (e["日時"], e["番号"]))


def label(entry: dict) -> str:
    """例：2026_省力化（一般型）第9回 1_申請 1回目（2026年11月4日（水）15:30）"""
    return f"{entry['案件']} {entry['段階']} {entry['番号']}回目（{shown_time(entry)}）"


def shown_time(entry: dict) -> str:
    try:
        return dates.format_datetime(datetime.fromisoformat(entry["日時"]))
    except ValueError:
        return entry["日時"]


def contents(folder: Path, entry: dict) -> List[Tuple[str, bytes]]:
    """提出版のファイルの中身（場所と中身）。どれも記録した sha256 と同じことを確かめる。"""
    found = []
    for f in entry["ファイル"]:
        try:
            data = history.content_at(Path(folder), entry["版"], f["書類"])
        except (KeyError, ValueError) as error:
            raise SubmissionError(f"提出版の版（{entry['版'][:10]}）が版の履歴にありません（{error}）") from error
        if data is None:
            raise SubmissionError(f"提出版の版に {f['書類']} がありません")
        if hashlib.sha256(data).hexdigest() != f["sha256"]:
            raise SubmissionError(f"{f['書類']} の中身が、提出したときの印（sha256）と合いません")
        found.append((f["書類"], data))
    return found


def view_name(entry: dict) -> str:
    """見るだけに出すフォルダの名前。"""
    when = entry["日時"]
    try:
        moment = dates.to_jst(datetime.fromisoformat(when))
        when = f"{moment.year}年{moment.month}月{moment.day}日 {moment.hour}時{moment.minute:02d}分"
    except ValueError:
        pass
    stage = entry["段階"].replace("/", "・")
    try:
        return case_folder.safe_name(f"提出版 {entry['案件']} {stage} {entry['番号']}回目（{when}）")
    except case_folder.CaseError:  # 案件の名前が長すぎるとき
        return case_folder.safe_name(f"提出版 {entry['番号']}回目（{when}）")


def view_items(entry: dict, files: List[Tuple[str, bytes]]) -> List[Tuple[str, bytes]]:
    """見るだけのフォルダの中の場所。段階のフォルダの中のものは、段階のフォルダからの場所（申請書/その1.docx）にし、
    ほか（財務モデル.xlsx）は会社のフォルダからの場所のままにする。重なれば、会社のフォルダからの場所にする。"""
    prefix = stage_dir(entry["案件"], entry["段階"]) + "/"
    short = [(p[len(prefix):] if p.startswith(prefix) else p, data) for p, data in files]
    if len({p for p, _ in short}) != len(short):
        return list(files)
    return short


def export(folder: Path, entry: dict) -> Tuple[str, List[str]]:
    """提出版を `見るだけ/` に読み取り専用で出す。(フォルダの場所, ファイルの場所の一覧) を返す。"""
    files = contents(folder, entry)
    return view_only.export_tree(Path(folder), view_name(entry), view_items(entry, files))


def documents(folder: Path) -> Dict[str, dict]:
    """書類ごとの、いちばん新しい提出版（今の状態の画面の「提出版に入っているか」に使う）。読めなければ空。"""
    try:
        entries = load(folder)
    except SubmissionError:
        return {}
    latest: Dict[str, dict] = {}
    for e in sorted(entries, key=lambda e: (e["日時"], e["番号"])):
        for f in e["ファイル"]:
            latest[f["書類"]] = e
    return latest
