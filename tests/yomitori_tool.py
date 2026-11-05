"""開発用：読み取り役（hojokin:yomitori）を、会社のフォルダを作業フォルダにして claude -p で呼ぶ（TASKS B1a）。

製品では、本体が Agent の道具で読み取り役を呼ぶ（junbi の SKILL.md）。開発で制度データを作るとき
（B1a の持続化 第20回、M2c の省力化 第8回）に、同じ agents/yomitori.md と指定のモデルで、章ごとに読ませるための道具。
依頼の文と返った文には公式資料の文が入るので、どちらもリポの外（作業の場所）に置く（CLAUDE.md「公開リポジトリとして」）。

使い方：
  python3 tests/yomitori_tool.py <会社のフォルダ> <依頼の文のファイル> <結果の置き場所（.json）> [--model opus] [--budget 3]

- プラグインは、この道具のあるリポを --plugin-dir で読み込む。
- 結果：claude の JSON の出力を <置き場所> に置き、返った文から ```json の囲みを取り出して <置き場所>.reading.json に置く。
  標準出力の最後の行に、費用（total_cost_usd）などを JSON で出す。
- 終了コード：0 囲みの JSON を取り出せた。1 取り出せなかった。2 claude の出力が JSON でない。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def build_command(company: Path, model: str, budget: float) -> list:
    settings = {"permissions": {"blockReadsExemptPaths": [str(PLUGIN_ROOT)]}}
    return [
        "claude", "-p",
        "--plugin-dir", str(PLUGIN_ROOT),
        "--agent", "hojokin:yomitori",
        "--model", model,
        # 読み取り役は読むだけにする（Bash はこの開発の呼び方では使わない。ページごとの文字と PDF の Read で足りる）
        "--tools", "Read", "Grep", "Glob",
        "--allowedTools", "Read", "Grep", "Glob",
        "--setting-sources", "project",
        "--settings", json.dumps(settings, ensure_ascii=False),
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--output-format", "json",
        "--max-budget-usd", str(budget),
    ]


def extract_json(text: str):
    """返った文の最後の ```json の囲みを取り出す。読めなければ None。"""
    found = re.findall(r"```json\s*(.*?)```", text or "", re.S)
    if not found:
        return None
    body = found[-1]
    try:
        json.loads(body)
    except ValueError:
        return None
    return body


def main(argv) -> int:
    parser = argparse.ArgumentParser(description="読み取り役を claude -p で呼ぶ（開発用）")
    parser.add_argument("company")
    parser.add_argument("prompt")
    parser.add_argument("out")
    parser.add_argument("--model", default="opus")
    parser.add_argument("--budget", type=float, default=3.0)
    parser.add_argument("--timeout", type=int, default=3000)
    args = parser.parse_args(argv)

    prompt = Path(args.prompt).read_text(encoding="utf-8")
    env = dict(os.environ, CLAUDE_CODE_MAX_OUTPUT_TOKENS="64000")  # 件の多い章を1回の応答で返し切れるように
    done = subprocess.run(build_command(Path(args.company), args.model, args.budget), input=prompt.encode("utf-8"),
                          cwd=args.company, env=env, capture_output=True, timeout=args.timeout)
    out = Path(args.out)
    out.write_bytes(done.stdout)
    Path(f"{out}.stderr").write_bytes(done.stderr)
    try:
        result = json.loads(done.stdout.decode("utf-8"))
    except ValueError:
        print("claude の出力が JSON ではありません：", done.stdout[:1500].decode("utf-8", "replace"),
              done.stderr[:1500].decode("utf-8", "replace"))
        return 2
    body = extract_json(result.get("result") or "")
    if body is not None:
        Path(f"{out}.reading.json").write_text(body, encoding="utf-8")
    summary = {k: result.get(k) for k in ("subtype", "is_error", "num_turns", "total_cost_usd", "duration_ms")}
    summary["取り出せた"] = body is not None
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if body is not None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
