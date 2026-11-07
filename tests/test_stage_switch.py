"""採択後に、次の手続きの段階（2_交付申請）へ切り替える（SPEC F12・F3・F6、DESIGN 4.5・4.7・6章・9章。TASKS M10）。

確かめること：
- 日付の差し替え（`.hojokin/設定.json` の「今日の日付」）で採択後に進め、確かめた採択発表日を渡すと、junbi の道具が
  制度データの手続きの段階から、次の段階のフォルダ（中は「申請書」と「添付する書類」）、その段階の書類の一覧（必須・条件付き・
  任意。ほかの段階の書類を混ぜない）、期限（採択発表日から2か月。日付・あと何日・もとにした日・出典）を作る。
- 日付と「あと何日」は、差し替えた今日から出す。開いたときの期限と今の状態.html（M3 の組み立て）にも、同じ期限が出る。
- 出来事の日付は期限の台帳（`記録/期限の台帳.json`）の「出来事」に「確定」として残り、直すと1件のまま書き換わる。
  ほかの項目・ほかの案件の出来事は消さない。
- 採択発表日が分からなければ、切り替えはするが、期限は決め方だけ示す（終了コード 1）。制度データに予定があれば「見込み」。
- 断るとき（制度データにない出来事、今日より後の日付、ない段階、前の段階、最後の段階、見るだけで日付を渡す、
  見つからない原本、読めない台帳、書く先の別名）は、何も書かない（終了コード 2）。

材料は、このファイルの中の架空の制度データ（tests の外の場所も、公式資料も使わない）。道具は、Claude が Bash で動かすのと
同じく、社長の Mac と同じ /usr/bin/python3 で、プラグインの写しから動かす。会社のフォルダは、会社のフォルダを作る道具で用意し、
開いたときの hook は hooks.json のコマンドで動かす（tests/version_tool.py）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import hook_runner as hr
import pytest
import version_tool as vt

CASE = "2026_試し省力（一般型）第4回"
SHORT = "試し省力"
TOOL = Path("skills") / "junbi" / "scripts" / "stage_switch.py"
LEDGER = "記録/期限の台帳.json"
CASE_DIR = f"案件/{CASE}"


def _sv(value, source="要領3", page=None, state="確認済み", note=None):
    src = {"資料": source}
    if page is not None:
        src["ページ"] = page
    node = {"値": value, "出典": [src], "根拠の文": "（架空の資料の文）", "状態": state}
    if note:
        node["注記"] = note
    return node


def _after(event, n, unit):
    return {"種類": "出来事からの期間", "出来事": event, "期間": {"数": n, "単位": unit}}


def _doc(name, group, issuer, stage, **extra):
    doc = {"名前": name, "区分": group, "発行元": issuer, "手続き": [stage], "内容": _sv(f"{name}の説明", page=30)}
    doc.update(extra)
    return doc


def seido(schedule=None):
    """架空の制度データ（第3回の資料から作り、案件は第4回）。schedule は「第4回 採択発表日」の値（なければ読み取れない）。"""
    announce = _sv(schedule, "スケジュール") if schedule is not None else \
        {"値": None, "状態": "読み取れない", "理由": "後日お知らせします、とある"}
    entry = {"名前": "第4回 採択発表日", "日時": announce}
    if schedule is not None:
        entry["注記"] = "予定"
    return {
        "スキーマの版": 1,
        "制度": {"名前": "試し省力補助金", "枠": "一般型", "種類": "補助金", "公募回": "第3回"},
        "決まった期日": [
            {"名前": "第4回 公募締切日", "日時": _sv({"年月": "2027-01", "旬": "下旬"}, "スケジュール"), "注記": "予定"},
            entry,
        ],
        "書類": [
            _doc("決算書", "必須", "自社", "応募申請"),
            _doc("履歴事項全部証明書", "条件付き", "役所", "応募申請", 条件=_sv("法人の場合", page=27)),
            _doc("見積書", "必須", "外部機関", "交付申請"),
            _doc("賃金引き上げ計画の表明書", "必須", "自社", "交付申請", 形式="指定様式"),
            _doc("研修動画の修了証", "必須", "外部機関", "交付申請"),
            _doc("期限内に出せない理由書", "条件付き", "自社", "交付申請", 条件=_sv("期限内に交付申請を出せないとき", page=27)),
            _doc("会社案内", "任意", "自社", "交付申請"),
            _doc("実績報告書", "必須", "自社", "実績報告"),
        ],
        "様式": [{"名前": "【参考様式】事業計画書"}],
        "手続きの段階": [
            {"id": "応募申請", "順番": 1, "名前": "応募申請", "フォルダ": "1_申請",
             "期限": {"値": None, "状態": "読み取れない", "理由": "締切は12月下旬の予定で、日が決まっていない"}},
            {"id": "採択発表", "順番": 2, "名前": "採択発表"},
            {"id": "交付申請", "順番": 3, "名前": "交付申請", "フォルダ": "2_交付申請",
             "始まる条件": _sv("採択を受けた後", page=38),
             "期限": _sv(_after("採択発表日", 2, "か月"), page=26),
             "書類": ["見積書", "賃金引き上げ計画の表明書", "研修動画の修了証", "期限内に出せない理由書", "会社案内"],
             "画面": "申請システム",
             "注意": [_sv("期限までに交付申請がなければ、採択の取り消し", page=27),
                      _sv("見積書は2者以上から取る", page=25)]},
            {"id": "交付決定", "順番": 4, "名前": "交付決定"},
            {"id": "実施", "順番": 5, "名前": "補助事業の実施",
             "期限": _sv({"種類": "早いほう", "期限": [_after("交付決定日", 17, "か月"), _after("採択発表日", 19, "か月")]},
                         page=26)},
            {"id": "実績報告", "順番": 6, "名前": "実績報告", "フォルダ": "3_実績報告",
             "期限": _sv({"種類": "早いほう", "期限": [_after("補助事業が完了", 30, "日"), _after("採択発表日", 19, "か月")]},
                         page=39)},
            {"id": "効果報告", "順番": 7, "名前": "効果報告", "フォルダ": "4_効果報告",
             "期限": _sv({"種類": "繰り返し", "回数": 5, "間隔": {"数": 1, "単位": "年"},
                          "提出期間": {"始まりの月": 4, "長さ": {"数": 3, "単位": "か月"}}}, page=40)},
        ],
        "してはいけないこと": [
            {"名前": "事前着手", "内容": _sv("交付決定の前に発注・契約した経費は、補助の対象にならない", page=22)},
            {"名前": "二重受給", "内容": _sv("同じ事業で複数の補助金を受けない", page=14)},
        ],
    }


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


class Shop:
    """道具で用意した会社のフォルダに、案件（1_申請 の段階）と制度データを置いたもの。"""

    def __init__(self, tmp_path: Path, data: dict = None) -> None:
        self.company = vt.Company(tmp_path, name="試し 製作所")
        self.folder = self.company.folder
        listed = {"案件": CASE, "制度": {"名前": "試し省力補助金", "略称": SHORT, "枠": "一般型", "種類": "補助金",
                                        "公募回": "第4回"},
                  "案件の回": "第4回", "資料": [{"id": "要領3", "名前": "公募要領", "公募回": "第3回"}]}
        _write_json(self.folder / "記録" / "資料の本文" / CASE / "資料の一覧.json", listed)
        _write_json(self.folder / "記録" / "制度データ" / f"{SHORT}_第3回.json", data or seido())
        for sub in ("申請書", "添付する書類"):
            (self.folder / CASE_DIR / "1_申請" / sub).mkdir(parents=True, exist_ok=True)

    def set_today(self, today: str) -> None:
        path = self.folder / ".hojokin" / "設定.json"
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        value["今日の日付"] = today
        _write_json(path, value)

    def run(self, *args: str) -> subprocess.CompletedProcess:
        env = self.company.env
        return subprocess.run([hr.real_python(), "-B", str(env.plugin / TOOL), "--folder", str(self.folder), *args],
                              env={"PATH": env.path, "HOME": str(env.home), "TMPDIR": str(env.tmp)}, cwd=env.cwd,
                              capture_output=True, timeout=120)

    def tool(self, *args: str, code: int = 0) -> str:
        r = self.run(*args)
        out = r.stdout.decode("utf-8")
        assert r.returncode == code, (r.returncode, out, r.stderr.decode("utf-8"))
        assert r.stderr == b"", r.stderr.decode("utf-8")
        return out

    def ledger(self) -> dict:
        return json.loads((self.folder / LEDGER).read_text(encoding="utf-8"))

    def snapshot(self) -> dict:
        """会社のフォルダの中身（版の履歴の .git を除く）。場所 → 中身（フォルダは None）。"""
        found = {}
        for root, dirs, files in os.walk(self.folder):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in dirs:
                found[os.path.relpath(os.path.join(root, name), self.folder)] = None
            for name in files:
                path = os.path.join(root, name)
                found[os.path.relpath(path, self.folder)] = None if os.path.islink(path) else Path(path).read_bytes()
        return found


def section(text: str, title: str) -> list:
    """結果の文の、見出し（## か ###）の下の「- 」の行。"""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.lstrip("#").strip() == title)
    out = []
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        if line.startswith("- "):
            out.append(line)
    return out


