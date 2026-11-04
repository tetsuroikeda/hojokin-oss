"""画面入力の道具（SPEC F10「入力シートの値を画面に入れ、一時保存まで進める」、DESIGN 5章・6章。TASKS M8）。

入力シート.xlsx（kaku の yoshiki.py sheet が作る）と、ブラウザの道具がページを読んだ結果（read_page）を突き合わせる。
画面に値を入れること（form_input・クリック）は Claude がブラウザの道具で行い、この道具は入れない。

使い方（--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/nyuryoku.py sheet [--case <案件>] [--stage <段階>] [--json]
      入力シートの画面ごとの欄の数（ツールが入れる・担当者が入れる・値がない）と、文字数の上限を超える値、
      チェック欄の値の書き方が分からない行を出す。画面に入れる前に流す。
  python3 -B <この場所>/nyuryoku.py list --screen "<画面>" [--case] [--stage] [--page -] [--json]
      いま読んだ画面と入力シートを突き合わせ、ツールが入れる欄ごとに、部品の番号（ref）と form_input に渡す値を出す。
      担当者が入れる欄、画面にあって入力シートにない欄、入力シートにあって画面に見当たらない欄も出す。
  python3 -B <この場所>/nyuryoku.py check --screen "<画面>" [--case] [--stage] [--page -] [--json]
      入れた後に読み直した画面と入力シートを比べる。文字の欄と選択欄は値で照らす。チェック欄とラジオボタンは、
      入れた後の状態をページの構造から読み取れないので（実験 E1）、担当者に画面で確かめてもらう欄として出す。

- 画面（read_page の結果）は、既定では、PostToolUse の hook が控えた最後の読み取り（`.hojokin/一時/画面入力/`）を使う。
  `--page -` を付けると、標準入力から read_page の文を読む（hook が動いていないときなど）。
- --screen：入力シートの「画面」の名前（加点項目 など）。画面の見出しの「❹ 加点項目」のような番号の印は付いていてもよい。
- 欄の名前の照らし方は、画面入力の守り（lib/browser_guard.py）と同じ（囲むラベルの名前の全文か、「：」より前の項目名）。
- チェック欄の値は「はい」（チェックを入れる）・「いいえ」（外す）で書く（M8 の仮の形）。空の欄には触れない。
  ラジオボタンの値は、選ぶ項目の名前（「いいえ」など）。
- 値が「該当なし」の欄（会社に当てはまらない欄。kaku が書く）も、空の欄と同じく画面に触れない（M12b）。
- 会社のフォルダの外は読まない。場所の確かめは lib/places.py で行う。
- 終了コード：0 照らした値がすべて合う（sheet・list は、入れられない値がない）、1 補助プログラムを読み込めない、
  2 しなかった（会社のフォルダでない、入力シート・画面の控えがない、引数が違う など）、
  4 合わない値・画面に見当たらない欄・文字数の上限を超える値・書き方の分からない値がある。

/usr/bin/python3（3.9）で動く。標準のライブラリと、プラグインの lib/ だけを使う。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import unicodedata  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company, places  # noqa: E402

CASES_DIR = "案件"
APPLICATION_DIR = "申請書"
STAGE_NAME = re.compile(r"^([0-9]+)_[^/\\]+$")
OK, BROKEN, REFUSED, MISMATCH = 0, 1, 2, 4

# チェック欄の値の書き方（M8 の仮の形。questions に挙げた）
CHECK_ON = ("はい", "入れる", "チェックする", "チェック", "あり", "○", "◯", "✓", "✔")
CHECK_OFF = ("いいえ", "入れない", "チェックしない", "外す", "なし", "×")
TEXT_KINDS = ("文字", "数字", "日付")
# 入力シートの種類 → 画面の部品の役割
KIND_ROLES = {
    "文字": ("textbox", "searchbox", "spinbutton"),
    "数字": ("textbox", "searchbox", "spinbutton"),
    "日付": ("textbox", "searchbox", "spinbutton"),
    "選択": ("combobox", "listbox"),
    "チェック": ("checkbox", "switch"),
    "ラジオ": ("radio",),
}
UNSELECTED = re.compile(r"^-*\s*(選択してください|選んでください|未選択)\s*-*$")
_LIMIT = re.compile(r"^([0-9]+)字（(.+)）$")


class Refused(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def parse(argv):
    parser = Parser(description="入力シートと画面を突き合わせる")
    sub = parser.add_subparsers(dest="command")
    for name, text in (("sheet", "入力シートの欄の数と、入れられない値"),
                       ("list", "画面の部品の番号と、入れる値の一覧"),
                       ("check", "入れた後の画面と入力シートを比べる")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
        p.add_argument("--case", help="案件のフォルダの名前（案件/ の下）。1つなら省いてよい")
        p.add_argument("--stage", help="段階のフォルダ（1_申請 など）。省くと番号のいちばん小さい段階")
        p.add_argument("--json", action="store_true", help="JSON で出す")
        if name != "sheet":
            p.add_argument("--screen", required=True, help="入力シートの画面の名前（加点項目 など）")
            p.add_argument("--page", help="「-」なら、標準入力から read_page の文を読む。省くと、hook の控えの最後の読み取り")
    args = parser.parse_args(argv)
    if not args.command:
        raise Refused("sheet・list・check のどれかを付けてください")
    return args


# ---------------------------------------------------------------- 文字

def norm(text) -> str:
    """名前を比べる形（NFC、続いた空白を1つに）。"""
    return " ".join(unicodedata.normalize("NFC", str(text or "")).split())


def unescape(text: str) -> str:
    """read_page の名前の中の \\" と \\\\ を戻す。"""
    return re.sub(r'\\(["\\])', r"\1", text)


