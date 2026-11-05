"""T7-1（改訂と新しい回）の場面の始まりを、保存した状態「書く前」を戻した会社のフォルダに作る（TASKS B28。D10 の申し送り）。

使い方（kaitei_scene.sh から）：/usr/bin/python3 -B kaitei_setup.py <変更あり|変更なし> [<フォルダ>]

- 公募要領の新旧2版は、testdata/制度データ/make_materials.py の build で作る（downloads/ の要領8 の文字を、決まった形に書き換えた
  架空の版。資料の本文〈ページごとの文字〉だけで、PDF は作らない）。公募要領の文を含むので、リポの外の一時の場所に作る。
- 後の版（要領8_書き換え）の資料の本文を、案件の `記録/資料の本文/<案件>/要領8_書き換え/` に写し、資料の一覧.json で、
  前の版（要領8）を「前の回の資料」に移し、後の版を「資料」に入れる（lib/kaitei.py の doc_pairs が、名前で前と後を対にする）。
  「変更なし」の組は、後の版が前の版と同じ文字。
- 公式資料のファイル（案件/<案件>/公式資料/）は足さない（後の版は資料の本文だけ）。公式サイトの確かめ（開いたとき）は、
  後の版の URL が前の版と同じなので、ふだんの確かめのまま。
- ここまでを「ツール」の版として版の履歴に残す（開いたときに、社長が手で変えたものに数えないため）。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

LIB_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = LIB_DIR.parent.parent
MATERIALS = PLUGIN_ROOT / "testdata" / "制度データ"
CASE = "2026_省力化（一般型）第9回"
KINDS = ("変更あり", "変更なし")


def setup(kind: str, folder: Path) -> str:
    sys.path.insert(0, str(PLUGIN_ROOT))
    sys.path.insert(0, str(MATERIALS))
    import make_materials as mm  # noqa: E402
    from lib import dates, history  # noqa: E402

    work = Path(tempfile.mkdtemp(prefix="hojokin-T7-1-"))
    try:
        built = mm.build(work)
        source = built["T7-1"][kind] / "記録" / "資料の本文" / mm.CASE
        listed_src = json.loads((source / "資料の一覧.json").read_text(encoding="utf-8"))
        root = folder / "記録" / "資料の本文" / CASE
        dest = root / mm.NEW_ID
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source / mm.NEW_ID, dest)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    list_path = root / "資料の一覧.json"
    listed = json.loads(list_path.read_text(encoding="utf-8"))
    older = [d for d in listed["資料"] if d.get("id") == "要領8"]
    if len(older) != 1:
        raise SystemExit("資料の一覧に要領8 がありません（保存した状態「書く前」を戻してから流してください）")
    newer = dict(listed_src["資料"][0])
    newer["取得日"] = dates.today(folder).isoformat()
    listed["資料"] = [newer if d.get("id") == "要領8" else d for d in listed["資料"]]
    listed["前の回の資料"] = list(listed.get("前の回の資料") or []) + older
    list_path.write_text(json.dumps(listed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    history.record(folder, history.TOOL, f"T7-1 の場面（{kind}）：公募要領の後の版の資料の本文を置いた",
                   when=dates.now(folder))
    return f"kaitei_setup: ok {kind}（後の版 {mm.NEW_ID}、前の版 要領8 を前の回の資料に）"


def main(argv) -> int:
    if not argv or argv[0] not in KINDS:
        print("使い方：kaitei_setup.py <変更あり|変更なし> [<フォルダ>]", file=sys.stderr)
        return 1
    folder = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    try:
        print(setup(argv[0], folder.resolve()))
    except Exception as e:  # 作れないときは、eval を始める前に止める
        print(f"kaitei_setup: 作れませんでした（{type(e).__name__}: {e}）", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