def names(lines: list) -> list:
    return [line[2:].split("｜", 1)[0] for line in lines if "｜" in line]


@pytest.fixture
def shop(tmp_path) -> Shop:
    s = Shop(tmp_path)
    s.set_today("2027-03-16")  # 日付を進めて、採択の後にする（本当の今日は 2026年11月）
    return s


# ---- 切り替え ----


def test_switch_makes_next_stage_folder_document_list_and_deadline(shop) -> None:
    out = shop.tool("--event", "採択発表日=2027-03-10")

    # 次の段階（2_交付申請）のフォルダだけを作る。中は「申請書」と「添付する書類」
    case = shop.folder / CASE_DIR
    assert {p.name for p in (case / "2_交付申請").iterdir()} == {"申請書", "添付する書類"}
    assert not (case / "3_実績報告").exists() and not (case / "4_効果報告").exists()
    assert "採択後の次の段階「交付申請」へ切り替えました" in out
    assert "段階：応募申請 → 交付申請（今の段階）" in out
    assert f"段階のフォルダを作りました：{CASE_DIR}/2_交付申請/" in out

    # 今日は差し替えた日付。期限は採択発表日から2か月で、あと何日も差し替えた今日から数える
    assert "今日：2027年3月16日（火）（日付を差し替えています）" in out
    deadline = section(out, "交付申請の期限")
    assert deadline[0] == "- 2027年5月10日（月）（確定）（あと55日）"
    assert "- もとにした日：採択発表日 2027年3月10日（水）（確定。出典：社長の答え）" in deadline
    assert "- 出典：要領3 p.26" in deadline
    assert "- 始まる条件：採択を受けた後（要領3 p.38）" in deadline

    # 書類の一覧：手続きが「交付申請」の書類だけを、必須・条件付き・任意に分ける（申請・実績報告の書類は混ぜない）
    assert "## 交付申請の書類（制度データの書類のうち、手続きが「交付申請」のもの。5件）" in out
    required = section(out, "必須（3件）")
    assert names(required) == ["見積書", "賃金引き上げ計画の表明書", "研修動画の修了証"]
    assert "見積書｜外部機関｜集める書類｜見当たらない" in required[0]
    assert "賃金引き上げ計画の表明書｜自社｜様式で作る書類｜様式で作る（申請書）" in required[1]
    conditional = section(out, "条件付き（1件）。条件に当たるときだけ出す")
    assert names(conditional) == ["期限内に出せない理由書"]
    assert "条件：期限内に交付申請を出せないとき（要領3 p.27）" in conditional[0]
    assert names(section(out, "任意（1件）")) == ["会社案内"]
    for other in ("決算書", "履歴事項全部証明書", "実績報告書"):
        assert other not in out, other

    # 交付決定の前なので、事前着手を強く注意する。段階の注意も出典つきで添える
    assert section(out, "特に注意（交付決定の前）") == [
        "- 事前着手：交付決定の前に発注・契約した経費は、補助の対象にならない（要領3 p.22）"]
    assert "- 期限までに交付申請がなければ、採択の取り消し（要領3 p.27）" in section(out, "交付申請の注意（制度データから）")

    # この後の段階の期限も、記録した採択発表日から出す（分からない出来事があるものは「遅くとも」）
    later = section(out, "この後の段階の期限（今の状態の組み立てから）")
    assert later[0].startswith("- 補助事業の実施：遅くとも 2028年10月10日（火）（確定）（あと574日）")
    assert later[1].startswith("- 実績報告：遅くとも 2028年10月10日（火）")
    assert "効果報告：日付はまだ出せません" in later[2]
    # 前の段階の提出版がないこと、制度データの回が案件の回と違うことを知らせる
    notes = "\n".join(section(out, "知らせること"))
    assert "前の段階（1_申請）の提出版が記録されていません" in notes
    assert "制度データは第3回の資料から作ったもので、この案件は第4回です" in notes

    # 採択発表日は、期限の台帳の「出来事」に「確定」として残る
    assert shop.ledger() == {"出来事": [{"案件": CASE, "名前": "採択発表日", "日付": "2027-03-10", "状態": "確定",
                                         "出典": "社長の答え", "記録した日": "2027-03-16"}]}


