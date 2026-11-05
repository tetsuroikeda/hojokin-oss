"""差し戻しへの対応の材料を出す道具（SPEC F12「差し戻し」・T12-2、DESIGN 4.2・4.5・10章。TASKS B32）。

使い方（する事の後に、--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/sashimodoshi.py show --case <案件> --stage <段階> [--number <番号>]
      進め方（この skill の別ファイル `差し戻し.md`。ファイルの道具はプラグインの中を読めないので道具が出す）、
      提出版（番号を省けばいちばん新しいもの）のファイルの一覧と、文字のファイル（JSON・テキストなど）の中身、
      差し戻しの原本（書類の台帳の、種類に「差し戻し」のある原本）、会社の記録の過去の差し戻しを出す。何も書かない。
  python3 -B <この場所>/sashimodoshi.py diff --case <案件> --stage <段階> [--number <番号>]
      提出版と、今の段階のフォルダのファイルを比べ、足した・消した・変わったファイルと、文字のファイルの変わった行を出す
      （直した後に、差し戻しが指す箇所だけが直ったかを確かめるため）。何も書かない。

- 提出版の中身は版の履歴から取り出し、記録した sha256 と照らしてから使う（lib/submission.py）。
- 会社のフォルダの外は読まない。場所の確かめは lib/places.py で行う。
- 終了コード：0 出した、1 補助プログラムを読み込めない、2 しなかった（会社のフォルダでない、提出版がない など）。
"""

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import difflib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import unicodedata  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company  # noqa: E402

GUIDE = Path(__file__).resolve().parents[1] / "差し戻し.md"
TEXT_SUFFIXES = (".json", ".txt", ".md", ".csv", ".tsv", ".xml")
SHOW_MAX = 6000  # 1つのファイルの中身を出す字数
DIFF_MAX = 120  # 出す差の行の数
RETURN_WORD = "差し戻し"


