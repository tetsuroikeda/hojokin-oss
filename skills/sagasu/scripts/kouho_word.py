"""補助金の候補.docx を作る道具（SPEC F1・T1-6）。探し直したときも、同じファイルを直す。

使い方（候補の一覧の JSON を標準入力で渡す。形は lib/kouho.py の先頭）：
  python3 -B <この場所>/kouho_word.py --folder "${CLAUDE_PROJECT_DIR}" <<'EOF'
  { "候補": [ ... ] }
  EOF
  （--input <ファイル> でも渡せる）

- 会社のフォルダ（.hojokin/ があるフォルダ）の直下の「補助金の候補.docx」だけを書く。ほかのファイルは作らない。
- 探した日は、今日の日付（.hojokin/設定.json の差し替えを含む）。
- 終了コード：0 書いた、2 書かなかった（会社のフォルダでない、候補の一覧の形が正しくない）。
"""

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company, kouho  # noqa: E402


def parse(argv):
    parser = argparse.ArgumentParser(description="補助金の候補.docx を作る（探し直したときも同じファイルを直す）")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--input", help="候補の一覧の JSON のファイル。なければ標準入力から読む")
    return parser.parse_args(argv)


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse(argv)
    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    try:
        text = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
        data = json.loads(text)
    except (OSError, ValueError) as e:
        print(f"補助金の候補.docx を作りませんでした。候補の一覧を JSON として読めません（{e}）。")
        return 2
    try:
        path = kouho.write(folder, data)
    except kouho.KouhoError as e:
        print("補助金の候補.docx を作りませんでした。何も変えていません。直す所：")
        for problem in e.problems:
            print(f"- {problem}")
        return 2
    counts = {c: sum(1 for item in data["候補"] if item["区分"] == c) for c in kouho.CATEGORIES}
    detail = "、".join(f"{c} {n}件" for c, n in counts.items())
    print(f"{path} を書きました（{detail}）。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