def screen_key(name) -> str:
    """画面の名前を比べる形。頭の「❹」「⓫」「4.」のような番号の印と空白を除く。"""
    text = norm(name)
    i = 0
    while i < len(text) and (unicodedata.category(text[i]) in ("No", "So", "Zs", "Nd") or text[i] in ".．、"):
        i += 1
    return text[i:]


def not_applicable(value) -> bool:
    """入力シートの値が「該当なし」（会社に当てはまらない欄。画面には入れない。M12b）か。"""
    from lib import input_sheet

    return input_sheet.is_not_applicable(value)


def check_state(value: str):
    """チェック欄の値 → True（入れる）・False（外す）・None（空か「該当なし」。触れない）。書き方が分からなければ Refused。"""
    text = norm(value)
    if text == "" or not_applicable(text):
        return None
    if text in CHECK_ON or text.lower() == "true":
        return True
    if text in CHECK_OFF or text.lower() == "false":
        return False
    raise Refused(f"チェック欄の値「{value}」の意味が分かりません（「はい」か「いいえ」で書いてください）")


# ---------------------------------------------------------------- 入力シート

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


def find_stage(folder: Path, case: str, given) -> str:
    rel = f"{CASES_DIR}/{case}"
    # 案件のフォルダが外を指す別名なら、その先の一覧を読まずに断る
    if not places.is_inside(folder, rel):
        raise Refused(f"{rel} が会社のフォルダの外を指しています（別名）。中を見ません。別名を外してください")
    case_dir = places.actual(folder, rel)
    stages = sorted((p for p in case_dir.iterdir() if p.is_dir() and STAGE_NAME.match(places.nfc(p.name))),
                    key=lambda p: int(STAGE_NAME.match(places.nfc(p.name)).group(1)))
    names = [places.nfc(p.name) for p in stages]
    if given:
        if places.nfc(given) not in names:
            raise Refused(f"段階のフォルダ「{given}」が {rel}/ にありません（あるもの：{'、'.join(names) or 'なし'}）")
        return places.nfc(given)
    if not names:
        raise Refused(f"{rel}/ に段階のフォルダ（1_申請 など）がありません。先に junbi で作ってください")
    return names[0]


