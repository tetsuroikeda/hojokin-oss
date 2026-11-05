"""会社のフォルダの中の書類（原本の PDF・Word・Excel など）の文字を出す道具（TASKS B13。波3 の気づき #7）。

kaku が、労働者名簿.xlsx や決算書の PDF の数字を読むときに使う。その場で読むためのコード（`記録/一時/` の .py や
`python3 -c`）を書かないための道具。書類は変えない。

使い方（--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/moji.py --file "<会社のフォルダからの場所>" [--page <PDF のページ>] [--max <字数>]
      PDF はページごと、Word は本文、Excel はシートごと（セルはタブでつなぐ。数式は残っている値）に出す。
      文字のない PDF のページ（スキャンしたもの）は「文字がありません」と出す（読み取り役に画像として読ませる）。

- 会社のフォルダの外は読まない（lib/places.py の resolve_inside）。
- 終了コード：0 出した、1 補助プログラムを読み込めない、2 しなかった（会社のフォルダでない、外のファイル、
  読めない形 など）。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company, places  # noqa: E402

OK, BROKEN, REFUSED = 0, 1, 2
DEFAULT_MAX = 30000


class Refused(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def parse(argv):
    parser = Parser(description="会社のフォルダの中の書類の文字を出す")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--file", required=True, help="書類の場所（会社のフォルダの中）")
    parser.add_argument("--page", type=int, help="PDF のページ（1から）。省くとすべて")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX, help=f"出す字数の上限（既定 {DEFAULT_MAX}）")
    return parser.parse_args(argv)


def text_of(path: Path, page, doc_text) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages = doc_text.pdf_pages(path)
        chosen = range(1, len(pages) + 1) if page is None else [page]
        out = []
        for n in chosen:
            if not 1 <= n <= len(pages):
                raise Refused(f"ページ {n} はありません（{len(pages)}ページ）")
            body = pages[n - 1].strip()
            out.append(f"--- {n}ページ目（全{len(pages)}ページ）")
            out.append(body if body else "（このページには文字がありません。スキャンしたものなら、読み取り役に画像として読ませる）")
        return "\n".join(out)
    if page is not None:
        raise Refused("--page は PDF のときだけ使えます")
    if suffix in (".docx", ".docm"):
        return doc_text.word_text(path)
    if suffix in (".xlsx", ".xlsm"):
        return "\n".join(f"--- シート「{name}」\n{body}" for name, body in doc_text.excel_sheets(path))
    if suffix in (".txt", ".md", ".csv", ".json"):
        return path.read_text(encoding="utf-8", errors="replace")
    raise Refused(f"{path.suffix or '拡張子のない'} のファイルは、この道具では読めません（PDF・Word・Excel・文字のファイル）")


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        args = parse(argv)
    except Refused as e:
        print(f"しませんでした：引数が違います（{e}）。")
        return REFUSED
    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    if company.company_folder(folder) is None:
        print(f"{folder} は会社のフォルダではありません（.hojokin/ がありません）。何もしていません。")
        return REFUSED
    try:
        from lib import doc_text
    except Exception as e:  # 同梱のファイルが欠けた・壊れた
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。プラグインを入れ直してください。")
        return BROKEN
    try:
        real = places.resolve_inside(folder, Path(args.file).expanduser())
    except places.PlaceError:
        print(f"しませんでした：{args.file} は会社のフォルダの外です。外の書類は、取り込みの道具で写してから読みます。")
        return REFUSED
    if not real.is_file():
        print(f"しませんでした：{args.file} がありません。")
        return REFUSED
    try:
        text = text_of(real, args.page, doc_text)
    except Refused as e:
        print(f"しませんでした：{e}。")
        return REFUSED
    except (doc_text.TextError, OSError, ValueError, KeyError) as e:
        print(f"しませんでした：{args.file} を読めませんでした（{e}）。")
        return REFUSED
    rel = places.relative_inside(folder, real)
    if len(text) > args.max:
        text = text[: args.max] + f"\n…（{args.max}字で切りました。--page や --max で続きを出す）"
    print(f"# {rel}")
    print(text)
    return OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