def test_dates_follow_the_substituted_today_and_the_status_assembly(shop) -> None:
    """日付を進めると、あと何日が変わる。開いたときの期限と今の状態.html（M3 の組み立て）にも同じ期限が出る。"""
    shop.tool("--event", "採択発表日=2027-03-10")
    shop.set_today("2027-04-20")
    shown = shop.tool("--show")
    assert "交付申請の書類の一覧と期限です" in shown and "何も書いていません" in shown
    assert section(shown, "交付申請の期限")[0] == "- 2027年5月10日（月）（確定）（あと20日）"
    assert "今日：2027年4月20日（火）（日付を差し替えています）" in shown

    text = vt.start_context(shop.company.start_raw("startup"))
    near = text[text.index("### 近い締切（30日以内）"):text.index("### 遅れている作業")]
    line = next(x for x in near.splitlines() if f"｜{CASE}｜交付申請の期限" in x)
    assert line.startswith("- 2027年5月10日（月）（確定）（あと20日）｜")
    assert "もとにした日：採択発表日 2027年3月10日（水）（確定。出典：社長の答え）" in line
    # 見当たらない書類の数に、様式で作る書類を入れていないことを書き添える（実験 E9 で、様式を「もうある」と読んだ応答があった）
    assert "見当たらないもの 2件（見積書、研修動画の修了証）" in line
    assert "様式で作る必須の書類 1件は、これから作る申請書なので、集める書類の数には入れていません" in line
    assert "今日：2027年4月20日（火）（日付を差し替えています）" in text
    page = (shop.folder / "今の状態.html").read_text(encoding="utf-8")
    assert "今の段階：交付申請" in page and "2027年5月10日（月）" in page


