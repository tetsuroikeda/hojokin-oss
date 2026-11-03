"""jGrants の実際の応答を1回だけ取り、テストの材料として残す開発用の道具（T1-3）。テストからは呼ばない。

使い方（リポジトリの根で）：
  uv run python tests/jgrants_record.py --keyword 補助金          # 応答そのものを残す
  uv run python tests/jgrants_record.py --keyword 補助金 --tool   # 製品の道具を動かした結果を残す

- 応答そのもの：製品と同じ lib.jgrants で URL を組み立て、同じ jgrants.fetch_raw で1回だけ通信し、
  送った URL・条件・取った日時（日本時間）と、応答をそのまま tests/data/jgrants/記録_<言葉>.json に書く。
- 道具の結果（--tool）：社長の Mac と同じ /usr/bin/python3 で、製品の道具
  skills/sagasu/scripts/jgrants_search.py を --json で1回だけ動かし（記録した応答は使わない）、
  動かしたコマンド・終了コード・出力をそのまま tests/data/jgrants/道具の実行_<言葉>.json に書く。
  製品の通信の経路（jgrants.fetch → summarize → 道具の出力）が、本物の jGrants に当たったことを残すため。
- 相手のサイトに負担をかけないため、やり直しはしない。取り直すのは、API の形が変わったときだけにする。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib import dates, jgrants  # noqa: E402

OUT_DIR = REPO_ROOT / "tests" / "data" / "jgrants"
TOOL = Path("skills") / "sagasu" / "scripts" / "jgrants_search.py"
SYSTEM_PYTHON = "/usr/bin/python3"
TOOL_LIMIT = "1000"  # 全件を出す（件数と示した件数が同じになる）


def now_jst() -> str:
    return dates.to_jst(datetime.now(timezone.utc)).isoformat(timespec="seconds")


def record_response(keyword: str) -> Path:
    query = jgrants.build_query(keyword)
    url = jgrants.build_url(query)
    fetched = now_jst()
    status, body = jgrants.fetch_raw(url)
    record = {
        "説明": "jGrants の公開API の実際の応答を1回だけ取ったもの（tests/jgrants_record.py）。応答は手を加えずに残す",
        "取った日時": fetched,
        "送った URL": url,
        "条件": query,
        "HTTP の状態": status,
        "応答": json.loads(body.decode("utf-8")),
    }
    out = OUT_DIR / f"記録_{keyword}.json"
    write(out, record)
    print(f"{out}（HTTP {status}、{len(record['応答'].get('result') or [])}件）")
    return out


def record_tool(keyword: str) -> Path:
    command = [SYSTEM_PYTHON, "-I", "-B", str(TOOL), "--keyword", keyword, "--json", "--limit", TOOL_LIMIT]
    ran = now_jst()
    result = subprocess.run(
        command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())}, timeout=120,
    )
    try:
        output = json.loads(result.stdout)
    except ValueError:
        output = result.stdout
    record = {
        "説明": "製品の道具（jgrants_search.py）を、記録した応答を使わずに1回だけ動かし、本物の jGrants に当てた結果"
                "（tests/jgrants_record.py --tool）。出力は手を加えずに残す",
        "動かした日時": ran,
        "コマンド": command,
        "終了コード": result.returncode,
        "出力": output,
        "エラー出力": result.stderr,
    }
    out = OUT_DIR / f"道具の実行_{keyword}.json"
    write(out, record)
    count = output.get("件数") if isinstance(output, dict) else "?"
    print(f"{out}（終了コード {result.returncode}、{count}件）")
    return out


def write(out: Path, record: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--tool", action="store_true", help="製品の道具を動かした結果を残す")
    args = parser.parse_args()
    if args.tool:
        record_tool(args.keyword)
    else:
        record_response(args.keyword)
    return 0


if __name__ == "__main__":
    sys.exit(main())
