"""jGrants の公開API で補助金を検索する道具（SPEC F1・T1-3）。会社のフォルダでなくても動く（探すことは許されている）。

使い方：
  python3 -B <この場所>/jgrants_search.py --keyword 省力化 [--sort acceptance_end_datetime] [--order ASC]
      [--all]（受付中でないものも含める） [--industry 製造業] [--employees "20名以下"] [--area 〇〇県]
      [--use-purpose "設備整備・IT導入をしたい"] [--json]

- 必須の検索条件（keyword・sort・order・acceptance）は、いつも4つとも付けて送る。
- 締切と受付開始は、日本時間で示す。
- 何も書かない（会社のフォルダにも、ほかの場所にも）。
- 終了コード：0 検索できた、1 つながらない・応答が読めない（ほかの集め方で続ける）、2 条件が正しくない。
- --response-file は、記録しておいた応答を読む（通信しない。テストと、通信できないときの確かめ用）。
"""

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import jgrants  # noqa: E402


def parse(argv):
    parser = argparse.ArgumentParser(description="jGrants の公開API で補助金を検索する")
    parser.add_argument("--keyword", required=True, help="検索の言葉（2文字以上）")
    parser.add_argument("--sort", default="acceptance_end_datetime", choices=jgrants.SORT_VALUES)
    parser.add_argument("--order", default="ASC", choices=jgrants.ORDER_VALUES)
    parser.add_argument("--all", action="store_true", help="受付中でないものも含める（acceptance=0）")
    parser.add_argument("--use-purpose", help="利用目的（jGrants の use_purpose）")
    parser.add_argument("--industry", help="業種（jGrants の industry）")
    parser.add_argument("--employees", help="従業員数（jGrants の target_number_of_employees）")
    parser.add_argument("--area", help="地域（jGrants の target_area_search）")
    parser.add_argument("--limit", type=int, default=30, help="示す件数（締切の早い順。はじめは30件）")
    parser.add_argument("--json", action="store_true", help="結果を JSON で出す")
    parser.add_argument("--response-file", help="記録しておいた応答の JSON を読む（通信しない）")
    return parser.parse_args(argv)


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse(argv)
    try:
        query = jgrants.build_query(
            args.keyword,
            sort=args.sort,
            order=args.order,
            acceptance=not args.all,
            use_purpose=args.use_purpose,
            industry=args.industry,
            target_number_of_employees=args.employees,
            target_area_search=args.area,
        )
        url = jgrants.build_url(query)
    except ValueError as e:
        print(f"検索の条件が正しくありません。{e}")
        return 2

    try:
        if args.response_file:
            data = jgrants.load_recorded(Path(args.response_file).read_bytes())
        else:
            data = jgrants.fetch(url)
        items = jgrants.summarize(data)
    except (jgrants.JGrantsError, OSError) as e:
        print(
            f"jGrants で検索できませんでした。{e}\n"
            "jGrants のほかの集め方（同梱の知見、国・自治体の公式サイトの Web 検索）で、候補を集め続けてください。"
        )
        return 1

    limit = max(args.limit, 1)
    if args.json:
        print(json.dumps(
            {"検索した URL": url, "条件": query, "件数": len(items), "示した件数": min(limit, len(items)), "候補": items[:limit]},
            ensure_ascii=False, indent=2,
        ))
    else:
        print(jgrants.render_text(items, url, limit), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
