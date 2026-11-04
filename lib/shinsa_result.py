"""審査役の結果を、本体を通さずに保存する（DESIGN 8章「結果の保存」、実験 E3b。TASKS M7）。

hook（hooks/shinsa_hooks.py）と、確かめの道具（lib/kakunin.py）が共通に使う。hook でも読み込むので、標準の
ライブラリだけを使い、軽く保つ。/usr/bin/python3（3.9）で動く。

- 確かめの道具は、審査役に渡すものを `記録/審査に渡すもの/` にまとめ、最後に控え（`控え.json`）を置く。
  控えには「確かめの番号」（確かめ-0001 の形）、案件、段階、申請書のハッシュ（申請書のファイルごとのハッシュを
  まとめたもの）を書く。控えは1つで、次に確かめるときに置き換わる。
- 審査役の最後の報告の取り出し方は、モードで違う（実験 E3b）。
  - default と eval（dontAsk）：SubagentStop の `last_assistant_message`。hooks.json の matcher で、審査役
    （`^hojokin:shinsa$`）のときだけ動く。
  - auto：審査役は報告を SubagentHandback の道具で渡し、SubagentStop には報告が来ない。PreToolUse の
    `tool_input.message` から取り出す。この入力に subagent の名前（agent_type）があるかは確かめていないので、
    名前があれば審査役かを照らし、なければ、報告の JSON の確かめの番号が控えと合うときだけ保存する。
- 報告は、前後に json の囲み（3つのバッククォート）が付いたまま届くので、外してから JSON として読む。
  読めなくても、報告の文はそのまま保存する（落とさないため）。
- 保存先は `記録/審査役の結果/<確かめの番号>.json`。報告の確かめの番号が控えと違うとき（前の確かめの報告が
  遅れて届いたときなど）は、その番号のファイルに保存し、控えと合わないことを書く（今の確かめの場所を埋めない）。
- 同じ番号に、もう中身のある結果があれば書き換えない（auto モードでは、報告のある SubagentHandback の後に、
  報告のない SubagentStop が来る。両方に報告があっても、先に届いたものを残す）。
- 保存するときに、今の申請書のハッシュを計算し、控えのハッシュと合うかを書く。報告の文のハッシュも書き、
  完成の判定のときに照らす（DESIGN 5章「審査役の結果は、保存したハッシュと照らし、合わなければ使わない」）。
- 場所の確かめは lib/places.py で行う。書く先と、そこまでのフォルダに別名（シンボリックリンク）があれば書かない。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from lib import places

RECORDS_DIR = "記録"
PACKAGE_DIR = f"{RECORDS_DIR}/審査に渡すもの"
NOTE_FILE = "控え.json"
NOTE_REL = f"{PACKAGE_DIR}/{NOTE_FILE}"
RESULTS_DIR = f"{RECORDS_DIR}/審査役の結果"
CASES_DIR = "案件"
APPLICATION_DIR = "申請書"
MODEL_FILE = "財務モデル.xlsx"

NUMBER_PREFIX = "確かめ-"
NUMBER = re.compile(r"^確かめ-([0-9]{4,})$")
SHINSA = "shinsa"
HANDBACK_TOOL = "SubagentHandback"
FROM_STOP = "SubagentStop.last_assistant_message"
FROM_HANDBACK = "PreToolUse.SubagentHandback.tool_input.message"

_FENCE = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\r?\n(.*?)\r?\n?```", re.S)


def is_shinsa(agent_type: str) -> bool:
    """subagent の名前が審査役か（プラグインの名前が前に付く。hojokin:shinsa）。"""
    name = str(agent_type or "")
    return name == SHINSA or name.endswith(":" + SHINSA)


def number_text(n: int) -> str:
    return f"{NUMBER_PREFIX}{n:04d}"


def number_of(text) -> Optional[int]:
    m = NUMBER.match(str(text or ""))
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- 申請書のハッシュ


def application_rel(case: str, stage: str) -> str:
    return f"{CASES_DIR}/{case}/{stage}/{APPLICATION_DIR}"


def _skipped_name(name: str) -> bool:
    """隠しファイルと、Word・Excel が開いている間だけ作るファイルは、申請書に数えない。"""
    return name.startswith(".") or name.startswith("~$") or name.startswith(".~lock")


def application_files(folder: Path, case: str, stage: str) -> Dict[str, Path]:
    """申請書のファイル（`案件/<案件>/<段階>/申請書/` の下と、会社のフォルダの直下の財務モデル.xlsx）。

    戻り値は、会社のフォルダからの場所（NFC）→ 実際の場所。申請書のフォルダか、その中のものに別名があれば
    places.PlaceError（別名の先の中は読まない）。申請書のフォルダがなければ空。
    """
    out: Dict[str, Path] = {}
    rel = application_rel(case, stage)
    places.no_link_on_the_way(folder, rel)
    top = places.actual(folder, rel)
    if top is not None and top.is_dir():
        for dirpath, dirnames, filenames in os.walk(str(top)):
            for name in list(dirnames) + list(filenames):
                path = Path(dirpath) / name
                if os.path.islink(str(path)) and not _skipped_name(name):
                    sub = places.relative_inside(folder, Path(dirpath)) + "/" + places.nfc(name)
                    raise places.PlaceError(f"{sub} が別名（シンボリックリンク）になっています", path=sub, link=sub)
            dirnames[:] = sorted(d for d in dirnames if not _skipped_name(d))
            for name in sorted(filenames):
                if _skipped_name(name):
                    continue
                path = Path(dirpath) / name
                out[places.relative_inside(folder, path)] = path
    places.no_link_on_the_way(folder, MODEL_FILE)
    model = places.actual(folder, MODEL_FILE)
    if model is not None and model.is_file():
        out[MODEL_FILE] = model
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def file_hashes(folder: Path, case: str, stage: str) -> Dict[str, str]:
    return {rel: sha256_file(path) for rel, path in sorted(application_files(folder, case, stage).items())}


def combined_hash(hashes: Dict[str, str]) -> str:
    """ファイルごとのハッシュをまとめた、申請書のハッシュ。ファイルが1つでも変われば変わる。"""
    text = json.dumps(sorted(hashes.items()), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def application_hash(folder: Path, case: str, stage: str) -> str:
    return combined_hash(file_hashes(folder, case, stage))


def text_hash(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 報告を読む


def strip_fence(text: str) -> str:
    """前後の json の囲み（```json … ```）を外す。囲みがなければそのまま。"""
    stripped = str(text or "").strip()
    m = _FENCE.search(stripped)
    return m.group(1).strip() if m else stripped


def parse_report(text: str) -> Tuple[Optional[dict], str]:
    """報告を JSON として読む。（読んだ中身、読めなかった理由）。中身は { } の形のときだけ返す。"""
    body = strip_fence(text)
    try:
        data = json.loads(body)
    except ValueError as e:
        start, end = body.find("{"), body.rfind("}")
        if start < 0 or end <= start:
            return None, f"JSON として読めません（{e}）"
        try:
            data = json.loads(body[start:end + 1])
        except ValueError as e2:
            return None, f"JSON として読めません（{e2}）"
    if not isinstance(data, dict):
        return None, "報告の JSON が { } の形ではありません"
    return data, ""


# ---------------------------------------------------------------- 控えと結果のファイル


def _read_json(folder: Path, rel: str) -> Optional[dict]:
    """会社のフォルダの中の JSON を読む。別名を通る・ない・読めないときは None。"""
    try:
        places.no_link_on_the_way(folder, rel)
    except places.PlaceError:
        return None
    path = places.actual(folder, rel)
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_note(folder: Path) -> Optional[dict]:
    """今の控え。ない・読めない・確かめの番号の形が違うときは None。"""
    note = _read_json(folder, NOTE_REL)
    if note is None or number_of(note.get("確かめの番号")) is None:
        return None
    return note


def result_rel(number: str) -> str:
    return f"{RESULTS_DIR}/{number}.json"


def load_result(folder: Path, number: str) -> Optional[dict]:
    return _read_json(folder, result_rel(number))


def _now_text(folder: Path) -> str:
    try:
        from lib import dates

        return dates.now(folder).isoformat(timespec="seconds")
    except Exception:  # 設定が読めないなど。時刻のために保存を止めない
        from datetime import datetime, timedelta, timezone

        return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")


def write_json(folder: Path, rel: str, data: dict) -> Path:
    """会社のフォルダの中の rel に JSON を書く（途中に別名があれば places.PlaceError）。"""
    places.no_link_on_the_way(folder, rel)
    target = places.actual(folder, rel, partial=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    # フォルダを作った後にも、もう一度確かめる
    places.no_link_on_the_way(folder, rel)
    if not places.is_inside(folder, target.parent):
        raise places.PlaceError(f"{rel} が会社のフォルダの外になります", path=rel)
    from lib.docx_min import write_replacing

    write_replacing(target, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return target


def save_report(folder: Path, report, where: str, payload: dict, trusted: bool) -> Optional[str]:
    """審査役の報告を、控えと結び付けて保存する。保存したら、その場所（会社のフォルダから）を返す。

    trusted：審査役からの報告だと分かっている（SubagentStop の matcher、または入力の agent_type）。
    分からないとき（auto モードの SubagentHandback で agent_type がないとき）は、報告の確かめの番号が控えと
    合うときだけ保存する。保存しないときは None（控えがない、報告が空、もう結果がある など）。
    """
    if not isinstance(report, str) or not report.strip():
        return None
    note = load_note(folder)
    if note is None:
        return None
    note_number = str(note["確かめの番号"])
    parsed, reason = parse_report(report)
    said = parsed.get("確かめの番号") if parsed is not None else None
    said = said.strip() if isinstance(said, str) else said
    if number_of(said) is not None:
        number = str(said)
    elif trusted:
        number = note_number
    else:
        return None
    if not trusted and number != note_number:
        return None
    rel = result_rel(number)
    existing = _read_json(folder, rel)
    if existing is not None and str(existing.get("報告") or "").strip():
        return None
    same_number = number == note_number
    note_hash = note.get("申請書のハッシュ") if same_number else None
    current = None
    hash_problem = ""
    if same_number:
        try:
            current = application_hash(folder, str(note.get("案件")), str(note.get("段階")))
        except (places.PlaceError, OSError) as e:
            hash_problem = f"今の申請書のハッシュを計算できませんでした（{e}）"
    record = {
        "確かめの番号": number,
        "案件": note.get("案件") if same_number else None,
        "段階": note.get("段階") if same_number else None,
        "控えと合う": same_number,
        "報告の確かめの番号": said,
        "控えの申請書のハッシュ": note_hash,
        "保存したときの申請書のハッシュ": current,
        "ハッシュが合う": bool(current) and current == note_hash,
        "取り出した所": where,
        "agent_type": payload.get("agent_type"),
        "agent_id": payload.get("agent_id"),
        "permission_mode": payload.get("permission_mode"),
        "session_id": payload.get("session_id"),
        "保存した時刻": _now_text(folder),
        "結果": parsed,
        "読めなかった理由": reason or None,
        "ハッシュの注意": hash_problem or None,
        "報告のハッシュ": text_hash(report),
        "報告": report,
    }
    write_json(folder, rel, record)
    return rel
