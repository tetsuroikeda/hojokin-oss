"""章ごとの読み取りを1つの制度データにまとめ、確かめ、段階のフォルダを作る道具（SPEC F3、DESIGN 4.5・9章・9.2、TASKS M2c）。

使い方：
  1. まとめる（章ごとの読み取りを、どれも裏取りの道具に通した後）
     python3 -B <この場所>/seido_data.py --folder "${CLAUDE_PROJECT_DIR}" [--case <案件>] --merge
  2. 確かめるだけ（書き換えない）
     python3 -B <この場所>/seido_data.py --folder "${CLAUDE_PROJECT_DIR}" [--case <案件>] --check
  3. 段階のフォルダを作る（採択後に次の段階へ進むとき。--stage がなければ、いちばん前の段階）
     python3 -B <この場所>/seido_data.py --folder "${CLAUDE_PROJECT_DIR}" [--case <案件>] --stage-folders [--stage 2_交付申請]

- まとめ方、確かめ方、段階のフォルダの作り方は、lib/seido_data.py の説明のとおり。
- --merge は、まとめた制度データを裏取りし直して `記録/制度データ/<制度の略称>_<公募回>.json` に置き、
  確かめた結果を出し、形が合えば、いちばん前の段階（申請）のフォルダを作る。置き場所は道具が決める（ほかの場所には書かない）。
- --merge と --check は、期限が読み取れない手続きの段階について、資料の本文にある期限らしい文（「<段階>は…<出来事>から
  <数>か月…期限」）を探し、あれば結果の終わりに示す（制度データの抜けかもしれない。終了コードには響かせない）。
- --case：案件の名前（`記録/資料の本文/` の下のフォルダの名前）。案件が1つなら、渡さなくてよい。
- Claude が Bash で動かすコマンドには、CLAUDE_PROJECT_DIR の環境変数が入らないので、--folder で渡す。
- 終了コード：
  0 確かめた結果がよい（形が合い、重要な項目がすべて値か「要確認」で埋まり、出典のない値が0件、
    書類の手続きと段階の様式がどれも手続きの段階の id・様式の名前に当たる）。--stage-folders はフォルダを用意した。
    重要な項目の任意の欄（数値の要件の満たせないとき など）が「読み取れない」のは、埋まっていないに数えない
    （「任意の欄で読み取れない値」として示す。問い合わせ文の案に回す）。問い合わせ文の案がまだない読み取れない値も、0 のまま示す。
  1 確かめた結果に、足りないところがある（重要な項目の空き（必須の欄の読み取れないを含む）、出典のない値、
    手続きの段階の id・様式の名前に当たらない名前）。--merge のときは、制度データは置いた。
  2 動かさなかった（会社のフォルダでない、案件を決められない、読み取りの結果や制度データがない、形が合わない、
    手続きの段階にない段階の名前、読む材料や作る先が別名などで会社のフォルダの外を指す）。何も書いていない。
  3 補助プログラムが動かない、または途中で止まった。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

NOT_DONE = "何も書いていません。\n\n"
BROKEN = 3


def parse(argv):
    parser = argparse.ArgumentParser(description="章ごとの読み取りを1つの制度データにまとめ、確かめ、段階のフォルダを作る")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--case", help="案件の名前（記録/資料の本文/ の下のフォルダの名前）")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--merge", action="store_true", help="章ごとの読み取りをまとめ、裏取りし直して置き、確かめる")
    action.add_argument("--check", action="store_true", help="置いた制度データを確かめる（書き換えない）")
    action.add_argument("--stage-folders", action="store_true", help="制度データの手続きの段階から、段階のフォルダを作る")
    parser.add_argument("--stage", action="append", metavar="フォルダ", help="作る段階のフォルダの名前（2_交付申請 など。いくつ並べてもよい）")
    return parser.parse_args(argv)


def stage_lines(made, wanted) -> str:
    if made:
        return f"- 段階のフォルダを作りました：{'、'.join(wanted)}（中は「申請書」と「添付する書類」）\n"
    return f"- 段階のフォルダは、もうあります：{'、'.join(wanted)}\n"


def main(argv) -> int:
    # 環境の文字コードによらず、日本語の結果を UTF-8 で返す
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse(argv)
    try:
        from lib import case_folder, company, seido_data, urakadori
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"{NOT_DONE}補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return BROKEN

    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    if company.company_folder(folder) is None:
        print(f"{NOT_DONE}このフォルダ（{folder}）は、まだ会社のフォルダではありません（目印の {company.MARKER_DIR}/ がありません）。"
              "先に、社長の了承を得て会社のフォルダを作り、公式資料を取ってください。")
        return 2
    try:
        case = urakadori.find_case(folder, args.case)
    except case_folder.CaseError as e:
        print(f"{NOT_DONE}案件を決められませんでした（{e}）。")
        return 2

    try:
        if args.merge:
            try:
                saved, merged, verified = seido_data.merge_and_save(folder, case)
            except urakadori.InputError as e:
                print("章ごとの読み取りをまとめましたが、制度データの形が合いません。" + NOT_DONE
                      + "足りない項目の章を読み取り役に読ませ、裏取りの道具に通してから、もう一度まとめてください：\n\n"
                      + "\n".join(f"- {x}" for x in e.errors[:40]) + "\n")
                return 2
            rel = verified.out_file
            result = seido_data.check(saved)
            out = seido_data.merge_report(case, merged, verified, rel) + "\n" + seido_data.check_report(result, rel)
            out += seido_data.clues_report(seido_data.deadline_clues(folder, case, saved))
            stage_ok = True
            if not result.schema_errors:
                try:
                    made, wanted = seido_data.make_stage_folders(folder, case, saved)
                    out += "\n" + stage_lines(made, wanted)
                except case_folder.CaseError as e:  # 制度データは置いた。段階のフォルダだけ作れなかった
                    out += f"\n- 段階のフォルダを作れませんでした（{e}）\n"
                    stage_ok = False
            print(out, end="")
            return 0 if result.ok and stage_ok else 1
        try:
            path, data = seido_data.load_data(folder, case)
        except seido_data.DataMissing as e:
            print(f"{NOT_DONE}{e}")
            return 2
        rel = str(path.relative_to(folder))
        if args.check:
            result = seido_data.check(data)
            print(seido_data.check_report(result, rel) + seido_data.clues_report(seido_data.deadline_clues(folder, case, data)),
                  end="")
            return 0 if result.ok else 1
        # --stage-folders
        if seido_data.check(data).schema_errors:
            print(f"{NOT_DONE}制度データ（{rel}）の形が合わないので、段階のフォルダを作りませんでした。--check で確かめてください。")
            return 2
        made, wanted = seido_data.make_stage_folders(folder, case, data, args.stage)
        print(f"段階のフォルダを用意しました（案件：{case}、制度データ：{rel}）。\n\n" + stage_lines(made, wanted), end="")
        return 0
    except (seido_data.MergeError, urakadori.PlaceError, case_folder.CaseError) as e:
        print(f"{NOT_DONE}{e}")
        return 2
    except Exception as e:  # スキーマや資料の本文が読めない、書けない場所など
        print(f"途中で止まりました（{type(e).__name__}: {e}）。結果は置いていないか、置きかけです。"
              "プラグインを入れ直すか、公式資料を取り直してから、もう一度試してください。")
        return BROKEN


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
