"""T6-6（依頼と待ち）のケースの準備：保存した状態「書く前」を戻した後に、場面ごとの始まりの状態を作る（TASKS K2、
SPEC T6-6、DESIGN 11章「学んだことはファイルに残るので、前の場面を終えた状態から始められる」）。

使い方（ケースの scaffold.sh から。今いるフォルダが会社のフォルダ）：
  /usr/bin/python3 -B evals/_lib/irai_setup.py <場面>      場面：場面1-聞く・場面1-答え・場面2・場面3・場面4

台本（testdata/期限/台本_外部への依頼.md）と、材料の一覧（testdata/期限/材料の一覧.md の「外部への依頼（T6-6）」）のとおりに作る。
前の場面の終わりの状態は、製品の道具（lib/deadline_tool.apply。kigen.py と同じ関数）で作る。社長役の答え（A1〜A3）を、
前の場面で Claude が聞いて残した形にする。

- どの場面にも：制度データ（省力化 第8回の正解）に、第9回の締切（仮の 2026-12-25 17:00）と採択発表の予定（仮の 2027-04-16）を
  決まった期日として足す（材料の一覧の「回答表にない事柄」）。会社の記録に、お金の用意（回答表 H-12。借入があるので、
  金融機関確認書が要る）と決算の月（A-10）を足す（前の段階の聞き取りで分かっていたこととして）。今日の日付を場面の日にする。
- 場面1-答え から：金融機関確認書と見積書（交付申請で取り直す）を、目安の日数なしで台帳に足した（場面1 の終わり）。
- 場面2 から：目安の日数（確認書 14日、見積 7日）と、頼む人（社長）を残した（A1〜A3 の答え）。
- 場面3 から：2026-11-18 に確認書を頼んだ（S2）。入れ口に、信用金庫からの確認書（材料）を入れる（S3 の前）。
- 場面4 から：確認書が届いた（S3）。2件目の案件（持続化 第20回）を足す（制度データは evals/_lib/T6-6/ の小さなもの）。
  会社の記録に、2件目を決めたときに分かっていたこと（冷凍惣菜の取り組み、見積はまだ、自己資金。回答表 I-01・I-04・I-08）を足す。

最後に、ここまでを「ツール」の版として残す（開いたときに、社長が手で変えたものに数えないため。evals/_lib/fukugen.py と同じ）。
標準のライブラリと、プラグインの lib/ だけで動く。終了コード：0 作った。1 作れなかった（理由を標準エラーに書く）。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True

LIB_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = LIB_DIR.parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

SCENES = ("場面1-聞く", "場面1-答え", "場面2", "場面3", "場面4")
TODAY = {"場面1-聞く": "2026-11-16", "場面1-答え": "2026-11-16", "場面2": "2026-11-18", "場面3": "2026-11-30",
         "場面4": "2026-11-30"}
CASE_1 = "2026_省力化（一般型）第9回"
CASE_2 = "2026_持続化（通常枠）第20回"
SEIDO_1 = "記録/制度データ/省力化_第8回.json"
BANK = "金融機関確認書"
QUOTE = "見積書"
LETTER = PLUGIN_ROOT / "testdata" / "期限" / "材料" / "外部への依頼" / "信用金庫からの確認書.pdf"
SEIDO_2 = LIB_DIR / "T6-6" / "持続化_第20回.json"
NOTE = "（テスト用の値。資料の文は写していない）"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def set_today(folder: Path, day: str) -> None:
    from lib import company, dates
    path = company.settings_path(folder)
    settings = _json(path) if path.exists() else {}
    settings[dates.TODAY_KEY] = day
    _write(path, settings)


def base(folder: Path) -> None:
    """第9回の締切と採択発表の予定（どちらも仮）を足し、会社の記録にお金の用意を足す。"""
    path = folder / SEIDO_1
    data = _json(path)
    names = {d.get("名前") for d in data.get("決まった期日") or []}
    extra = [
        {"名前": "第9回 締切", "日時": {"値": {"日時": "2026-12-25T17:00+09:00"}, "出典": [{"資料": "スケジュール"}],
                                        "根拠の文": NOTE, "状態": "確認済み"}, "注記": "予定"},
        {"名前": "第9回 採択発表", "日時": {"値": {"日時": "2027-04-16"}, "出典": [{"資料": "スケジュール"}],
                                          "根拠の文": NOTE, "状態": "確認済み"}, "注記": "予定"},
    ]
    data["決まった期日"] = list(data.get("決まった期日") or []) + [e for e in extra if e["名前"] not in names]
    _write(path, data)
    from lib import company_record
    source = company_record.make_source(folder, "社長の発言", utterance="自己資金7,000千円と、信用金庫からの借入15,500千円です")
    company_record.add_fact(folder, "お金の用意（機械の補助金）",
                            "自己資金7,000千円と、信用金庫からの借入15,500千円。信用金庫には相談していて、前向きな返事をもらっている",
                            True, source)
    source = company_record.make_source(folder, "社長の発言", utterance="決算は3月です")
    company_record.add_fact(folder, "決算の月", "3月（直近の決算は第18期の2026年3月期）", False, source)  # 回答表 A-10


def apply(folder: Path, changes) -> None:
    from lib import deadline_tool
    deadline_tool.apply(folder, CASE_1, changes)


def add_second_case(folder: Path) -> None:
    listed = {"案件": CASE_2,
              "制度": {"名前": "小規模事業者持続化補助金", "略称": "持続化", "枠": "通常枠", "種類": "補助金", "公募回": "第20回"},
              "案件の回": "第20回", "資料": [{"id": "要領20", "名前": "公募要領", "公募回": "第20回"}]}
    _write(folder / "記録" / "資料の本文" / CASE_2 / "資料の一覧.json", listed)
    shutil.copyfile(SEIDO_2, folder / "記録" / "制度データ" / "持続化_第20回.json")
    for sub in ("申請書", "添付する書類"):
        (folder / "案件" / CASE_2 / "1_申請" / sub).mkdir(parents=True, exist_ok=True)
    # 2件目を決めたときの聞き取りで分かっていたこと（回答表 I-01・I-04・I-08）
    from lib import company_record
    for name, value, said in (
            ("申請する補助金（2件目）", "小規模事業者持続化補助金（通常枠）。冷凍惣菜の取り組みに使う", "冷凍惣菜のほうは持続化補助金にします"),
            ("2件目でやりたいこと", "自社のブランドで冷凍惣菜をつくり、ネットと店頭で売りたい", "冷凍惣菜をネットと店頭で売りたいです"),
            ("2件目の見積", "まだ取っていない。頼む会社も決めていない", "見積はまだです"),
            ("2件目のお金の用意", "自己資金でまかなう", "冷凍惣菜のほうは自己資金でやります")):
        source = company_record.make_source(folder, "社長の発言", utterance=said)
        company_record.add_fact(folder, name, value, True, source)


def prepare(folder: Path, scene: str) -> None:
    from lib import dates, deadline_tool, history
    Change = deadline_tool.Change
    step = SCENES.index(scene)
    set_today(folder, "2026-11-16")
    base(folder)
    if step >= 1:  # 場面1 の終わり：頼む書類を台帳に足した（目安の日数はまだ）
        apply(folder, [Change(doc=BANK, add=True), Change(doc=QUOTE, add=True)])
    if step >= 2:  # A1〜A3 の答え
        apply(folder, [Change(doc=BANK, days=14, asker="社長", to="信用金庫"), Change(doc=QUOTE, days=7, asker="社長")])
    if step >= 3:  # S2（2026-11-18）：確認書を頼んだ
        set_today(folder, "2026-11-18")
        apply(folder, [Change(doc=BANK, state="依頼した", day=dates.today(folder))])
        inbox = folder / "入れ口"
        inbox.mkdir(exist_ok=True)
        shutil.copyfile(LETTER, inbox / LETTER.name)
    if step >= 4:  # S3（2026-11-30）：確認書が届いた。2件目の案件を足す
        set_today(folder, "2026-11-30")
        (folder / "入れ口" / LETTER.name).unlink()
        apply(folder, [Change(doc=BANK, state="届いた", day=dates.today(folder))])
        add_second_case(folder)
    set_today(folder, TODAY[scene])
    history.record(folder, history.TOOL, f"T6-6 の準備（{scene} の始まり）", when=dates.now(folder))


def main(argv) -> int:
    if len(argv) != 1 or argv[0] not in SCENES:
        print(f"使い方：irai_setup.py <場面>（{'・'.join(SCENES)}）", file=sys.stderr)
        return 1
    try:
        prepare(Path.cwd(), argv[0])
    except Exception as error:
        print(f"irai_setup: 作れませんでした（{type(error).__name__}: {error}）", file=sys.stderr)
        return 1
    print(f"irai_setup: ok {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
