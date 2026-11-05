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
    if not saved.is_dir():
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


def restore(stage: str, target: Path, downloads: Optional[Path] = None) -> Dict:
    """保存した状態 stage を target に戻す。戻した中身の要約を返す。"""
    from lib import company, company_init, dates, history

    recipe = load_recipe(stage)
    target = target.resolve()
    downloads = downloads or find_downloads(LIB_DIR)

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
    if not argv or len(argv) > 2:
        print("使い方：fukugen.py <段階> [<フォルダ>]", file=sys.stderr)
        return 1
    target = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    try:
        summary = restore(argv[0], target)
    except Exception as e:  # 戻せないときは、eval を始める前に止める
        print(f"fukugen: 戻せませんでした（{type(e).__name__}: {e}）", file=sys.stderr)
        return 1
    print("fukugen: ok " + json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