def test_without_the_event_date_it_switches_and_asks_for_the_date(shop) -> None:
    """採択発表日が分からなければ、切り替えはするが、期限は決め方だけ示す。後から日付を渡すと期限が出る。"""
    out = shop.tool(code=1)
    assert (shop.folder / CASE_DIR / "2_交付申請" / "申請書").is_dir()
    deadline = section(out, "交付申請の期限")
    assert deadline[0] == "- 日付はまだ出せません（「採択発表日」から2か月。「採択発表日」の日付が分かってから出します）"
    assert any("決め方にある出来事（採択発表日）の日付を" in x and "--event で渡し直してください" in x for x in deadline)
    assert not (shop.folder / LEDGER).exists()

    again = shop.tool("--stage", "2_交付申請", "--event", "採択発表日=2027-03-10")
    assert "今の段階「交付申請」のままです" in again
    assert f"段階のフォルダは、もうあります：{CASE_DIR}/2_交付申請/" in again
    assert section(again, "交付申請の期限")[0] == "- 2027年5月10日（月）（確定）（あと55日）"


def test_rerun_without_stage_keeps_the_stage(shop) -> None:
    """期限が出なかった後に --event だけを足して流し直しても、日付を直しても、交付申請を飛ばさない。"""
    shop.tool(code=1)
    again = shop.tool("--event", "採択発表日=2027-03-10")
    assert "今の段階「交付申請」のままです" in again
    assert "段階は進めていません" in again
    assert section(again, "交付申請の期限")[0] == "- 2027年5月10日（月）（確定）（あと55日）"
    fixed = shop.tool("--event", "採択発表日=2027-03-12")
    assert "前に残っていた 2027年3月10日（水） から直しました" in fixed
    assert "今の段階「交付申請」のままです" in fixed
    assert not (shop.folder / CASE_DIR / "3_実績報告").exists()
    # 今の段階の期限にない出来事を渡したときは、次の段階へ進む
    later = shop.run("--event", "交付決定日=2027-03-15")
    assert later.returncode in (0, 1), later.stderr.decode("utf-8")
    assert "「実績報告」へ切り替えました" in later.stdout.decode("utf-8")
    assert (shop.folder / CASE_DIR / "3_実績報告" / "申請書").is_dir()


def test_schedule_gives_an_estimate_when_no_date_is_recorded(tmp_path) -> None:
    """制度データに採択発表の予定（3月上旬）があれば、日付を渡さなくても「見込み」の期限を出す。"""
    shop = Shop(tmp_path, seido(schedule={"年月": "2027-03", "旬": "上旬"}))
    shop.set_today("2027-03-16")
    out = shop.tool()
    assert section(out, "交付申請の期限")[0] == "- 2027年5月1日（土）〜2027年5月10日（月）のどこか（見込み）（あと46日）"
    # 確かめた日付を渡すと、予定より先に使い、見込みでなくなる
    fixed = shop.tool("--stage", "2_交付申請", "--event", "採択発表日=2027-03-05")
    assert section(fixed, "交付申請の期限")[0] == "- 2027年5月5日（水）（確定）（あと50日）"


def test_correcting_the_date_keeps_one_event_and_other_entries(shop) -> None:
    other = {"案件": "2025_別の補助第1回", "名前": "採択発表日", "日付": "2025-09-01", "状態": "確定", "出典": "社長の答え",
             "記録した日": "2025-09-02"}
    _write_json(shop.folder / LEDGER, {"作業": [{"名前": "K1 が足す欄"}], "出来事": [other]})
    shop.tool("--event", "採択発表日=2027-03-10")
    out = shop.tool("--stage", "2_交付申請", "--event", "採択発表日＝2027-03-12")
    assert "前に残っていた 2027年3月10日（水） から直しました" in out
    ledger = shop.ledger()
    assert ledger["作業"] == [{"名前": "K1 が足す欄"}]
    mine = [e for e in ledger["出来事"] if e["案件"] == CASE]
    assert [e["日付"] for e in mine] == ["2027-03-12"] and other in ledger["出来事"]
    assert section(out, "交付申請の期限")[0] == "- 2027年5月12日（水）（確定）（あと57日）"