def sheet_path(folder: Path, case: str, stage: str):
    from lib import input_sheet

    rel = f"{CASES_DIR}/{case}/{stage}/{APPLICATION_DIR}/{input_sheet.FILE_NAME}"
    path = places.actual(folder, rel)
    if path is None or not path.is_file():
        raise Refused(f"{rel} がありません。先に kaku で入力シートを作ってください（yoshiki.py sheet）")
    try:
        real = places.resolve_inside(folder, path)
    except places.PlaceError:
        raise Refused(f"{rel} が会社のフォルダの外を指しています（別名）。読みません")
    return rel, real


def parse_limit(text: str):
    m = _LIMIT.match(norm(text))
    if not m:
        return None
    return (m.group(2), int(m.group(1)))


def read_sheet(path: Path) -> list:
    """入力シートの行（画面の順番・画面・欄・種類・上限・担当者が入れる・値）。"""
    from lib import input_sheet

    _parts, _name, grid = input_sheet.read_grid(path.read_bytes())
    _head, cols = grid.header()

    def cell(col_name, r):
        col = cols.get(col_name)
        return grid.texts.get(f"{col}{r}", "") if col else ""

    rows = []
    for r, screen, field, staff in grid.field_rows():
        rows.append({
            "行": r,
            "画面の順番": cell("画面の順番", r).strip(),
            "画面": screen,
            "欄": field,
            "種類": cell("種類", r).strip(),
            "上限": parse_limit(cell("上限", r)),
            "担当者が入れる": staff,
            "値": cell(input_sheet.HEAD_VALUE, r),
        })
    return rows


def over_limit(row) -> str:
    """上限（目安でないもの）を超えていれば、その説明。"""
    from lib import input_sheet
    from lib.docx_min import clean_text

    limit = row["上限"]
    if not limit or row["種類"] not in TEXT_KINDS or row["担当者が入れる"]:
        return ""
    kind, chars = limit
    count = len(clean_text(row["値"]))
    if count > chars and kind in input_sheet.HARD_LIMITS:
        return f"{kind}は{chars}字で、値は{count}字です"
    return ""


def over_guide(row) -> str:
    limit = row["上限"]
    if not limit or row["種類"] not in TEXT_KINDS or row["担当者が入れる"]:
        return ""
    from lib import input_sheet
    from lib.docx_min import clean_text

    kind, chars = limit
    count = len(clean_text(row["値"]))
    if count > chars and kind not in input_sheet.HARD_LIMITS:
        return f"{kind}の{chars}字を超えています（{count}字）"
    return ""


def rows_of_screen(rows: list, screen: str) -> list:
    want = screen_key(screen)
    found = [r for r in rows if screen_key(r["画面"]) == want]
    if not found:
        names = []
        for r in rows:
            if r["画面"] not in names:
                names.append(r["画面"])
        raise Refused(f"入力シートに画面「{screen}」の欄がありません（ある画面：{'、'.join(names) or 'なし'}）")
    return found


# ---------------------------------------------------------------- 画面（read_page）

def latest_snapshot(folder: Path):
    """PostToolUse の hook が控えた、いちばん新しい読み取り（部品の控え）と、その時刻。"""
    from lib import browser_guard

    rel = f"{company.MARKER_DIR}/{company.TEMP_DIR}/{browser_guard.STATE_DIR}"
    top = places.actual(folder, rel)
    if top is None or not top.is_dir() or not places.is_inside(folder, top):
        return None, None
    best, best_time = None, -1
    for path in sorted(top.glob(f"*/{browser_guard.SNAPSHOT_FILE}")):
        if not places.is_inside(folder, path):
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        for snapshot in value.values():
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("elements"), dict):
                continue
            stamp = snapshot.get("time") if isinstance(snapshot.get("time"), int) else 0
            if stamp > best_time:
                best, best_time = snapshot["elements"], stamp
    return best, (best_time if best is not None else None)


