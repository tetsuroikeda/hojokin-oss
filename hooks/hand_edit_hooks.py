"""社長が Word・Excel の申請書を手で直したときに、前の版との差分を Claude に渡す（SPEC F13「申請書の手直しから学ぶ」、
DESIGN 10章「学ぶきっかけと、残し方」、TASKS B5）。

- 社長が送ったとき（UserPromptSubmit）と開いたとき（SessionStart）に、版の記録（version_hooks）が「社長」として
  残した版のうち、申請書（`案件/<案件>/<段階>/申請書/` の Word・Excel）で、まだ伝えていないものを探す。
- 書類ごとに、その版と1つ前の版の文字を取り出し（lib/doc_text.py。Word は段落、Excel は行）、
  タブ・改行・空白の違いはそろえてから比べる（LibreOffice で保存し直すと、中身が同じでもずれるため。実験 E2）。
- 差分を、Claude に渡す一言（additionalContext）にする。Claude は、事実の訂正か、言い回しか、方針かを判断して
  記録の道具で残す（迷えば社長に確かめる。kiroku の SKILL.md）。差分は3,000字（仮）までにし、超えたら
  直した書類と段落の数だけを渡し、中身は版の道具（versions.py show）で読ませる。
- 伝えた版は `.hojokin/一時/手直し/伝えた版.json` に控え、同じ手直しを2回伝えない（版の履歴に入れない場所）。
- どんな失敗でも例外を外に出さない（hook が落ちると、run.sh が「Python が動かない」とみなすため）。何も足さないだけにする。
"""

from __future__ import annotations

import difflib
import io
import json
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from lib import company, view_only

STATE_DIR = "手直し"
STATE_FILE = "伝えた版.json"
DIFF_LIMIT = 3000  # 渡す差分の字数の上限（仮。DESIGN 10章）
LOG_LIMIT = 60  # 探す履歴の件数（書類ごとの1件で数える）
KEEP = 300  # 控える版の数
PARAGRAPH_LIMIT = 300  # 1つの段落を渡す字数
SUFFIXES = (".docx", ".xlsx")
_SPACE = re.compile(r"[\s　]+")


def _state_path(folder: Path) -> Path:
    return Path(folder) / company.MARKER_DIR / company.TEMP_DIR / STATE_DIR / STATE_FILE


def _load(folder: Path) -> List[str]:
    try:
        value = json.loads(_state_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _save(folder: Path, keys: List[str]) -> None:
    path = _state_path(folder)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(keys[-KEEP:], ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        pass


def is_application(document: str) -> bool:
    """申請書（案件/<案件>/<段階>/申請書/ の Word・Excel）か。"""
    parts = document.split("/")
    return (len(parts) >= 5 and parts[0] == "案件" and parts[3] == "申請書"
            and document.lower().endswith(SUFFIXES) and not parts[-1].startswith("~$"))


def paragraphs(document: str, blob: Optional[bytes]) -> List[str]:
    """書類の文字を、段落（Excel は行）ごとに並べる。読めなければ空。"""
    if not blob:
        return []
    from lib import doc_text

    try:
        if document.lower().endswith(".docx"):
            text = doc_text.word_text(io.BytesIO(blob))
            return [line for line in text.splitlines() if line.strip()]
        lines = []
        for name, text in doc_text.excel_sheets(io.BytesIO(blob)):
            lines += [f"{name}：{line}" for line in text.splitlines() if line.strip()]
        return lines
    except Exception:
        return []


def _same(text: str) -> str:
    return _SPACE.sub("", text)


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= PARAGRAPH_LIMIT else text[: PARAGRAPH_LIMIT - 1] + "…"


def diff_lines(before: List[str], after: List[str]) -> List[str]:
    """段落ごとの差（空白・タブ・改行の違いは除く）。「前：」「後：」の行で返す。"""
    a = [_same(p) for p in before]
    b = [_same(p) for p in after]
    out: List[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        old = [before[i] for i in range(i1, i2)]
        new = [after[j] for j in range(j1, j2)]
        for k in range(max(len(old), len(new))):
            if k < len(old) and k < len(new):
                out += [f"- 前：{_short(old[k])}", f"  後：{_short(new[k])}"]
            elif k < len(old):
                out.append(f"- 消した：{_short(old[k])}")
            else:
                out.append(f"- 足した：{_short(new[k])}")
    return out


def _previous(folder: Path, record) -> Optional[str]:
    """その書類の、その版の1つ前の版の印。"""
    from lib import history

    found = False
    for rec in history.log(folder, record.document):
        if found:
            return rec.version
        if rec.version == record.version:
            found = True
    return None


def find_new(folder: Path) -> List[Tuple[object, List[str]]]:
    """まだ伝えていない、社長の手直しの版と、その差分の行。伝えたものとして控える。"""
    from lib import history

    if not history.enabled(folder):
        return []
    told = _load(folder)
    found = []
    keys = []
    for rec in reversed(history.log(folder, limit=LOG_LIMIT)):  # 古い順
        if rec.who != history.OWNER or not is_application(rec.document) or rec.change == history.DELETED:
            continue
        key = f"{rec.version}:{rec.document}"
        if key in told:
            continue
        keys.append(key)
        prev = _previous(folder, rec)
        before = paragraphs(rec.document, history.content_at(folder, prev, rec.document)) if prev else []
        after = paragraphs(rec.document, history.content_at(folder, rec.version, rec.document))
        lines = diff_lines(before, after)
        if lines:
            found.append((rec, lines))
    if keys:
        _save(folder, told + keys)
    return found


def note(folder: Path) -> str:
    found = find_new(folder)
    if not found:
        return ""
    head = ("【hojokin】社長が申請書を手で直しました（前の版との差分。空白・改行の違いは除いています）。"
            "直した所ごとに、事実の訂正か、言い回しか、書き方の方針かを判断してください。kiroku の skill を呼び、"
            "次の申請でも守るもの（言い回し・方針）は、記録の道具で書き方の決まりとして残し（record.py add-rule。出典は "
            "--source 社長の手直し --file <直した書類>）、事実の訂正は add-fact・update-fact で残します。"
            "どれか迷うとき、今回だけの直しか分からないときは、社長に「次からもそうしますか」と確かめてから残します。"
            "社長が直した文は、ツールが書き戻さないでください。")
    blocks = []
    for rec, lines in found:
        when = rec.time.strftime("%Y-%m-%d %H:%M")
        blocks.append(f"### {rec.document}（社長の手直し {when}）\n" + "\n".join(lines))
    text = head + "\n\n" + "\n\n".join(blocks)
    if len(text) <= DIFF_LIMIT:
        return text
    summary = [f"- {rec.document}：直した段落 {sum(1 for l in lines if l.startswith('- '))}か所" for rec, lines in found]
    return (head + "\n\n差分が長いので、直した書類と数だけを示します。中身は kiroku の版の道具（versions.py log・show）で、"
            "前の版を 見るだけ/ に出して読んでください。\n" + "\n".join(summary))


def add(output: Optional[dict], folder: Path, event: str) -> Optional[dict]:
    """その場面の出力に、手直しの差分の一言を足して返す（ほかの処理が渡す情報は消さない）。"""
    try:
        text = note(folder)
    except Exception:
        return output
    if not text:
        return output
    result = view_only.add_context(output, text)
    result["hookSpecificOutput"]["hookEventName"] = event
    return result
