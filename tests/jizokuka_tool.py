"""開発用：持続化 第20回を、プログラムを変えずに制度データだけを足して、段階ごとの道具に通す（TASKS B1b、T0-1）。

1件目（省力化）の「書く前」の状態を戻した会社のフォルダに、持続化 第20回の公式資料を downloads/ から置き、
読み取り役で作った制度データ（B1a。資料の文を含むのでリポの外にある）を写してから、
探す・記録・準備・書類・書く・確かめる・入力（入力シートの形まで）・練習・採択後 の道具を順に動かし、終了コードを出す。
社長と Claude の判断に当たる所（概要の文、要件の判定、入力シートの値）は、デモの会社の回答表に沿って短く書いたもの。

使い方：
  python3 tests/jizokuka_tool.py setup <会社のフォルダ> <制度データの JSON>
  python3 tests/jizokuka_tool.py run <会社のフォルダ> [段階 ...]   段階：探す 記録 準備 書類 書く 確かめる 入力 練習 採択後

- 会社のフォルダは、リポの外（作業の場所）に作る。
- 画面への入力（模擬画面）は B29 で確かめる。ここでは入力シートの形と、入力の道具の入力シートの確かめまで。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(PLUGIN_ROOT / "evals" / "_lib"))

CASE = "2026_持続化（一般型・通常枠）第20回"
SEIDO = "記録/制度データ/持続化_第20回.json"
PY = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else sys.executable
SKILLS = PLUGIN_ROOT / "skills"
STAGES = ("探す", "記録", "準備", "書類", "書く", "確かめる", "入力", "練習", "採択後")
DOWNLOADS = {
    "https://r6.jizokukahojokin.info/doc/r6_koubover8_ip20.pdf": "jizokuka_20/r6_koubover8_ip20.pdf",
    "https://r6.jizokukahojokin.info/doc/r6_qa_ip20.pdf": "jizokuka_20/r6_qa_ip20.pdf",
    "https://r6.jizokukahojokin.info/doc/r6_sanko_ip20.pdf": "jizokuka_20/r6_sanko_ip20.pdf",
    "https://r6.jizokukahojokin.info/doc/r6_chantei_ip20.xlsx": "jizokuka_20/r6_chantei_ip20.xlsx",
    "https://r6.jizokukahojokin.info/doc/r6_chanteimanual_ip20.pdf": "jizokuka_20/r6_chanteimanual_ip20.pdf",
    "https://r6.jizokukahojokin.info/doc/r6_koubomanual_ip0306.pdf": "jizokuka_20/r6_koubomanual_ip0306.pdf",
    "https://r6.jizokukahojokin.info/doc/r6_js_tebiki_ip19.pdf": "jizokuka_20/r6_js_tebiki_ip19.pdf",
}


def setup(folder: Path, seido_file: Path) -> None:
    """1件目の「書く前」を戻し、持続化の公式資料を置き、制度データを写して、いちばん前の段階のフォルダを作る。"""
    import fukugen
    from lib import official_docs, seido_data

    if not (folder / ".hojokin").is_dir():
        folder.mkdir(parents=True, exist_ok=True)
        print(fukugen.restore("書く前", folder))
    data = json.loads((SKILLS / "junbi/取る資料/持続化_通常枠_第20回.json").read_text(encoding="utf-8"))
    downloads = fukugen.find_downloads(PLUGIN_ROOT)
    result = official_docs.fetch_all(folder, data, downloader=fukugen.local_downloader(downloads, DOWNLOADS))
    print("公式資料：", "そろった" if result.complete else "そろっていない", [r.doc["id"] for r in result.docs])
    dest = folder / SEIDO
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(seido_file), str(dest))
    seido_data.make_stage_folders(folder, CASE, json.loads(dest.read_text(encoding="utf-8")), only=["1_申請"])


class Runner:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.results: List[tuple] = []

    def run(self, stage: str, args: list, input_text: Optional[str] = None, env: Optional[dict] = None):
        done = subprocess.run([PY, "-B", *map(str, args)], capture_output=True, text=True, encoding="utf-8",
                              input=input_text, env=dict(os.environ, **(env or {})))
        self.results.append((stage, Path(str(args[0])).name, done.returncode))
        print(f"\n===== {stage}（終了コード {done.returncode}）：{Path(str(args[0])).name} {' '.join(str(a) for a in args[1:2])}")
        print(done.stdout[-3000:])
        if done.stderr.strip():
            print("[stderr]", done.stderr[-2000:])
        return done

    def put(self, name: str, data) -> str:
        path = self.folder / "記録" / "一時" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return f"記録/一時/{name}"

    def fact_ids(self) -> dict:
        data = json.loads((self.folder / "記録/会社の記録.json").read_text(encoding="utf-8"))
        return {it.get("名前"): it["id"] for it in data["項目"] if it["種類"] == "事実"}


def run_stages(folder: Path, only: List[str]) -> int:
    r = Runner(folder)
    f = ["--folder", folder]
    want = set(only or STAGES)
    seido = json.loads((folder / SEIDO).read_text(encoding="utf-8"))

    if "探す" in want:
        rel = r.put("補助金の候補.json", {"会社名": "株式会社やまぶき惣菜", "聞き取りの要点": ["冷凍惣菜の販路開拓"], "候補": [{
            "区分": "公募中", "名前": "小規模事業者持続化補助金（一般型・通常枠）",
            "合う理由": "従業員15人の製造業で小規模事業者に当たり、冷凍惣菜の販路開拓に使える",
            "対象外になりそうな点": "1件目（省力化）と経費を分ける必要がある",
            "次の公募の見込み": "第20回は12月15日締切", "予算の状況": "見つからなかった",
            "出典URL": ["https://r6.jizokukahojokin.info/"]}]})
        r.run("探す", [SKILLS / "sagasu/scripts/kouho_word.py", *f, "--input", rel])
    if "記録" in want:
        rec = SKILLS / "kiroku/scripts/record.py"
        for name, value, said in (
                ("2件目でやりたいこと", "自社ブランドの冷凍惣菜をネットと店頭で売る販路開拓", "次は自社ブランドの冷凍惣菜を、ネットと店頭で売りたい。"),
                ("2件目の補助の対象にする経費", 3000000, "ネットの店づくりとチラシ、展示会で300万円くらい。"),
                ("申請する補助金（2件目）", "小規模事業者持続化補助金（一般型・通常枠）", "2件目は持続化補助金にする。")):
            r.run("記録", [rec, "add-fact", *f, "--name", name, "--value", value, "--changeable",
                         "--source", "社長の発言", "--utterance", said])
    if "準備" in want:
        ids = r.fact_ids()
        rel = r.put("概要と流れ.json", {
            "制度の概要": ["小規模事業者が、自ら作った経営計画に沿って販路を広げる取り組みを支える国の補助金です。",
                       "やまぶき惣菜では、自社ブランドの冷凍惣菜をネットと店頭で売る取り組みに使う予定です。"],
            "流れの説明": "申請の後、採択されたら見積書などを出し、交付決定を受けてから発注します。事業が終わったら実績報告と効果報告を出します。",
            "要件の判定": [{"要件": "小規模事業者であること（業種ごとの従業員の数）", "判定": "満たす",
                         "理由": "製造業で、常時使用する従業員が15人", "会社の記録": [ids["従業員の数"]]}],
            "加点の判定": [{"加点": "賃金引上げ加点", "判定": "確かめが要る", "理由": "賃上げの予定はあるが、判定シートで確かめる",
                         "会社の記録": [ids["賃上げの予定"]]}],
            "補助額の見込み": {"区分": "通常枠", "特例": ["賃金引上げ特例"], "補助の対象にする経費": ids["2件目の補助の対象にする経費"],
                           "理由": "賃上げの予定があるため、賃金引上げ特例を使う見込み",
                           "会社の記録": [ids["賃上げの予定"], ids["2件目の補助の対象にする経費"]]}})
        r.run("準備", [SKILLS / "junbi/scripts/gaiyou_word.py", *f, "--case", CASE, "--input", rel])
    if "書類" in want:
        r.run("書類", [SKILLS / "shorui/scripts/seiri.py", "list", *f])
        r.run("書類（開いたとき）", [PLUGIN_ROOT / "hooks/main.py", "SessionStart"],
              input_text=json.dumps({"source": "startup", "session_id": "jizokuka-tool"}), env={"CLAUDE_PROJECT_DIR": str(folder)})
    if "書く" in want:
        spec = folder / "記録/財務モデルの指定.json"
        if not spec.exists():
            text = (PLUGIN_ROOT / "tests/data/zaimu/指定_前提3つ.json").read_text(encoding="utf-8")
            spec.write_text(text.replace(', "仮": true', ""), encoding="utf-8")
        r.run("書く", [SKILLS / "kaku/scripts/zaimu_model.py", "build", *f, "--spec", "記録/財務モデルの指定.json",
                     "--seido", SEIDO, "--replace"])
        r.run("書く", [SKILLS / "kaku/scripts/relevant_records.py", *f, "--item", "常時使用する従業員数", "--item", "経営計画"])
        values = []
        for screen in seido["申請画面"]["画面"]:
            for field in screen["欄"]:
                if field.get("担当者が入れる"):
                    continue
                name = field["名前"]
                fixed = {"常時使用する従業員数": 15, "資本金額": 10000000, "法人名/屋号": "株式会社やまぶき惣菜"}
                if name in fixed:
                    value = fixed[name]
                elif field.get("種類") == "文字" and screen["名前"] in ("経営計画入力", "補助事業計画入力"):
                    value = "冷凍惣菜の販路開拓" if "30文字" in name else "自社ブランドの冷凍惣菜をネットと店頭で売る計画です。"
                else:
                    value = "該当なし"
                values.append({"画面": screen["名前"], "欄": name, "値": value})
        rel = r.put("入力シートの値.json", {"値": values})
        r.run("書く", [SKILLS / "kaku/scripts/yoshiki.py", "sheet", *f, "--case", CASE, "--seido", SEIDO, "--values", rel])
    if "確かめる" in want:
        ids = r.fact_ids()
        rel = r.put("根拠.json", {"行": [
            {"記述": "15人", "種類": "数字", "書いた場所": "応募者概要入力：常時使用する従業員数",
             "出典": f"会社の記録 {ids['従業員の数']}（従業員の数）"},
            {"記述": "株式会社やまぶき惣菜", "種類": "固有名詞", "書いた場所": "基本情報入力：法人名/屋号",
             "出典": f"会社の記録 {ids['会社名']}（会社名）"}]})
        kakunin = SKILLS / "kaku/scripts/kakunin.py"
        r.run("確かめる", [kakunin, "konkyo", *f, "--case", CASE, "--input", rel])
        r.run("確かめる", [kakunin, "count", *f, "--case", CASE, "--seido", SEIDO])
        r.run("確かめる", [kakunin, "prepare", *f, "--case", CASE, "--seido", SEIDO])
    if "入力" in want:
        r.run("入力", [SKILLS / "nyuryoku/scripts/nyuryoku.py", "sheet", *f, "--case", CASE])
    if "練習" in want:
        r.run("練習", [SKILLS / "kaku/scripts/renshu.py", *f, "--case", CASE, "--seido", SEIDO])
    if "採択後" in want:
        r.run("採択後", [SKILLS / "junbi/scripts/stage_switch.py", *f, "--case", CASE])

    print("\n===== まとめ（段階・道具・終了コード）")
    for stage, tool, code in r.results:
        print(f"- {stage}：{tool} {code}")
    return 0 if all(code == 0 for _s, _t, code in r.results) else 1


def main(argv: List[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) >= 3 and argv[0] == "setup":
        setup(Path(argv[1]).resolve(), Path(argv[2]).resolve())
        return 0
    if len(argv) >= 2 and argv[0] == "run":
        return run_stages(Path(argv[1]).resolve(), argv[2:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
