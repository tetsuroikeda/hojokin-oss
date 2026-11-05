"""採択後のケースと通しの準備：保存した状態「書く前」を戻した後に、採択後の場面の始まりの状態を作る
（TASKS B31b・B32、SPEC T12-1・T12-2・T13-5、DESIGN 11章）。

使い方（今いるフォルダが会社のフォルダ。ケースの scaffold.sh か、tests/multiturn/t12_1.py から）：
  /usr/bin/python3 -B evals/_lib/saitakugo.py <場面> [<会社のフォルダ>]
  場面：申請の後・採択後・差し戻しの後

材料は testdata/期限（通知の日付）と testdata/計画書（D9 の交付申請の提出版と差し戻し）のとおり。製品の道具（lib/stage_switch.py、
lib/submission.py、lib/company_record.py）で作る。

- 申請の後（T12-1 の始まり。今日 2026-12-20）：1件目（省力化 第9回）に、第9回の締切と採択発表の予定（どちらも仮。
  testdata/期限）を決まった期日として足し、制度データの正解にまだない「義務」（tests/data/gimu/ の下書き）を足す。会社の記録に、
  決算の月（回答表 A-10）とお金の用意（H-12）を足す。2件目（持続化 第20回。制度データは testdata/正解/ の下書き）の案件を足す。
  どちらも申請の段階の提出版を記録する（申請書の控えを1つ置いて、「提出した」と伝えたときと同じ道具で）。
- 採択後（T12-2・T13-5 の土台。今日 2027-06-02）：持続化は採択（2027-03-12）の後に見積書等の提出の段階へ、省力化は採択
  （2027-04-16）の後に交付申請の段階へ切り替える。省力化の交付申請の提出版（2027-05-28）は、D9 の交付申請の入力と、
  見積書2通（D2b）の写し。
- 差し戻しの後（T13-5。今日 2027-06-14）：省力化の交付申請の差し戻し1（見積書の有効期限）を受け取って直し、不備の型として
  会社の記録に残した（kiroku の add-defect と同じ形）。差し戻しの文面は原本（役所からの通知）として置く。

最後に、ここまでを「ツール」の版として残す（開いたときに、社長が手で変えたものに数えないため）。
標準のライブラリと、プラグインの lib/（と同梱の dulwich）だけで動く。終了コード：0 作った。1 作れなかった（理由を標準エラー）。
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

SCENES = ("申請の後", "採択後", "差し戻しの後")
CASE_1 = "2026_省力化（一般型）第9回"
CASE_2 = "2026_持続化（通常枠）第20回"
SEIDO_1 = "記録/制度データ/省力化_第8回.json"
SEIDO_2 = PLUGIN_ROOT / "testdata" / "正解" / "持続化_第20回.json"
DUTIES = PLUGIN_ROOT / "tests" / "data" / "gimu" / "省力化_第8回_義務.json"
D9 = PLUGIN_ROOT / "testdata" / "計画書" / "材料" / "5_差し戻し"
QUOTES = PLUGIN_ROOT / "testdata" / "デモの会社" / "書類"
NOTICES = PLUGIN_ROOT / "testdata" / "期限" / "材料" / "通知"
NOTE = "（テスト用の値。資料の文は写していない）"
RETURN_1 = "差し戻し_1_見積書の有効期限.txt"
RETURN_1_ORIGINAL = "原本/役所からの通知/2027-06-02_差し戻し_見積書の有効期限.txt"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def set_today(folder: Path, day: str) -> None:
    from lib import company, dates
    path = company.settings_path(folder)
    settings = _json(path) if path.exists() else {}
    settings[dates.TODAY_KEY] = day
    _write(path, settings)


def fact(folder: Path, name: str, value: str, changeable: bool, said: str) -> None:
    from lib import company_record
    source = company_record.make_source(folder, "社長の発言", utterance=said)
    company_record.add_fact(folder, name, value, changeable, source)


def base(folder: Path) -> None:
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
    data["義務"] = _json(DUTIES)["義務"]
    _write(path, data)
    fact(folder, "決算の月", "3月（直近の決算は第18期の2026年3月期）", False, "決算は3月です")  # 回答表 A-10
    fact(folder, "お金の用意（機械の補助金）",
         "自己資金7,000千円と、信用金庫からの借入15,500千円。信用金庫には相談していて、前向きな返事をもらっている",
         True, "自己資金7,000千円と、信用金庫からの借入15,500千円です")  # 回答表 H-12


def add_second_case(folder: Path) -> None:
    listed = {"案件": CASE_2,
              "制度": {"名前": "小規模事業者持続化補助金", "略称": "持続化", "枠": "通常枠", "種類": "補助金", "公募回": "第20回"},
              "案件の回": "第20回", "資料": [{"id": "要領20", "名前": "公募要領", "公募回": "第20回"}]}
    _write(folder / "記録" / "資料の本文" / CASE_2 / "資料の一覧.json", listed)
    shutil.copyfile(SEIDO_2, folder / "記録" / "制度データ" / "持続化_第20回.json")
    for sub in ("申請書", "添付する書類"):
        (folder / "案件" / CASE_2 / "1_申請" / sub).mkdir(parents=True, exist_ok=True)
    for name, value, said in (  # 回答表 I-01・I-04・I-08
            ("申請する補助金（2件目）", "小規模事業者持続化補助金（通常枠）。冷凍惣菜の取り組みに使う", "冷凍惣菜のほうは持続化補助金にします"),
            ("2件目でやりたいこと", "自社のブランドで冷凍惣菜をつくり、ネットと店頭で売りたい", "冷凍惣菜をネットと店頭で売りたいです"),
            ("2件目のお金の用意", "自己資金でまかなう", "冷凍惣菜のほうは自己資金でやります")):
        fact(folder, name, value, True, said)


def submit(folder: Path, case: str, stage: str, files=None) -> None:
    """段階の申請書の控え（なければ1つ置く）を、「提出した」と伝えたときと同じ道具で提出版にする。"""
    from lib import history, submission
    stage_dir = folder / "案件" / case / stage
    for rel, data in (files or {}).items():
        path = stage_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    app = stage_dir / "申請書"
    if not any(p.is_file() for p in app.rglob("*")):
        (app / "申請の控え.txt").write_text("（テスト用。この段階で出した申請書の控え）\n", encoding="utf-8")
    history.record(folder, history.TOOL, f"{case} の {stage} を出す前の版")
    submission.record(folder, case, stage, reason="提出しました")


def switch(folder: Path, case: str, events=(), stage=None) -> None:
    from lib import stage_switch
    stage_switch.switch(folder, case, stage=stage, events=list(events))


def receive(folder: Path, src: Path, kind: str, day: str, note: str = "") -> str:
    """届いた書類を入れ口に入れ、書類を整理する道具（lib/seiri.py。shorui と同じ）で原本の置き場へ移す。原本の場所を返す。"""
    from lib import seiri
    inbox = folder / "入れ口"
    inbox.mkdir(exist_ok=True)
    shutil.copyfile(src, inbox / src.name)
    entry = seiri.organize(folder, f"入れ口/{src.name}", "役所からの通知", kind, day, note=note)
    return entry["場所"]


def prepare(folder: Path, scene: str) -> None:
    from lib import dates, history
    step = SCENES.index(scene)
    set_today(folder, "2026-12-20")
    base(folder)
    add_second_case(folder)
    submit(folder, CASE_2, "1_申請")
    submit(folder, CASE_1, "1_申請")
    if step >= 1:
        set_today(folder, "2027-03-15")
        receive(folder, NOTICES / "持続化_第20回_採択通知書.pdf", "採択通知書", "2027-03-12", "持続化")
        switch(folder, CASE_2)  # 見積書等の提出の段階へ（期限は決まった日付なので、出来事は渡さない）
        set_today(folder, "2027-04-20")
        notice = receive(folder, NOTICES / "省力化_第9回_採択の通知.pdf", "採択の通知", "2027-04-16", "省力化")
        from lib import stage_switch
        stage_switch.switch(folder, CASE_1, events=["採択発表日=2027-04-16"], source=notice)
        set_today(folder, "2027-05-28")
        inputs = (D9 / "提出版" / "交付申請の入力.json").read_bytes()
        files = {"申請書/交付申請の入力.json": inputs}
        for name in ("見積書_つばさ台フードシステム.pdf", "見積書_ほしみ機工.pdf"):
            files[f"添付する書類/{name}"] = (QUOTES / name).read_bytes()
        submit(folder, CASE_1, "2_交付申請", files)
        set_today(folder, "2027-06-02")
    if step >= 2:
        from lib import company_record
        place = receive(folder, D9 / RETURN_1, "差し戻し", "2027-06-02", "見積書の有効期限")
        assert place == RETURN_1_ORIGINAL, place
        set_today(folder, "2027-06-14")
        data = company_record.load(folder)
        items = data.setdefault("項目", [])
        number = 1 + sum(1 for it in items if it.get("種類") == company_record.DEFECT)
        items.append({"id": f"不備-{number:04d}", "種類": company_record.DEFECT, "案件": CASE_1, "手続きの段階": "2_交付申請",
                      "内容": "交付申請に添付した見積書2通の有効期限（2027-01-31）が、交付申請の日より前に切れていた",
                      "原因": "応募のときに取った見積書を、採択の後もそのまま使った（交付申請の時期に有効な見積書を取り直していなかった）",
                      "次に注意する書類": ["見積書"],
                      "照合の決まり": "見積書の有効期限が、出す日（提出の締切）より後であることを確かめる。切れそうなら取り直しを頼む",
                      "出典": {"種類": "原本", "ファイル": RETURN_1_ORIGINAL}, "受け取った日": "2027-06-02",
                      "覚えた日": "2027-06-14"})
        company_record.save(folder, data)
    history.record(folder, history.TOOL, f"採択後の準備（{scene} の始まり）", when=dates.now(folder))


def main(argv) -> int:
    if not argv or argv[0] not in SCENES or len(argv) > 2:
        print(f"使い方：saitakugo.py <場面>（{'・'.join(SCENES)}） [<会社のフォルダ>]", file=sys.stderr)
        return 1
    folder = Path(argv[1]) if len(argv) == 2 else Path.cwd()
    try:
        prepare(folder.resolve(), argv[0])
    except Exception as error:
        print(f"saitakugo: 作れませんでした（{type(error).__name__}: {error}）", file=sys.stderr)
        return 1
    print(f"saitakugo: ok {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
