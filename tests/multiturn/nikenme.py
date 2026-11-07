"""2件目（持続化）の初稿までの会話を、記録あり・なしで流した結果を調べる（TASKS B7・B4・B5 の2件目の部分）。

会話は tests/multiturn/run.py で流す（社長役は回答表と 台本_2件目.md だけを見て答える）。この道具はモデルを使わず、
run.py の記録（会話.jsonl・道具と確かめの画面.jsonl）と、流した後の会社のフォルダを読んで、次を確かめる。

- T13-2 二度聞かない：記録ありで、初稿までの質問のうち、1件目で答えた事実の聞き直しが0件。
  変わりうる情報の確かめ（「前回は◯でしたが、変わりましたか」）は、聞き直しに数えない。
- T13-3 すばやく反映：記録ありの初稿までの質問の数が、なしの半分以下（仮）。記録にある関連する強み・事実が初稿に入る。
- 2件目への反映（1件目で学んだこと）：T13-6（「14社」「高齢者向け」が出ない、締めくくりに「まちの台所」、強みの段落を
  病院・介護施設向けとスーパー向けに分ける）、T13-7（「今回だけ」の「やまぶき惣菜は」が出ない、金額は万円）、
  T13-14（社長が Word で直す前の「きめ細かな対応」が出ない）。

数え方（決めたこと。SPEC・DESIGN にない細部）：
- 質問：選択肢の画面の問いの数と、応答の「【質問】」の番号つきの行（hooks/shitsumon_hooks.py の from_text と同じ読み方）。
- 初稿まで：初めて申請書に書いた呼び出し（Bash で yoshiki.py の write・sheet・cells、または申請書/ への Write・Edit。
  run.py の is_draft）より前の呼び出しの質問。
  初稿に届かなければ、全部の質問（記録なしの側では、届く前に半分の線を超えていれば、それで足りる）。
- 確かめ：「前回」「変わりましたか」「変わっていませんか」「のままで」などを含む問い。
- 聞き直し：確かめでなく、1件目で答えた事実の語（KNOWN）を含み、2件目のことの語（NEW）を含まない問い。目安なので、
  結果には問いごとの分け方を並べ、人が見て確かめられるようにする。
- 初稿の文：2件目の案件の入力シート.xlsx の「経営計画入力」「補助事業計画入力」の画面の値（lib/input_sheet.py で読む）。
- T13-3 の質問の数：初稿までに聞いた質問に、初稿に残った【空欄】【仮】の数を足したもの（初稿を仕上げるのに要る質問）。
  kaku は答えを待つ間にも【空欄】【仮】で下書きを書くので、聞いた数だけでは、記録がなく空欄だらけの初稿のほうが少なく見えるため。

使い方：
  python3 tests/multiturn/nikenme.py --with-out <記録ありの run.py の --out> --with-folder <記録ありの会社のフォルダ>
      [--without-out <記録なしの --out> --without-folder <記録なしの会社のフォルダ>] [--json]
- 終了コード：0 すべて合格、1 合格しないものがある、2 使い方の誤り・読めない。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
if str(PLUGIN_ROOT / "hooks") not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))

SECOND_CASE = "2026_持続化（通常枠）第20回"
PLAN_SCREENS = ("経営計画入力", "補助事業計画入力")
CONFIRM = re.compile(r"前回|変わりましたか|変わっていませんか|変わりはありませんか|変わりないですか|のままで|今も同じ|お変わり|変更はありますか|変わった")
# 1件目で答えた事実の語（回答表の A〜H・J・K 節。会社の記録に入っている）
KNOWN = {
    "従業員の数": r"従業員の?数|従業員数|何人|人数",
    "資本金": r"資本金",
    "設立": r"設立|創業",
    "所在地": r"所在地|住所|郵便番号",
    "決算の数字": r"売上高|売上総利益|経常利益|営業利益|直近.{0,6}売上|決算",
    "業種": r"業種",
    "代表者・役員": r"代表者|役員",
    "取引先": r"取引先",
    "強み": r"強み",
    "法人番号": r"法人番号",
    "インボイス": r"インボイス|登録番号|適格請求書",
    "連絡先": r"電話番号|ホームページ|URL|メール",
    "商品と品数": r"主な商品|品目|品数",
    "工場と設備": r"工場|設備",
    "GビズID": r"Gビズ|ＧビズID|GビズID",
    "過去の補助金": r"過去.{0,10}(補助金|申請)|申請したこと",
    "賃金": r"賃金|時給|給与|賃上げ|昇給",
}
# 2件目のこと（回答表の I 節）を聞く問いの語。これを含む問いは、聞き直しに数えない
NEW = r"冷凍|ネット|ショップ|通販|直売|展示会|パッケージ|ロゴ|チラシ|販路|今回の(取り組み|事業)|補助事業|持続化|見積|経費|売り始め|新しい商品|自社ブランド|急速冷凍"
STRENGTH = r"細かい注文|やわらか食|減塩|きざみ|ペースト"
FACTS = r"15\s*人|大田区|3\s*社|14\s*店|40\s*品目|3,?500\s*パック|20,?160\s*万円|2億160万円|201,?600"
HALF = 0.5  # T13-3 の「なしの半分以下（仮）」
OPEN = re.compile(r"【\s*(空欄|仮)")  # 初稿に残った、社長に聞かないと埋まらない所（kaku の仮の印と空欄）


def read_jsonl(path: Path) -> List[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def draft_call(tool_log: List[dict]) -> Optional[int]:
    """初めて申請書（様式・入力シート、または申請書/ の中の文書）に書いた呼び出しの番号（なければ None）。"""
    import run

    current = 0
    for row in tool_log:
        if row.get("場面") == "呼び出し":
            current = int(row.get("番") or 0)
            continue
        if row.get("場面", "PreToolUse") == "PreToolUse" and run.is_draft(row):
            return current
    return None


def questions(conversation: List[dict], before: Optional[int]) -> List[dict]:
    """初稿まで（before の呼び出しより前）の質問。{"呼び出し", "経路", "問い"} の一覧。"""
    import shitsumon_hooks

    out = []
    for item in conversation:
        if item.get("だれ") != "ツール":
            continue
        call = int(item.get("呼び出し") or 0)
        if before is not None and call >= before:
            continue
        if item.get("種類") == "選択肢の画面":
            try:
                asked = json.loads(item.get("文") or "[]")
            except ValueError:
                asked = []
            for q in asked:
                out.append({"呼び出し": call, "経路": "選択肢の画面", "問い": str(q.get("question") or "")})
        elif item.get("種類") == "応答":
            for q in shitsumon_hooks.from_text(item.get("文") or ""):
                out.append({"呼び出し": call, "経路": "【質問】", "問い": str(q.get("問い") or "")})
    return out


def classify(question: str) -> str:
    """確かめ・聞き直し・新しいこと のどれか（目安）。"""
    if CONFIRM.search(question):
        return "確かめ"
    if re.search(NEW, question):
        return "新しいこと"
    for _name, pattern in KNOWN.items():
        if re.search(pattern, question):
            return "聞き直し"
    return "新しいこと"


def plan_text(folder: Path, case: str = SECOND_CASE) -> Dict[str, str]:
    """2件目の入力シートの、計画の画面の欄の値（欄の名前 → 値）。なければ空。"""
    sheet = folder / "案件" / case / "1_申請" / "申請書" / "入力シート.xlsx"
    if not sheet.is_file():
        return markdown_text(sheet.parent)
    from lib import input_sheet

    _parts, _name, grid = input_sheet.read_grid(sheet.read_bytes())
    _head, cols = grid.header()
    values: Dict[str, str] = {}
    for row, screen, field, _staff in grid.field_rows():
        if not any(s in screen for s in PLAN_SCREENS):
            continue
        value = grid.texts.get(f"{cols[input_sheet.HEAD_VALUE]}{row}", "").strip()
        if value and not input_sheet.is_not_applicable(value):
            values[f"{screen}：{field}"] = value
    return values


def markdown_text(folder: Path) -> Dict[str, str]:
    """入力シートがないときの代わり：申請書/ の Markdown・文字のファイルを、見出し（## ）ごとの文にする。
    kaku は画面の様式の本文も入力シートに書く決まり（SKILL.md）なので、これで読んだときは結果に「入力シートでない」と出す。"""
    values: Dict[str, str] = {}
    if not folder.is_dir():
        return values
    for path in sorted(folder.glob("*.md")) + sorted(folder.glob("*.txt")):
        heading, lines = path.stem, []
        for line in path.read_text(encoding="utf-8").splitlines() + ["## （終わり）"]:
            if line.startswith("## "):
                body = "\n".join(lines).strip()
                if body and not heading.startswith("（"):
                    values[f"Markdown：{heading}"] = body
                heading, lines = line[3:].strip(), []
            elif not line.startswith("# "):
                lines.append(line)
    return values


def _paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n+", text) if p.strip()]


def reflect(values: Dict[str, str]) -> Dict[str, dict]:
    """2件目の初稿に、1件目で学んだことが入っているか（T13-6・T13-7・T13-14）。"""
    body = "\n".join(values.values())
    strength = "\n".join(v for k, v in values.items() if "強み" in k)
    paras = _paragraphs(strength)
    hospital_only = [p for p in paras if re.search(r"病院|介護", p) and "スーパー" not in p]
    super_only = [p for p in paras if "スーパー" in p and not re.search(r"病院|介護", p)]
    amounts = re.findall(r"[0-9０-９][0-9０-９,，.]*\s*(千円|万円|億円|円)", body)
    names = [k for k in values if re.search(r"事業者名|法人名|名称|屋号", k)]
    texts = []
    for k, v in values.items():
        if k in names:
            continue
        if "概要" in k:  # 概要の欄の最初の文で会社を名乗るのは、ふだんの書き方（「今回だけ」の指示が残ったものと見ない）
            v = re.split(r"(?<=。)", v, maxsplit=1)[-1] if "。" in v else ""
        texts.append(v)
    company_as_subject = re.findall(r"やまぶき惣菜(は|が)", "\n".join(texts))
    last = list(values.values())[-1] if values else ""
    checks = {
        "T13-6 数字（14社が出ない）": {"合格": "14社" not in body},
        "T13-6 表現（高齢者向けが出ない）": {"合格": "高齢者向け" not in body},
        "T13-6 方針（まちの台所に触れる）": {"合格": "まちの台所" in body, "締めくくりの欄にある": "まちの台所" in last},
        "T13-6 構成（強みの段落を分ける）": {"合格": bool(hospital_only and super_only), "段落の数": len(paras)},
        "T13-7 今回だけ（やまぶき惣菜は・が が出ない）": {"合格": not company_as_subject, "出た数": len(company_as_subject)},
        "T13-7 どちらとも（金額は万円）": {"合格": bool(amounts) and "千円" not in amounts and "円" not in amounts,
                                   "金額の単位": sorted(set(amounts))},
        "T13-14 手直し（きめ細かな対応が出ない）": {"合格": not re.search(r"きめ細[かや]", body)},
    }
    return checks


def summarize(out: Path, folder: Path) -> dict:
    conversation = read_jsonl(out / "会話.jsonl")
    tool_log = read_jsonl(out / "道具と確かめの画面.jsonl")
    if not conversation:
        raise ValueError(f"{out}/会話.jsonl がありません（run.py の --out を渡してください）")
    draft = draft_call(tool_log)
    asked = questions(conversation, draft)
    for q in asked:
        q["分け方"] = classify(q["問い"])
    values = plan_text(folder)
    summary = json.loads((out / "まとめ.json").read_text(encoding="utf-8")) if (out / "まとめ.json").is_file() else {}
    marks = sum(len(OPEN.findall(v)) for v in values.values())
    return {"初稿を書いた呼び出し": draft, "初稿に届いた": draft is not None, "質問": asked, "質問の数": len(asked),
            "初稿に残った印": marks, "初稿までに要る質問": len(asked) + marks,
            "聞き直し": sum(1 for q in asked if q["分け方"] == "聞き直し"),
            "確かめ": sum(1 for q in asked if q["分け方"] == "確かめ"),
            "初稿の欄": len(values), "入力シートでない": any(k.startswith("Markdown：") for k in values),
            "初稿": values, "費用": summary.get("費用", {})}


def judge(with_side: dict, without_side: Optional[dict]) -> dict:
    body = "\n".join(with_side["初稿"].values())
    result = {
        # 初稿の会社の紹介には従業員の数などの変わりうる情報を必ず使うので、使い回す前の確かめが1つはあること
        "T13-2 二度聞かない": {"合格": with_side["初稿に届いた"] and with_side["聞き直し"] == 0 and with_side["確かめ"] >= 1,
                         "聞き直し": with_side["聞き直し"], "確かめ": with_side["確かめ"]},
        "T13-3 強み・事実が初稿に入る": {"合格": bool(re.search(STRENGTH, body)) and bool(re.search(FACTS, body)),
                                "強み": sorted(set(re.findall(STRENGTH, body))),
                                "事実": sorted(set(m.group(0) for m in re.finditer(FACTS, body)))},
    }
    if without_side is not None:
        limit = without_side["初稿までに要る質問"] * HALF
        result["T13-3 質問の数（なしの半分以下）"] = {
            "合格": with_side["初稿に届いた"] and with_side["初稿までに要る質問"] <= limit,
            "記録あり": f"{with_side['初稿までに要る質問']}（聞いた {with_side['質問の数']}・残った印 {with_side['初稿に残った印']}）",
            "記録なし": f"{without_side['初稿までに要る質問']}（聞いた {without_side['質問の数']}・残った印 "
                    f"{without_side['初稿に残った印']}）",
            "記録なしは初稿に届いた": without_side["初稿に届いた"]}
    result.update(reflect(with_side["初稿"]))
    return result


def main(argv: List[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="2件目の初稿までの会話を、記録あり・なしで比べる（T13-2・T13-3・2件目への反映）")
    p.add_argument("--with-out", required=True)
    p.add_argument("--with-folder", required=True)
    p.add_argument("--without-out")
    p.add_argument("--without-folder")
    p.add_argument("--json", action="store_true")
    try:
        args = p.parse_args(argv)
    except SystemExit:
        return 2
    try:
        with_side = summarize(Path(args.with_out), Path(args.with_folder))
        without_side = summarize(Path(args.without_out), Path(args.without_folder)) if args.without_out else None
    except (OSError, ValueError) as e:
        print(f"読めませんでした：{e}")
        return 2
    verdict = judge(with_side, without_side)
    report = {"判定": verdict, "記録あり": with_side, "記録なし": without_side}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for name, v in verdict.items():
            print(f"{'合格' if v['合格'] else '不合格'}：{name} {json.dumps({k: x for k, x in v.items() if k != '合格'}, ensure_ascii=False)}")
        for side, data in (("記録あり", with_side), ("記録なし", without_side)):
            if data is None:
                continue
            print(f"\n## {side}：質問 {data['質問の数']}（初稿に届いた：{data['初稿に届いた']}）")
            for q in data["質問"]:
                print(f"- [{q['分け方']}] 呼び出し{q['呼び出し']}・{q['経路']}：{q['問い']}")
    return 0 if all(v["合格"] for v in verdict.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
