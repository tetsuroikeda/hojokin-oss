"""決める（F2）ための道具：義務と返還の条件の一覧と、二重受給の照合（SPEC F2・T2-1・T2-2、DESIGN 4.2）。

使い方：
  python3 -B <この場所>/kimeru.py gimu --folder <会社のフォルダ> [--seido <制度データのファイル名か、その一部>]
  python3 -B <この場所>/kimeru.py nijuu --folder <会社のフォルダ> [--input 記録/一時/二重受給.json]

- gimu：`記録/制度データ/` の制度データから、義務・返還・取消など・注意を、出典つきで1件ずつ並べる（lib/gimu.py）。
  制度データが2つ以上あれば `--seido` で選ぶ（例：`--seido 省力化`）。何も書かない。
- nijuu：`記録/経費明細.json` と、予定の経費（`--input` のファイル。会社のフォルダの中だけ）を、案件どうしで照らす（lib/nijuu.py）。
  何も書かない。
- 会社のフォルダでないと動かない（どちらも会社のフォルダの記録を読むため）。
- 終了コード：
  - gimu：0 出した。2 何もしていない（会社のフォルダでない、制度データがない・選べない・読めない）。3 補助プログラムが動かない。
  - nijuu：0 同じ経費は見つからなかった。1 重大か確かめが要るものがある。2 何もしていない（形が違う、外の場所 など）。3 動かない。
"""

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

NOT_DONE = "何もしていません："
SEIDO_DIR = "記録/制度データ"


def parse(argv):
    parser = argparse.ArgumentParser(description="義務と返還の条件の一覧と、二重受給の照合")
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("gimu", help="義務と返還の条件の一覧")
    g.add_argument("--folder", required=True)
    g.add_argument("--seido", help="制度データのファイル名か、その一部（2つ以上あるとき）")
    n = sub.add_parser("nijuu", help="二重受給の照合")
    n.add_argument("--folder", required=True)
    n.add_argument("--input", help="予定の経費の JSON（会社のフォルダの中のファイル。例：記録/一時/二重受給.json）")
    return parser.parse_args(argv)


def seido_files(folder: Path, places):
    base = folder / SEIDO_DIR
    if not base.is_dir():
        return []
    out = []
    for path in sorted(base.glob("*.json")):
        rel = path.relative_to(folder).as_posix()
        if places.first_link(folder, rel) is not None:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and "スキーマの版" in data:
            out.append((path, data))
    return out


def run_gimu(args, folder: Path) -> int:
    from lib import gimu, places

    files = seido_files(folder, places)
    if args.seido:
        files = [(p, d) for p, d in files if args.seido in p.name]
    if not files:
        print(f"{NOT_DONE}制度データ（{SEIDO_DIR}/<制度>_<公募回>.json）がありません"
              + (f"（「{args.seido}」に当たるもの）" if args.seido else "")
              + "。制度データを作る前なら、公募要領を読んで、要件・義務・返還の条件を出典のページ付きで示してください。")
        return 2
    if len(files) > 1:
        names = "、".join(p.name for p, _ in files)
        print(f"{NOT_DONE}制度データが2つ以上あります（{names}）。--seido で選んでください。")
        return 2
    path, data = files[0]
    print(f"制度データ：{path.relative_to(folder).as_posix()}")
    print(gimu.report(data))
    return 0


def run_nijuu(args, folder: Path) -> int:
    from lib import nijuu, places

    planned = None
    if args.input:
        where = Path(args.input).expanduser()
        if not places.is_inside(folder, where):
            print(f"{NOT_DONE}予定の経費のファイルが、会社のフォルダの外を指しています（{args.input}）。"
                  "会社のフォルダの 記録/一時/ に置いて渡してください。")
            return 2
        real = places.resolve_inside(folder, where)
        try:
            planned = json.loads(real.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"{NOT_DONE}予定の経費のファイルが読めません（{type(e).__name__}）")
            return 2
    try:
        result = nijuu.check(folder, planned)
    except nijuu.NijuuError as e:
        print(f"{NOT_DONE}{e}")
        return 2
    print(nijuu.report(result, nijuu.rule_sources(folder)))
    return 1 if result.findings else 0


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse(argv)
    try:
        from lib import company
    except Exception as e:  # 同梱のファイルが欠けた・壊れた
        print(f"{NOT_DONE}補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。プラグインを入れ直してください。")
        return 3
    folder = Path(args.folder)
    if not company.is_company_folder(folder):
        print(f"{NOT_DONE}ここは会社のフォルダではありません（.hojokin/ がありません）。")
        return 2
    try:
        if args.command == "gimu":
            return run_gimu(args, folder)
        return run_nijuu(args, folder)
    except Exception as e:  # 途中で止まった
        print(f"{NOT_DONE}途中で止まりました（{type(e).__name__}: {e}）。プラグインを入れ直してから、もう一度試してください。")
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
