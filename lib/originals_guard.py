"""原本と公式資料の照らしと戻し（SPEC 共通の要件「原本と公式資料は中身を書き換えない」・T0-7、
DESIGN 4.7 の2・5章「原本・公式資料を1バイトも変えない」・10章。TASKS M4）。

開いたとき（SessionStart）と、Claude が応答を終えるたび（Stop）に、hook から呼ぶ（hooks/originals_hooks.py）。
- 照らすもの：書類の台帳（`記録/書類の台帳.json`、lib/seiri.py）の原本と、公式資料を取る道具が残した
  資料の一覧（`記録/資料の本文/<案件>/資料の一覧.json`、lib/official_docs.py）の公式資料に、
  原本の控え（`.hojokin/一時/原本の印.json`、lib/protected_store.py）にあるものを合わせる。
  どれも、入れたときの中身のハッシュ（sha256）を持つ。今の中身と比べ、違う・消えたものを戻す。
- 照らして戻すのは、`原本/<区分>/…` と `案件/<案件>/公式資料/…` の下だけ（lib/protected_store.allowed_place）。
  台帳や資料の一覧は Claude も社長も直せるので（DESIGN 4.5）、その外を指す場所は照らさず、何も書かずに知らせる。
  置き場のフォルダが別名（エイリアス）になっているものも、書き戻さずに知らせる。
- 台帳や資料の一覧が消えた・読めない・項目が消えた・ハッシュが書き換えられたときも、控えにある入れたときの値で
  照らし続け、そのことを知らせる（どの経路で変わっても結果で守る。DESIGN 5章）。
- 戻す元：版の履歴の置き場（.git）から、入れたときのハッシュと同じ中身を探す。版の印（Git の中身の印）が
  あればそれを先に見て、なければ、その場所の版を新しい方からさかのぼる（社長が送ったときに、書き換わった中身が
  先に版になっていることがあるため、いちばん新しい版とは限らない）。見つからなければ戻さずに知らせる。
  原本と公式資料は、道具が置く前に中身を版の履歴の置き場に入れ、版の印を台帳・資料の一覧・控えに残す。
- 戻した原本と公式資料は、読み取り専用にする。中身が同じで書き込めるようになっていたものも、読み取り専用に戻す。
- 版の記録より先に動かす（hooks/originals_hooks.py）。書き換わった中身を版に残さず、原本と公式資料の版が
  入れたときの1版のままになるようにするため（DESIGN 10章）。
- 毎回すべてを読まないよう、照らした中身の大きさ・更新時刻・状態の変わった時刻・番号を
  `.hojokin/一時/原本の照らし.json` に控え、同じなら読まずに同じとみなす（中身を書き換えると、状態の変わった時刻は
  必ず変わる）。違えばハッシュで比べる。1回に使う時間に上限を設け、照らしきれなかった分は次の場面に回す。
- 戻せなかったもの（版の履歴に入れたときの中身がない）と、確かめられないもの（台帳が読めない など）は、
  応答の終わりには一度だけ伝える（同じことで毎回 Claude を続けさせない）。開いたときは、まだ残っていれば伝え直す。

版の履歴の置き場を読むときだけ、同梱の dulwich（lib/history.py）を読み込む。照らすだけなら標準のライブラリで動く。
"""

from __future__ import annotations

import json
import os
import stat as stat_mode
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lib import company, protected_store, seiri
from lib.company_init import RECORDS_DIR

ORIGINAL = protected_store.ORIGINAL
OFFICIAL = protected_store.OFFICIAL
TEXT_DIR = "資料の本文"  # lib/official_docs.py の TEXT_DIR と同じ
LIST_FILE = "資料の一覧.json"  # lib/official_docs.py の LIST_FILE と同じ
CACHE_FILE = "原本の照らし.json"
READ_ONLY = seiri.READ_ONLY
# 1回の照らしで、中身を読むのに使う秒数（hook の見張りと、版の記録の時間を残す。仮）
BUDGET_SECONDS = 8.0
NOTE_LIST_MAX = 5
FIX_LEDGER = "台帳を前の版に戻してください（kiroku の版の道具の revert）"
FIX_LIST = "資料の一覧を前の版に戻すか、同じ資料の一覧で取り直してください"


@dataclass
class Target:
    """照らすもの1つ。path は会社のフォルダからの場所。"""

    path: str
    sha256: str
    kind: str  # 原本・公式資料
    blob: str = ""  # Git の中身の印（台帳・資料の一覧・控えにあれば）