def test_document_states_come_from_the_ledger_and_the_attach_folder(shop) -> None:
    """集める書類は、書類の台帳に同じ種類の原本があるか、その段階の「添付する書類」にあるかを示す。"""
    _write_json(shop.folder / "記録" / "書類の台帳.json",
                {"説明": "架空", "原本": [{"場所": "原本/見積・契約・請求/2027-03-01_見積書_架空機械.pdf", "種類": "見積書"}],
                 "確かめ済み": []})
    shop.tool("--event", "採択発表日=2027-03-10")
    attach = shop.folder / CASE_DIR / "2_交付申請" / "添付する書類" / "研修動画の修了証.pdf"
    attach.write_bytes(b"%PDF-1.4")
    out = shop.tool("--show")
    required = section(out, "必須（3件）")
    assert "見積書｜外部機関｜集める書類｜台帳にあり" in required[0]
    assert "研修動画の修了証｜外部機関｜集める書類｜添付する書類にあり" in required[2]


def test_source_can_be_the_notice_original(shop) -> None:
    notice = "原本/役所からの通知/2027-03-10_採択の通知_事務局.pdf"
    path = shop.folder / notice
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("%PDF-1.4 （架空の通知）".encode("utf-8"))
    out = shop.tool("--event", "採択発表日=2027-03-10", "--source", notice)
    assert f"採択発表日 2027年3月10日（水）（確定。出典：{notice}）" in out
    assert shop.ledger()["出来事"][0]["出典"] == notice


def test_a_later_stage_can_be_named_and_the_folder_list_follows(shop) -> None:
    """--stage で、フォルダのある後の段階を選べる。その段階の書類だけを並べる。交付決定の後なので事前着手は添えない。"""
    out = shop.tool("--stage", "3_実績報告", "--event", "採択発表日=2027-03-10")
    assert (shop.folder / CASE_DIR / "3_実績報告" / "添付する書類").is_dir()
    assert names(section(out, "必須（1件）")) == ["実績報告書"]
    assert "特に注意" not in out
    assert section(out, "実績報告の期限")[0].startswith("- 遅くとも 2028年10月10日（火）")


# ---- 断るとき（何も書かない） ----


@pytest.mark.parametrize("args, message", [
    (["--event", "採択発表日=2027-03-20"], "採択発表日（2027年3月20日（土））が、今日（2027年3月16日（火））より後です"),
    (["--event", "採択日=2027-03-10"], "制度データの期限の決め方にない出来事です：採択日（使える出来事：採択発表日・交付決定日・補助事業が完了）"),
    (["--event", "採択発表日=3月10日"], "出来事は「採択発表日=2027-03-10」の形で渡してください"),
    (["--event", "採択発表日=2027-02-30"], "日付として正しくありません"),
    (["--stage", "9_ない段階"], "手続きの段階にないフォルダの名前です：9_ない段階（段階のフォルダは 1_申請・2_交付申請・3_実績報告・4_効果報告）"),
    (["--show", "--event", "採択発表日=2027-03-10"], "一覧を見るだけのときは、出来事の日付を渡せません"),
    (["--event", "採択発表日=2027-03-10", "--source", "原本/役所からの通知/ない通知.pdf"], "出典の原本（原本/役所からの通知/ない通知.pdf）が見つかりません"),
])
def test_refusals_write_nothing(shop, args, message) -> None:
    before = shop.snapshot()
    out = shop.tool(*args, code=2)
    assert out.startswith("何も書いていません。")
    assert message in out
    assert shop.snapshot() == before


def test_backward_and_past_the_last_stage_are_refused(shop) -> None:
    # 効果報告の期限（毎年の繰り返し）は、事業の完了と決算の月が分かるまで日付が出ない（終了コード 1）。
    # 渡せる出来事はないので、--event で渡し直すようには促さない
    out = shop.tool("--stage", "4_効果報告", "--event", "採択発表日=2027-03-10", code=1)
    deadline = section(out, "効果報告（1年目）の期限")  # 繰り返しの報告は、次に出す回を見出しに付ける（B31a）
    assert "- 毎年の期限は、事業の完了と決算の月が分かってから出します（期限の台帳で扱います）" in deadline
    assert not any("--event" in x for x in deadline)
    before = shop.snapshot()
    assert "今の段階（4_効果報告）より前の段階（2_交付申請）には切り替えません" in shop.tool("--stage", "2_交付申請", code=2)
    assert shop.snapshot() == before
    # 最後の段階でも、繰り返しの報告でまだ出していない回があれば、段階は進めずに次の回（1年目）の年のフォルダを作る（B31a）。
    # 最後の段階で断るのは、すべての回の提出版を記録した後（tests/test_postaward_shoryokuka.py が次の回を確かめる）
    out = shop.tool(code=1)
    assert "今の段階「効果報告（1年目）」のままです" in out, out
    assert (shop.folder / CASE_DIR / "4_効果報告" / "1年目" / "添付する書類").is_dir()


