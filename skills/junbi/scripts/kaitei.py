"""公募要領の改訂や新しい公募回の資料が出たときに、変わったページだけを読み直し、制度データの差を出す道具（SPEC F7、DESIGN 9.2、TASKS M14）。

使い方（公式資料を取り直した後。前の回の資料は、資料の一覧の「前の回の資料」にある）：
  1. 変わったページを見る（書き換えない）
     python3 -B <この場所>/kaitei.py --folder "${CLAUDE_PROJECT_DIR}" [--case <案件>] --pages
  2. 章ごとの読み取りを引き継ぐ（出典を今の資料に付け替え、今の資料の本文で裏取りし直す）。読み直す値の一覧が出る
     python3 -B <この場所>/kaitei.py --folder "${CLAUDE_PROJECT_DIR}" [--case <案件>] --carry
  3. 読み取り役が読み直した件（変わったページの件だけ）を、同じ章に差し替える（標準入力で JSON を渡す）
     python3 -B <この場所>/kaitei.py --folder "${CLAUDE_PROJECT_DIR}" [--case <案件>] --apply - <<'EOF' … EOF
  4. 前と後の制度データの差と、自社の申請で影響するところを出す（書き換えない）
     python3 -B <この場所>/kaitei.py --folder "${CLAUDE_PROJECT_DIR}" [--case <案件>] --diff [--old <場所> --new <場所>] [--json]

- 変わったページの見つけ方、引き継ぎ方、差の出し方は、lib/kaitei.py の説明のとおり。
- --diff の --old・--new：会社のフォルダからの制度データの場所。渡さなければ、その制度のいちばん新しい2つの回を比べる。
- 終了コード：
  0 できた。--diff は、変わった項目のどれにも出典のページがある（ページの番号のない HTML などは資料だけでよい）か、変更なし。
    --carry・--apply は、どの値も裏取りで外れなかった。
  1 --diff：出典のページのない変わった項目がある（その項目の章を読み直す）。
    --carry・--apply：裏取りで外れた値がある（読み直す値の一覧のとおりに、読み取り役に読ませる）。結果は置いた。
  2 動かさなかった（会社のフォルダでない、案件を決められない、前の回の資料や制度データがない、形が合わない、
    会社のフォルダの外を指す など）。何も書いていない。
  3 補助プログラムが動かない、または途中で止まった。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

NOT_DONE = "何も書いていません。\n\n"
BROKEN = 3
SHOW_LINES = 3


def parse(argv):
    parser = argparse.ArgumentParser(description="改訂や新しい公募回の資料で、変わったページだけを読み直し、制度データの差を出す")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--case", help="案件の名前（記録/資料の本文/ の下のフォルダの名前）")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--pages", action="store_true", help="前の回の資料と今の資料の、変わったページを出す")
    action.add_argument("--carry", action="store_true", help="章ごとの読み取りの出典を今の資料に付け替え、裏取りし直す")
    action.add_argument("--apply", metavar="-", help="読み直した件の JSON（標準入力は -）を、同じ章に差し替える")
    action.add_argument("--diff", action="store_true", help="前と後の制度データの差と、自社で影響するところを出す")
    parser.add_argument("--old", help="--diff：前の制度データ（会社のフォルダからの場所）")
    parser.add_argument("--new", help="--diff：後の制度データ（会社のフォルダからの場所）")
    parser.add_argument("--json", action="store_true", help="--diff：結果を JSON で出す")
    return parser.parse_args(argv)


def short(lines, limit=SHOW_LINES):
    text = " ／ ".join(x for x in lines[:limit] if x)
    return (text[:150] + "…") if len(text) > 150 else text


def pages_report(kaitei, folder, case, diffs) -> str:
    out = [f"前の回の資料と今の資料の、変わったページ（案件：{case}）。頁の番号のずれと、目次の頁の番号だけの違いは除いた。", ""]
    for old, d in diffs.items():
        if d.same:
            out.append(f"- {old} → {d.new_id}：変更なし")
            continue
        pages = "、".join(f"p.{p}" for p in d.changed_new_pages) or "（ページの番号なし）"
        out.append(f"- {old} → {d.new_id}：変わった所 {len(d.changes)}か所。今の資料の {pages}")
        for c in d.changes:
            where = f"p.{c.new_page}" if c.new_page is not None else "（ページなし）"
            out.append(f"  - {where}（前 p.{c.old_page}）{c.kind}：{short(c.old_lines) or '（なし）'} → {short(c.new_lines) or '（なし）'}")
    out += ["", "変わったページに当たる章（前の回の資料で読んだページ）："]
    for path in kaitei.reading_files(folder, case):
        chapter = kaitei._load_json(folder, path)
        hits = kaitei.chapter_hits(chapter, diffs)
        out.append(f"- {chapter['読み取り']['章']}：" + ("、".join(f"p.{p}" for p in hits) if hits else "当たらない"))
    return "\n".join(out) + "\n"


def carry_report(kaitei, carried, todo) -> str:
    out = ["章ごとの読み取りを引き継ぎ、出典を今の資料に付け替えて、今の資料の本文で裏取りし直しました。", ""]
    for c in carried:
        out.append(f"- {c.chapter}：付け替えた出典 {c.moved}、今の資料で外れた値 {len(c.broken)}、前から要確認の値 {len(c.still)}")
    out += ["", "読み直すもの（読み取り役に、変わったページと、この値の件を渡す。件は全部の欄を返させる）："]
    if not todo:
        out.append("- ありません（変わったページに当たる値は、どれも今の資料の文のとおりでした）")
    for t in todo:
        pages = "、".join(f"{doc} " + "・".join(f"p.{p}" for p in ps) for doc, ps in t["変わったページ"].items()) or "（ページなし）"
        out.append(f"- {t['章']}：変わったページ {pages}")
        out += [f"  - {w}" for w in t["読み直す値"]]
    return "\n".join(out) + "\n"


def apply_report(r) -> str:
    out = [f"読み直した件を、章「{r.chapter}」に差し替えました。", ""]
    out.append("- 差し替えた件：" + ("、".join(r.replaced) or "なし"))
    out.append("- 足した件：" + ("、".join(r.added) or "なし"))
    out.append("- 消した件：" + ("、".join(r.removed) or "なし"))
    if r.missing:
        out.append("- 消す件に挙がったが、前の結果になかった件：" + "、".join(r.missing))
    res = r.result
    out.append(f"- 裏取り：照らした値 {res.checked}、状態ごとの数 {dict(sorted(res.states.items()))}")
    for f in res.downgraded:
        out.append(f"  - 要確認にした：{f.where}（{'。'.join(f.problems)[:160]}）")
    return "\n".join(out) + "\n"


def main(argv) -> int:
    # 環境の文字コードによらず、日本語の結果を UTF-8 で返す
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse(argv)
    try:
        from lib import case_folder, company, kaitei, urakadori
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"{NOT_DONE}補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return BROKEN

    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    if company.company_folder(folder) is None:
        print(f"{NOT_DONE}このフォルダ（{folder}）は、まだ会社のフォルダではありません（目印の {company.MARKER_DIR}/ がありません）。")
        return 2
    try:
        case = urakadori.find_case(folder, args.case)
    except case_folder.CaseError as e:
        print(f"{NOT_DONE}案件を決められませんでした（{e}）。")
        return 2

    try:
        if args.pages:
            listed = kaitei.load_listed(folder, case)
            pairs = kaitei.doc_pairs(listed)
            if not pairs:
                print(f"{NOT_DONE}前の回の資料がありません（資料の一覧の「前の回の資料」が空）。比べるものはありません。")
                return 2
            print(pages_report(kaitei, folder, case, kaitei.page_diffs(folder, case, pairs)), end="")
            return 0
        if args.carry:
            diffs, carried = kaitei.carry(folder, case)
            todo = kaitei.reread_list(diffs, carried, folder, case)
            print(carry_report(kaitei, carried, todo), end="")
            return 1 if any(t["読み直す値"] for t in todo) else 0
        if args.apply is not None:
            if args.apply != "-":
                print(f"{NOT_DONE}--apply には - を渡し、JSON を標準入力で渡してください（会社のフォルダの外のファイルは読みません）。")
                return 2
            try:
                data = json.loads(sys.stdin.read())
            except ValueError as e:
                print(f"{NOT_DONE}標準入力が JSON として読めません（{e}）。")
                return 2
            try:
                r = kaitei.apply_items(folder, case, data)
            except urakadori.InputError as e:
                print(f"{NOT_DONE}形が合いません：\n\n" + "\n".join(f"- {x}" for x in e.errors[:40]) + "\n")
                return 2
            print(apply_report(r), end="")
            return 1 if r.result.downgraded else 0
        # --diff
        r = kaitei.compare_seido(folder, case, args.old, args.new)
        if args.json:
            print(json.dumps(kaitei.diff_json(r), ensure_ascii=False, indent=2))
        else:
            print(kaitei.diff_report(r), end="")
        return 1 if r.missing_pages else 0
    except urakadori.InputError as e:  # 引き継いだ章の形が合わない（その章は書いていない）
        print(f"章の読み取りの形が合いません。その章は書いていません：\n\n" + "\n".join(f"- {x}" for x in e.errors[:40]) + "\n")
        return 2
    except (kaitei.KaiteiError, urakadori.PlaceError, case_folder.CaseError) as e:
        print(f"{NOT_DONE}{e}")
        return 2
    except Exception as e:  # 資料の本文が読めない、書けない場所など
        print(f"途中で止まりました（{type(e).__name__}: {e}）。結果は置いていないか、置きかけです。"
              "プラグインを入れ直すか、公式資料を取り直してから、もう一度試してください。")
        return BROKEN


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
