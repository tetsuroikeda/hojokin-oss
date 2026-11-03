"""公式資料を取り、書類フォルダを作り、ページごとの文字にする道具（SPEC F3、DESIGN 9.2、TASKS M2a）。

使い方：
  python3 -B <この場所>/fetch_documents.py --folder "${CLAUDE_PROJECT_DIR}" --list <取る資料の一覧.json> [--case-round 第9回]
  python3 -B <この場所>/fetch_documents.py --folder "${CLAUDE_PROJECT_DIR}" --list - <<'EOF'
  { "制度": {…}, "資料": [ … ] }
  EOF

- 取る資料の一覧の形は、lib/official_docs.py の load_list の説明のとおり。省力化 第8回と持続化 第20回の一覧は、
  この skill の `取る資料/` にある。ほかの制度は、公式サイトのダウンロードのページで確かめて作る。
- --case-round：申請する回（案件の回）。一覧の「制度」の「公募回」の代わりに使う。
  申請する回の資料がまだ公表されていないときは、直近回の資料の一覧に、申請する回をここで渡す。
  結果に「直近回である第◯回の資料に基づいています」と出る。
- Claude が Bash で動かすコマンドには、CLAUDE_PROJECT_DIR の環境変数が入らないので、--folder で渡す。
- 通信は、標準のライブラリだけで行う。PDF を文字にする pypdf は、プラグインに同梱している（lib/vendor/）。
- 終了コード：0 資料がすべてそろい、文字にできた。
  1 そろわなかった（取れなかった、前と中身が違う、文字にできなかった）か、補助プログラムが動かない。
  2 動かさなかった（会社のフォルダでない、一覧の形が違う）。何も書いていない。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))


def parse(argv):
    parser = argparse.ArgumentParser(description="公式資料を取り、書類フォルダを作り、ページごとの文字にする")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--list", required=True, help="取る資料の一覧（JSON のファイル。- なら標準入力）")
    parser.add_argument("--case-round", help="申請する回（例：第9回）。一覧の制度の公募回の代わりに使う")
    return parser.parse_args(argv)


def read_list(where: str) -> object:
    text = sys.stdin.read() if where == "-" else Path(where).expanduser().read_text(encoding="utf-8")
    return json.loads(text)


def main(argv) -> int:
    # 環境の文字コードによらず、日本語の結果を UTF-8 で返す
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    args = parse(argv)
    try:
        from lib import company, official_docs
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"公式資料を取れませんでした。何も変えていません。\n\n補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return 1

    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    if company.company_folder(folder) is None:
        print("公式資料を取りませんでした。何も変えていません。\n\n"
              f"このフォルダ（{folder}）は、まだ会社のフォルダではありません（目印の {company.MARKER_DIR}/ がありません）。"
              "先に、社長の了承を得て会社のフォルダを作ってください。")
        return 2
    try:
        data = read_list(args.list)
        if args.case_round and isinstance(data, dict) and isinstance(data.get("制度"), dict):
            data["制度"] = dict(data["制度"], 公募回=args.case_round)
        official_docs.load_list(data)
    except (OSError, ValueError) as e:  # ListError と JSON の読み違いも ValueError
        print(f"公式資料を取りませんでした。何も変えていません。\n\n取る資料の一覧を読めませんでした（{e}）。")
        return 2

    try:
        result = official_docs.fetch_all(folder, data)
    except Exception as e:  # 書けない場所、思わぬ形の資料など
        print(f"公式資料を取る途中で止まりました（{type(e).__name__}: {e}）。"
              "置き終えた資料はそのまま残っています。もう一度動かすと、足りない分だけ取ります。")
        return 1
    print(official_docs.report(result), end="")
    return 0 if result.complete else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