@dataclass
class Report:
    restored: List[Target] = field(default_factory=list)  # 戻したもの
    failed: List[Target] = field(default_factory=list)  # 変わっていたが、戻せなかったもの（新しく見つけたもの）
    failed_known: List[Target] = field(default_factory=list)  # 戻せなかったもの（前の場面で伝え、中身も同じもの）
    unchecked: List[Target] = field(default_factory=list)  # 時間の上限で、照らしきれなかったもの
    problems: List[str] = field(default_factory=list)  # 台帳や資料の一覧が読めないなど（新しく見つけたもの）
    problems_known: List[str] = field(default_factory=list)  # 同じく、前の場面で伝えたもの


def _shown(paths: List[str]) -> str:
    rest = len(paths) - NOTE_LIST_MAX
    return "、".join(paths[:NOTE_LIST_MAX]) + (f"（ほか{rest}件）" if rest > 0 else "")


# ---- 照らすもの ----


def _list_files(folder: Path) -> List[Path]:
    base = Path(folder) / RECORDS_DIR / TEXT_DIR
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob(f"*/{LIST_FILE}") if p.is_file())


def _hash_text(value: object) -> str:
    return value if isinstance(value, str) and value else ""


def _from_ledger(folder: Path, problems: List[str]) -> Tuple[List[Target], bool]:
    """台帳の原本。(照らすもの, 台帳が読めたか)。"""
    try:
        ledger = seiri.load_ledger(folder)
    except seiri.SeiriError as e:
        problems.append(str(e))
        return [], False
    except Exception as e:  # 思わぬ形でも、公式資料の照らしは続ける
        problems.append(f"{seiri.LEDGER_PATH} が読めません（{type(e).__name__}）")
        return [], False
    found: List[Target] = []
    outside: List[str] = []
    for e in seiri.originals(ledger):
        place = seiri.nfc(e["場所"])
        digest = _hash_text(e.get("ハッシュ"))
        if not digest:
            continue
        if not protected_store.allowed_place(place, ORIGINAL):
            outside.append(place)
            continue
        found.append(Target(place, digest, ORIGINAL, _hash_text(e.get("版の印"))))
    if outside:
        problems.append(f"{seiri.LEDGER_PATH} の原本の場所のうち、原本の置き場（原本/<区分>/）の外を指すものは、"
                        f"照らしていません（何も書き戻していません）：{_shown(outside)}")
    return found, True