def test_show_writes_nothing(shop) -> None:
    before = shop.snapshot()
    out = shop.tool("--show")
    assert "応募申請の書類の一覧と期限です" in out
    # 申請の期限は、段階では読み取れないので、決まった期日の「第4回 公募締切日」（予定）から出す（M3 と同じ）
    assert section(out, "応募申請の期限")[0] == "- 2027年1月下旬（日はまだ決まっていません）（見込み）（44日過ぎています）"
    assert names(section(out, "必須（1件）")) == ["決算書"]
    assert names(section(out, "条件付き（1件）。条件に当たるときだけ出す")) == ["履歴事項全部証明書"]
    assert shop.snapshot() == before


def test_unreadable_ledger_writes_nothing_and_does_not_stop_the_start(shop) -> None:
    (shop.folder / LEDGER).write_text("{ 壊れた", encoding="utf-8")
    before = shop.snapshot()
    out = shop.tool("--event", "採択発表日=2027-03-10", code=2)
    assert "期限の台帳（記録/期限の台帳.json）が JSON として読めません" in out
    assert shop.snapshot() == before
    # 開いたときの組み立ては止めずに、わけを示す
    text = vt.start_context(shop.company.start_raw("startup"))
    assert "記録した出来事の日付を使わずに、期限を組み立てました" in text


def test_ledger_link_writes_nothing(shop, tmp_path) -> None:
    outside = tmp_path / "外" / "期限の台帳.json"
    outside.parent.mkdir()
    outside.write_text('{"出来事": []}', encoding="utf-8")
    os.symlink(outside, shop.folder / LEDGER)
    before = shop.snapshot()
    out = shop.tool("--event", "採択発表日=2027-03-10", code=2)
    assert f"{LEDGER} が別名（シンボリックリンク）になっているため、出来事の日付を期限の台帳に残していません" in out
    assert shop.snapshot() == before
    assert outside.read_text(encoding="utf-8") == '{"出来事": []}'
    assert not (shop.folder / CASE_DIR / "2_交付申請").exists()


def test_stage_folder_link_writes_nothing(shop, tmp_path) -> None:
    """切り替える先の段階のフォルダが別名なら、台帳にも書かずに断る。

    今の状態の組み立て（M3）は、段階のフォルダの名前だけを見るので、別名の 2_交付申請 も「ある」とみなし、今の段階を交付申請にする。
    そのため、ここでは切り替える先を --stage で渡す。
    """
    outside = tmp_path / "外の段階"
    outside.mkdir()
    os.symlink(outside, shop.folder / CASE_DIR / "2_交付申請")
    before = shop.snapshot()
    out = shop.tool("--stage", "2_交付申請", "--event", "採択発表日=2027-03-10", code=2)
    assert f"{CASE_DIR}/2_交付申請 が別名（シンボリックリンク）になっているため、段階のフォルダを作りません" in out
    assert shop.snapshot() == before
    assert list(outside.iterdir()) == []
    assert not (shop.folder / LEDGER).exists()


