"""実験 E7：読み取り役を呼ぶときに、モデルを替えられるか（DESIGN 7章・13.2、TASKS M2b）。

`claude -p` で、このリポジトリをプラグインとして読み込み（--plugin-dir）、本体に読み取り役を呼ばせる。
本体のモデルは --main-model（既定は sonnet）にし、読み取り役を呼ぶときに --subagent-model を指定させる。
読み取り役の yomitori.md は `model: inherit` なので、指定が効かなければ、読み取り役は本体と同じモデルで動く。

stream-json の出力から、本体と読み取り役のそれぞれの応答のモデル（message.model）を数える。
出力（会話の記録と、公式資料の文を含む）は、リポの外（--out）に置く。リポには入れない。

使い方（作業のフォルダには、`記録/資料の本文/2026_省力化（一般型）第9回/要領8/` を置いておく。目印の .hojokin/ は置かない）：
  python3 experiments/E7/run_e7.py --work <作業のフォルダ> --out <出力の置き場所> --subagent-model opus
  python3 experiments/E7/run_e7.py --summarize <出力の置き場所>/stream.jsonl   # 数え直すだけ
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).resolve().parent / "依頼.md"
TOOL = REPO_ROOT / "skills" / "junbi" / "scripts" / "urakadori.py"


def build_prompt(subagent_model: str) -> str:
    form = subprocess.run([sys.executable, "-B", str(TOOL), "--form", "補助額"], capture_output=True, check=True,
                          text=True).stdout.strip()
    if subagent_model == "none":
        how = "モデルは指定しない（model の引数を渡さない）。"
    else:
        how = f"呼ぶときに、model の引数に \"{subagent_model}\" を指定する。"
    return TEMPLATE.read_text(encoding="utf-8").replace("{モデルの指定}", how).replace("{形}", form)


def summarize(stream: Path) -> dict:
    main_models: Counter = Counter()
    sub_models: Counter = Counter()
    agent_calls = []
    init_model = None
    cost = None
    final_text = ""
    for line in stream.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            init_model = event.get("model")
        elif kind == "assistant":
            message = event.get("message") or {}
            model = message.get("model")
            (sub_models if event.get("parent_tool_use_id") else main_models)[model] += 1
            for block in message.get("content") or []:
                if block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                    agent_calls.append({k: v for k, v in (block.get("input") or {}).items() if k != "prompt"})
        elif kind == "result":
            cost = event.get("total_cost_usd")
            final_text = event.get("result") or ""
    match = re.search(r"```json\s*(\{.*\})\s*```", final_text, re.S)
    return {
        "本体のモデル（init）": init_model,
        "本体の応答のモデル": dict(main_models),
        "読み取り役の応答のモデル": dict(sub_models),
        "Agent の呼び出し（prompt を除く）": agent_calls,
        "費用（USD）": cost,
        "返った JSON": match.group(1) if match else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--subagent-model", default="opus", choices=["opus", "sonnet", "haiku", "none"])
    parser.add_argument("--main-model", default="sonnet")
    parser.add_argument("--budget", default="1.5")
    parser.add_argument("--summarize", type=Path)
    args = parser.parse_args()
    if args.summarize:
        stream = args.summarize
    else:
        args.out.mkdir(parents=True, exist_ok=True)
        stream = args.out / "stream.jsonl"
        prompt = build_prompt(args.subagent_model)
        (args.out / "prompt.txt").write_text(prompt, encoding="utf-8")
        cmd = ["claude", "-p", prompt, "--plugin-dir", str(REPO_ROOT), "--model", args.main_model,
               "--output-format", "stream-json", "--verbose", "--permission-mode", "dontAsk",
               "--allowedTools", "Agent", "Read", "Grep", "Glob", "--max-budget-usd", args.budget]
        with stream.open("w", encoding="utf-8") as f:
            r = subprocess.run(cmd, cwd=args.work, stdout=f, stderr=subprocess.PIPE, text=True, timeout=900)
        if r.returncode != 0:
            print(f"claude の終了コード {r.returncode}：{r.stderr[-2000:]}", file=sys.stderr)
    result = summarize(stream)
    returned = result.pop("返った JSON")
    if returned and args.out:
        (args.out / "返った.json").write_text(returned + "\n", encoding="utf-8")
    result["返った JSON を取り出せた"] = bool(returned)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
