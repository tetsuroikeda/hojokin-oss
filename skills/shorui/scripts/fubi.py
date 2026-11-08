"""書類の不備チェックの道具（SPEC F5「不備チェック」、DESIGN 6章・8.4。TASKS B12。T5-1・T5-2）。

使い方（する事の後に、--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/fubi.py rules --case <案件> [--stage 1_申請]
      不備チェックの物差しを出す：不備の型（同梱の知見 knowledge/不備の型.json）、その段階で集める書類の決まり
      （期数・有効期限・形式。制度データ）、補助の対象にならない経費の名前と資料のページ、過去の差し戻しの型（会社の記録）、
      今日の日付、交付決定の日（期限の台帳。まだならまだ）、金額の照合で外れた書類（記録/金額の読み取り.json）。
  python3 -B <この場所>/fubi.py check --case <案件> --input 記録/一時/書類の読み取り.json
      Claude が書類から読み取った項目（書類ごとの発行日・有効期限・期・社名・所在地・代表者・宛名・従業員数・発注日など）を
      コードで照らし、不備の候補（期限切れ・期数不足・名義の不一致・従業員数・事前着手・金額）を、重さと直し方つきで出す。何も書かない。
  python3 -B <この場所>/fubi.py record --case <案件> --input 記録/一時/不備.json
      不備の一覧を 記録/不備の一覧.json に残し、今の状態の画面（不備の数）を作り直す。すべての指摘に重さ（重大・要確認・助言）と
      直し方がないと残さない。
  python3 -B <この場所>/fubi.py list
      残した不備の一覧を出す。

- 解釈が要る不備（補助の対象にならない経費、宛名の書き違い、図面と見積書の食い違い など）は Claude が判断して record に入れる。
- 終了コード：0 できた、1 補助プログラムを読み込めない、2 しなかった（形が違う、案件がない など。何も書いていない）。
"""

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import calendar  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import tempfile  # noqa: E402
import unicodedata  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company  # noqa: E402

TYPES_FILE = PLUGIN_ROOT / "knowledge" / "不備の型.json"
RECORD_PATH = "記録/不備の一覧.json"
WEIGHTS = ("重大", "要確認", "助言")
NAME_KEYS = ("社名", "所在地", "代表者")


def nfc(text) -> str:
    return unicodedata.normalize("NFC", str(text or ""))


