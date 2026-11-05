"""段階ごとに保存した会社のフォルダを、今いるフォルダ（eval の作業フォルダ）に戻す（TASKS M13、DESIGN 11章）。

使い方（ケースの scaffold.sh が evals/_lib/fukugen.sh から呼ぶ）：
  /usr/bin/python3 -B evals/_lib/fukugen.py <段階>          今いるフォルダに戻す
  /usr/bin/python3 -B evals/_lib/fukugen.py <段階> <フォルダ>  そのフォルダに戻す（tests/test_evals_fukugen.py）

保存した状態は2つに分けて置く（公開のリポジトリに、公式資料とその写しを入れないため。CLAUDE.md、DESIGN 11章）。
- `evals/状態/<段階>/`：作り直せないものだけ。社長から受け取った原本（架空のデモの会社の書類）、会社の記録、
  書類の台帳、補助金の候補.docx など。保存したときの会社のフォルダの中の場所のまま置く。
- `evals/状態/<段階>.json`（戻し方）：作り直すものの材料。今日の日付、制度データの元（リポにある正解）、
  取る資料の一覧と downloads/ のファイルの対応、段階のフォルダ、概要と流れ.docx に渡す説明の文。
  「保存した状態」があれば、その段階の保存したものを使い回し、「除くもの」で始まる場所は写さない
  （例：「書類の前」は「書く前」から原本と書類の台帳を除いたもの。TASKS B9）。

戻す順番（製品の道具をそのまま使う。社長が使うときと同じ形にするため）：
1. 会社のフォルダを用意する（lib/company_init.py。目印・フォルダの形・設定・送り先のない版の履歴）。
2. 保存したもの（原本・記録など）を写し、今日の日付を差し替える。原本は製品と同じく読み取り専用にする。
3. 制度データを置く。保存した状態には読み取り役が作った制度データを入れない（資料の文を写した値が多いため）。
   代わりに、リポにある正解（testdata/正解/。資料の文を写さない形）を置く。
4. 原本の控え（.hojokin/一時/原本の印.json）を、書類を整理する道具と同じ形で作る（中身を版の履歴に預ける）。
5. 公式資料を、取る道具（lib/official_docs.py の fetch_all）で置く。通信の代わりに downloads/ から写す。
   ページごとの文字（記録/資料の本文/）と資料の一覧も、この道具が作る。
6. 段階のフォルダを、制度データの手続きの段階から作る（lib/seido_data.py）。
7. 概要と流れ.docx を、作る道具（skills/junbi/scripts/gaiyou_word.py）で作る。
8. ここまでを「ツール」の版として1件、版の履歴に残す（lib/history.py）。開いたときに、社長が手で変えたものに数えないため。
9. 戻した形を確かめる（公式資料の数、資料の本文、版の履歴に残っていないものがないか）。

- 版の履歴は、保存したときのもの（何件もの版）は戻さない。公式資料が入っているため。戻した状態の版は1件になる。
  前の版を使うケース（T0-9 など）は、ケースの scaffold で版を足す。
- 標準のライブラリと、プラグインの lib/ だけで動く（/usr/bin/python3 の 3.9 でも動く書き方にする）。
- 終了コード：0 戻した。1 戻せなかった（理由を標準エラーに書く）。
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.dont_write_bytecode = True

LIB_DIR = Path(__file__).resolve().parent
EVALS_DIR = LIB_DIR.parent
PLUGIN_ROOT = EVALS_DIR.parent
STATES_DIR = EVALS_DIR / "状態"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

READ_ONLY = 0o444
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
REASON = "保存した状態（{stage}）から戻した"


class RestoreError(Exception):
    """戻せなかった。"""


def find_downloads(start: Path) -> Path:
    """上へたどって downloads/ を探す（worktree でも元のフォルダでも見つかるように。実験 E3）。"""
    here = start.resolve()
    for folder in [here] + list(here.parents):
        if (folder / "downloads").is_dir():
            return folder / "downloads"
    raise RestoreError(f"downloads/ が見つかりません（{start} から上へたどった）。先に公式資料を downloads/ に取ってください")


def saved_dir(stage: str, recipe: Dict) -> Path:
    """保存したものの置き場。戻し方に「保存した状態」があれば、その段階のもの（ほかの段階のものを使い回す。TASKS B9）。"""
    return STATES_DIR / recipe.get("保存した状態", stage)


def load_recipe(stage: str) -> Dict:
    path = STATES_DIR / f"{stage}.json"
    if not path.is_file():
        raise RestoreError(f"保存した状態「{stage}」がありません（{path} が要る）")
    recipe = json.loads(path.read_text(encoding="utf-8"))
    saved = saved_dir(stage, recipe)
    # 作り直せないものがない段階（「もと」の段階の上に製品の道具で作るもの。書いた後）は、保存したものを持たない
    if not saved.is_dir() and not recipe.get("もと"):
        raise RestoreError(f"保存した状態「{stage}」の保存したもの（{saved}/）がありません")
    return recipe


def local_downloader(downloads: Path, files: Dict[str, str]):
    """通信の代わりに downloads/ から写す downloader（lib/official_docs.py の fetch_all に渡す）。"""

    def download(url: str, dest: Path) -> str:
        rel = files.get(url)
        if not rel:
            raise OSError(f"downloads/ のどのファイルに当たるかが、戻し方にありません（{url}）")
        source = downloads / rel
        if not source.is_file():
            raise OSError(f"downloads/{rel} がありません（{url}）")
        shutil.copyfile(str(source), str(dest))
        return CONTENT_TYPES.get(source.suffix.lower(), "application/octet-stream")

    return download


def _copy_saved(saved: Path, target: Path, skip: tuple = ()) -> List[str]:
    """保存したものを写す（skip で始まる場所は写さない）。写したファイルの場所（会社のフォルダから）を返す。"""
    copied = []
    for path in sorted(saved.rglob("*")):
        if path.is_dir() or path.name == ".DS_Store":
            continue
        rel = path.relative_to(saved)
        if rel.as_posix().startswith(skip):
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(path), str(dest))
        copied.append(rel.as_posix())
    return copied


def _remember_originals(target: Path) -> int:
    """書類の台帳の原本を、整理する道具と同じく、読み取り専用にして版の履歴に預け、控えに残す。"""
    from lib import official_docs, protected_store, seiri

    ledger_file = target / seiri.LEDGER_PATH
    if not ledger_file.exists():
        return 0
    ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
    count = 0
    for entry in ledger.get(seiri.ORIGINALS_KEY, []):
        rel = entry.get("場所")
        path = target / rel
        if not path.is_file():
            raise RestoreError(f"書類の台帳にある原本が、保存した状態にありません（{rel}）")
        digest = official_docs.sha256_of(path)
        if digest != entry.get("ハッシュ"):
            raise RestoreError(f"保存した原本の中身が、書類の台帳のハッシュと合いません（{rel}）")
        path.chmod(READ_ONLY)
        blob = protected_store.store(target, path)
        protected_store.remember(target, rel, digest, blob, protected_store.ORIGINAL)
        count += 1
    return count


def _place_official(target: Path, downloads: Path, item: Dict) -> int:
    """公式資料を取る道具で置く（通信の代わりに downloads/ から写す）。置いた資料の数を返す。"""
    from lib import official_docs

    data = json.loads((PLUGIN_ROOT / item["取る資料"]).read_text(encoding="utf-8"))
    if item.get("案件の回"):
        data["制度"] = dict(data["制度"], 公募回=item["案件の回"])
    data["案件の名前"] = item["案件"]
    result = official_docs.fetch_all(target, data, downloader=local_downloader(downloads, item["ファイル"]))
    if not result.complete:
        broken = [f"{r.doc['id']}：{r.status} {r.message} {r.text_error}".strip() for r in result.docs
                  if r.status not in (official_docs.GOT, official_docs.SAME) or r.text_error]
        raise RestoreError("公式資料がそろいませんでした（" + "、".join(broken) + "）")
    return len(result.docs)


def _make_stages(target: Path, item: Dict) -> None:
    from lib import seido_data

    data = json.loads((target / item["制度データ"]).read_text(encoding="utf-8"))
    seido_data.make_stage_folders(target, item["案件"], data, only=item.get("フォルダ"))


def _make_gaiyou(target: Path, item: Dict) -> None:
    script = PLUGIN_ROOT / "skills" / "junbi" / "scripts" / "gaiyou_word.py"
    done = subprocess.run(
        [sys.executable, "-B", str(script), "--folder", str(target), "--case", item["案件"]],
        input=json.dumps(item["入力"], ensure_ascii=False), capture_output=True, text=True, encoding="utf-8",
    )
    if done.returncode != 0:
        raise RestoreError(f"概要と流れ.docx を作れませんでした（終了コード {done.returncode}）：{done.stdout}{done.stderr}")


def _tool(script: str, target: Path, *args: str) -> str:
    """製品の道具を、社長の Mac と同じく引数で場所を渡して動かす。終了コードが0でなければ RestoreError。"""
    path = PLUGIN_ROOT / "skills" / script
    done = subprocess.run([sys.executable, "-B", str(path), args[0], "--folder", str(target), *args[1:]],
                          capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise RestoreError(f"{script} {args[0]} が終了コード {done.returncode} で止まりました：{done.stdout}{done.stderr}")
    return done.stdout


def _write_json(target: Path, rel: str, data) -> str:
    path = target / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return rel


def answer_rows(path: Path) -> List[Dict[str, str]]:
    """回答表（testdata/デモの会社/回答表.md）の表の行（ID・項目・答え）。"""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0][:1].isalpha() and "-" in cells[0] and cells[0] != "ID":
            rows.append({"ID": cells[0], "項目": cells[1], "答え": cells[2]})
    return rows


def _questions(target: Path, item: Dict, when: str) -> int:
    """回答表から、聞き取りの記録（記録/質問の記録.json）を作る（社長に聞いて答えてもらった形。答えが空けの行は除く）。"""
    rows = [r for r in answer_rows(PLUGIN_ROOT / item["回答表"]) if r["答え"] and r["答え"] != "（空け）"]
    entries = []
    for n, r in enumerate(rows, 1):
        entries.append({"番号": f"質問-{n:04d}", "案件": item["案件"], "段階": item["段階"], "聞いた日時": when,
                        "問い": f"{r['項目']}を教えてください。", "理由": item.get("理由", "計画書に書くため"),
                        "答え": r["答え"], "答えた日時": when, "経路": "聞き取り（回答表から戻した）", "回答表の ID": r["ID"]})
    _write_json(target, "記録/質問の記録.json", {"説明": item.get("説明", ""), "質問": entries})
    return len(entries)


def _round(value: float, digits: int):
    from decimal import ROUND_HALF_UP, Decimal

    q = Decimal(1).scaleb(-digits)
    got = Decimal(repr(float(value))).quantize(q, rounding=ROUND_HALF_UP)
    return int(got) if digits == 0 else float(got)


def _from_numbers(target: Path, specs: List[Dict]) -> List[Dict]:
    """数字の控え（財務モデルの道具が書いたもの）から、その3 のセルの値を取り出す（計算はしない。丸めるだけ）。"""
    numbers = json.loads((target / "記録" / "財務モデルの数字.json").read_text(encoding="utf-8"))["中身"]

    def pick(path: str):
        node = numbers
        for key in path.split("."):
            node = node[key]
        return node

    out = []
    for s in specs:
        node = pick(s["控え"])
        digits = int(s.get("桁", 0))
        if "セル" in s:
            value = node[s["年"]] if isinstance(node, list) else node
            out.append({"シート": s["シート"], "セル": s["セル"], "値": _round(value, digits)})
            continue
        for k, col in enumerate(s["列"]):
            year = int(s.get("最初の年", 0)) + k
            out.append({"シート": s["シート"], "セル": f"{col}{s['行']}", "値": _round(node[year], digits)})
    return out


def _write_plan(target: Path, recipe: Dict, plan_name: Optional[str]) -> Dict:
    """財務モデル・様式の対応・その1・2 の本文・根拠対照表を、製品の道具で書く（書いた後の状態）。"""
    from lib import dates

    out = {}
    spec_item = recipe.get("財務モデル")
    if spec_item:
        spec = json.loads((PLUGIN_ROOT / spec_item["指定"]).read_text(encoding="utf-8"))
        spec.pop("説明", None)
        for a in spec.get("前提", []):
            if a.get("名前") in spec_item.get("仮を外す", []):
                a["仮"] = False
        _write_json(target, "記録/財務モデルの指定.json", spec)
        # 戻すときは LibreOffice の計算し直しをしない（時間がかかるため。計算はテスト tests/test_T8_10.py で確かめる）
        _tool("kaku/scripts/zaimu_model.py", target, "build", "--spec", "記録/財務モデルの指定.json",
              "--soffice", str(target / ".hojokin" / "LibreOffice を使わない"))
        out["財務モデル"] = True
    plan_item = recipe.get("計画書")
    if plan_item:
        base = PLUGIN_ROOT / plan_item["材料"]
        if plan_name:
            base = base.parent / plan_name
        plan = json.loads((base / "本文.json").read_text(encoding="utf-8"))
        pairs = [{"項目": it["名前"], "書き込む位置": it["書き込む位置"]} for it in plan["項目"]]
        _tool("kaku/scripts/yoshiki.py", target, "map", "--input",
              _write_json(target, "記録/一時/様式の対応.json", {"様式": plan["様式"], "対応": pairs}))
        for it in plan["項目"]:
            path = target / "記録" / "一時" / "書く文.txt"
            path.write_text(it["本文"], encoding="utf-8")
            _tool("kaku/scripts/yoshiki.py", target, "write", "--item", it["名前"], "--input", "記録/一時/書く文.txt")
        rows = json.loads((base / "根拠対照表.json").read_text(encoding="utf-8"))["行"] + list(plan_item.get("足す根拠", []))
        fields = recipe.get("表の欄")
        if fields:  # 表の欄を持つ項目（（1）事業者情報など）を、欄ごとに対応づけて書く（B19 の直し）
            pairs = [{"項目": f["項目"], "欄": f["欄"], "書き込む位置": f["書き込む位置"]} for f in fields["欄"]]
            _tool("kaku/scripts/yoshiki.py", target, "map", "--input",
                  _write_json(target, "記録/一時/様式の対応.json", {"様式": plan["様式"], "対応": pairs}))
            for f in fields["欄"]:
                (target / "記録" / "一時" / "書く文.txt").write_text(f["文"], encoding="utf-8")
                _tool("kaku/scripts/yoshiki.py", target, "write", "--item", f["項目"], "--field", f["欄"],
                      "--input", "記録/一時/書く文.txt")
            rows += list(fields.get("足す根拠", []))
            out["表の欄"] = len(fields["欄"])
        _tool("kaku/scripts/kakunin.py", target, "konkyo", "--input",
              _write_json(target, "記録/一時/根拠.json", {"行": rows}))
        out["計画書"] = base.name
        out["項目"] = len(plan["項目"])
        out["根拠対照表の行"] = len(rows)
    form3 = recipe.get("その3")
    if form3:
        values = list(form3.get("値", [])) + _from_numbers(target, form3.get("控えから", []))
        _tool("kaku/scripts/yoshiki.py", target, "cells", "--input",
              _write_json(target, "記録/一時/その3の値.json", {"値": values}))
        out["その3のセル"] = len(values)
    q = recipe.get("質問の記録")
    if q:
        out["聞き取り"] = _questions(target, q, dates.format_datetime(dates.now(target)))
    shutil.rmtree(str(target / "記録" / "一時"), ignore_errors=True)  # 道具に渡した一時のファイルは残さない
    return out


def restore(stage: str, target: Path, downloads: Optional[Path] = None, plan: Optional[str] = None) -> Dict:
    """保存した状態 stage を target に戻す。戻した中身の要約を返す。

    戻し方に「もと」があれば、先にその段階を戻し、その上に、戻し方の「財務モデル」「計画書」「質問の記録」を
    製品の道具で作る（書いた後の状態。TASKS B18・B19）。plan は計画書の材料のフォルダの名前（変種に差し替える）。
    """
    from lib import company, company_init, dates, history

    recipe = load_recipe(stage)
    target = target.resolve()
    downloads = downloads or find_downloads(LIB_DIR)
    if recipe.get("もと"):
        summary = restore(recipe["もと"], target, downloads)
        if recipe.get("今日の日付"):  # 書いた後の材料（D9）の日付に合わせて、今日の日付を差し替え直す
            settings = target / company.MARKER_DIR / company.SETTINGS_FILE
            data = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
            data[dates.TODAY_KEY] = recipe["今日の日付"]
            settings.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        made = _write_plan(target, recipe, plan)
        history.record(target, history.TOOL, REASON.format(stage=stage), when=dates.now(target))
        left = history.pending_changes(target)
        if left:
            raise RestoreError("版の履歴に残っていないファイルがあります：" + "、".join(c.path for c in left[:10]))
        summary.update({"段階": stage, "作ったもの": made, "版": len(history.version_list(target))})
        return summary

    company_init.init(target)
    copied = _copy_saved(saved_dir(stage, recipe), target, tuple(recipe.get("除くもの", [])))
    settings = {}
    if recipe.get("今日の日付"):
        settings[dates.TODAY_KEY] = recipe["今日の日付"]
    (target / company.MARKER_DIR / company.SETTINGS_FILE).write_text(
        json.dumps(settings, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for item in recipe.get("制度データ", []):
        dest = target / item["先"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(PLUGIN_ROOT / item["元"]), str(dest))
    originals = _remember_originals(target)
    official = sum(_place_official(target, downloads, item) for item in recipe.get("公式資料", []))
    for item in recipe.get("段階のフォルダ", []):
        _make_stages(target, item)
    for item in recipe.get("概要と流れ", []):
        _make_gaiyou(target, item)

    history.record(target, history.TOOL, REASON.format(stage=stage), when=dates.now(target))
    left = history.pending_changes(target)
    if left:
        raise RestoreError("版の履歴に残っていないファイルがあります：" + "、".join(c.path for c in left[:10]))
    return {"段階": stage, "写したもの": len(copied), "原本": originals, "公式資料": official,
            "版": len(history.version_list(target))}


def main(argv: List[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    plan = None
    if "--plan" in argv:
        i = argv.index("--plan")
        if i + 1 >= len(argv):
            print("使い方：fukugen.py <段階> [<フォルダ>] [--plan <計画書の材料の名前>]", file=sys.stderr)
            return 1
        plan = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if not argv or len(argv) > 2:
        print("使い方：fukugen.py <段階> [<フォルダ>] [--plan <計画書の材料の名前>]", file=sys.stderr)
        return 1
    target = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    try:
        summary = restore(argv[0], target, plan=plan)
    except Exception as e:  # 戻せないときは、eval を始める前に止める
        print(f"fukugen: 戻せませんでした（{type(e).__name__}: {e}）", file=sys.stderr)
        return 1
    print("fukugen: ok " + json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
