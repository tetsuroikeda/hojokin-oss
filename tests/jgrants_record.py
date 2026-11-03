"""jGrants の実際の応答を1回だけ取り、テストの材料として残す開発用の道具（T1-3）。テストからは呼ばない。

使い方（リポジトリの根で）：
  uv run python tests/jgrants_record.py --keyword 補助金

- 製品と同じ lib.jgrants で URL を組み立てて1回だけ通信し、送った URL・条件・取った日時（日本時間）と、
  応答をそのまま tests/data/jgrants/記録_<言葉>.json に書く。
- 相手のサイトに負担をかけないため、やり直しはしない。取り直すのは、API の形が変わったときだけにする。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib import dates, jgrants  # noqa: E402

OUT_DIR = REPO_ROOT / "tests" / "data" / "jgrants"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", required=True)
    args = parser.parse_args()
    query = jgrants.build_query(args.keyword)
    url = jgrants.build_url(query)
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": jgrants.USER_AGENT})
    fetched = datetime.now(timezone.utc)
    with urllib.request.urlopen(request, timeout=jgrants.TIMEOUT_SECONDS) as response:
        status = response.status
        body = response.read()
    record = {
        "説明": "jGrants の公開API の実際の応答を1回だけ取ったもの（tests/jgrants_record.py）。応答は手を加えずに残す",
        "取った日時": dates.to_jst(fetched).isoformat(timespec="seconds"),
        "送った URL": url,
        "条件": query,
        "HTTP の状態": status,
        "応答": json.loads(body.decode("utf-8")),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"記録_{args.keyword}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{out}（HTTP {status}、{len(record['応答'].get('result') or [])}件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
