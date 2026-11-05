"""質問の記録（記録/質問の記録.json）を残す hook の中身（SPEC 共通の要件「作業の記録」「聞き方」T0-11、DESIGN 6章。TASKS B15）。

社長への質問と答えを、どの案件のどの段階で聞いたかを付けて残す。2つの経路がある（DESIGN 6章）。
- 選択肢の画面（AskUserQuestion）：PostToolUse hook が、道具の入力（問い・選択肢）と結果（選んだ答え）を読み取って残す。
- 選択肢の画面が使えないとき（画面のない実行など）：Claude が普段の文章で「【質問】」と書き、番号と「（理由：…）」を
  付けて並べる。Stop hook が最後の応答から読み取って問いを残し、社長の次の発言（UserPromptSubmit）を答えとして付ける。

- 1回に聞いた質問の数（同じ回の数）を、問いごとに残す（T0-11 の「1回の質問は3つまで（仮）」を数えるため）。
- 案件と段階：案件のフォルダが1つならそれ。2つ以上なら、いちばん最近に変わったもの。段階は、その案件の段階の
  フォルダのうち、いちばん進んだもの（lib/stage_switch.py と同じ決め方）。案件がなければ空。
- 場所の確かめは lib/places.py で行う（書く先とその途中に別名があれば書かない）。どんな失敗でも例外を外に出さない
  （hook を落とさない）。

標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LOG = "記録/質問の記録.json"
CASES_DIR = "案件"
ROUTE_SCREEN = "選択肢の画面"
ROUTE_TEXT = "【質問】"
_STAGE = re.compile(r"^([0-9]+)_")
_REASON = re.compile(r"[（(]\s*理由\s*[:：]\s*(.+?)\s*[）)]\s*$")
_NUMBERED = re.compile(r"^\s*(?:[0-9０-９]+[.．、)）]|[①-⑳]|[-・*])\s*(.+)$")


def _now(folder: Path) -> str:
    from lib import dates

    return dates.format_datetime(dates.now(folder))


def _stamp(folder: Path) -> str:
    """比べるための時刻（ISO の形。kakunin が、社長の答えの後に審査役の回数を数え直すときに使う）。"""
    from lib import dates

    return dates.now(folder).isoformat(timespec="seconds")


def latest_answer(folder: Path) -> str:
    """いちばん新しい答えの時刻（ISO の形）。答えがなければ空。"""
    try:
        stamps = [str(e.get("答えた時刻") or "") for e in load(folder)["質問"] if e.get("答え")]
    except Exception:
        return ""
    return max(stamps, default="")


def case_and_stage(folder: Path) -> Tuple[str, str]:
    top = folder / CASES_DIR
    try:
        cases = [p for p in top.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        return "", ""
    if not cases:
        return "", ""

    def latest(p: Path) -> float:
        newest = 0.0
        for root, _dirs, files in os.walk(str(p)):
            for name in files:
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(root, name)))
                except OSError:
                    continue
        return newest

    case = cases[0] if len(cases) == 1 else max(cases, key=latest)
    stages = sorted((int(m.group(1)), p.name) for p in case.iterdir() if p.is_dir() and (m := _STAGE.match(p.name)))
    return unicodedata.normalize("NFC", case.name), (stages[-1][1] if stages else "")


def load(folder: Path) -> Dict[str, Any]:
    from lib import places

    path = places.actual(folder, LOG)
    if path is None or not path.is_file():
        return {"説明": "社長への質問と答え（hook が残す）。案件と段階、1回に聞いた数、理由を付ける", "質問": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("質問"), list):
        raise ValueError("質問の記録の形が違います")
    return data


def save(folder: Path, data: Dict[str, Any]) -> None:
    from lib import places

    places.no_link_on_the_way(folder, LOG)
    target = places.actual(folder, LOG, partial=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.書きかけ")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(target))


def _next_number(entries: List[dict]) -> int:
    seen = [int(m.group(1)) for e in entries if (m := re.match(r"質問-([0-9]+)$", str(e.get("番号", ""))))]
    return max(seen, default=0) + 1


def add(folder: Path, questions: List[Dict[str, Any]], route: str, session: str = "") -> List[dict]:
    """1回に聞いた質問（{"問い", "理由", "選択肢", "答え"}）を足す。足した項目を返す。"""
    if not questions:
        return []
    data = load(folder)
    entries = data["質問"]
    case, stage = case_and_stage(folder)
    when = _now(folder)
    n = _next_number(entries)
    added = []
    for q in questions:
        entry = {"番号": f"質問-{n:04d}", "案件": case, "段階": stage, "聞いた日時": when, "問い": q.get("問い", ""),
                 "理由": q.get("理由", ""), "同じ回の数": len(questions), "経路": route}
        if q.get("選択肢"):
            entry["選択肢"] = q["選択肢"]
        if q.get("答え"):
            entry["答え"] = q["答え"]
            entry["答えた日時"] = when
            entry["答えた時刻"] = _stamp(folder)
        if session:
            entry["session_id"] = session
        entries.append(entry)
        added.append(entry)
        n += 1
    save(folder, data)
    return added


# ---------------------------------------------------------------- 選択肢の画面（AskUserQuestion）


def _answer_text(response: Any, question: str) -> str:
    """道具の結果から、その問いの答え。形が分からなければ、結果の文をそのまま。"""
    if isinstance(response, dict):
        answers = response.get("answers")
        if isinstance(answers, dict):
            hit = answers.get(question)
            if hit is not None:
                return ", ".join(hit) if isinstance(hit, list) else str(hit)
        for key in ("answer", "result", "content"):
            if isinstance(response.get(key), str):
                return response[key]
        return json.dumps(response, ensure_ascii=False)[:500]
    if isinstance(response, list):
        return " ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in response)[:500]
    return str(response or "")[:500]


def from_ask_user(tool_input: Any, tool_response: Any) -> List[Dict[str, Any]]:
    out = []
    items = tool_input.get("questions") if isinstance(tool_input, dict) else None
    for q in items or []:
        if not isinstance(q, dict):
            continue
        text = str(q.get("question") or "").strip()
        if not text:
            continue
        options = [str(o.get("label") if isinstance(o, dict) else o) for o in q.get("options") or []]
        m = _REASON.search(text)
        reason = m.group(1) if m else ""
        out.append({"問い": text, "理由": reason, "選択肢": options, "答え": _answer_text(tool_response, text)})
    return out


def post_tool_use(data: Dict[str, Any], folder: Path) -> None:
    try:
        if data.get("tool_name") != "AskUserQuestion":
            return
        found = from_ask_user(data.get("tool_input"), data.get("tool_response"))
        add(folder, found, ROUTE_SCREEN, str(data.get("session_id") or ""))
    except Exception:
        return


# ---------------------------------------------------------------- 普段の文章の【質問】


def from_text(message: str) -> List[Dict[str, Any]]:
    """最後の応答の「【質問】」の後の、番号を付けた問いと（理由：…）。"""
    text = unicodedata.normalize("NFKC", message or "")
    at = text.rfind("【質問】")
    if at < 0:
        return []
    out = []
    for line in text[at + len("【質問】"):].splitlines():
        if out and line.strip().startswith(("【", "#")):
            break  # 次の見出しや印から先は、質問ではない
        m = _NUMBERED.match(line)
        if not m:
            continue
        body = m.group(1).strip()
        r = _REASON.search(body)
        reason = r.group(1).strip() if r else ""
        question = body[: r.start()].strip() if r else body
        out.append({"問い": question, "理由": reason})
    return out


def _last_assistant_text(data: Dict[str, Any]) -> str:
    text = data.get("last_assistant_message")
    if isinstance(text, str) and text.strip():
        return text
    path = data.get("transcript_path")
    if not path:
        return ""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in reversed(lines[-400:]):
        try:
            item = json.loads(line)
        except ValueError:
            continue
        msg = item.get("message") if isinstance(item, dict) else None
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        texts = [c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return ""


def stop(data: Dict[str, Any], folder: Path) -> None:
    try:
        found = from_text(_last_assistant_text(data))
        if not found:
            return
        waiting = [e.get("問い") for e in load(folder)["質問"] if e.get("経路") == ROUTE_TEXT and not e.get("答え")]
        if waiting[-len(found):] == [q["問い"] for q in found]:
            return  # 同じ応答の終わりが2回来たとき（続けさせた後など）に、同じ問いを二重に残さない
        add(folder, found, ROUTE_TEXT, str(data.get("session_id") or ""))
    except Exception:
        return


def user_prompt_submit(data: Dict[str, Any], folder: Path) -> None:
    """【質問】で聞いて、まだ答えのない問いに、社長の次の発言を答えとして付ける。"""
    try:
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            return
        log = load(folder)
        waiting = [e for e in log["質問"] if e.get("経路") == ROUTE_TEXT and not e.get("答え")]
        if not waiting:
            return
        when, stamp = _now(folder), _stamp(folder)
        for e in waiting:
            e["答え"] = prompt[:2000]
            e["答えた日時"] = when
            e["答えた時刻"] = stamp
        save(folder, log)
    except Exception:
        return