def test_grant_decision_without_a_deadline_rule_is_recorded_without_switching(tmp_path) -> None:
    """持続化のように、交付決定がどの段階の期限の決め方にもない制度でも、交付決定の日を台帳に残せる（段階は進めない）。
    書類の確かめ（shorui の fubi.py rules）は、その日を交付決定の日として返す（事前着手の確かめに使う。TASKS B31c）。"""
    data = json.loads((hr.REPO_ROOT / "testdata" / "正解" / "持続化_第20回.json").read_text(encoding="utf-8"))
    shop = Shop(tmp_path, data)
    case = "2026_持続化（通常枠）第20回"
    listed = {"案件": case, "制度": {"名前": "小規模事業者持続化補助金", "略称": "持続化", "公募回": "第20回"},
              "案件の回": "第20回", "資料": []}
    _write_json(shop.folder / "記録" / "資料の本文" / case / "資料の一覧.json", listed)
    _write_json(shop.folder / "記録" / "制度データ" / "持続化_第20回.json", data)
    (shop.folder / "記録" / "制度データ" / f"{SHORT}_第3回.json").unlink()
    for sub in ("申請書", "添付する書類"):
        (shop.folder / "案件" / case / "1_申請" / sub).mkdir(parents=True, exist_ok=True)
    shutil.rmtree(shop.folder / CASE_DIR)
    shop.set_today("2027-03-15")
    out = shop.tool("--case", case)
    assert "採択後の次の段階「見積書等の提出（採択後）」へ切り替えました" in out, out
    assert "特に注意（交付決定の前）" in out and "事前着手" in out
    shop.set_today("2027-04-26")
    out = shop.tool("--case", case, "--event", "交付決定=2027-04-23")
    assert "今の段階「見積書等の提出（採択後）」のままです" in out, out
    assert "交付決定 2027年4月23日（金）（確定" in out, out
    assert not (shop.folder / "案件" / case / "3_実績報告").exists()
    events = [(e["案件"], e["名前"], e["日付"]) for e in shop.ledger()["出来事"]]
    assert events == [(case, "交付決定", "2027-04-23")]
    fubi = subprocess.run([hr.real_python(), "-B", str(hr.REPO_ROOT / "skills" / "shorui" / "scripts" / "fubi.py"), "rules",
                           "--folder", str(shop.folder), "--case", case, "--stage", "2_見積書等の提出"],
                          capture_output=True, text=True, timeout=60)
    assert json.loads(fubi.stdout)["交付決定の日"] == "2027-04-23", fubi.stdout + fubi.stderr


# ---- 期限が読み取れない段階の手がかり（11/7 の採択後の通し） ----


def _page(doc_dir: Path, number: int, text: str) -> dict:
    """資料の本文の1ページ（lib/doc_text.write_text と同じ形。1行目は見出し）。"""
    name = f"ページ_{number:03d}.txt"
    (doc_dir / name).write_text(f"【架空の公募要領／印刷されたページ {number}】\n\n{text}", encoding="utf-8")
    return {"PDFのページ": number, "印刷されたページ": number, "番号を見つけた": True, "文字数": len(text), "ファイル": name}


def test_unread_deadline_shows_clue_from_another_chapter_and_keeps_data(tmp_path) -> None:
    """交付申請の期限を、採択後の章（p.38）だけで読ませて「読み取れない」になった制度データ。期限の定めは別の章（p.26 の
    実施期間の節の※書き）にある。切り替えの道具と制度データの確かめの道具が、そのページと文と決め方の見当を示し、
    制度データは書き換えない。出来事の名前として段階の語を使っただけの文（「交付申請日から」）は、手がかりにしない。
    資料の文は、公募要領の文を写さず、このテストのために書いた架空のもの。"""
    data = seido()
    stage = next(s for s in data["手続きの段階"] if s["id"] == "交付申請")
    stage["期限"] = {"値": None, "状態": "読み取れない", "理由": "p.38 には「早めに出す」とだけある"}
    shop = Shop(tmp_path, data)
    shop.set_today("2027-03-16")
    doc_dir = shop.folder / "記録" / "資料の本文" / CASE / "要領3"
    doc_dir.mkdir(parents=True)
    pages = [
        _page(doc_dir, 26, "（3）実施期間\n交付決定の日から17か月の内に終える。\n※ 交付申請は、なるべく\n"
                           "採択発表日から２か月後の日までに出すこと（架空の資料の文）。"),
        _page(doc_dir, 27, "実績報告は、交付申請日から30日の内に出す決まりではありません。期限は別に示します。"),
        _page(doc_dir, 38, "採択の後は、交付申請を早めに出す。"),
    ]
    index = {"資料": "要領3", "名前": "公募要領", "公募回": "第3回", "ファイル": "公式資料/要領.pdf", "ハッシュ": "",
             "種類": "PDF", "ページ数": 38, "ページのずれ": 0, "ページ": pages}
    _write_json(doc_dir / "ページの対応.json", index)
    data_file = shop.folder / "記録" / "制度データ" / f"{SHORT}_第3回.json"
    before = data_file.read_bytes()

    out = shop.tool("--event", "採択発表日=2027-03-10", code=1)
    deadline = section(out, "交付申請の期限")
    assert deadline[0].startswith("- 日付はまだ出せません（資料から読み取れませんでした"), deadline
    # 文は形をそろえたもの（NFKC。改行と空白を除き、全角の数字とかっこは半角になる）
    clue = "要領3 p.26「…交付申請は、なるべく採択発表日から2か月後の日までに出すこと(架空の資料の文)」（決め方の見当：採択発表日から2か月）"
    assert f"  - {clue}" in out.splitlines(), out
    assert any("junbi の手順（制度データの期限の抜けを直す）" in line for line in deadline), deadline
    assert "なければ事務局への問い合わせ文の案を作ってください" not in out  # 手がかりがあるときは、問い合わせに回さない
    assert "要領3 p.27「" not in out  # 「交付申請日から」は出来事の名前なので、交付申請の期限の手がかりにしない
    assert data_file.read_bytes() == before  # 制度データは書き換えない

    # 制度データの確かめ（--check）の終わりにも、同じ手がかりを出す（終了コードには響かせない）
    r = subprocess.run([hr.real_python(), "-B", str(hr.REPO_ROOT / "skills" / "junbi" / "scripts" / "seido_data.py"),
                        "--folder", str(shop.folder), "--case", CASE, "--check"], capture_output=True, timeout=120)
    checked = r.stdout.decode("utf-8")
    assert "読み取れないとした段階の期限に、資料の本文で当たりそうな文：1段階" in checked, checked
    assert f"  - {clue}" in checked.splitlines(), checked
    assert data_file.read_bytes() == before

    # 期限の定めが資料にない段階（手がかりがない）は、今までどおり問い合わせに回す
    (doc_dir / "ページ_026.txt").write_text("【架空】\n\n（3）実施期間\n交付決定の日から17か月の内に終える。", encoding="utf-8")
    out = shop.tool("--show", code=1)
    assert "資料の本文に、期限らしい文があります" not in out
    assert "なければ事務局への問い合わせ文の案を作ってください" in out


