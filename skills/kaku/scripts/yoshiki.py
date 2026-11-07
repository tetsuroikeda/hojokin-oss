"""様式（Word のその1・2）と入力シート.xlsx に書く道具（SPEC F8「様式に書式を壊さずに書き込む」・F10、DESIGN 1.1・
5章・6章・9.1。TASKS M6）。

使い方（--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/yoshiki.py outline [--case <案件>] [--source <公式資料の様式>] [--json]
      様式の表・セル・文字のある段落の一覧を、場所の名前（t4.r2.c0.p0 など）付きで出す。読み取り役に渡す。
  python3 -B <この場所>/yoshiki.py map [--case <案件>] [--seido <制度データ>] [--source <公式資料の様式>] <<'EOF'
      {"様式": "<制度データの様式の名前>", "対応": [{"項目": "<項目の名前>", "書き込む位置": {"見出し": "…", "場所": "…", "範囲": "見出しの後"}}]}
      EOF
      読み取り役の対応づけを、様式の一覧と照らして確かめ、制度データの 様式[].項目[].書き込む位置 に書く。
      表の欄を持つ項目（「（1）事業者情報」の商号又は名称など）は、対応に "欄": "<欄の名前>" を付けると、項目の
      「欄」の並びに書き込む位置を書く（TASKS B14a）。
  python3 -B <この場所>/yoshiki.py write --item "<項目の名前>" [--field "<欄の名前>"] [--form "<様式の名前>"] [--case]
                                       [--stage] [--seido] [--source] [--input <書く文のファイル> | --text "<書く文>"]
      `案件/<案件>/<段階>/申請書/その1・2.docx` の、その項目（--field があればその欄）の書いてよい範囲に書く
      （なければ公式資料の様式から写して作る）。
  python3 -B <この場所>/yoshiki.py cells --input <書く値の JSON> [--source <公式資料の Excel の様式>] [--file <申請書のファイル名>]
                                       [--case] [--stage] [--soffice <LibreOffice の場所>]
      Excel の様式（その3・要件確認書など）の書いてよいセルに書き、数式のセルの値を LibreOffice で計算し直して保存する。
      書き先は --file。省くと --source の様式の名前から決める（その3 の様式なら その3.xlsx、ほかは【】と _第N回 を外した名前）。
  python3 -B <この場所>/yoshiki.py recalc [--file <申請書の Excel のファイル名>] [--case] [--stage] [--soffice <場所>]
      申請書の Excel の様式（省くと、申請書/ の保護したシートのある Excel のすべて）の、数式のセルの値だけを計算し直して保存する。
  python3 -B <この場所>/yoshiki.py pdf [--case] [--stage] [--soffice <LibreOffice の場所>]
      申請書の その1・2.docx を LibreOffice で PDF にした写しを、段階の `添付する書類/その1・2.pdf` に作る（元は変えない）。
  python3 -B <この場所>/yoshiki.py sheet --field "<欄の名前>" [--screen "<画面の名前>"] [--case] [--stage] [--seido]
                                       [--value "<値>"]   （--value がなければ標準入力から読む）
      `案件/<案件>/<段階>/申請書/入力シート.xlsx` の、その欄の「値」に書く（なければ制度データの申請画面から作る）。
  python3 -B <この場所>/yoshiki.py sheet --values - [--case] [--stage] [--seido] <<'EOF'
      {"値": [{"画面": "<画面の名前>", "欄": "<欄の名前>", "値": "<値>"}]}
      EOF
      入力シートの欄に、まとめて書く（M12b。欄が数百あるため）。1件でも書けなければ、何も書かない。
      会社に当てはまらない欄には「該当なし」と書く（数字の欄にも書ける。画面入力の道具は、その欄を画面に入れない）。

- --case：`案件/` の下の案件のフォルダの名前。1つなら省いてよい。--stage：段階のフォルダ（1_申請 など）。省くと、
  番号のいちばん小さい段階。--seido：制度データ（`記録/制度データ/` の中の JSON）。1つなら省いてよい。
- --source：公式資料の様式（会社のフォルダの中の .docx）。省くと、案件の資料の一覧（`記録/資料の本文/<案件>/資料の一覧.json`）
  の置き場所から、様式の「元のファイル」の資料を使う。それもなければ、資料の一覧にある .docx が1つならそれを使う。
- 書いた後に直前の版と構造を比べ、書いてよい範囲の外が1か所でも変わっていたら保存しない（終了コード3）。
- 会社のフォルダの外は読まない・書かない。場所の確かめは lib/places.py で行う（書き出す先とその途中に別名があれば断る。
  案件のフォルダ・`記録/制度データ/` が別名のときも、中の一覧を読まずに断る）。
- 終了コード：0 書いた（outline は出した）、1 補助プログラムを読み込めない、2 しなかった（会社のフォルダでない、
  引数・制度データ・書き込む位置が正しくない など）、3 書くと書いてよい範囲の外が変わるので、保存しなかった。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company, places  # noqa: E402

CASES_DIR = "案件"
SEIDO_DIR = "記録/制度データ"
TEXT_DIR = "記録/資料の本文"
LIST_FILE = "資料の一覧.json"
APPLICATION_DIR = "申請書"
WORD_FILE = "その1・2.docx"
STAGE_NAME = re.compile(r"^([0-9]+)_[^/\\]+$")
OK, BROKEN, REFUSED, OUTSIDE = 0, 1, 2, 3


class Refused(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def parse(argv):
    parser = Parser(description="様式と入力シートに書く")
    sub = parser.add_subparsers(dest="command")

    def common(p, stage=False, seido=True, source=True):
        p.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
        p.add_argument("--case", help="案件のフォルダの名前（案件/ の下）。1つなら省いてよい")
        if stage:
            p.add_argument("--stage", help="段階のフォルダ（1_申請 など）。省くと番号のいちばん小さい段階")
        if seido:
            p.add_argument("--seido", help="制度データ（記録/制度データ/ の中の JSON）。1つなら省いてよい")
        if source:
            p.add_argument("--source", help="公式資料の様式（会社のフォルダの中の .docx）")

    p = sub.add_parser("outline", help="様式の見出し・表・セルの一覧")
    common(p, seido=False)
    p.add_argument("--excel", action="store_true", help="Excel の様式（その3 など）の、シートごとの書いてよいセルの一覧")
    p.add_argument("--json", action="store_true", help="JSON で出す")
    p = sub.add_parser("cells", help="Excel の様式（その3 など）の書いてよいセルに書く")
    common(p, stage=True)
    p.add_argument("--input", required=True, help="書く値の JSON（会社のフォルダの中。記録/一時/その3の値.json など）。"
                                                  "{\"値\": [{\"シート\": \"…\", \"セル\": \"C6\", \"値\": …}]} の形")
    p.add_argument("--file", help="書き先の申請書の Excel のファイル名（申請書/ の中。例：事業場内最低賃金引き上げに係る要件確認書.xlsx）。"
                                  "省くと --source の様式の名前から決める（--source もなければ その3.xlsx）")
    p.add_argument("--soffice", help="LibreOffice（soffice）の場所。省くと決まった場所と Spotlight で探す")
    p = sub.add_parser("recalc", help="申請書の Excel の様式の、数式のセルの値を計算し直して保存する")
    common(p, stage=True, seido=False, source=False)
    p.add_argument("--file", help="申請書の Excel のファイル名（申請書/ の中）。省くと、保護したシートのある Excel のすべて")
    p.add_argument("--soffice", help="LibreOffice（soffice）の場所。省くと決まった場所と Spotlight で探す")
    p = sub.add_parser("map", help="読み取り役の対応づけを確かめて、制度データに書く")
    common(p)
    p.add_argument("--input", help="対応づけの JSON（会社のフォルダの中のファイル）。省くか - なら標準入力")
    p = sub.add_parser("write", help="様式の項目に書く")
    common(p, stage=True)
    p.add_argument("--item", required=True, help="制度データの様式の項目の名前")
    p.add_argument("--field", help="項目の中の表の欄の名前（「（1）事業者情報」の「商号又は名称」など）")
    p.add_argument("--form", help="制度データの様式の名前（項目の名前が2つの様式にあるとき）")
    p.add_argument("--text", help="書く文（省くか - なら標準入力）。改行で段落を分ける")
    p.add_argument("--input", help="書く文のファイル（会社のフォルダの中の .txt。記録/一時/書く文.txt など）")
    p.add_argument("--figures", help="図表の指定の JSON（会社のフォルダの中。工程表の行など。記録/一時/図表.json など）")
    p = sub.add_parser("pdf", help="その1・2.docx を PDF にした写しを、添付する書類に作る（元は変えない）")
    common(p, stage=True, seido=False, source=False)
    p.add_argument("--soffice", help="LibreOffice（soffice）の場所。省くと決まった場所と Spotlight で探す")
    p = sub.add_parser("sheet", help="入力シートの欄に書く")
    common(p, stage=True, source=False)
    p.add_argument("--field", help="入力シートの欄の名前（制度データの申請画面の欄の名前）")
    p.add_argument("--screen", help="画面の名前（同じ名前の欄が2つの画面にあるとき）")
    p.add_argument("--value", help="書く値（省くか - なら標準入力）")
    p.add_argument("--values", help="まとめて書く欄と値の JSON（- なら標準入力）。"
                                    "{\"値\": [{\"画面\": \"…\", \"欄\": \"…\", \"値\": …}]} の形")
    args = parser.parse_args(argv)
    if args.command is None:
        raise Refused("outline・map・write・sheet・cells・recalc・pdf のどれかを付けてください")
    if args.command == "sheet":
        if args.values is not None and (args.field or args.value is not None or args.screen):
            raise Refused("--values と、--field・--value・--screen は一緒に使えません")
        if args.values is None and not args.field:
            raise Refused("--field（1つの欄）か --values（まとめて）を付けてください")
    return args


# ---------------------------------------------------------------- 場所と材料


def inside(folder: Path, given, what: str) -> Path:
    try:
        return places.resolve_inside(folder, Path(given).expanduser())
    except places.PlaceError:
        raise Refused(f"{what}（{given}）が会社のフォルダの外です。会社のフォルダの中のものだけを使います")


def read_json(folder: Path, given, what: str):
    real = inside(folder, given, what)
    try:
        return json.loads(real.read_text(encoding="utf-8")), real
    except OSError as e:
        raise Refused(f"{what}（{given}）を読めませんでした（{e.strerror or e}）")
    except ValueError as e:
        raise Refused(f"{what}（{given}）が JSON として読めません（{e}）")


def find_case(folder: Path, given) -> str:
    top = places.actual(folder, CASES_DIR)
    if top is None or not top.is_dir() or not places.is_inside(folder, top):
        raise Refused(f"{CASES_DIR}/ がありません（または会社のフォルダの外を指しています）。先に junbi で案件を作ってください")
    names = sorted(places.nfc(p.name) for p in top.iterdir() if p.is_dir() and not p.name.startswith("."))
    if given:
        if places.nfc(given) not in names:
            raise Refused(f"案件「{given}」が {CASES_DIR}/ にありません（あるもの：{'、'.join(names) or 'なし'}）")
        return places.nfc(given)
    if len(names) != 1:
        raise Refused(f"{CASES_DIR}/ に案件が{len(names)}つあります。--case で、どれかを渡してください"
                      f"（{'、'.join(names) or 'なし'}）")
    return names[0]


def no_link_before_looking(folder: Path, rel: str) -> None:
    """中の一覧を読む前に、rel（とその途中のフォルダ）が別名でないかを確かめる（lib/places.py）。別名なら Refused。

    別名の先（会社のフォルダの外かもしれない）の中の名前を読まず、出さないため。first_link は、最初の別名で止まり、
    その中の一覧は読まない。
    """
    try:
        places.no_link_on_the_way(folder, rel)
    except places.PlaceError as e:
        raise Refused(f"{e.link} が別名（シンボリックリンク）になっているので、中を見ません。別名を外してください")


def find_stage(folder: Path, case: str, given) -> str:
    # 案件のフォルダが別名なら、その先の段階のフォルダの一覧を読まずに断る（書き出す先も別名を断る。application_file）
    no_link_before_looking(folder, f"{CASES_DIR}/{case}")
    case_dir = places.actual(folder, f"{CASES_DIR}/{case}")
    stages = sorted((p for p in case_dir.iterdir() if p.is_dir() and STAGE_NAME.match(places.nfc(p.name))),
                    key=lambda p: int(STAGE_NAME.match(places.nfc(p.name)).group(1)))
    names = [places.nfc(p.name) for p in stages]
    if given:
        if places.nfc(given) not in names:
            raise Refused(f"段階のフォルダ「{given}」が {CASES_DIR}/{case}/ にありません（あるもの：{'、'.join(names) or 'なし'}）")
        return places.nfc(given)
    if not names:
        raise Refused(f"{CASES_DIR}/{case}/ に段階のフォルダ（1_申請 など）がありません。先に junbi で作ってください")
    return names[0]


def find_seido(folder: Path, given):
    if given:
        return read_json(folder, given, "制度データ")
    # 記録/ か 記録/制度データ/ が別名なら、その先の一覧を読まずに断る（places.actual も途中の一覧を読むので、その前に）。
    # map はここで見つけた制度データに書き戻すので、中を指す別名も断る
    no_link_before_looking(folder, SEIDO_DIR)
    top = places.actual(folder, SEIDO_DIR)
    if top is None or not top.is_dir():
        raise Refused(f"{SEIDO_DIR}/ に制度データがありません。先に junbi で制度データを作ってください")
    found = sorted(p for p in top.iterdir() if p.suffix == ".json" and not p.name.startswith("."))
    if len(found) != 1:
        raise Refused(f"{SEIDO_DIR}/ に制度データが{len(found)}つあります。--seido で、どれを使うかを渡してください")
    return read_json(folder, str(found[0]), "制度データ")


def find_source(folder: Path, case: str, given, form=None) -> Path:
    """公式資料の Word の様式。"""
    if given:
        real = inside(folder, given, "公式資料の様式")
    else:
        listed_rel = f"{TEXT_DIR}/{case}/{LIST_FILE}"
        # places.actual は途中のフォルダの一覧を読むので、その前に、別名をたどった後も中かを確かめる（一覧は読まない）
        if not places.is_inside(folder, f"{TEXT_DIR}/{case}"):
            raise Refused(f"{TEXT_DIR}/{case}/ が会社のフォルダの外を指しています（別名）。中を見ません。別名を外してください")
        listed_path = places.actual(folder, listed_rel)
        placed = {}
        if listed_path is not None and listed_path.is_file():
            listed, _ = read_json(folder, str(listed_path), "案件の資料の一覧")
            placed = listed.get("置き場所") or {} if isinstance(listed, dict) else {}
        wanted = None
        if isinstance(form, dict):
            dest = (form.get("入力先") or {}).get("値") or {}
            wanted = dest.get("元のファイル") if isinstance(dest, dict) else None
        if wanted and isinstance(placed.get(wanted), dict) and placed[wanted].get("ファイル"):
            rel = placed[wanted]["ファイル"]
        else:
            docx = sorted({v.get("ファイル") for v in placed.values()
                           if isinstance(v, dict) and str(v.get("ファイル", "")).lower().endswith(".docx")})
            if len(docx) != 1:
                raise Refused(f"公式資料の Word の様式を決められません（資料の一覧の .docx が{len(docx)}つ）。"
                              "--source で、公式資料/ の様式を渡してください")
            rel = docx[0]
        real = inside(folder, rel, "公式資料の様式")
    if real.suffix.lower() != ".docx" or not real.is_file():
        raise Refused(f"公式資料の様式（{given or real.name}）が Word のファイル（.docx）ではないか、ありません")
    return real


def application_file(folder: Path, case: str, stage: str, name: str) -> Path:
    """`案件/<案件>/<段階>/申請書/<name>` の場所（書き出す先）。別名があれば断る。"""
    rel = f"{CASES_DIR}/{case}/{stage}/{APPLICATION_DIR}/{name}"
    try:
        places.no_link_on_the_way(folder, rel)
    except places.PlaceError as e:
        raise Refused(f"{e.link} が別名（シンボリックリンク）になっているので、書きません。別名を外してください")
    target = places.actual(folder, rel, partial=True)
    if not target.parent.is_dir():
        raise Refused(f"{CASES_DIR}/{case}/{stage}/{APPLICATION_DIR}/ がありません。先に junbi で段階のフォルダを作ってください")
    if not places.is_inside(folder, target):
        raise Refused(f"{rel} が会社のフォルダの外を指しています。書きません")
    return target


def read_text_arg(value) -> str:
    if value is None or value == "-":
        return sys.stdin.read()
    return value


# ---------------------------------------------------------------- 制度データの様式


def forms_with_item(seido, item: str, form_name=None):
    forms = seido.get("様式") if isinstance(seido, dict) else None
    if not isinstance(forms, list):
        raise Refused("制度データに「様式」の並びがありません")
    hits = []
    for form in forms:
        if not isinstance(form, dict):
            continue
        if form_name and form.get("名前") != form_name:
            continue
        for entry in form.get("項目") or []:
            if isinstance(entry, dict) and entry.get("名前") == item:
                hits.append((form, entry))
    if not hits:
        where = f"様式「{form_name}」" if form_name else "制度データの様式"
        raise Refused(f"{where}に、項目「{item}」がありません")
    if len(hits) > 1:
        raise Refused(f"項目「{item}」が{len(hits)}つの様式にあります。--form で様式の名前を渡してください")
    return hits[0]


def mapped_positions(form):
    """様式の項目と欄の、対応づけた書き込む位置（lib/yoshiki_word.py の item_positions）。"""
    from lib import yoshiki_word

    return yoshiki_word.item_positions(form)


def field_entry(entry, field: str, create: bool = False):
    """項目の「欄」の1つ。create なら、なければ足す。なければ None。"""
    subs = entry.get("欄")
    if not isinstance(subs, list):
        if not create:
            return None
        subs = entry["欄"] = []
    for sub in subs:
        if isinstance(sub, dict) and sub.get("名前") == field:
            return sub
    if not create:
        return None
    sub = {"名前": field}
    subs.append(sub)
    return sub


# ---------------------------------------------------------------- 各コマンド


def find_excel_source(folder: Path, case: str, given) -> Path:
    """公式資料の Excel の様式（その3 など）。--source か、案件の資料の一覧の .xlsx の様式。"""
    if given:
        real = inside(folder, given, "公式資料の様式")
    else:
        listed_rel = f"{TEXT_DIR}/{case}/{LIST_FILE}"
        if not places.is_inside(folder, f"{TEXT_DIR}/{case}"):
            raise Refused(f"{TEXT_DIR}/{case}/ が会社のフォルダの外を指しています（別名）。中を見ません。別名を外してください")
        listed_path = places.actual(folder, listed_rel)
        placed = {}
        if listed_path is not None and listed_path.is_file():
            listed, _ = read_json(folder, str(listed_path), "案件の資料の一覧")
            placed = listed.get("置き場所") or {} if isinstance(listed, dict) else {}
        books = sorted({v.get("ファイル") for v in placed.values()
                        if isinstance(v, dict) and str(v.get("ファイル", "")).lower().endswith((".xlsx", ".xlsm"))})
        if len(books) != 1:
            raise Refused(f"公式資料の Excel の様式を決められません（資料の一覧の .xlsx が{len(books)}つ）。"
                          "--source で、公式資料/ の様式を渡してください")
        real = inside(folder, books[0], "公式資料の様式")
    if real.suffix.lower() not in (".xlsx", ".xlsm") or not real.is_file():
        raise Refused(f"{places.relative_inside(folder, real)} は Excel の様式ではありません")
    return real


def do_outline(folder: Path, args, yw) -> int:
    case = find_case(folder, args.case)
    if args.excel:
        from lib import yoshiki_excel

        source = find_excel_source(folder, case, args.source)
        entries = yoshiki_excel.outline(source.read_bytes())
        rel = places.relative_inside(folder, source)
        if args.json:
            print(json.dumps({"様式": rel, "シート": entries}, ensure_ascii=False, indent=1))
        else:
            print(f"様式：{rel}（書いてよいセルは、様式が入力の欄として開けているセル。数式のセルには書かない）")
            print(yoshiki_excel.outline_text(entries), end="")
        return OK
    source = find_source(folder, case, args.source)
    _infos, parts = yw.read_parts(source.read_bytes())
    if yw.DOC not in parts:
        raise Refused(f"{source.name} に Word の本文がありません")
    from lib import xml_spans

    entries = yw.outline(xml_spans.parse(parts[yw.DOC]))
    rel = places.relative_inside(folder, source)
    if args.json:
        print(json.dumps({"様式": rel, "一覧": entries}, ensure_ascii=False, indent=1))
    else:
        print(f"様式：{rel}（場所の名前は、t＝表、r＝行、c＝セル、p＝段落。数は0から）")
        print(yw.outline_text(entries), end="")
    return OK


def do_map(folder: Path, args, yw) -> int:
    case = find_case(folder, args.case)
    seido, seido_path = find_seido(folder, args.seido)
    if args.input and args.input != "-":
        data, _ = read_json(folder, args.input, "対応づけの JSON")
    else:
        try:
            data = json.loads(sys.stdin.read())
        except ValueError as e:
            raise Refused(f"標準入力の対応づけが JSON として読めません（{e}）")
    if not isinstance(data, dict) or not isinstance(data.get("対応"), list) or not data["対応"]:
        raise Refused("対応づけは {\"様式\": \"…\", \"対応\": [{\"項目\": \"…\", \"書き込む位置\": {…}}]} の形で渡してください")
    form_name = data.get("様式")
    from lib import xml_spans

    checked = []
    problems = []
    source = None
    root = None
    for k, pair in enumerate(data["対応"], 1):
        if not isinstance(pair, dict) or not isinstance(pair.get("項目"), str):
            problems.append(f"{k}件目：「項目」がありません")
            continue
        try:
            form, entry = forms_with_item(seido, pair["項目"], form_name)
        except Refused as e:
            problems.append(f"{k}件目：{e}")
            continue
        field = pair.get("欄")
        if field is not None and (not isinstance(field, str) or not field.strip()):
            problems.append(f"{k}件目（{pair['項目']}）：「欄」は、表の欄の名前の文字にしてください")
            continue
        label = yw.field_label(pair["項目"], field) if field else pair["項目"]
        if root is None:
            source = find_source(folder, case, args.source, form)
            root = xml_spans.parse(yw.read_parts(source.read_bytes())[1][yw.DOC])
        try:
            fixed = yw.check_position(root, pair.get("書き込む位置"), label)
        except yw.FormError as e:
            problems.append(f"{k}件目（{label}）：{e}")
            continue
        checked.append((entry, field, fixed))
    if problems:
        print("しませんでした（制度データは変えていません）。直す所：")
        for p in problems:
            print(f"- {p}")
        return REFUSED
    seido_rel = places.relative_inside(folder, seido_path)
    try:
        places.no_link_on_the_way(folder, seido_rel)
    except places.PlaceError as e:
        raise Refused(f"{e.link} が別名（シンボリックリンク）になっているので、制度データに書きません")
    for entry, field, fixed in checked:
        if field:
            field_entry(entry, field, create=True)["書き込む位置"] = fixed
        else:
            entry["書き込む位置"] = fixed
    from lib.docx_min import write_replacing

    write_replacing(seido_path, (json.dumps(seido, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(f"制度データ（{seido_rel}）に、書き込む位置を{len(checked)}件書きました（様式：{places.relative_inside(folder, source)}）。")
    for entry, field, fixed in checked:
        name = yw.field_label(entry["名前"], field) if field else entry["名前"]
        print(f"- {name}：{fixed['範囲']}（見出し「{fixed['見出し']}」、場所 {fixed['場所']}）")
    return OK


def do_write(folder: Path, args, yw) -> int:
    case = find_case(folder, args.case)
    stage = find_stage(folder, case, args.stage)
    seido, _seido_path = find_seido(folder, args.seido)
    form, entry = forms_with_item(seido, args.item, args.form)
    label = args.item
    if args.field:
        sub = field_entry(entry, args.field)
        if sub is None:
            names = "、".join(str(s.get("名前")) for s in entry.get("欄") or [] if isinstance(s, dict)) or "なし"
            raise Refused(f"項目「{args.item}」に、欄「{args.field}」がありません（対応づけた欄：{names}）。"
                          "outline の一覧を読み取り役に渡して、欄ごとに対応づけてください")
        position = sub.get("書き込む位置")
        label = yw.field_label(args.item, args.field)
    else:
        position = entry.get("書き込む位置")
    if not isinstance(position, dict) or not position.get("範囲"):
        if not args.field and entry.get("欄"):
            raise Refused(f"項目「{args.item}」は表の欄ごとに書きます。--field で欄の名前を渡してください")
        raise Refused(f"「{label}」の書き込む位置が、まだ様式と対応づけられていません。outline の一覧を読み取り役に"
                      "渡して対応づけ、map で制度データに書いてから、もう一度試してください")
    if args.input and args.text is not None:
        raise Refused("--input と --text は一緒に使えません")
    if args.input:
        real = inside(folder, args.input, "書く文のファイル")
        try:
            text = real.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise Refused(f"書く文のファイル（{args.input}）を読めませんでした（{e}）")
    else:
        text = read_text_arg(args.text)
    # 図を置く行（【図：前後比較】など）の図を作る（数字は財務モデルの控えから。TASKS B33）
    from lib import zuhyo

    spec = None
    if args.figures:
        spec, _ = read_json(folder, args.figures, "図表の指定の JSON")
        if not isinstance(spec, dict):
            raise Refused("図表の指定の JSON は { } の形にしてください（{\"工程表\": {\"題\": …, \"行\": [ … ]}}）")
    try:
        figures = zuhyo.build(folder, text, spec)
    except zuhyo.FigureError as e:
        raise Refused(f"図を作れなかったので、何も書いていません：{e}")
    target = application_file(folder, case, stage, WORD_FILE)
    first = not os.path.lexists(str(target))
    if first:
        before = find_source(folder, case, args.source, form).read_bytes()
    else:
        before = target.read_bytes()
    try:
        new_blob, summary = yw.write_item(before, position, text, label, mapped_positions(form), figures)
    except yw.OutsideChange as e:
        print(f"保存しませんでした：{WORD_FILE} に書くと、書いてよい範囲の外が変わります（{len(e.differences)}か所）。"
              "前のファイルのままです。道具か様式の想定が違うので、作者に知らせてください。")
        for d in e.differences:
            print(f"- {d}")
        return OUTSIDE
    # 書く直前にもう一度、書き出す先に別名がないかを確かめる
    target = application_file(folder, case, stage, WORD_FILE)
    from lib.docx_min import write_replacing

    write_replacing(target, new_blob)
    rel = places.relative_inside(folder, target)
    made = "公式資料の様式から写して作り、" if first else ""
    print(f"{rel} に、{made}「{summary['項目']}」を書きました（段落 {summary['段落']}、{summary['文字数']}字）。")
    if summary["消した説明の青字の段落"]:
        print(f"- 様式の説明の青字（{summary['消した説明の青字の段落']}段落）は、様式の求めに合わせて消しました。")
    for title, width in zip(summary.get("図") or [], summary.get("図の幅（cm）") or []):
        print(f"- 図「{title}」を入れました（幅 {width}cm。セルの幅に収めています）。")
    print("- 直前の版と比べ、書いてよい範囲の外は変わっていません。")
    return OK


EXCEL_FILE = "その3.xlsx"
RECALC_WORK_DIR = f"{company.MARKER_DIR}/{company.TEMP_DIR}/計算し直し"
_ROUND_SUFFIX = re.compile(r"[_＿\s]*第\s*[0-9０-９]+\s*回$")
_BRACKET_PREFIX = re.compile(r"^【[^】]*】\s*")


def excel_target_name(source: Path, given) -> str:
    """書き先の申請書の Excel のファイル名。--file、なければ公式資料の様式の名前から決める。

    11/6 のリハーサルで、書き先が その3.xlsx に決め打ちされ、要件確認書の様式を --source に渡しても その3 に書こうと
    したため、様式ごとに書き先を分ける。
    """
    if given:
        name = places.nfc(str(given)).strip()
        if not name or "/" in name or name.startswith(".") or not name.lower().endswith((".xlsx", ".xlsm")):
            raise Refused(f"--file には、申請書/ の中の Excel のファイル名（.xlsx）を渡してください（{given}）")
        return name
    stem = places.nfc(source.stem)
    if "その3" in stem:
        return EXCEL_FILE
    stem = _ROUND_SUFFIX.sub("", _BRACKET_PREFIX.sub("", stem)).strip()
    if not stem:
        raise Refused("書き先の名前を様式の名前から決められません。--file で申請書のファイル名を渡してください")
    return stem + source.suffix.lower()


def _same_form(a: bytes, b: bytes) -> bool:
    """2つの Excel が同じ様式か（入力のシートの名前の並びが同じか）。"""
    from lib import yoshiki_excel

    names = lambda blob: [s.name for s in yoshiki_excel.Book(blob).sheets]  # noqa: E731
    return names(a) == names(b)


def recalc_values(folder: Path, blob: bytes, soffice_arg) -> tuple:
    """blob（Excel の様式）の数式のセルの値を、LibreOffice で計算し直した写しから写す。

    戻り値は（新しいバイト列、要約か None、できなかった理由）。数式がなければ（blob, None, ""）。
    """
    import shutil
    import uuid

    from lib import libreoffice, yoshiki_excel

    if not yoshiki_excel.formula_cell_count(blob):
        return blob, None, ""
    soffice = soffice_arg if soffice_arg else libreoffice.find_soffice()
    if not soffice or not (os.path.isfile(soffice) and os.access(soffice, os.X_OK)):
        return blob, None, "LibreOffice が見つかりません"
    try:
        places.no_link_on_the_way(folder, RECALC_WORK_DIR)
    except places.PlaceError as e:
        return blob, None, f"{e.link} が別名（シンボリックリンク）になっています"
    work = places.actual(folder, RECALC_WORK_DIR, partial=True) / uuid.uuid4().hex
    work.mkdir(parents=True)
    try:
        src = work / "様式.xlsx"
        src.write_bytes(blob)
        data = libreoffice.recalc_xlsx(src, work / "計算", str(soffice)).read_bytes()
        new_blob, summary = yoshiki_excel.store_formula_values(blob, data)
    except (libreoffice.LibreOfficeError, OSError, ValueError) as e:
        return blob, None, str(e)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return new_blob, summary, ""


def _recalc_lines(name: str, summary, why: str) -> list:
    if summary is None and not why:
        return []
    if summary is None:
        return [f"- 数式のセルの値は計算し直せませんでした（{why}）。{name} の数式のセルには前の計算の値が残っています。"
                "社長に Excel で開いて保存してもらうか、LibreOffice を入れてから recalc を動かしてください。"]
    lines = [f"- 数式のセル（省力化指数・投資回収期間・伸び率など）の値を、LibreOffice で計算し直して保存しました"
             f"（値が変わったセル {summary['替えたセル']}個。数式と書式は変えていません）。"]
    if summary["エラーのセル"]:
        lines.append("- 計算の結果がエラーのセルがあります（入力の欄の空きや、0 で割る式など）："
                     + "、".join(summary["エラーのセル"][:10]) + ("…" if len(summary["エラーのセル"]) > 10 else ""))
    return lines


def do_cells(folder: Path, args, yw) -> int:
    """Excel の様式の書いてよいセルに、まとめて書く。1件でも書けなければ何も書かない。書いた後、数式の値を計算し直す。"""
    from lib import yoshiki_excel
    from lib.docx_min import write_replacing

    case = find_case(folder, args.case)
    stage = find_stage(folder, case, args.stage)
    data, _ = read_json(folder, args.input, "書く値の JSON")
    items = data.get("値") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise Refused("書く値は {\"値\": [{\"シート\": \"…\", \"セル\": \"C6\", \"値\": …}]} の形で渡してください")
    source = find_excel_source(folder, case, args.source) if args.source else None
    name = excel_target_name(source if source is not None else Path(EXCEL_FILE), args.file)
    target = application_file(folder, case, stage, name)
    first = not os.path.lexists(str(target))
    if first:
        if source is None:
            if name != EXCEL_FILE:
                raise Refused(f"{name} がまだありません。初めて書くときは --source で公式資料の様式を渡してください")
            source = find_excel_source(folder, case, None)
        before = yoshiki_excel.first_copy(source.read_bytes())
    else:
        before = target.read_bytes()
        if source is not None and not _same_form(before, source.read_bytes()):
            raise Refused(f"書き先の {name} は、--source の様式（{places.relative_inside(folder, source)}）とシートの構成が"
                          "違います。--file で書き先を正しく渡してください")
    try:
        new_blob, summary = yoshiki_excel.write_cells(before, items)
    except yw.OutsideChange as e:
        print(f"保存しませんでした：{name} に書くと、書いてよい範囲の外が変わります（{len(e.differences)}か所）。"
              "前のファイルのままです。道具か様式の想定が違うので、作者に知らせてください。")
        for d in e.differences:
            print(f"- {d}")
        return OUTSIDE
    except yw.FormError as e:
        print(f"しませんでした（{name} は前のままです）。{e}")
        print("書いてよいセルは outline --excel で確かめてください。")
        return REFUSED
    new_blob, recalc, why = recalc_values(folder, new_blob, getattr(args, "soffice", None))
    differences = yoshiki_excel.compare_xlsx(before, new_blob)
    if differences:
        print(f"保存しませんでした：{name} の数式の値を写すと、書いてよい範囲の外が変わります（{len(differences)}か所）。"
              "前のファイルのままです。作者に知らせてください。")
        for d in differences:
            print(f"- {d}")
        return OUTSIDE
    target = application_file(folder, case, stage, name)
    write_replacing(target, new_blob)
    rel = places.relative_inside(folder, target)
    made = "公式資料の様式から写して作り（開いたときに計算し直す設定を付けた）、" if first else ""
    print(f"{rel} に、{made}{summary['書いたセル']}個のセルを書きました（シート：{'・'.join(summary['シート'])}）。")
    print("- 直前の版と比べ、書いてよい範囲（様式の入力の欄）と数式のセルの値の外は変わっていません。")
    for line in _recalc_lines(name, recalc, why):
        print(line)
    print("- 計画書に書く数字は、財務モデルの道具の出力から取ってください。")
    return OK


def do_recalc(folder: Path, args, yw) -> int:
    """申請書の Excel の様式の、数式のセルの値だけを計算し直して保存する（書いてよい範囲の外は変えない）。"""
    from lib import yoshiki_excel
    from lib.docx_min import write_replacing

    case = find_case(folder, args.case)
    stage = find_stage(folder, case, args.stage)
    if args.file:
        names = [excel_target_name(Path(EXCEL_FILE), args.file)]
    else:
        top = application_file(folder, case, stage, EXCEL_FILE).parent
        names = []
        for path in sorted(top.iterdir()):
            if path.name.startswith((".", "~$")) or path.suffix.lower() not in (".xlsx", ".xlsm") or path.is_symlink():
                continue
            try:
                if any(sh.protected for sh in yoshiki_excel.Book(path.read_bytes()).sheets):
                    names.append(places.nfc(path.name))
            except (yw.FormError, ValueError):
                continue
        if not names:
            raise Refused("申請書/ に、保護したシートのある Excel の様式がありません")
    code = OK
    for name in names:
        target = application_file(folder, case, stage, name)
        if not target.is_file():
            raise Refused(f"{places.relative_inside(folder, target)} がありません")
        before = target.read_bytes()
        new_blob, recalc, why = recalc_values(folder, before, getattr(args, "soffice", None))
        if recalc is None:
            if why:
                print(f"{name}：数式のセルの値は計算し直せませんでした（{why}）。ファイルは前のままです。")
                code = REFUSED
            else:
                print(f"{name}：数式のセルがないので、何もしていません。")
            continue
        differences = yoshiki_excel.compare_xlsx(before, new_blob)
        if differences:
            print(f"{name}：保存しませんでした（数式の値を写すと、範囲の外が変わります。{len(differences)}か所）。作者に知らせてください。")
            for d in differences:
                print(f"- {d}")
            code = OUTSIDE
            continue
        if new_blob != before:
            write_replacing(application_file(folder, case, stage, name), new_blob)
        print(f"{places.relative_inside(folder, target)}：数式のセルの値を計算し直しました（値が変わったセル {recalc['替えたセル']}個。"
              "数式・書式・入力の欄は変えていません）。")
        for line in _recalc_lines(name, recalc, "")[1:]:
            print(line)
    return code


ATTACH_DIR = "添付する書類"
PDF_WORK_DIR = f"{company.MARKER_DIR}/{company.TEMP_DIR}/PDF"


def do_pdf(folder: Path, args, yw) -> int:
    """申請書の その1・2.docx を PDF にした写しを、段階の「添付する書類」に作る。元の Word は変えない。"""
    import shutil
    import uuid

    from lib import libreoffice
    from lib.docx_min import write_replacing

    case = find_case(folder, args.case)
    stage = find_stage(folder, case, args.stage)
    src = application_file(folder, case, stage, WORD_FILE)
    if not src.is_file():
        raise Refused(f"{places.relative_inside(folder, src)} がまだありません。先に write で様式に書いてください")
    rel = f"{CASES_DIR}/{case}/{stage}/{ATTACH_DIR}/{Path(WORD_FILE).stem}.pdf"
    try:
        places.no_link_on_the_way(folder, rel)
        places.no_link_on_the_way(folder, PDF_WORK_DIR)
    except places.PlaceError as e:
        raise Refused(f"{e.link} が別名（シンボリックリンク）になっているので、書きません。別名を外してください")
    target = places.actual(folder, rel, partial=True)
    if not target.parent.is_dir():
        raise Refused(f"{CASES_DIR}/{case}/{stage}/{ATTACH_DIR}/ がありません。先に junbi で段階のフォルダを作ってください")
    soffice = args.soffice if args.soffice else libreoffice.find_soffice()
    if not soffice or not (os.path.isfile(soffice) and os.access(soffice, os.X_OK)):
        print("しませんでした：LibreOffice が見つからないので、PDF にできません。LibreOffice を入れるか、"
              f"社長に Word で {WORD_FILE} を開いて「PDF として保存」し、{ATTACH_DIR}/ に置いてもらってください。")
        return REFUSED
    before = src.read_bytes()
    work = places.actual(folder, PDF_WORK_DIR, partial=True) / uuid.uuid4().hex
    try:
        work.mkdir(parents=True)
        try:
            made = libreoffice.convert_to_pdf(src, work, soffice)
        except libreoffice.LibreOfficeError as e:
            print(f"しませんでした：{e}。{WORD_FILE} は前のままです。")
            return REFUSED
        data = made.read_bytes()
        if not data.startswith(b"%PDF"):
            print("しませんでした：できたファイルが PDF ではありませんでした。作者に知らせてください。")
            return REFUSED
        write_replacing(target, data)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
        try:
            work.parent.rmdir()
        except OSError:
            pass
    if src.read_bytes() != before:  # 元の Word は変えない（DESIGN 5章）
        print(f"注意：{WORD_FILE} が変わりました。作者に知らせてください。")
        return OUTSIDE
    pages = data.count(b"/Type /Page") - data.count(b"/Type /Pages")
    shown = f"（{pages}ページ）" if pages > 0 else ""
    print(f"{rel} に、{WORD_FILE} を PDF にした写しを作りました{shown}。{WORD_FILE} は変えていません。")
    print("- 書体がない Mac では、別の書体に置き換わります。ページの区切りを、PDF を開いて確かめてください。")
    return OK


def sheet_field(seido, name, screen_name):
    """制度データの申請画面の（画面、欄）。見つからない・2つ以上なら Refused。"""
    from lib import input_sheet

    hits = [(s, f) for s, f in input_sheet.fields_of(seido)
            if f.get("名前") == name and (not screen_name or s.get("名前") == screen_name)]
    if not hits:
        where = f"画面「{screen_name}」に" if screen_name else ""
        raise Refused(f"制度データの申請画面の{where}、欄「{name}」がありません")
    if len(hits) > 1:
        raise Refused(f"制度データの申請画面に、欄「{name}」が{len(hits)}つあります。画面の名前を渡してください")
    return hits[0]


def sheet_value(field, value):
    """欄の種類に合わせた値（数字の欄は数。「該当なし」は文字のまま）。"""
    from lib import input_sheet

    if isinstance(value, bool):
        value = "はい" if value else "いいえ"
    if field.get("種類") == "数字":
        if input_sheet.is_not_applicable(value):
            return input_sheet.NOT_APPLICABLE
        if isinstance(value, (int, float)):
            return value
        return input_sheet.parse_number(str(value))
    if value is None:
        return ""
    return str(value)


def print_supporter_notes(blob: bytes) -> None:
    """入力シートの支援者の欄に入れた案内（SPEC 2.3。「案内」の列）を出す。Claude はこれを社長に伝える（T10-4）。"""
    from lib import input_sheet

    try:
        notes = input_sheet.notes_of(blob)
    except ValueError:
        return
    if not notes:
        return
    screen, field, note = notes[0]
    print(f"- 支援者の欄（{screen}の「{field}」など{len(notes)}欄）には、入力シートの「案内」の列に「{note}」と"
          "入れてあります。社長に、この案内を伝えてください（SPEC 2.3）。")


def do_sheet(folder: Path, args, yw) -> int:
    from lib import input_sheet

    case = find_case(folder, args.case)
    stage = find_stage(folder, case, args.stage)
    seido, _seido_path = find_seido(folder, args.seido)
    if args.values is not None:
        return do_sheet_many(folder, args, yw, case, stage, seido)
    screen, field = sheet_field(seido, args.field, args.screen)
    value = read_text_arg(args.value)
    if value.endswith("\n") and args.value in (None, "-"):
        value = value[:-1]
    value = sheet_value(field, value)
    target = application_file(folder, case, stage, input_sheet.FILE_NAME)
    first = not os.path.lexists(str(target))
    before = input_sheet.build(seido) if first else target.read_bytes()
    try:
        new_blob, summary = input_sheet.write_value(before, args.field, value, screen.get("名前"),
                                                    input_sheet.limit_of(field))
    except yw.OutsideChange as e:
        print(f"保存しませんでした：{input_sheet.FILE_NAME} に書くと、書いてよい範囲の外が変わります（{len(e.differences)}か所）。"
              "前のファイルのままです。作者に知らせてください。")
        for d in e.differences:
            print(f"- {d}")
        return OUTSIDE
    target = application_file(folder, case, stage, input_sheet.FILE_NAME)
    from lib.docx_min import write_replacing

    write_replacing(target, new_blob)
    rel = places.relative_inside(folder, target)
    made = "制度データの申請画面から作り、" if first else ""
    print(f"{rel} に、{made}欄「{summary['欄']}」（{screen.get('名前')}）の値を書きました（セル {summary['セル']}）。")
    if summary.get("注意"):
        print(f"- 注意：{summary['注意']}。")
    print("- 直前の版と比べ、書いてよい範囲の外は変わっていません。")
    print_supporter_notes(new_blob)
    return OK


def read_values(folder: Path, given) -> list:
    """--values の JSON（{"値": [...]} か、並びそのもの）。"""
    if given in (None, "-"):
        try:
            data = json.loads(sys.stdin.read())
        except ValueError as e:
            raise Refused(f"標準入力の欄と値が JSON として読めません（{e}）")
    else:
        data, _ = read_json(folder, given, "欄と値の JSON")
    entries = data.get("値") if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise Refused("欄と値は {\"値\": [{\"画面\": \"…\", \"欄\": \"…\", \"値\": …}]} の形で渡してください")
    return entries


def do_sheet_many(folder: Path, args, yw, case: str, stage: str, seido) -> int:
    """入力シートの欄に、まとめて書く。1件でも書けなければ、何も書かない（入力シートは前のまま）。"""
    from lib import input_sheet

    entries = read_values(folder, args.values)
    target = application_file(folder, case, stage, input_sheet.FILE_NAME)
    first = not os.path.lexists(str(target))
    original = input_sheet.build(seido) if first else target.read_bytes()
    blob = original
    problems, written, notes = [], [], []
    for k, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or not isinstance(entry.get("欄"), str) or "値" not in entry:
            problems.append(f"{k}件目：「欄」と「値」がありません")
            continue
        name, screen_name = entry["欄"], entry.get("画面")
        try:
            screen, field = sheet_field(seido, name, screen_name)
            value = sheet_value(field, entry["値"])
            blob, summary = input_sheet.write_value(blob, name, value, screen.get("名前"), input_sheet.limit_of(field))
        except yw.OutsideChange as e:
            print(f"保存しませんでした：{input_sheet.FILE_NAME} に書くと、書いてよい範囲の外が変わります（{len(e.differences)}か所）。"
                  "前のファイルのままです。作者に知らせてください。")
            for d in e.differences:
                print(f"- {d}")
            return OUTSIDE
        except (Refused, ValueError) as e:
            problems.append(f"{k}件目（{screen_name + '・' if screen_name else ''}{name}）：{e}")
            continue
        written.append((screen.get("名前"), summary))
        if summary.get("注意"):
            notes.append(f"{screen.get('名前')}・{summary['欄']}：{summary['注意']}")
    if problems:
        print(f"しませんでした（{input_sheet.FILE_NAME} は前のままです）。直す所：")
        for p in problems:
            print(f"- {p}")
        return REFUSED
    # 書く前に、はじめの版と最後の版も比べる（1件ずつの比べに加えて）
    differences = input_sheet.compare_xlsx(original, blob)
    if differences:
        print(f"保存しませんでした：{input_sheet.FILE_NAME} の書いてよい範囲の外が変わります（{len(differences)}か所）。"
              "前のファイルのままです。作者に知らせてください。")
        for d in differences:
            print(f"- {d}")
        return OUTSIDE
    target = application_file(folder, case, stage, input_sheet.FILE_NAME)
    from lib.docx_min import write_replacing

    write_replacing(target, blob)
    rel = places.relative_inside(folder, target)
    made = "制度データの申請画面から作り、" if first else ""
    print(f"{rel} に、{made}{len(written)}件の欄の値を書きました。")
    for screen_name, summary in written:
        print(f"- {screen_name}・{summary['欄']}（セル {summary['セル']}）")
    for n in notes:
        print(f"- 注意：{n}。")
    print("- 直前の版と比べ、書いてよい範囲の外は変わっていません。")
    print_supporter_notes(blob)
    return OK


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        args = parse(argv)
    except Refused as e:
        print(f"しませんでした：引数が違います（{e}）。")
        return REFUSED
    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    if company.company_folder(folder) is None:
        print(f"{folder} は会社のフォルダではありません（.hojokin/ がありません）。何もしていません。"
              "会社のフォルダで動かしてください。")
        return REFUSED
    try:
        from lib import input_sheet  # noqa: F401
        from lib import yoshiki_word as yw
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return BROKEN
    handlers = {"outline": do_outline, "map": do_map, "write": do_write, "sheet": do_sheet, "pdf": do_pdf,
                "cells": do_cells, "recalc": do_recalc}
    try:
        return handlers[args.command](folder, args, yw)
    except Refused as e:
        print(f"しませんでした：{e}。")
        return REFUSED
    except ValueError as e:  # 書き込む位置が見つからない、様式や入力シートが読めない（FormError・SpanError）など
        print(f"しませんでした：{e}。ファイルは前のままです。")
        return REFUSED
    except OSError as e:
        print(f"しませんでした：ファイルを読めないか書けませんでした（{e.strerror or e}）。ファイルは前のままです。")
        return REFUSED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