def load_page(folder: Path, given):
    from lib import page_tree

    if given == "-":
        text = sys.stdin.read()
        elements = page_tree.parse(text)["elements"]
        if not elements:
            raise Refused("標準入力の文から、ページの部品を読み取れませんでした（read_page の結果をそのまま渡してください）")
        return page_tree.Page(elements), "標準入力の read_page の結果"
    if given:
        raise Refused("--page には「-」（標準入力）だけを渡せます")
    elements, stamp = latest_snapshot(folder)
    if not elements:
        raise Refused("画面の控えがありません。先にブラウザの道具でページを読んでください（read_page。filter は all）。"
                      "hook が動いていないときは、read_page の結果を --page - で標準入力から渡してください")
    return page_tree.Page(elements), "hook が控えた最後の読み取り"


def page_controls(page) -> list:
    """画面の欄（番号・役割・種類・名前・読み取れた値・照らす名前）を、ページの順に。"""
    from lib import browser_guard, page_tree

    out = []
    roles = page_tree.CHOICE_ROLES + page_tree.TEXT_ROLES
    for ref in sorted(page.elements, key=lambda r: page.elements[r].get("order", 0)):
        element = page.elements[ref]
        if element.get("role") not in roles and element.get("type") != "file":
            continue
        name = page.field_name(ref)
        out.append({
            "ref": ref,
            "role": element.get("role"),
            "type": element.get("type", ""),
            "name": name,
            "value": unescape(element.get("name") or ""),
            # 守りと同じ照らし方（名前の全文と、「：」より前の項目名）
            "keys": browser_guard._name_keys(name) if name else [],
        })
    return out


def headings(page) -> list:
    return [norm(e.get("name")) for e in page.elements.values() if e.get("role") == "heading"]


def match(row, controls: list) -> list:
    """入力シートの行に当たる画面の欄。"""
    roles = KIND_ROLES.get(row["種類"], ())
    field = norm(row["欄"])
    hits = []
    for c in controls:
        if row["種類"] == "添付":
            ok = c["type"] == "file"
        else:
            ok = c["role"] in roles and c["type"] not in ("password", "hidden", "file")
        if ok and field in c["keys"]:
            hits.append(c)
    return hits


def radio_choice(hits: list, value: str):
    want = norm(value)
    for c in hits:
        tail = c["name"].split("：", 1)[1] if "：" in c["name"] else ""
        if norm(tail) == want or norm(c["value"]) == want:
            return c
    return None


def prohibited_word(name: str):
    from lib import browser_guard

    compact = "".join(norm(name).split())
    for word in browser_guard.PROHIBITED_FIELD_WORDS:
        if word in compact:
            return word
    return None


# ---------------------------------------------------------------- 突き合わせ