# ---- 工程表の帯の始まり（11/7 の採択後の通し：補助事業の実施の帯が、採択より前・交付決定より前から塗られた） ----


def _bars(folder: Path) -> dict:
    from lib import deadlines, status_book
    ov = deadlines.build(folder)
    return {b.label: b for b in status_book.bars(ov) if b.case == CASE}


def test_gantt_bars_start_at_the_starting_event(shop) -> None:
    """帯は、段階が始まる出来事の日付から。交付申請は期限の決め方の出来事（採択発表日）、補助事業の実施は交付決定日から。
    交付決定日が分からないうちは見込み（斜線）とし、前の段階の期限の次の日より前・採択発表日より前には塗らない。
    交付決定日を残すと、その日からの確定の帯になる。画面は g-est の斜線、Excel は見込みの帯の書式（5）で区別する。"""
    from datetime import date

    shop.tool("--event", "採択発表日=2027-03-10")
    bars = _bars(shop.folder)
    apply_bar, run_bar = bars["交付申請"], bars["補助事業の実施"]
    assert (apply_bar.start, apply_bar.end, apply_bar.estimate) == (date(2027, 3, 10), date(2027, 5, 10), False)
    assert run_bar.estimate and run_bar.start == date(2027, 5, 11), run_bar  # 交付申請の期限の次の日から（見込み）
    assert run_bar.state == "これから。始まりは見込み"
    page = (shop.folder / "今の状態.html").read_text(encoding="utf-8")
    assert 'class="g g-est' in page and "斜線の帯は、始まる日がまだ決まっていないので" in page
    import zipfile
    with zipfile.ZipFile(shop.folder / "今の状態.xlsx") as book:
        sheets = [n for n in book.namelist() if n.startswith("xl/worksheets/")]
        assert any(' s="5"' in book.read(n).decode("utf-8") for n in sheets)

    # 交付決定日を残すと、その日からの帯（見込みでない）
    shop.set_today("2027-05-25")
    shop.tool("--stage", "2_交付申請", "--event", "交付決定日=2027-05-20")
    run_bar = _bars(shop.folder)["補助事業の実施"]
    assert (run_bar.start, run_bar.estimate, run_bar.state) == (date(2027, 5, 20), False, "これから")


def test_gantt_bar_never_starts_before_the_recorded_award(tmp_path) -> None:
    """交付申請の期限が制度データにない（読み取れない）とき、前の段階は申請の締切（2027年1月下旬）だけになる。それでも
    補助事業の実施の帯を、記録した採択発表日より前（申請の締切の次の日 2027-02-01）から塗らない（11/7 の通しの形）。"""
    from datetime import date

    data = seido()
    stage = next(s for s in data["手続きの段階"] if s["id"] == "交付申請")
    stage["期限"] = {"値": None, "状態": "読み取れない", "理由": "期限の定めがない"}
    shop = Shop(tmp_path, data)
    shop.set_today("2027-03-16")
    shop.tool("--event", "採択発表日=2027-03-10", code=1)
    bars = _bars(shop.folder)
    assert "交付申請" not in bars
    run_bar = bars["補助事業の実施"]
    assert run_bar.estimate and run_bar.start == date(2027, 3, 16), run_bar  # 採択発表日と今日のうち遅い日から
    assert run_bar.start >= date(2027, 3, 10)
