"""T12-1 採択後の通し（SPEC F12・T12-1、DESIGN 11章「複数回のやりとり」。TASKS B31b）。

日付を進めながら、省力化の交付申請 → 実績報告 → 効果報告1年目と、持続化の見積書等の提出 → 実績報告を、
会話を続けるテストの仕組み（tests/multiturn/run.py。claude -p と --resume、社長役は Haiku 5.5）で流す。

合格ライン（SPEC T12-1）：各段階で書類の一覧と不備チェックが動き、期限が示される。効果報告1年目の後に2年目の期限が示される。

- 始まりの状態：保存した状態「書く前」を戻し（evals/_lib/fukugen.py）、evals/_lib/saitakugo.py の「申請の後」を作る
  （省力化 第9回と持続化 第20回。どちらも申請の段階の提出版がある。今日 2026-12-20）。
- 場面ごとに、会社のフォルダの今日の日付を進め、通知の原本（testdata/期限 の架空の通知）を入れ口に入れ、前の場面で担当者が
  出した段階の提出版を記録してから（担当者が「提出した」と伝えたときと同じ道具）、社長の発言で会話を始める。
- 採点はコードで行う：その場面の会話の記録（Claude Code の会話のファイル）の Bash のコマンドに、段階の切り替えの道具
  （stage_switch.py）と不備チェックの道具（fubi.py）がその段階で動いた跡があり、応答に期限の日付があるか。
  書類の一覧は、段階の切り替えの道具の結果に必ず入るので、道具が動いたことで見る。
- 会話の記録と会社のフォルダは --out の下（リポの外）に置く。

使い方：
  python3 tests/multiturn/t12_1.py --out <リポの外の置き場> [--model sonnet] [--budget 2.0] [--only <場面の名前>]
- 終了コード：0 すべての場面が合格、1 合格しない場面があった、2 準備できなかった。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent.parent
EVALS_LIB = PLUGIN_ROOT / "evals" / "_lib"
NOTICES = PLUGIN_ROOT / "testdata" / "期限" / "材料" / "通知"
PY = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else sys.executable
CASE_1 = "2026_省力化（一般型）第9回"
CASE_2 = "2026_持続化（通常枠）第20回"

OWNER_RULES = """- 今日の日付は、ツールが示す日付のとおりです。
- 通知の日付を聞かれたら、入れ口に入れた通知のとおりに答えます。持続化の採択通知書の採択発表日は2027年3月12日、持続化の交付決定通知書の交付決定日は2027年4月23日、省力化の採択の通知の採択発表日は2027年4月16日、省力化の交付決定通知書の交付決定日は2027年6月25日です。
- 発注の日を聞かれたら：どちらも交付決定の後に発注しました。持続化は2027年5月10日、省力化の機械は2027年7月5日に発注しました。交付決定の前には、発注も契約も支払いもしていません。
- 事業が終わった日を聞かれたら：持続化は2028年1月31日に支払いまで全部済みました。省力化の機械も2028年1月31日に支払いまで済み、その日から使い始めました。
- 前の段階の書類は、担当者がもう出しました（提出したかを聞かれたら「出しました」）。省力化の交付申請は2027年5月28日、持続化の見積書等は2027年4月2日、省力化の実績報告は2028年2月20日、省力化の効果報告の1年目は2029年6月10日に出しました。
- 省力化は、2028年4月に補助金の額の確定の通知が届き、5月に補助金が入りました。2029年3月期の決算書は5月にできます。賃金台帳はすぐ出せます。
- 選択肢の画面で日付や進め方を確かめられたら、通知と上のとおりの日付で「はい」「その日付で合っています」を選びます。
- 書類を集めるのはこれからです。まだ手元にない書類は「まだありません」と答えます。
"""

# 場面ごと：今日、入れ口に入れる通知、前の場面で担当者が出した段階（案件・段階・出した日）、社長の発言、合格の条件。
# 合格の条件は、会社のフォルダの段階のフォルダ（段階の切り替えの道具が作る）、期限の台帳の出来事（案件・名前の一部・日付）、
# 会話の記録の Bash のコマンド（不備チェックの道具）、応答の文字（期限の日付）。
STEPS = [
    {"名前": "1_持続化の採択", "今日": "2027-03-15", "通知": ["持続化_第20回_採択通知書.pdf"], "出した": [],
     "発言": "持続化補助金の採択の通知が届いたので、入れ口に入れました。次の手続きに進めて、出す書類の一覧と期限を教えてください。書類に不備がないかも見てください。",
     "フォルダ": [f"案件/{CASE_2}/2_見積書等の提出"], "出来事": [], "道具": [r"fubi\.py"], "応答": [r"2028年2月29日"]},
    {"名前": "2_省力化の採択", "今日": "2027-04-20", "通知": ["省力化_第9回_採択の通知.pdf"],
     "出した": [(CASE_2, "2_見積書等の提出", "2027-04-02")],
     "発言": "今度は省力化補助金の採択の通知が届きました。入れ口に入れたので、交付申請に進めて、出す書類の一覧と期限を教えてください。不備がないかも見てください。",
     "フォルダ": [f"案件/{CASE_1}/2_交付申請"], "出来事": [(CASE_1, "採択発表", "2027-04-16")], "道具": [r"fubi\.py"],
     "応答": [r"2027年6月16日"]},
    {"名前": "3_交付決定", "今日": "2027-06-28",
     "通知": ["省力化_第9回_交付決定通知書.pdf", "持続化_第20回_交付決定通知書.pdf"],
     "出した": [(CASE_1, "2_交付申請", "2027-05-28")],
     "発言": "省力化の交付決定通知書が届きました。4月に届いていた持続化の交付決定通知書も、一緒に入れ口に入れました。どちらも交付決定の日を残して、これからの期限を教えてください。",
     "フォルダ": [], "出来事": [(CASE_1, "交付決定", "2027-06-25"), (CASE_2, "交付決定", "2027-04-23")], "道具": [],
     "応答": [r"2028年11月16日", r"2028年3月31日"]},
    {"名前": "4_両方の事業の完了", "今日": "2028-02-05", "通知": [], "出した": [],
     "発言": "持続化の事業も、省力化の機械も、2028年1月31日に支払いまで全部済みました（省力化の機械はその日から使っています）。どちらも実績報告に進めて、出す書類の一覧と期限を教えてください。不備がないかも見てください。",
     "フォルダ": [f"案件/{CASE_1}/3_実績報告", f"案件/{CASE_2}/3_実績報告"],
     "出来事": [(CASE_1, "完了", "2028-01-31"), (CASE_2, "終了", "2028-01-31")], "道具": [r"fubi\.py"],
     "応答": [r"2028年3月1日"]},
    {"名前": "5_省力化の効果報告1年目", "今日": "2029-04-03", "通知": [],
     "出した": [(CASE_1, "3_実績報告", "2028-02-20")],
     "発言": "省力化の効果報告の時期だと思います。効果報告に進めて、何をいつまでに出せばいいか教えてください。書類の不備も見てください。",
     "フォルダ": [f"案件/{CASE_1}/4_効果報告/1年目"], "出来事": [], "道具": [r"fubi\.py"], "応答": [r"2029年6月30日"]},
    {"名前": "6_効果報告1年目の後", "今日": "2029-07-10", "通知": [], "出した": [(CASE_1, "4_効果報告/1年目", "2029-06-10")],
     "発言": "省力化の効果報告の1年目を出しました。次の効果報告の期限はいつですか。",
     "フォルダ": [], "出来事": [], "道具": [], "応答": [r"2年目", r"2030年4月1日"]},
]


def prepare(folder: Path) -> None:
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for args in (["fukugen.py", "書く前", str(folder)], ["saitakugo.py", "申請の後", str(folder)]):
        done = subprocess.run([PY, "-B", str(EVALS_LIB / args[0]), *args[1:]], capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"{args[0]}：{done.stderr.strip()}")


def before_step(folder: Path, step: dict) -> None:
    """今日を進め、前の場面で出した段階の提出版を残し、通知を入れ口に入れる（製品の道具で）。"""
    code = ("import sys, json; sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2]);"
            "import saitakugo as s; from pathlib import Path; f = Path(sys.argv[3]);"
            "[(s.set_today(f, d), s.submit(f, c, st)) for c, st, d in json.loads(sys.argv[5])];"
            "s.set_today(f, sys.argv[4])")
    done = subprocess.run([PY, "-B", "-c", code, str(PLUGIN_ROOT), str(EVALS_LIB), str(folder), step["今日"],
                           json.dumps(step["出した"], ensure_ascii=False)], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"場面の準備（{step['名前']}）：{done.stderr.strip()[-800:]}")
    inbox = folder / "入れ口"
    inbox.mkdir(exist_ok=True)
    for name in step["通知"]:
        shutil.copyfile(NOTICES / name, inbox / name)


def transcript_commands(session: str) -> List[str]:
    """Claude Code の会話のファイル（~/.claude/projects/ の下）から、Bash のコマンドを集める。"""
    found = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{session}.jsonl"))
    commands = []
    for path in found:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            content = ((item.get("message") or {}).get("content")) if isinstance(item, dict) else None
            for part in content if isinstance(content, list) else []:
                if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("name") == "Bash":
                    commands.append(str((part.get("input") or {}).get("command") or ""))
    return commands


def ledger_events(folder: Path) -> List[dict]:
    path = folder / "記録" / "期限の台帳.json"
    try:
        return [e for e in json.loads(path.read_text(encoding="utf-8")).get("出来事") or [] if isinstance(e, dict)]
    except (OSError, ValueError):
        return []


def judge(step: dict, out: Path, folder: Path) -> Dict:
    summary = json.loads((out / "まとめ.json").read_text(encoding="utf-8"))
    log = [json.loads(x) for x in (out / "会話.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    replies = "\n".join(item["文"] for item in log if item["だれ"] == "ツール" and item["種類"] == "応答")
    commands = transcript_commands(summary.get("セッション") or "") if summary.get("セッション") else []
    joined = "\n".join(c.replace("\n", " ") for c in commands)
    tools = {p: bool(re.search(p, joined)) for p in step["道具"]}
    texts = {p: bool(re.search(p, replies)) for p in step["応答"]}
    folders = {p: (folder / p).is_dir() for p in step["フォルダ"]}
    events = ledger_events(folder)
    marks = {f"{c}／{n}／{d}": any(e.get("案件") == c and n in str(e.get("名前")) and e.get("日付") == d for e in events)
             for c, n, d in step["出来事"]}
    ok = all(tools.values()) and all(texts.values()) and all(folders.values()) and all(marks.values())
    return {"場面": step["名前"], "合格": ok, "段階のフォルダ": folders, "期限の台帳の出来事": marks,
            "道具": tools, "応答": texts, "道具のコマンドの数": len(commands), "費用": summary.get("費用"),
            "止まった": summary.get("止まった")}


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description="T12-1 採択後の通しを、会話を続けるテストの仕組みで流す")
    p.add_argument("--out", required=True, help="記録と会社のフォルダの置き場（リポの外）")
    p.add_argument("--model", default="sonnet")
    p.add_argument("--budget", type=float, default=2.0, help="試す側の1回の費用の上限（USD）")
    p.add_argument("--turns", type=int, default=4)
    p.add_argument("--only", help="この名前の場面まで（それより前の場面も流す）")
    p.add_argument("--start", help="この名前の場面から続ける（前に流した会社のフォルダと結果を使い、準備をしない）")
    args = p.parse_args(argv)
    out = Path(args.out).resolve()
    if str(out).startswith(str(PLUGIN_ROOT)):
        print("--out はリポの外にしてください", file=sys.stderr)
        return 2
    folder = out / "やまぶき惣菜"
    names = [s["名前"] for s in STEPS]
    if args.start and args.start not in names:
        print(f"--start は場面の名前（{'・'.join(names)}）にしてください", file=sys.stderr)
        return 2
    results = []
    if args.start:
        old = out / "結果.json"
        kept = json.loads(old.read_text(encoding="utf-8")) if old.exists() else []
        results = [r for r in kept if r.get("場面") in names[:names.index(args.start)]]
    else:
        try:
            prepare(folder)
        except Exception as error:
            print(f"準備できませんでした：{error}", file=sys.stderr)
            return 2
    rules = out / "台本の決まり.md"
    rules.write_text(OWNER_RULES, encoding="utf-8")
    for step in STEPS[names.index(args.start) if args.start else 0:]:
        try:
            before_step(folder, step)
        except Exception as error:
            results.append({"場面": step["名前"], "合格": False, "止まった": str(error)})
            break
        step_out = out / step["名前"]
        if step_out.exists():
            shutil.rmtree(step_out)
        subprocess.run([sys.executable, str(HERE / "run.py"), "--folder", str(folder), "--first", step["発言"],
                        "--turns", str(args.turns), "--out", str(step_out), "--rules", str(rules),
                        "--model", args.model, "--budget", str(args.budget)], text=True)
        result = judge(step, step_out, folder)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))
        if args.only and step["名前"] == args.only:
            break
    (out / "結果.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    passed = sum(1 for r in results if r["合格"])
    print(f"T12-1：{passed}/{len(STEPS)} 場面が合格")
    return 0 if passed == len(STEPS) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
