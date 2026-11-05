"""会話を続けるテストの仕組み（TASKS B2、DESIGN 11章「複数回のやりとり」、SPEC 6章「社長役のAI」）。

`claude plugin eval` では社長役を置けないので、`claude -p` と `--resume` で会話を続ける小さな仕組みを作る。

- 試す側：会社のフォルダを作業フォルダにして、このリポを --plugin-dir で読み込んだ claude -p（モデルは --model）。
- 社長役：Haiku 5.5（--owner-model）。回答表（testdata/デモの会社/回答表.md など）と、あれば台本の決まりだけを見て答える。
  道具は持たせない。回答表にないことは「分かりません」と答える（回答表の「社長役への決まり」と SPEC 6章）。
- 選択肢の画面（AskUserQuestion）：PreToolUse の defer で止め（defer_hook.py）、社長役に選ばせて、答えのファイルに書き、
  --resume で続ける。同じ呼び出しで hook がもう一度動き、答えを入れて通す（DESIGN 11章で「B2 で試して決める」とした答え方。
  `--permission-prompt-tool` の MCP の道具だけで答える形は、渡る値の形が公式文書にないので使わない）。
  claude -p は確かめの相手がいるときだけ AskUserQuestion を出すので、相手として host.py（許すだけ）を付ける。
- skill の allowed-tools は --resume の後に効かないことがある。そのときの確かめの画面は host.py が許し、記録に残す
  （数えられるように）。SKILL.md の「呼び直す」の1行が効いているかは、記録の「確かめの画面」の数で見る。

使い方：
  python3 tests/multiturn/run.py --folder <会社のフォルダ> --first "<社長の最初の発言>" --turns 3 --out <記録の置き場>
    [--answers testdata/デモの会社/回答表.md] [--rules <台本の決まりの文のファイル>] [--model sonnet]
    [--owner-model haiku] [--budget 2.0] [--owner-budget 0.2]

- 1往復は、社長の発言1つ（最初の発言、応答への返事、選択肢の画面への答えのどれか）と、それへのツールの応答。
- 記録（--out の下）：会話.jsonl（1行が1つの発言・応答・選択肢の画面）、道具と確かめの画面.jsonl（hook と host の記録）、
  答え.json（選択肢の画面の答え）、まとめ.json（セッションの id、往復の数、費用、社長役の「分かりません」の数）。
  会話の記録はリポに入れない（CLAUDE.md「公開リポジトリとして」）。--out はリポの外にする。
- 終了コード：0 終わった、1 途中で止まった（claude の出力が読めない、費用の上限など）、2 使い方の誤り。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent.parent
DEFAULT_ANSWERS = PLUGIN_ROOT / "testdata" / "デモの会社" / "回答表.md"
HOST_NAME = "mt"
PY = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else sys.executable
UNKNOWN = "分かりません"

OWNER_RULES = """あなたは、補助金の申請を自社で進めようとしている会社の社長の役です。次の回答表だけを見て、社長として答えます。

