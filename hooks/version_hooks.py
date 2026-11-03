"""版の記録と、版の名前のファイルの守り（DESIGN 5章「版を自動で残す」「版のファイルを増やさない」、
10章「書類の版」。TASKS M0a）。hook の場面ごとの入口で、それぞれの場面のファイルから1行で呼ぶ。

- SessionStart（startup・resume・clear）：閉じている間に社長が手で変えたファイルを「社長」として残す。
  理由は「社長が手で変更」。compact では残さない（応答の途中で自動の compact が走ると、ツールが変えた分を
  社長の分として残してしまうため。社長の分は、次に送ったときに残る）。
  版の記録が止まっているとき、大きすぎて残せないファイルがあるとき、読めないファイル・フォルダがあるとき
  （権限がないなど。そのファイルだけを飛ばし、ほかは残す）、残しきれずに次に回したファイルがあるときは、
  開いたときの情報（additionalContext）で Claude に伝える。
- UserPromptSubmit：社長が手で変えたファイルを「社長」として残し、社長の依頼の文を控える（Stop の理由に使う）。
  控えは `.hojokin/一時/版の記録/<セッション>.json`（版の履歴に入れない）。
  前の応答が終わらないまま次の発言が来たとき（応答を途中で止めたとき）は、それまでに変わった分は
  前の応答でツールが変えたものとして「ツール」で残す（仮。TASKS M0a の質問）。そのとき足された版の名前の
  ファイルは控えておき、次の Stop で伝える。
- PreToolUse：Write・Edit・NotebookEdit で、版の名前の新しいファイル・フォルダを拒む（lib/version_names.py）。
- Stop：ツールが変えたファイルを「ツール」として残す。理由は、控えた依頼の文。
  その応答で足されたファイル（とフォルダ）に版の名前のものがあれば、元のファイルにまとめるよう Claude に伝える
  （decision: block）。Stop の hook で続けているとき（stop_hook_active）も、新しく足された分は伝える
  （伝えるのは新しく足されたものだけなので、同じものを繰り返し伝えない）。1つの応答で続けさせるのは
  MAX_BLOCKS 回までにし、超えた分は控えて、次の応答の終わりに伝える。
  続けさせるときは、応答をまだ終わっていないもの（応答中）として控える。続きの中でツールが変えた分は、
  続きの Stop で「ツール」として残し、社長が続きを止めて次を送ったときも「ツール」で残す（社長の分にしない）。
  Stop のほかの hook が続けさせるときは、continue_response() で同じように控える（後のタスク）。

1回の場面で版を残すのに使う時間には、hooks/run.sh の見張りより短い上限を設ける（BUDGET_SECONDS）。
残しきれない分は次の場面に回す（lib/history.py）。版を残す処理が落ちたとき（.git が壊れた、書けないなど）は、
hook を落とさずに控え（`.hojokin/一時/版の記録/止まった.json`）、開いたときに伝える。hook が落ちると、
run.sh が「Python が動かない」とみなし、開いたときに誤った案内（開発ツールを入れる）を渡すため。

会社のフォルダに Git の形の版の履歴（.git）がないときは、何もしない（.git を作らない）。
版の履歴は lib/history.py が扱う。dulwich を読み込むので、PreToolUse では読み込まない。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import outside_read
from lib import company, dates, version_names

WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")
STATE_DIR = "版の記録"
FAILURE_FILE = "止まった.json"
RECORDED_SOURCES = ("startup", "resume", "clear")
FALLBACK_REASON = "Claude の作業（依頼の文を控えられなかった）"
INTERRUPTED_NOTE = "（応答が途中で止まったため、次の発言のときに残した）"
# 1回の場面で版を残すのに使う秒数。hooks/run.sh の見張り（開いたとき・送ったときは25秒、応答の終わりは55秒）より
# 短くし、同じ hook のほかの処理（開いたときの情報の組み立て、応答の終わりの確かめなど）の時間を残す（仮）
BUDGET_SECONDS = {"SessionStart": 15.0, "UserPromptSubmit": 15.0, "Stop": 35.0}
# テストのために短くだけできる（長くはできない。見張りに止められないように）
BUDGET_ENV = "HOJOKIN_RECORD_SECONDS"
# 1つの応答の中で、版の名前のファイルを伝えて続けさせる回数の上限（仮）
MAX_BLOCKS = 3
# 開いたときに名前を挙げるファイルの数
NOTE_LIST_MAX = 5
SCENE_WORDS = {"SessionStart": "開いたとき", "UserPromptSubmit": "社長が送ったとき", "Stop": "応答の終わり"}
_SAFE_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


# ---- 社長の依頼の文の控え（版の履歴に入れない場所） ----

def _state_dir(folder: Path) -> Path:
    return Path(folder) / company.MARKER_DIR / company.TEMP_DIR / STATE_DIR


def _state_path(folder: Path, session_id) -> Optional[Path]:
    if not session_id:
        return None
    text = str(session_id)
    key = text if _SAFE_SESSION.match(text) else hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
    return _state_dir(folder) / f"{key}.json"


def _read_json(path: Optional[Path]) -> Optional[dict]:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Optional[Path], value: dict) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        # 控えを書けなくても、hook は落とさない（版の記録と守りは続ける）
        pass


def _load_state(folder: Path, session_id) -> Optional[dict]:
    return _read_json(_state_path(folder, session_id))


def _save_state(folder: Path, session_id, value: dict) -> None:
    _write_json(_state_path(folder, session_id), value)


def _now(folder: Path) -> datetime:
    """版の日時（今日の日付の差し替えを含む日本時間）。設定が読めないときは、今の時刻。"""
    try:
        return dates.now(folder)
    except ValueError:
        return datetime.now(timezone.utc)


# ---- 版を残す（落ちても hook を落とさない） ----

def _budget(event: str) -> float:
    limit = BUDGET_SECONDS[event]
    try:
        value = float(os.environ.get(BUDGET_ENV, ""))
    except ValueError:
        return limit
    return value if 0 < value < limit else limit


def _failure_path(folder: Path) -> Path:
    return _state_dir(folder) / FAILURE_FILE


def _save_failure(folder: Path, event: str, error: BaseException) -> None:
    detail = f"{type(error).__name__}: {error}".strip()
    _write_json(_failure_path(folder), {
        "日時": _now(folder).isoformat(timespec="seconds"),
        "場面": event,
        "内容": _one_line(detail, 200),
    })


def _clear_failure(folder: Path) -> None:
    try:
        _failure_path(folder).unlink()
    except OSError:
        pass


def _one_line(text: str, limit: int) -> str:
    line = " ".join(str(text).split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _record(folder: Path, role: str, reason: Optional[str], event: str):
    """版を残す。role は "tool"（ツール）か "owner"（社長。理由は「社長が手で変更」）。

    lib.history.Result を返す。ほかのセッションが残しているところ（HistoryBusy）なら None（変わった分は次の場面で
    残る）。落ちたときも None を返し、止まったことを控える（開いたときに伝える）。
    """
    try:
        from lib import history  # dulwich を読み込むので、使うときだけ
    except Exception as error:  # 同梱が欠けたなど
        _save_failure(folder, event, error)
        return None
    who = history.TOOL if role == "tool" else history.OWNER
    try:
        result = history.record_scene(folder, who, history.OWNER_REASON if reason is None else reason,
                                      when=_now(folder), budget=_budget(event))
    except history.HistoryBusy:
        return None
    except Exception as error:
        _save_failure(folder, event, error)
        return None
    _clear_failure(folder)
    return result


def _enabled(folder: Path) -> bool:
    return (Path(folder) / ".git").is_dir()


# ---- 版の名前のファイル（Stop で伝えるもの） ----

def _found(folder: Path, result) -> List[list]:
    """この場面のツールの分で足されたもののうち、版の名前のもの（[場所, 型の説明, 元のファイル] の一覧）。"""
    if result is None:
        return []
    from lib import history

    added = [ch.path for ch in result.mine if ch.kind == history.ADDED]
    return [list(item) for item in version_names.found_at_stop(Path(folder), added, result.known_dirs)]


def _still_there(folder: Path, entries) -> List[list]:
    """控えた版の名前のファイルのうち、まだあるもの。"""
    kept = []
    for entry in entries if isinstance(entries, list) else []:
        if not (isinstance(entry, list) and len(entry) == 3 and isinstance(entry[0], str) and entry[0]):
            continue
        path = Path(folder) / entry[0].rstrip("/")
        if (path.is_dir() if entry[0].endswith("/") else os.path.lexists(str(path))):
            kept.append(entry)
    return kept


def _merge(first: List[list], second: List[list]) -> List[list]:
    seen = set()
    merged = []
    for entry in first + second:
        if entry[0] in seen:
            continue
        seen.add(entry[0])
        merged.append(entry)
    return merged


def _int(value) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


# ---- 開いたときに伝えること ----

def _names(names: List[str]) -> str:
    """名前を NOTE_LIST_MAX 件まで並べる（超えた分は件数）。"""
    return "、".join(names[:NOTE_LIST_MAX]) + (f"（ほか{len(names) - NOTE_LIST_MAX}件）"
                                              if len(names) > NOTE_LIST_MAX else "")


def _notes(folder: Path, result) -> List[str]:
    notes = []
    failure = _read_json(_failure_path(folder))
    if failure is not None:
        when = failure.get("日時")
        try:
            shown = dates.format_datetime(datetime.fromisoformat(when)) if isinstance(when, str) else ""
        except ValueError:
            shown = ""
        scene = SCENE_WORDS.get(failure.get("場面"), "")
        detail = failure.get("内容") if isinstance(failure.get("内容"), str) else ""
        where = "、".join(p for p in (shown, scene) if p)
        where = "。".join(p for p in (where, detail) if p)
        notes.append(
            f"【hojokin】版の記録が止まっています（{where}）。止まっている間に変えたファイルは、前の版を取り出せない"
            "ことがあります。社長の最初の発言に答えるときに、このことを伝えてください。"
            "次に版を残せたときに、この知らせは消えます。"
        )
    if result is not None and result.too_large:
        from lib import history

        limit = f"{history.LARGE_FILE_BYTES // 1024 ** 3}GB"
        notes.append(
            f"【hojokin】次のファイルは大きすぎるため（1つ{limit}まで。時間内に読みきれないものも含む）、"
            f"版の履歴に残していません（前の版を取り出せません）：{_names([ch.path for ch in result.too_large])}。"
            "社長に伝え、版を残さなくてよいかを確かめてください。"
        )
    if result is not None and (result.unreadable or result.unreadable_dirs):
        dirs = sorted(set(result.unreadable_dirs))
        names = [f"{d}/" for d in dirs] + [ch.path for ch in result.unreadable
                                            if not any(ch.path.startswith(d + "/") for d in dirs)]
        notes.append(
            "【hojokin】次のファイル・フォルダは読めないため（読む権限がないなど）、今の中身を版の履歴に残せていません"
            f"（消したことにもしていません）：{_names(names)}。ほかのファイルは残しています。"
            "社長に伝え、読めるように直す（Finder の「情報を見る」で、自分に読み書きできる権限を付ける）か、"
            "要らなければ消してもらってください。読めるようになれば、次から残します。"
        )
    if result is not None and result.deferred:
        notes.append(
            f"【hojokin】ファイルが多いため、{len(result.deferred)}件はまだ版の履歴に残していません。"
            "次に社長が送ったときなどに、続けて残します。"
        )
    return notes


# ---- 場面ごとの入口 ----

def session_start(data: dict, folder: Path) -> Optional[dict]:
    if not _enabled(folder):
        return None
    source = data.get("source")
    result = None
    if source is None or source in RECORDED_SOURCES:
        result = _record(folder, "owner", None, "SessionStart")
    notes = _notes(folder, result)
    if not notes:
        return None
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(notes)}}


def user_prompt_submit(data: dict, folder: Path) -> None:
    if not _enabled(folder):
        return
    session_id = data.get("session_id")
    state = _load_state(folder, session_id) or {}
    carried = _still_there(folder, state.get("伝えていない"))
    if state.get("応答中"):
        result = _record(folder, "tool", f"{state.get('依頼') or FALLBACK_REASON}{INTERRUPTED_NOTE}",
                         "UserPromptSubmit")
        carried = _merge(carried, _found(folder, result))
    else:
        _record(folder, "owner", None, "UserPromptSubmit")
    prompt = data.get("prompt")
    _save_state(folder, session_id, {"依頼": prompt if isinstance(prompt, str) else "", "応答中": True,
                                     "続けた回数": 0, "伝えていない": carried})


def stop(data: dict, folder: Path) -> Optional[dict]:
    if not _enabled(folder):
        return None
    session_id = data.get("session_id")
    state = _load_state(folder, session_id) or {}
    reason = (state.get("依頼") or "").strip() if isinstance(state.get("依頼"), str) else ""
    result = _record(folder, "tool", reason or FALLBACK_REASON, "Stop")
    items = _merge(_still_there(folder, state.get("伝えていない")), _found(folder, result))
    active = bool(data.get("stop_hook_active"))
    count = _int(state.get("続けた回数")) if active else 0
    new_state = {**state, "依頼": state.get("依頼") or "", "応答中": False, "続けた回数": count, "伝えていない": []}
    output = None
    if items:
        if active and count >= MAX_BLOCKS:
            # 続けさせすぎない。次の応答の終わりに伝える
            new_state["伝えていない"] = items
        else:
            new_state["続けた回数"] = count + 1
            # 続けさせるので、応答はまだ終わっていない。続きの中でツールが変えた分は、続きの Stop で「ツール」として
            # 残す。社長が続きを止めて次を送ったとき（Stop が来ない）も、途中で止まった応答として「ツール」で残す
            new_state["応答中"] = True
            output = {"decision": "block", "reason": version_names.stop_reason([tuple(i) for i in items])}
    _save_state(folder, session_id, new_state)
    return output


def continue_response(data: dict, folder: Path) -> None:
    """Stop のほかの hook（後のタスクの書式の戻しなど）が続けさせる（decision: block）ときに、stop() の後に呼ぶ。

    応答をまだ終わっていないものとして控え、続きの中でツールが変えた分を、社長が続きを止めたときも
    「社長が手で変更」にしないようにする（仮。TASKS M0a の質問）。
    """
    if not _enabled(folder):
        return
    session_id = data.get("session_id")
    state = _load_state(folder, session_id)
    if state is None:
        return
    _save_state(folder, session_id, {**state, "応答中": True})


def pre_tool_use(data: dict, folder: Path) -> Optional[dict]:
    """Write・Edit・NotebookEdit で、版の名前の新しいファイル（か、新しく作られるフォルダ）があれば拒む。

    会社のフォルダの外への書き込みは、先に pre_tool_use._outside_write が拒む（ここでは見ない）。
    """
    if data.get("tool_name") not in WRITE_TOOLS:
        return None
    tool_input = data.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw:
        return None
    target = outside_read.resolve(str(raw), outside_read.tool_cwd(data, folder))
    real_folder = outside_read.real_path(folder)
    if not outside_read.is_inside(target, real_folder) or os.path.lexists(str(target)):
        return None
    rel = target.relative_to(real_folder).as_posix()
    hit = version_names.version_part(rel, lambda prefix: os.path.lexists(str(real_folder / prefix)))
    if hit is None:
        return None
    where, label, is_dir = hit
    original = version_names.original_of(real_folder, where, is_dir=is_dir)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": version_names.deny_reason(where, label, original, is_dir=is_dir),
        }
    }