def plan(rows: list, controls: list) -> dict:
    """画面の欄と入力シートを突き合わせ、入れる欄・入れない欄・担当者の欄・見当たらない欄を分ける。"""
    result = {"入れる": [], "値がない": [], "担当者が入れる": [], "見当たらない": [], "重なり": [],
              "入れられない": [], "画面だけにある": [], "添付": []}
    used = set()
    for row in rows:
        hits = match(row, controls)
        for c in hits:
            used.add(c["ref"])
        base = {"欄": row["欄"], "種類": row["種類"], "値": row["値"]}
        if row["担当者が入れる"]:
            result["担当者が入れる"].append({**base, "ref": [c["ref"] for c in hits], "理由": "入力シートで担当者が入れる欄"})
            continue
        word = prohibited_word(row["欄"]) if row["種類"] in ("チェック", "ラジオ", "選択") else None
        if word:
            result["担当者が入れる"].append({**base, "ref": [c["ref"] for c in hits],
                                        "理由": f"名前に「{word}」を含むので、ツールは入れない"})
            continue
        if not_applicable(row["値"]):
            # 会社に当てはまらない欄。空の欄と同じく、画面には触れない
            result["値がない"].append({**base, "理由": "該当なし"})
            continue
        if row["種類"] == "添付":
            result["添付"].append({**base, "ref": [c["ref"] for c in hits]})
            continue
        problem = over_limit(row)
        if problem:
            result["入れられない"].append({**base, "理由": problem})
            continue
        if norm(row["値"]) == "":
            result["値がない"].append(base)
            continue
        try:
            state = check_state(row["値"]) if row["種類"] == "チェック" else None
        except Refused as e:
            result["入れられない"].append({**base, "理由": str(e)})
            continue
        if not hits:
            result["見当たらない"].append(base)
            continue
        if row["種類"] == "ラジオ":
            choice = radio_choice(hits, row["値"])
            if choice is None:
                result["見当たらない"].append({**base, "理由": f"選ぶ項目「{row['値']}」が画面にありません"})
                continue
            result["入れる"].append({**base, "ref": choice["ref"], "form_input": True})
            continue
        if len(hits) > 1:
            result["重なり"].append({**base, "ref": [c["ref"] for c in hits]})
            continue
        value = state if row["種類"] == "チェック" else row["値"]
        entry = {**base, "ref": hits[0]["ref"], "form_input": value}
        guide = over_guide(row)
        if guide:
            entry["注意"] = guide
        result["入れる"].append(entry)
    for c in controls:
        if c["ref"] in used:
            continue
        word = prohibited_word(c["name"]) if c["role"] in KIND_ROLES["チェック"] + KIND_ROLES["ラジオ"] + KIND_ROLES["選択"] else None
        result["画面だけにある"].append({"ref": c["ref"], "名前": c["name"] or "（名前が読めない欄）", "役割": c["role"],
                                    "種類": c["type"], "担当者が入れる": bool(word) or c["type"] == "password"
                                    or not c["name"]})
    return result


def compare(rows: list, controls: list) -> dict:
    """入れた後の画面と入力シートを比べる。"""
    planned = plan(rows, controls)
    result = {"合う": [], "合わない": [], "見当たらない": planned["見当たらない"] + planned["重なり"],
              "担当者に確かめる": [], "担当者が入れる": planned["担当者が入れる"], "入れられない": planned["入れられない"],
              "値がない": planned["値がない"], "添付": planned["添付"]}
    by_ref = {c["ref"]: c for c in controls}
    for entry in planned["入れる"]:
        control = by_ref[entry["ref"]]
        kind = entry["種類"]
        if kind in ("チェック", "ラジオ"):
            if kind == "チェック":
                want = "チェックが入っている" if entry["form_input"] else "チェックが入っていない"
            else:
                want = f"「{entry['値']}」が選ばれている"
            result["担当者に確かめる"].append({**entry, "確かめること": want})
            continue
        seen = control["value"]
        if kind == "選択" and UNSELECTED.match(norm(seen)):
            seen = ""
        if values_match(kind, entry["値"], seen):
            result["合う"].append({**entry, "画面の値": seen})
        else:
            result["合わない"].append({**entry, "画面の値": seen})
    return result


def values_match(kind: str, want: str, seen: str) -> bool:
    a, b = norm(want), norm(seen)
    if a == b:
        return True
    # 改行や空白は、読み取りの結果で変わることがあるので除いて比べる
    a2, b2 = "".join(a.split()), "".join(b.split())
    if a2 == b2:
        return True
    if kind == "数字":
        strip = lambda t: unicodedata.normalize("NFKC", t).replace(",", "").replace("円", "")  # noqa: E731
        return strip(a2) == strip(b2)
    return False


# ---------------------------------------------------------------- 出し方

def show_value(value) -> str:
    if value is True:
        return "true（チェックを入れる）"
    if value is False:
        return "false（チェックを外す）"
    return json.dumps(value, ensure_ascii=False)