- 回答表にないことは「分かりません」と答えます。推測や、ありそうな答えを作りません。
- 回答表の「社長役への決まり」に従います。ふだんの言葉で、短く答えます（1〜3文）。
- 台本の決まりがあれば、それにも従います。台本の発言は、書いてあるとおりに言います。
- Git やコマンドなど、パソコンの細かい操作は知りません。頼まれたら「分かりません」と答えます。
- 答えるのは社長の言葉だけです。説明や前置き、かぎかっこは付けません。
"""


class Stop(Exception):
    pass


def main_command(model: str, budget: float, session: Optional[str]) -> List[str]:
    host = {"mcpServers": {HOST_NAME: {"command": PY, "args": ["-B", str(HERE / "host.py")]}}}
    settings = {
        "permissions": {"blockReadsExemptPaths": [str(PLUGIN_ROOT)]},
        "hooks": {"PreToolUse": [{"matcher": "AskUserQuestion", "hooks": [
            {"type": "command", "command": f"{PY} -B \"{HERE / 'defer_hook.py'}\""}]}]},
    }
    cmd = ["claude", "-p", "--plugin-dir", str(PLUGIN_ROOT), "--output-format", "json", "--model", model,
           "--max-budget-usd", str(budget), "--strict-mcp-config", "--mcp-config", json.dumps(host),
           "--permission-prompt-tool", f"mcp__{HOST_NAME}__approve", "--setting-sources", "project",
           "--settings", json.dumps(settings, ensure_ascii=False)]
    if session:
        cmd += ["--resume", session]
    return cmd


def call_main(folder: Path, cmd: List[str], prompt: Optional[str], env: dict) -> dict:
    done = subprocess.run(cmd + ([prompt] if prompt is not None else []), cwd=str(folder), env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=1800)
    try:
        return json.loads(done.stdout)
    except ValueError:
        raise Stop(f"claude の出力が読めません（終了コード {done.returncode}）：{done.stdout[-800:]} {done.stderr[-800:]}")


def owner_system(answers_text: str, rules_text: str) -> str:
    text = OWNER_RULES + "\n# 回答表\n\n" + answers_text
    if rules_text.strip():
        text += "\n\n# 台本の決まり\n\n" + rules_text
    return text


def call_owner(system: str, prompt: str, model: str, budget: float, workdir: Path) -> tuple:
    """社長役に答えさせる。(文, 費用) を返す。道具は持たせない。"""
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = ["claude", "-p", "--model", model, "--tools", "", "--system-prompt", system, "--no-session-persistence",
           "--output-format", "json", "--max-budget-usd", str(budget), "--strict-mcp-config",
           "--setting-sources", "project", "--disable-slash-commands", prompt]
    done = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True, encoding="utf-8", timeout=600)
    try:
        result = json.loads(done.stdout)
    except ValueError:
        raise Stop(f"社長役の出力が読めません：{done.stdout[-500:]} {done.stderr[-500:]}")
    return (result.get("result") or "").strip(), float(result.get("total_cost_usd") or 0)


def transcript_text(log: List[dict], limit: int = 6000) -> str:
    lines = []
    for item in log:
        who = "社長" if item["だれ"] == "社長役" else "ツール"
        lines.append(f"【{who}】{item['文']}")
    text = "\n".join(lines)
    return text[-limit:]


def question_prompt(log: List[dict], questions: list) -> str:
    parts = ["これまでの会話：", transcript_text(log), "", "ツールが選択肢の画面で、次のことを聞いています。"]
    for q in questions:
        options = "・".join(str(o.get("label")) for o in q.get("options") or [])
        parts.append(f"- 問い：{q.get('question')}（選択肢：{options}）")
    parts += ["", "それぞれの問いに、社長として答えてください。選択肢に当てはまるものがあればその名前を、当てはまらなければ"
              "社長の短い言葉を書きます。回答表にないことは「分かりません」と書きます。",
              "JSON だけを返します：{\"<問いの文のとおり>\": \"<答え>\", …}"]
    return "\n".join(parts)


def parse_answers(text: str, questions: list) -> dict:
    found = re.findall(r"\{.*\}", text, re.S)
    data = {}
    if found:
        try:
            data = json.loads(found[-1])
        except ValueError:
            data = {}
    out = {}
    for q in questions:
        key = str(q.get("question"))
        value = data.get(key) if isinstance(data, dict) else None
        out[key] = str(value).strip() if value else UNKNOWN
    return out


def run(args) -> int:
    folder = Path(args.folder).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    answers_file = out / "答え.json"
    answers_file.write_text("{}", encoding="utf-8")
    env = dict(os.environ, MULTITURN_ANSWERS=str(answers_file), MULTITURN_LOG=str(out / "道具と確かめの画面.jsonl"))
    system = owner_system(Path(args.answers).read_text(encoding="utf-8"),
                          Path(args.rules).read_text(encoding="utf-8") if args.rules else "")
    log: List[dict] = []
    cost = {"試す側": 0.0, "社長役": 0.0}
    session = None
    prompt: Optional[str] = args.first
    turns = 0
    stopped = ""

    def note(who: str, kind: str, text: str, extra: Optional[dict] = None) -> None:
        item = {"番": len(log) + 1, "だれ": who, "種類": kind, "文": text}
        if extra:
            item.update(extra)
        log.append(item)
        with (out / "会話.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    note("社長役", "発言", prompt)
    turns += 1
    try:
        while True:
            result = call_main(folder, main_command(args.model, args.budget, session), prompt, env)
            session = result.get("session_id") or session
            cost["試す側"] += float(result.get("total_cost_usd") or 0)
            if result.get("is_error") and result.get("stop_reason") != "tool_deferred":
                stopped = f"試す側が止まりました（{result.get('subtype')}）"
                note("ツール", "応答", result.get("result") or "", {"止まった": result.get("subtype")})
                break
            deferred = result.get("deferred_tool_use") or {}
            if result.get("stop_reason") == "tool_deferred" and deferred.get("name") == "AskUserQuestion":
                questions = (deferred.get("input") or {}).get("questions") or []
                note("ツール", "選択肢の画面", json.dumps(questions, ensure_ascii=False), {"tool_use_id": deferred.get("id")})
                if turns >= args.turns:
                    stopped = "往復の数に達したので、選択肢の画面に答えずに終えました"
                    break
                text, c = call_owner(system, question_prompt(log, questions), args.owner_model, args.owner_budget, out / "社長役")
                cost["社長役"] += c
                chosen = parse_answers(text, questions)
                stored = json.loads(answers_file.read_text(encoding="utf-8"))
                stored[str(deferred.get("id"))] = chosen
                answers_file.write_text(json.dumps(stored, ensure_ascii=False, indent=1), encoding="utf-8")
                note("社長役", "選択肢の答え", json.dumps(chosen, ensure_ascii=False))
                turns += 1
                prompt = None  # 続けるときは、何も言わずに再開する（hook が答えを入れて通す）
                continue
            note("ツール", "応答", result.get("result") or "")
            if turns >= args.turns:
                break
            reply, c = call_owner(system, "これまでの会話：\n" + transcript_text(log) +
                                  "\n\n最後のツールの発言に、社長として返事をしてください。", args.owner_model, args.owner_budget,
                                  out / "社長役")
            cost["社長役"] += c
            note("社長役", "発言", reply)
            turns += 1
            prompt = reply
    except Stop as e:
        stopped = str(e)
    unknown = sum(1 for item in log if item["だれ"] == "社長役" and UNKNOWN in item["文"])
    summary = {"セッション": session, "往復": turns, "費用": {k: round(v, 4) for k, v in cost.items()},
               "社長役の「分かりません」": unknown, "止まった": stopped,
               "確かめの画面": _count_prompts(out / "道具と確かめの画面.jsonl")}
    (out / "まとめ.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if stopped and not stopped.startswith("往復の数") else 0


def _count_prompts(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if '"確かめの画面"' in line)


def parse(argv: List[str]):
    p = argparse.ArgumentParser(description="claude -p と --resume で、社長役と会話を続ける（会話を続けるテストの仕組み）")
    p.add_argument("--folder", required=True, help="会社のフォルダ（試す側の作業フォルダ）")
    p.add_argument("--first", required=True, help="社長の最初の発言")
    p.add_argument("--turns", type=int, default=3, help="往復の数（社長の発言と選択肢の答えの数）")
    p.add_argument("--out", required=True, help="記録の置き場（リポの外）")
    p.add_argument("--answers", default=str(DEFAULT_ANSWERS), help="回答表")
    p.add_argument("--rules", help="台本の決まり（社長役に渡す文のファイル）")
    p.add_argument("--model", default="sonnet", help="試す側のモデル")
    p.add_argument("--owner-model", default="haiku", help="社長役のモデル")
    p.add_argument("--budget", type=float, default=2.0, help="試す側の1回の費用の上限（USD）")
    p.add_argument("--owner-budget", type=float, default=0.2, help="社長役の1回の費用の上限（USD）")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(run(parse(sys.argv[1:])))
