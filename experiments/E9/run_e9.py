"""実験 E9：差し替えた「今日の日付」を、Claude が実際の日付より優先するか（DESIGN 13.2、TASKS M10）。

`claude -p` で、このリポジトリをプラグインとして読み込み（--plugin-dir）、日付を差し替えた会社のフォルダで、日付の問いに答えさせる。
Claude Code の文脈には、本当の今日（環境の「Today's date」）と、プラグインの hook が渡す差し替えた今日の、2つの日付が入る。

- 会社のフォルダ（--work）は、あらかじめ採択後の段階に切り替え（skills/junbi/scripts/stage_switch.py）、
  `.hojokin/設定.json` の「今日の日付」を差し替えておく。
- 問い（--prompt のファイル）と、使ってよい道具（--tools）を変えて流す。
  --tools none：道具を使わせない（文脈の日付だけで答える）。--tools bash：Bash（python3・cd・ls・echo だけ）・Read・Skill を
  使わせる（junbi の道具で日付を出すか）。許可は --permission-mode dontAsk なので、許していないコマンドは確認なしに断られる。
- stream-json の出力から、最後の答え、道具の呼び出し（Bash のコマンド）、モデル、費用を取り出す。
- 出力（会話の記録）は、リポの外（--out）に置く。リポには入れない。

使い方：
  python3 experiments/E9/run_e9.py --work <会社のフォルダ> --out <出力の置き場所> --prompt experiments/E9/問い_道具なし.md --tools none
  python3 experiments/E9/run_e9.py --summarize <出力の置き場所>/stream.jsonl   # 取り出し直すだけ
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def summarize(stream: Path) -> dict:
    models: Counter = Counter()
    commands = []
    others = []
    init = {}
    cost = None
    final_text = ""
    texts = []
    stop = ""
    context_dates = []
    for line in stream.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            init = {"model": event.get("model"), "tools": event.get("tools"), "plugins": event.get("plugins")}
        elif kind == "system" and event.get("subtype") in ("hook_response", "hook_started"):
            text = json.dumps(event, ensure_ascii=False)
            if "日付を差し替えています" in text and "SessionStart" in text:
                context_dates.append("SessionStart が差し替えた今日を渡した")
        elif kind == "assistant":
            message = event.get("message") or {}
            models[message.get("model")] += 1
            for block in message.get("content") or []:
                if block.get("type") == "text" and (block.get("text") or "").strip():
                    texts.append(block["text"])
                if block.get("type") != "tool_use":
                    continue
                if block.get("name") == "Bash":
                    commands.append((block.get("input") or {}).get("command"))
                else:
                    others.append({"道具": block.get("name"), "入力": block.get("input")})
        elif kind == "result":
            cost = event.get("total_cost_usd")
            final_text = event.get("result") or ""
            stop = f"{event.get('subtype')}（{event.get('terminal_reason')}）"
    return {
        "init": {"model": init.get("model"), "道具": init.get("tools"),
                 "プラグイン": [p.get("name") for p in init.get("plugins") or [] if isinstance(p, dict)]},
        "応答のモデル": dict(models),
        "Bash のコマンド": commands,
        "ほかの道具の呼び出し": others,
        "hook の記録": sorted(set(context_dates)),
        "費用（USD）": cost,
        "終わり方": stop,
        # 費用の上限で止まると、result の文は空になる。応答の文はそのまま残るので、両方を取り出す
        "最後の答え": final_text or (texts[-1] if texts else ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--prompt", type=Path)
    parser.add_argument("--tools", choices=["none", "bash"], default="none")
    parser.add_argument("--model", default="")
    parser.add_argument("--budget", default="1.0")
    parser.add_argument("--summarize", type=Path)
    args = parser.parse_args()
    if args.summarize:
        stream = args.summarize
    else:
        args.out.mkdir(parents=True, exist_ok=True)
        stream = args.out / "stream.jsonl"
        prompt = args.prompt.read_text(encoding="utf-8")
        # 利用者の設定（ほかのプラグイン）と MCP の道具を読まない（文脈を小さくして費用を抑える。社長の新しい環境にも近い）
        cmd = ["claude", "-p", prompt, "--plugin-dir", str(REPO_ROOT), "--output-format", "stream-json", "--verbose",
               "--include-hook-events", "--no-session-persistence", "--permission-mode", "dontAsk",
               "--setting-sources", "project,local", "--strict-mcp-config", "--max-budget-usd", args.budget]
        if args.model:
            cmd += ["--model", args.model]
        if args.tools == "none":
            cmd += ["--tools", ""]
        else:
            # Skill がないと junbi の SKILL.md（道具の使い方）が読み込まれない（1回目の道具ありで分かった）。
            # Claude は道具を「cd … && python3 …」の形で動かすので、cd・ls・echo も許す（2回目の道具ありで分かった）
            cmd += ["--tools", "Bash", "Read", "Skill", "--allowedTools", "Bash(python3:*)", "Bash(cd:*)", "Bash(ls:*)",
                    "Bash(echo:*)", "Read", "Skill"]
        with stream.open("w", encoding="utf-8") as f:
            r = subprocess.run(cmd, cwd=args.work, stdout=f, stderr=subprocess.PIPE, text=True, timeout=900)
        if r.returncode != 0:
            print(f"claude の終了コード {r.returncode}：{r.stderr[-2000:]}", file=sys.stderr)
    result = summarize(stream)
    if args.out:
        (args.out / "要約.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