def print_list(screen: str, source: str, result: dict, warn: str) -> None:
    print(f"画面「{screen}」の入れる欄（入力シートの値。部品の番号は {source} のもの）")
    if warn:
        print(f"- 注意：{warn}")
    if result["入れる"]:
        for i, e in enumerate(result["入れる"], 1):
            note = f"（{e['注意']}）" if e.get("注意") else ""
            print(f"{i}. {e['欄']}（{e['種類']}）：{e['ref']} に form_input で {show_value(e['form_input'])}{note}")
    else:
        print("- ツールが入れる欄はありません。")
    sections = (
        ("値がない・該当なし（入れない）", "値がない", lambda e: e["欄"] + (f"（{e['理由']}）" if e.get("理由") else "")),
        ("担当者が入れる（ツールは入れない。入れるべき欄を担当者に示す）", "担当者が入れる",
         lambda e: f"{e['欄']}（{e['理由']}）"),
        ("入れられない（入力シートを直す）", "入れられない", lambda e: f"{e['欄']}：{e['理由']}"),
        ("入力シートにあって、画面に見当たらない", "見当たらない", lambda e: e["欄"] + (f"（{e['理由']}）" if e.get("理由") else "")),
        ("画面に同じ名前の欄が2つ以上ある（担当者に確かめる）", "重なり", lambda e: f"{e['欄']}（{'・'.join(e['ref'])}）"),
        ("添付の欄（Claude in Chrome は file_upload で写しを添付。内蔵ブラウザは担当者に頼む）", "添付",
         lambda e: f"{e['欄']}：{e['値'] or '（入力シートに書類の名前がない）'}"),
    )
    for title, key, fmt in sections:
        if result[key]:
            print(f"{title}：")
            for e in result[key]:
                print(f"- {fmt(e)}")
    extra = result.get("画面だけにある") or []
    if extra:
        print("画面にあって、入力シートにない欄（ツールは入れない）：")
        for e in extra:
            who = "担当者が入れる" if e["担当者が入れる"] else "入力シートを確かめる"
            print(f"- {e['名前']}（{e['ref']}・{e['役割']}。{who}）")


def print_check(screen: str, source: str, result: dict, warn: str) -> None:
    total = len(result["合う"]) + len(result["合わない"])
    print(f"画面「{screen}」を入力シートと照らしました（{source}）。")
    if warn:
        print(f"- 注意：{warn}")
    print(f"- 値で照らした欄 {total}：合う {len(result['合う'])}、合わない {len(result['合わない'])}。"
          f"画面に見当たらない {len(result['見当たらない'])}。入れられない {len(result['入れられない'])}。")
    for e in result["合わない"]:
        print(f"- 合わない：{e['欄']}（{e['ref']}）入力シート {json.dumps(e['値'], ensure_ascii=False)}、"
              f"画面 {json.dumps(e['画面の値'], ensure_ascii=False)}")
    for e in result["見当たらない"]:
        print(f"- 画面に見当たらない：{e['欄']}" + (f"（{e['理由']}）" if e.get("理由") else ""))
    for e in result["入れられない"]:
        print(f"- 入れられない：{e['欄']}：{e['理由']}")
    print("ツールが入れた欄（担当者に示す）：")
    for e in result["合う"] + result["合わない"]:
        print(f"- {e['欄']}：{e['値']}")
    if result["担当者に確かめる"]:
        print("チェック欄・ラジオボタン（入れた後の状態を読み取れないので、担当者に画面で確かめてもらう）：")
        for e in result["担当者に確かめる"]:
            print(f"- {e['欄']}：{e['確かめること']}")
    if result["担当者が入れる"]:
        print("担当者が入れる欄（ツールは入れていない）：")
        for e in result["担当者が入れる"]:
            print(f"- {e['欄']}（{e['理由']}）")
    if result["添付"]:
        print("添付の欄（添付した後は、画面を読み直してファイルの名前を確かめる）：")
        for e in result["添付"]:
            print(f"- {e['欄']}：{e['値'] or '（入力シートに書類の名前がない）'}")


# ---------------------------------------------------------------- 命令