def _from_list(folder: Path, list_file: Path, problems: List[str]) -> List[Target]:
    """資料の一覧の公式資料。"""
    rel_list = list_file.relative_to(folder).as_posix()
    try:
        data = json.loads(list_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        problems.append(f"{rel_list} が読めません（{type(e).__name__}）")
        return []
    if not isinstance(data, dict):
        problems.append(f"{rel_list} の形が違います")
        return []
    places = data.get("置き場所") if isinstance(data.get("置き場所"), dict) else {}
    docs = data.get("資料") if isinstance(data.get("資料"), list) else []
    found: List[Target] = []
    outside: List[str] = []
    for doc in docs:
        if not isinstance(doc, dict) or not isinstance(doc.get("id"), str):
            continue
        place = places.get(doc["id"])
        file = place.get("ファイル") if isinstance(place, dict) else None
        digest = _hash_text(doc.get("ハッシュ"))
        if not isinstance(file, str) or not file or not digest:
            continue
        file = seiri.nfc(file)
        if not protected_store.allowed_place(file, OFFICIAL):
            outside.append(file)
            continue
        found.append(Target(file, digest, OFFICIAL, _hash_text(place.get("版の印"))))
    if outside:
        problems.append(f"{rel_list} の公式資料の場所のうち、公式資料の置き場（案件/<案件>/公式資料/）の外を指すものは、"
                        f"照らしていません（何も書き戻していません）：{_shown(outside)}")
    return found


def _listed(folder: Path, problems: List[str]) -> Tuple[List[Target], bool]:
    """台帳の原本と、資料の一覧の公式資料（同じ場所は1つ）。(照らすもの, 台帳が読めたか)。"""
    folder = Path(folder)
    found, ledger_ok = _from_ledger(folder, problems)
    for list_file in _list_files(folder):
        found += _from_list(folder, list_file, problems)
    unique: List[Target] = []
    seen = set()
    for t in found:
        if t.path not in seen:
            seen.add(t.path)
            unique.append(t)
    return unique, ledger_ok


def targets(folder: Path, problems: Optional[List[str]] = None) -> List[Target]:
    """台帳の原本と、資料の一覧の公式資料。読めないもの・置き場の外を指すものは problems に理由を足して飛ばす。"""
    return _listed(Path(folder), problems if problems is not None else [])[0]


def _merge(listed: List[Target], anchors: Dict[str, dict], ledger_ok: bool,
           problems: List[str]) -> Tuple[List[Target], Dict[str, dict]]:
    """台帳・資料の一覧と控えを合わせる。(照らすもの, 新しい控え)。

    控えにあるものは、控えの値（入れたときの値）で照らす。台帳・資料の一覧にない・ハッシュが違うものは知らせる。
    """
    result: List[Target] = []
    new_anchors = dict(anchors)
    differ: List[str] = []
    seen = set()
    for t in listed:
        seen.add(t.path)
        old = anchors.get(t.path)
        if old is None:
            new_anchors[t.path] = {"ハッシュ": t.sha256, "版の印": t.blob, "種類": t.kind}
        elif old["ハッシュ"] != t.sha256 or old["種類"] != t.kind:
            differ.append(t.path)
        elif not old["版の印"] and t.blob:
            new_anchors[t.path] = dict(old, 版の印=t.blob)
        a = new_anchors[t.path]
        result.append(Target(t.path, a["ハッシュ"], a["種類"], a["版の印"]))
    missing = {ORIGINAL: [], OFFICIAL: []}
    for path in sorted(anchors):
        if path not in seen:
            a = anchors[path]
            missing[a["種類"]].append(path)
            result.append(Target(path, a["ハッシュ"], a["種類"], a["版の印"]))
    if differ:
        problems.append(f"台帳・資料の一覧のハッシュが、入れたときと違うものがあります（書き換えられた可能性があります）："
                        f"{_shown(differ)}。入れたときの中身で照らしています。{FIX_LEDGER}。公式資料なら{FIX_LIST}")
    if missing[ORIGINAL]:
        if ledger_ok:
            problems.append(f"{seiri.LEDGER_PATH} に、前に照らした原本がありません（台帳から項目が消えました）："
                            f"{_shown(missing[ORIGINAL])}。控えにある入れたときの中身で照らし続けます。{FIX_LEDGER}")
        else:
            problems.append(f"台帳が読めないため、前に照らした原本 {len(missing[ORIGINAL])} 件は、"
                            f"控えにある入れたときの中身で照らしています。{FIX_LEDGER}")
    if missing[OFFICIAL]:
        problems.append(f"資料の一覧（{RECORDS_DIR}/{TEXT_DIR}/<案件>/{LIST_FILE}）に、前に照らした公式資料がありません"
                        f"（一覧が消えたか、読めないか、項目が消えました）：{_shown(missing[OFFICIAL])}。"
                        f"控えにある入れたときの中身で照らし続けます。{FIX_LIST}")
    return result, new_anchors


# ---- 控え（読まずに済ませるための、大きさと時刻） ----


def _cache_path(folder: Path) -> Path:
    return Path(folder) / company.MARKER_DIR / company.TEMP_DIR / CACHE_FILE


CHECKED_KEY = "照らした"  # 場所 → [大きさ, 更新時刻, 状態の変わった時刻, 番号, 入れたときのハッシュ]
FAILED_KEY = "戻せなかった"  # 場所 → 伝えたときの今の中身のハッシュ（同じなら、応答の終わりに伝え直さない）
PROBLEMS_KEY = "伝えたこと"  # 伝えた「確かめられないもの」の文


def _load_cache(folder: Path) -> dict:
    try:
        data = json.loads(_cache_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(folder: Path, cache: dict) -> None:
    path = _cache_path(folder)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".原本の照らし_", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except OSError:
        pass  # 控えは無くてもよい（次は中身を読んで照らす）


def _stat_key(st: os.stat_result) -> list:
    return [st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino]


# ---- 戻す ----


def _inside(folder: Path, path: Path) -> bool:
    real_folder = os.path.realpath(str(folder))
    real_parent = os.path.realpath(str(path.parent))
    return os.path.commonpath([real_folder, real_parent]) == real_folder


def find_content(folder: Path, target: Target) -> Optional[bytes]:
    """版の履歴の置き場から、target のハッシュと同じ中身を探す。なければ None。"""
    from lib import history  # 同梱の dulwich を読み込む（戻すときだけ）

    if not history.enabled(folder):
        return None
    if target.blob:
        from dulwich.repo import Repo

        repo = Repo(str(folder))
        try:
            obj = repo.object_store[target.blob.encode("ascii")]
            data = obj.as_raw_string()
            if seiri.sha256_bytes(data) == target.sha256:
                return data
        except (KeyError, ValueError, AttributeError, UnicodeEncodeError):
            pass
        finally:
            repo.close()
    for record in history.log(folder, target.path):
        data = history.content_at(folder, record.version, target.path)
        if data is not None and seiri.sha256_bytes(data) == target.sha256:
            return data
    return None


def _write_back(folder: Path, target: Target, data: bytes) -> None:
    """入れたときの中身を書き戻し、読み取り専用にする。書きかけのファイルが残らないよう、隣に書いてから置き換える。

    書き戻すのは、原本の置き場と公式資料の置き場の下だけ。途中のフォルダが別名のときも書かない。
    """
    if not protected_store.allowed_place(target.path, target.kind):
        raise OSError(f"{target.path} は原本・公式資料の置き場の外です")
    problem = protected_store.real_place_problem(folder, target.path)
    if problem:
        raise OSError(problem)
    path = Path(folder) / target.path
    if not _inside(folder, path):
        raise OSError(f"{target.path} の置き場が会社のフォルダの外を指しています")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.isdir(str(path)) and not os.path.islink(str(path)):
        raise OSError(f"{target.path} がフォルダになっています")
    fd, tmp = tempfile.mkstemp(prefix=".hojokin-戻し_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, READ_ONLY)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---- 照らす ----


def _current_sha(path: Path) -> str:
    try:
        return seiri.sha256_of(path) if os.path.isfile(str(path)) else ""
    except OSError:
        return ""


def _check_one(folder: Path, t: Target, cache: dict, deadline: Optional[float], report: Report,
               new_cache: Dict[str, list], changed: List[Target]) -> None:
    """1つを照らす。変わった・消えたものは changed に足す。"""
    problem = protected_store.real_place_problem(folder, t.path)
    if problem:
        report.problems.append(f"{t.path}（{t.kind}）は、{problem}。照らしていません（何も書き戻していません）")
        return
    path = folder / t.path
    try:
        st = os.lstat(str(path))
    except FileNotFoundError:
        changed.append(t)
        return
    except OSError as e:
        report.problems.append(f"{t.path} を確かめられません（{type(e).__name__}）")
        return
    if not stat_mode.S_ISREG(st.st_mode):
        changed.append(t)
        return
    cached = cache.get(t.path)
    if isinstance(cached, list) and cached == _stat_key(st) + [t.sha256]:
        new_cache[t.path] = cached
        return
    if deadline is not None and time.monotonic() > deadline:
        report.unchecked.append(t)
        return
    try:
        digest = seiri.sha256_of(path)
    except OSError as e:
        report.problems.append(f"{t.path} を読めません（{type(e).__name__}）")
        return
    if digest != t.sha256:
        changed.append(t)
        return
    if stat_mode.S_IMODE(st.st_mode) & 0o222:
        try:
            os.chmod(str(path), READ_ONLY)
            st = os.lstat(str(path))
        except OSError:
            pass
    new_cache[t.path] = _stat_key(st) + [t.sha256]


def check(folder: Path, budget: Optional[float] = BUDGET_SECONDS) -> Report:
    """原本と公式資料を照らし、変わった・消えたものを戻す。結果を返す。

    戻せなかったものと確かめられないものは、前の場面で伝えたものと同じなら *_known に分ける
    （応答の終わりのたびに同じことで Claude を続けさせないため。開いたときは、どちらも伝える）。
    """
    folder = Path(folder)
    report = Report()
    found_problems: List[str] = []
    listed, ledger_ok = _listed(folder, found_problems)
    anchors, anchor_problem = protected_store.load_anchors(folder)
    saved = _load_cache(folder)
    if not listed and not found_problems and not saved and not anchors and not anchor_problem:
        return report
    if anchor_problem:
        found_problems.append(f"{anchor_problem}。台帳と資料の一覧で照らし、控えを作り直します")
    all_targets, new_anchors = _merge(listed, anchors, ledger_ok, found_problems)
    deadline = None if budget is None else time.monotonic() + budget
    cache = saved.get(CHECKED_KEY) if isinstance(saved.get(CHECKED_KEY), dict) else {}
    told_failed = saved.get(FAILED_KEY) if isinstance(saved.get(FAILED_KEY), dict) else {}
    told_problems = saved.get(PROBLEMS_KEY) if isinstance(saved.get(PROBLEMS_KEY), list) else []
    new_cache: Dict[str, list] = {}
    new_failed: Dict[str, str] = {}
    changed: List[Target] = []
    report.problems = found_problems
    for t in all_targets:
        try:
            _check_one(folder, t, cache, deadline, report, new_cache, changed)
        except Exception as e:  # 1つが思わぬ形でも、ほかのものは続ける
            report.problems.append(f"{t.path} を確かめられません（{type(e).__name__}）")
    for t in changed:
        try:
            data = find_content(folder, t)
        except Exception as e:  # 版の履歴が読めないなど。ほかのものは続ける
            report.problems.append(f"{t.path} の入れたときの中身を、版の履歴から探せませんでした（{type(e).__name__}: {e}）")
            data = None
        written = False
        if data is not None:
            try:
                _write_back(folder, t, data)
                written = True
            except OSError as e:
                report.problems.append(f"{t.path} を戻せませんでした（{e}）")
        if not written:
            now = _current_sha(folder / t.path)
            new_failed[t.path] = now
            (report.failed_known if told_failed.get(t.path) == now else report.failed).append(t)
            continue
        report.restored.append(t)
        try:
            new_cache[t.path] = _stat_key(os.lstat(str(folder / t.path))) + [t.sha256]
        except OSError:
            pass
    report.problems_known = [p for p in report.problems if p in told_problems]
    report.problems = [p for p in report.problems if p not in told_problems]
    _save_cache(folder, {CHECKED_KEY: new_cache, FAILED_KEY: new_failed,
                         PROBLEMS_KEY: report.problems_known + report.problems})
    if new_anchors != anchors or anchor_problem:
        try:
            protected_store.save_anchors(folder, new_anchors)
        except OSError:
            pass  # 控えに書けなくても、台帳と資料の一覧で照らす（次の場面で書き直す）
    return report


def failure_notes(folder: Path, error: BaseException, at_start: bool) -> List[str]:
    """照らしそのものが止まったときに伝える文。応答の終わりには、前に伝えた同じ文は伝え直さない。"""
    text = f"【hojokin】原本と公式資料を照らせませんでした（{type(error).__name__}: {error}）。次の場面で、また照らします。"
    try:
        saved = _load_cache(folder)
        told = saved.get(PROBLEMS_KEY) if isinstance(saved.get(PROBLEMS_KEY), list) else []
        if text in told:
            return [text] if at_start else []
        saved[PROBLEMS_KEY] = told + [text]
        _save_cache(folder, saved)
    except Exception:
        pass  # 控えが使えなくても、伝えることは伝える
    return [text]


# ---- Claude に伝える文 ----


def _names(items: List[Target]) -> str:
    return _shown([f"{t.path}（{t.kind}）" for t in items])


def notes(report: Report, at_start: bool) -> List[str]:
    """照らした結果のうち、Claude に伝えることの文。何もなければ空。

    開いたときは、前の場面で伝えた「戻せなかったもの」「確かめられないもの」も伝え直す。応答の終わりは、
    新しく見つけたものだけを伝え、照らしきれなかった分は伝えない（次の場面で照らすだけなので、続けさせない）。
    """
    when = "社長の最初の発言に答えるときに" if at_start else "社長に"
    failed = report.failed + (report.failed_known if at_start else [])
    problems = report.problems + (report.problems_known if at_start else [])
    result = []
    if report.restored:
        result.append(
            "【hojokin】原本・公式資料のうち、次のファイルが入れたときの中身から変わっていた（または消えていた）ため、"
            f"版の履歴から入れたときの中身に戻しました：{_names(report.restored)}。"
            "原本と公式資料は書き換えません。直した形が要るときは、原本はそのままにして、案件の書類フォルダに写しを作ります。"
            f"{when}、戻したことを平易に伝えてください。"
        )
    if failed:
        result.append(
            "【hojokin】次の原本・公式資料は、入れたときの中身から変わっている（または消えている）のに、"
            f"版の履歴に入れたときの中身が見つからず、戻せませんでした：{_names(failed)}。"
            f"{when}伝え、原本なら元の書類をもう一度入れてもらうか、公式資料なら取り直すかを相談してください。"
        )
    if report.unchecked and at_start:
        result.append(
            f"【hojokin】原本・公式資料が多いため、{len(report.unchecked)}件は今回照らしきれませんでした。次の場面で照らします。"
        )
    if problems:
        shown = "。".join(problems[:NOTE_LIST_MAX])
        result.append(f"【hojokin】原本・公式資料の照らしで、確かめられないものがありました：{shown}。{when}伝えてください。")
    return result