def squash(text) -> str:
    """名義を比べる形（空白・全角半角の違いをそろえる）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or "")))


def types() -> dict:
    data = json.loads(TYPES_FILE.read_text(encoding="utf-8"))
    return {t["id"]: t for t in data["型"]}


def finding(type_id: str, kind: str, documents, content: str, weight: str = "", fix: str = "", source: str = "") -> dict:
    t = types().get(type_id, {})
    return {"重さ": weight or t.get("重さ", "要確認"), "種類": kind,
            "書類": "、".join(documents) if isinstance(documents, (list, tuple)) else str(documents),
            "内容": content, "直し方": fix or t.get("直し方", ""), "型": type_id, "出典": source}


# ---- 物差し ----


def _seido(folder: Path, case: str):
    from lib import seido_data
    try:
        _path, data = seido_data.load_data(folder, case)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _sources(node) -> str:
    out = []
    for s in (node or {}).get("出典") or [] if isinstance(node, dict) else []:
        if isinstance(s, dict) and s.get("資料"):
            out.append(f"{s['資料']} p.{s['ページ']}" if s.get("ページ") else str(s["資料"]))
    return "、".join(out)


def _value(node):
    return node.get("値") if isinstance(node, dict) else node


def stage_procedure(seido: dict, stage: str) -> str:
    """段階のフォルダの名前（1_申請。効果報告の年は「4_効果報告/1年目」）から、制度データの「手続き」の言葉（段階の id）を出す。

    制度データの手続きの段階に、そのフォルダの名前の段階があれば、その id（採択後の段階も同じ。B31a）。なければ名前から推す。
    """
    folder = nfc(stage).strip().strip("/").split("/")[0]
    for s in (seido or {}).get("手続きの段階") or []:
        if isinstance(s, dict) and nfc(s.get("フォルダ")) == folder and s.get("id"):
            return nfc(s["id"])
    name = re.sub(r"^[0-9]+_", "", folder)
    if "申請" in name and "交付" not in name:
        return "応募申請"
    return name


def document_rules(seido: dict, stage: str) -> list:
    procedure = stage_procedure(seido, stage)
    out = []
    for d in seido.get("書類") or []:
        if not isinstance(d, dict):
            continue
        if procedure and d.get("手続き") and procedure not in d["手続き"]:
            continue
        item = {"名前": d.get("名前"), "区分": d.get("区分"), "出す人": d.get("出す人"), "発行元": d.get("発行元"),
                "形式": d.get("形式")}
        for key in ("期数", "有効期限", "取得の決まり"):
            if d.get(key):
                item[key] = _value(d[key])
                item[f"{key}の出典"] = _sources(d[key])
        out.append(item)
    return out


def excluded_costs(seido: dict) -> list:
    return [{"名前": x.get("名前"), "種類": x.get("種類"), "経費の区分": x.get("経費の区分"),
             "内容": _value(x.get("内容")), "出典": _sources(x.get("内容"))}
            for x in seido.get("補助の対象にならない経費") or [] if isinstance(x, dict)]


def past_defects(folder: Path) -> list:
    try:
        from lib import company_record
        data = company_record.load(folder)
        return [{k: v for k, v in item.items() if k in ("id", "案件", "手続きの段階", "内容", "原因", "次に注意する書類",
                                                         "照合の決まり")}
                for item in data.get("項目", []) if item.get("種類") == company_record.DEFECT]
    except Exception:
        return []


def decision_date(folder: Path, case: str):
    """交付決定の日（期限の台帳の出来事。確定・見込みとも）。なければ None。"""
    try:
        from lib import event_ledger
        data = event_ledger.load(folder)
    except Exception:
        return None
    for e in data.get(event_ledger.EVENTS_KEY) or []:
        if isinstance(e, dict) and "交付決定" in nfc(e.get("出来事") or e.get("名前")) and \
                (not e.get("案件") or nfc(e.get("案件")) == nfc(case)) and e.get("日付"):
            return str(e["日付"])[:10]
    return None


def amount_problems(folder: Path) -> list:
    try:
        from lib import kingaku
        data = kingaku.load(folder)
    except Exception:
        return []
    out = []
    for d in data.get("書類") or []:
        if d.get("状態") != kingaku.VERIFIED and d.get("照合", {}).get("外れ"):
            out.append({"原本": d.get("原本"), "外れ": [m.get("内容") for m in d["照合"]["外れ"]]})
    return out


# ---- コードで照らす ----


def parse_date(text):
    m = re.match(r"^\s*([0-9]{4})-([0-9]{2})-([0-9]{2})", str(text or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def add_months(d: date, months: int) -> date:
    year, month = divmod(d.month - 1 + months, 12)
    year, month = d.year + year, month + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _rule_for(rules: list, doc: dict):
    name = nfc(doc.get("制度データの書類") or doc.get("種類"))
    for r in rules:
        if nfc(r["名前"]) == name:
            return r
    for r in rules:
        if name and (name in nfc(r["名前"]) or nfc(r["名前"]).split("（")[0] in name):
            return r
    return None


def code_checks(docs: list, rules: list, today: date, decision, amounts: list) -> list:
    found = []
    label = {id(d): f"{d.get('種類') or ''}（{d.get('原本') or ''}）" for d in docs}
    # 期限切れ：書類の有効期限、制度データの「発行から N か月以内」
    for d in docs:
        until = parse_date(d.get("有効期限"))
        if until and until < today:
            found.append(finding("不備-01", f"{d.get('種類')}の有効期限が切れている", [label[id(d)]],
                                 f"有効期限 {until.isoformat()} が、今日（{today.isoformat()}）より前です"))
        rule = _rule_for(rules, d)
        issued = parse_date(d.get("発行日"))
        m = re.search(r"発行から\s*([0-9０-９]+)\s*か月", nfc((rule or {}).get("有効期限")))
        if rule and issued and m:
            months = int(unicodedata.normalize("NFKC", m.group(1)))
            last = add_months(issued, months)
            if last < today:
                found.append(finding("不備-01", f"{rule['名前']}が、発行から{months}か月を超えている", [label[id(d)]],
                                     f"発行日 {issued.isoformat()} から{months}か月は {last.isoformat()} までで、"
                                     f"今日（{today.isoformat()}）には切れています（{rule['有効期限']}）",
                                     source=rule.get("有効期限の出典", "")))
    # 期数不足：制度データの書類ごとに、そろった期を数える
    by_rule = {}
    for d in docs:
        rule = _rule_for(rules, d)
        if rule and rule.get("期数"):
            by_rule.setdefault(rule["名前"], (rule, []))[1].append(d)
    for name, (rule, items) in by_rule.items():
        try:
            need = int(rule["期数"])
        except (TypeError, ValueError):
            continue
        periods = set()
        for d in items:
            for p in d.get("期") or []:
                periods.add(squash(p))
        if len(periods) < need:
            found.append(finding("不備-02", f"{name}が直近{need}期そろっていない", [label[id(d)] for d in items],
                                 f"そろっている期は{len(periods)}期（{'・'.join(sorted(periods)) or 'なし'}）で、"
                                 f"{need}期が要ります", source=rule.get("期数の出典", "")))
    # 名義の不一致：登記（履歴事項全部証明書）の値を基準に、なければ多いほうを基準にする
    for key in NAME_KEYS:
        values = [(d, squash(d.get(key))) for d in docs if d.get(key)]
        if len(values) < 2:
            continue
        base_doc = next((d for d, _v in values if "履歴事項" in nfc(d.get("種類"))), None)
        if base_doc is not None:
            base = squash(base_doc.get(key))
        else:
            counts = {}
            for _d, v in values:
                counts[v] = counts.get(v, 0) + 1
            base = max(counts, key=lambda v: counts[v])
        for d, v in values:
            if v != base:
                found.append(finding("不備-03", f"{key}が書類によって違う（{d.get('種類')}）", [label[id(d)]],
                                     f"{key}が「{d.get(key)}」で、基準（{base_doc.get('種類') if base_doc else 'ほかの書類'}）の"
                                     f"「{base}」と違います"))
    # 見積書の宛名
    company_names = {squash(d.get("社名")) for d in docs if d.get("社名") and "履歴事項" in nfc(d.get("種類"))}
    for d in docs:
        if d.get("宛名") and company_names and squash(d["宛名"]).replace("御中", "") not in company_names:
            found.append(finding("不備-03", f"{d.get('種類')}の宛名が社名と違う", [label[id(d)]],
                                 f"宛名が「{d['宛名']}」で、登記の社名（{'・'.join(company_names)}）と違います"))
    # 従業員数
    counts = [(d, d.get("従業員数")) for d in docs if isinstance(d.get("従業員数"), int)]
    if len({c for _d, c in counts}) > 1:
        found.append(finding("不備-06", "従業員数が書類によって違う", [label[id(d)] for d, _c in counts],
                             "、".join(f"{d.get('種類')}は{c}人" for d, c in counts)))
    # 事前着手：補助事業の発注・契約が、交付決定より前
    for d in docs:
        ordered = parse_date(d.get("発注日") or d.get("契約日"))
        if not ordered or d.get("補助事業の経費") is False:
            continue
        if decision is None or ordered < parse_date(decision):
            when = f"交付決定（{decision}）より前" if decision else "まだ交付決定を受けていない時期"
            found.append(finding("不備-07", "交付決定より前に発注・契約している（事前着手）", [label[id(d)]],
                                 f"発注・契約の日 {ordered.isoformat()} は、{when}です"))
    # 金額の照合で外れた書類
    for a in amounts:
        found.append(finding("不備-04", "見積書・請求書の金額の計算が合わない", [a["原本"]], "。".join(a["外れ"])))
    return found


# ---- 記録 ----


def check_record(items: list) -> list:
    problems = []
    if not isinstance(items, list):
        return ["「不備」は [ ] の一覧にしてください"]
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            problems.append(f"{i}件目が {{ }} の形ではありません")
            continue
        if item.get("重さ") not in WEIGHTS:
            problems.append(f"{i}件目の重さ（{item.get('重さ')}）は、重大・要確認・助言のどれかにしてください")
        for key in ("種類", "書類", "直し方"):
            if not nfc(item.get(key)).strip():
                problems.append(f"{i}件目に「{key}」がありません（すべての指摘に重さと直し方を付けます）")
        for key, value in item.items():
            if isinstance(value, (dict, list)):
                problems.append(f"{i}件目の「{key}」は、文字にしてください（一覧で数えやすくするため）")
    return problems


def save_record(folder: Path, data: dict) -> None:
    from lib import place_text
    problem = place_text.write_problem(folder, RECORD_PATH, f"{RECORD_PATH} を書いていません")
    if problem:
        raise ValueError(problem)
    path = folder / RECORD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".不備の一覧_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_input(folder: Path, given: str):
    from lib import places
    try:
        path = places.resolve_inside(folder, given)
    except places.PlaceError:
        raise ValueError(f"{given} は会社のフォルダの外です。記録/一時/ に置いてください")
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{given} が JSON として読めません（{type(e).__name__}: {e}）")


def parse(argv):
    parser = argparse.ArgumentParser(description="書類の不備をコードで照らし、不備の一覧を残す")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    sub = parser.add_subparsers(dest="command")
    for name, text in (("rules", "不備チェックの物差しを出す"), ("check", "読み取った項目をコードで照らす"),
                       ("record", "不備の一覧を残す")):
        p = sub.add_parser(name, parents=[common], help=text)
        p.add_argument("--case", required=True, help="案件の名前")
        p.add_argument("--stage", default="1_申請", help="段階のフォルダ（1_申請 など）")
        if name != "rules":
            p.add_argument("--input", required=True, help="Claude が Write で置いた JSON（記録/一時/ の下）")
    sub.add_parser("list", parents=[common], help="残した不備の一覧を出す")
    return parser.parse_args(argv)


def main(argv) -> int:
    args = parse(argv)
    if not args.command:
        print("する事（rules・check・record・list）を指定してください。")
        return 2
    folder = company.company_folder(args.folder) if args.folder else company.company_folder()
    if folder is None:
        print(f"{args.folder or company.project_dir()} は会社のフォルダではありません（目印の .hojokin/ がありません）。何もしていません。")
        return 2
    try:
        from lib import dates
    except Exception as e:
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。何もしていません。")
        return 1
    try:
        if args.command == "list":
            path = folder / RECORD_PATH
            print(path.read_text(encoding="utf-8") if path.exists() else '{"不備": []}')
            return 0
        if not (folder / "案件" / args.case).is_dir():
            print(f"案件（{args.case}）のフォルダがありません。案件/ の下のフォルダの名前を渡してください。")
            return 2
        seido = _seido(folder, args.case)
        today = dates.today(folder)
        rules = document_rules(seido, args.stage)
        if args.command == "rules":
            t = json.loads(TYPES_FILE.read_text(encoding="utf-8"))
            out = {
                "今日": today.isoformat(),
                "交付決定の日": decision_date(folder, args.case) or "まだ（交付決定より前の発注・契約は、事前着手）",
                "重さの決め手": t["重さの決め手"],
                "不備の型": [{k: v for k, v in x.items() if k in ("id", "名前", "書類", "確かめること", "重さ", "見つけ方", "直し方")}
                          for x in t["型"]],
                "この段階で集める書類の決まり": rules,
                "補助の対象にならない経費": excluded_costs(seido),
                "過去の差し戻しの型": past_defects(folder),
                "金額の照合で外れた書類": amount_problems(folder),
            }
            if not seido:
                out["注意"] = "この案件の制度データが見つかりません。書類の期数・有効期限は、junbi で制度データを作ってから照らします"
            print(json.dumps(out, ensure_ascii=False, indent=1))
        elif args.command == "check":
            data = read_input(folder, args.input)
            docs = data.get("書類") if isinstance(data, dict) else data
            if not isinstance(docs, list) or not all(isinstance(d, dict) for d in docs):
                print("読み取りは {\"書類\": [ {…}, … ]} の形にしてください。")
                return 2
            found = code_checks(docs, rules, today, decision_date(folder, args.case), amount_problems(folder))
            print(json.dumps({"コードで見つけた不備の候補": found, "数": len(found),
                              "説明": "これに、解釈が要る不備（対象にならない経費、図面と見積書、税込と税抜の混在 など）を足し、"
                                      "record で残してください"}, ensure_ascii=False, indent=1))
        else:
            data = read_input(folder, args.input)
            items = data.get("不備") if isinstance(data, dict) else data
            problems = check_record(items)
            if problems:
                print("残していません：\n- " + "\n- ".join(problems))
                return 2
            numbered = [dict(item, 番号=f"指摘-{i:03d}", 直した=bool(item.get("直した"))) for i, item in enumerate(items, 1)]
            record = {
                "説明": "書類の不備の一覧（skills/shorui/scripts/fubi.py が書く）。重さは 重大・要確認・助言",
                "案件": args.case, "段階": args.stage,
                "確かめた日時": dates.now(folder).isoformat(timespec="seconds"),
                "確かめた書類": data.get("確かめた書類", []) if isinstance(data, dict) else [],
                "まだない書類": data.get("まだない書類", []) if isinstance(data, dict) else [],
                "数": {w: sum(1 for i in numbered if i["重さ"] == w) for w in WEIGHTS},
                "不備": numbered,
            }
            save_record(folder, record)
            refreshed = ""
            try:
                from lib import status_view
                refreshed = status_view.refresh_page(folder) or "今の状態の画面を作り直しました"
            except Exception as e:  # 画面は開いたときにも作り直されるので、止めない
                refreshed = f"今の状態の画面を作り直せませんでした（{type(e).__name__}）"
            print(json.dumps({"結果": f"不備の一覧を {RECORD_PATH} に残しました", "数": record["数"], "画面": refreshed},
                             ensure_ascii=False, indent=1))
    except ValueError as e:
        print(f"{e}")
        return 2
    except OSError as e:
        print(f"ファイルを扱えませんでした（{e}）。")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