def materials(folder: Path, args):
    case = find_case(folder, args.case)
    stage = find_stage(folder, case, args.stage)
    rel, path = sheet_path(folder, case, stage)
    return rel, read_sheet(path)


def screen_warning(page, screen: str) -> str:
    want = screen_key(screen)
    for name in headings(page):
        if want and want in screen_key(name):
            return ""
    return f"読んだ画面の見出しに「{screen}」が見当たりません。違う画面を読んでいないか確かめてください"


def do_sheet(folder: Path, args) -> int:
    rel, rows = materials(folder, args)
    screens = []
    for row in rows:
        key = (row["画面の順番"], row["画面"])
        if key not in [s["key"] for s in screens]:
            screens.append({"key": key, "画面": row["画面"], "順番": row["画面の順番"], "ツール": 0, "値がある": 0,
                            "担当者": 0})
        s = next(s for s in screens if s["key"] == key)
        if row["担当者が入れる"]:
            s["担当者"] += 1
        else:
            s["ツール"] += 1
            if norm(row["値"]):
                s["値がある"] += 1
    problems = []
    for row in rows:
        problem = over_limit(row)
        if not problem and row["種類"] == "チェック" and not row["担当者が入れる"]:
            try:
                check_state(row["値"])
            except Refused as e:
                problem = str(e)
        if problem:
            problems.append({"画面": row["画面"], "欄": row["欄"], "理由": problem})
    if args.json:
        print(json.dumps({"入力シート": rel, "画面": [{k: v for k, v in s.items() if k != "key"} for s in screens],
                          "入れられない": problems}, ensure_ascii=False, indent=1))
    else:
        print(f"{rel} の画面ごとの欄")
        for s in screens:
            print(f"- {s['順番']} {s['画面']}：ツールが入れる欄 {s['ツール']}（値がある {s['値がある']}）、"
                  f"担当者が入れる欄 {s['担当者']}")
        if problems:
            print("入れられない値（kaku の yoshiki.py sheet で直してから、画面に入れる）：")
            for p in problems:
                print(f"- {p['画面']}・{p['欄']}：{p['理由']}")
        else:
            print("- 文字数の上限を超える値と、書き方の分からない値はありません。")
    return MISMATCH if problems else OK


def do_list(folder: Path, args) -> int:
    _rel, rows = materials(folder, args)
    screen_rows = rows_of_screen(rows, args.screen)
    page, source = load_page(folder, args.page)
    result = plan(screen_rows, page_controls(page))
    warn = screen_warning(page, args.screen)
    if args.json:
        print(json.dumps({"画面": args.screen, "注意": warn, **result}, ensure_ascii=False, indent=1))
    else:
        print_list(args.screen, source, result, warn)
    bad = result["見当たらない"] or result["入れられない"] or result["重なり"]
    return MISMATCH if bad else OK


def do_check(folder: Path, args) -> int:
    _rel, rows = materials(folder, args)
    screen_rows = rows_of_screen(rows, args.screen)
    page, source = load_page(folder, args.page)
    result = compare(screen_rows, page_controls(page))
    warn = screen_warning(page, args.screen)
    if args.json:
        print(json.dumps({"画面": args.screen, "注意": warn, **result}, ensure_ascii=False, indent=1))
    else:
        print_check(args.screen, source, result, warn)
    bad = result["合わない"] or result["見当たらない"] or result["入れられない"]
    return MISMATCH if bad else OK


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
        from lib import browser_guard, input_sheet, page_tree  # noqa: F401
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return BROKEN
    handlers = {"sheet": do_sheet, "list": do_list, "check": do_check}
    try:
        return handlers[args.command](folder, args)
    except Refused as e:
        print(f"しませんでした：{e}。")
        return REFUSED
    except ValueError as e:  # 入力シートが読めない（FormError）など
        print(f"しませんでした：{e}。")
        return REFUSED
    except OSError as e:
        print(f"しませんでした：ファイルを読めませんでした（{e.strerror or e}）。")
        return REFUSED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