class Refused(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def nfc(text) -> str:
    return unicodedata.normalize("NFC", str(text or ""))


def parse(argv):
    parser = Parser(description="差し戻しへの対応の材料を出す（提出版と照らす）")
    sub = parser.add_subparsers(dest="command", parser_class=Parser)
    for name, text in (("show", "進め方・提出版の中身・差し戻しの原本を出す"), ("diff", "提出版と今のファイルを比べる")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
        p.add_argument("--case", required=True, help="案件（案件/ の下のフォルダの名前）")
        p.add_argument("--stage", required=True, help="段階のフォルダ（2_交付申請 など）")
        p.add_argument("--number", type=int, help="提出版の番号（省けばいちばん新しいもの）")
    args = parser.parse_args(argv)
    if args.command not in ("show", "diff"):
        raise Refused("show か diff を付けてください")
    return args


def guide() -> str:
    lines = GUIDE.read_text(encoding="utf-8").rstrip().splitlines()
    return "\n".join(("#" + line) if line.startswith("#") else line for line in lines[1:]).strip()


def is_text(path: str) -> bool:
    return Path(path).suffix.lower() in TEXT_SUFFIXES


def decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def current_files(folder: Path, case: str, stage: str):
    """今の段階のフォルダのファイル（会社のフォルダからの場所 → 中身）。"""
    from lib import places
    rel = f"案件/{case}/{stage}"
    base = places.actual(folder, rel)
    found = {}
    if base is None or not base.is_dir() or not places.is_inside(folder, base):
        return found
    for p in sorted(base.rglob("*")):
        if p.is_file() and not p.name.startswith((".", "~")) and places.is_inside(folder, p):
            found[nfc(p.relative_to(folder).as_posix())] = p.read_bytes()
    return found


def returns_in_ledger(folder: Path):
    try:
        from lib import seiri
        ledger = seiri.load_ledger(folder)
    except Exception:
        return []
    return [o for o in seiri.originals(ledger) if RETURN_WORD in nfc(o.get("種類")) + nfc(o.get("補足"))]


def past_defects(folder: Path):
    try:
        from lib import company_record
        data = company_record.load(folder)
    except Exception:
        return []
    return [it for it in data.get("項目", []) if it.get("種類") == company_record.DEFECT]


def run_show(folder: Path, args, submission) -> int:
    entry = submission.find(folder, args.case, args.stage, args.number)
    files = submission.contents(folder, entry)
    out = ["# 進め方", "", guide(), "", f"# 提出版：{submission.label(entry)}", ""]
    out.append("ファイル（会社のフォルダからの場所。中身は提出したときのもの）：")
    out += [f"- {path}（{len(data):,}バイト）" for path, data in files]
    for path, data in files:
        if is_text(path):
            text = decode(data)
            cut = "\n…（長いので、ここで切りました）" if len(text) > SHOW_MAX else ""
            out += ["", f"## 提出版の中身：{path}", "", "```", text[:SHOW_MAX] + cut, "```"]
    others = [path for path, _data in files if not is_text(path)]
    if others:
        out += ["", "文字のファイルでないもの（PDF・Word・Excel・画像）は、上の場所の今のファイルを Read で開くか、"
                    "kiroku の show-submitted で 見るだけ/ に出して照らす：" + "、".join(others)]
    found = returns_in_ledger(folder)
    out += ["", "# 差し戻しの原本（書類の台帳）", ""]
    out += [f"- {o['場所']}（{o.get('日付') or '日付なし'}）" for o in found] or ["- まだありません（入れ口にあれば、shorui で整理して原本にする）"]
    defects = past_defects(folder)
    out += ["", "# 過去の差し戻し（会社の記録）", ""]
    out += [f"- {d['id']}：{d['案件']}／{d['手続きの段階']}：{d['内容']}。照合の決まり：{d['照合の決まり']}" for d in defects] \
        or ["- ありません"]
    print("\n".join(out))
    return 0


def run_diff(folder: Path, args, submission) -> int:
    entry = submission.find(folder, args.case, args.stage, args.number)
    before = {nfc(path): data for path, data in submission.contents(folder, entry)}
    after = current_files(folder, nfc(args.case), nfc(args.stage).strip("/"))
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(p for p in set(before) & set(after)
                     if hashlib.sha256(before[p]).digest() != hashlib.sha256(after[p]).digest())
    out = [f"提出版（{submission.label(entry)}）と、今の段階のフォルダを比べました。", ""]
    out.append(f"- 変わったファイル：{len(changed)}件、足したファイル：{len(added)}件、消したファイル：{len(removed)}件")
    out += [f"  - 変わった：{p}" for p in changed] + [f"  - 足した：{p}" for p in added] + [f"  - 消した：{p}" for p in removed]
    shown = 0
    for p in changed:
        if not is_text(p):
            out.append(f"\n## {p}\n- 文字のファイルでないので、変わったことだけを示します（中身は開いて確かめる）")
            continue
        a, b = before[p], after[p]
        if p.lower().endswith(".json"):
            try:  # 書式の違い（字下げなど）を除いて比べる
                a = json.dumps(json.loads(decode(a)), ensure_ascii=False, indent=1).encode("utf-8")
                b = json.dumps(json.loads(decode(b)), ensure_ascii=False, indent=1).encode("utf-8")
            except ValueError:
                pass
        lines = list(difflib.unified_diff(decode(a).splitlines(), decode(b).splitlines(), "提出版", "今", lineterm="", n=1))
        out += ["", f"## {p}（- が提出版、+ が今）", "```"]
        for line in lines[2:]:
            if shown >= DIFF_MAX:
                out.append("…（長いので、ここで切りました）")
                break
            out.append(line)
            shown += 1
        out.append("```")
    if not (changed or added or removed):
        out.append("\n提出版から何も変わっていません（まだ直していないか、直す前に戻っています）。")
    print("\n".join(out))
    return 0


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        args = parse(argv)
    except Refused as e:
        print(f"しませんでした：引数が足りないか違います（{e}）。")
        return 2
    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    if company.company_folder(folder) is None:
        print(f"{folder} は会社のフォルダではありません（.hojokin/ がありません）。何もしていません。")
        return 2
    try:
        from lib import submission
    except Exception as e:
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。プラグインを入れ直してから、もう一度試してください。")
        return 1
    try:
        return run_show(folder, args, submission) if args.command == "show" else run_diff(folder, args, submission)
    except submission.SubmissionError as e:
        print(f"しませんでした：{e}。")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
