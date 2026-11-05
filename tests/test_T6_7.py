"""T6-7 事業期間中と事業後の義務（SPEC F6「事業期間中の義務」「事業後の義務」、DESIGN 4.5・4.6・9章の義務の行。TASKS K3）。

合格ライン：日付を、交付決定の後、決算月の後、翌年の最低賃金の改定の後へと進める → 経費ごとの証拠の揃い具合、
計画変更の事前の申請の注意、効果報告の数字の用意、事業場内最低賃金の確かめ、処分の制限と書類を残す期間が、
それぞれの時期に示される。

- 材料：省力化 第8回の制度データの正解（testdata/正解/。資料の文を写さない形）に、義務の下書き
  （tests/data/gimu/省力化_第8回_義務.json）を足したもの。日付は testdata/期限 の正解と同じ（採択発表 2027-04-16、
  交付決定 2027-06-25）。事業の完了は 2028-01-31、決算は3月（回答表 A-10）とした。
- 交付決定の後（2027-07-10）：事業期間中。経費明細の行ごとに、証拠の書類の種類（見積書・発注書・納品書…）がそろったか。
  交付決定より前の日付の発注書は数えずに知らせる。計画変更の事前の承認の注意。事業後の義務（処分の制限など）はまだ出さない。
- 決算月の後（2029-04-05。完了した事業年度の翌年度＝1年目が 2029-03-31 に終わった後）：事業後。効果報告（1年目）の
  数字を用意する作業、処分の制限（期間は資料から読み取れない）と、書類を残す期間（完了の年度の終わりから5年 = 2033-03-31）。
- 翌年の最低賃金の改定の後（2029-10-05）：事業場内最低賃金を確かめる作業が、近い締切に出る。
- 開いたときの文と今の状態.html にも出る。義務の欄がない制度データでは、出せないことを知らせ、計画変更は手続きの段階から出す。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import hook_runner as hr
from jsonschema import Draft202012Validator
from lib import deadlines, status_view

CASE = "2026_省力化（一般型）第9回"
DATA = hr.REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json"
DUTIES = hr.REPO_ROOT / "tests" / "data" / "gimu" / "省力化_第8回_義務.json"
SCHEMA = json.loads((hr.REPO_ROOT / "schema" / "制度データ.schema.json").read_text(encoding="utf-8"))
QUOTE = "原本/見積・契約・請求/2026-10-20_見積書_つばさ台フードシステム.pdf"
EARLY_ORDER = "原本/見積・契約・請求/2027-06-10_発注書_つばさ台フードシステム.pdf"
ORDER = "原本/見積・契約・請求/2027-07-01_発注書_つばさ台フードシステム.pdf"
VENDOR = "株式会社つばさ台フードシステム"


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


def seido(with_duties: bool = True) -> dict:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    if with_duties:
        data["義務"] = json.loads(DUTIES.read_text(encoding="utf-8"))["義務"]
        errors = sorted(e.message for e in Draft202012Validator(SCHEMA).iter_errors(data))
        assert errors == [], errors  # 義務を足しても、制度データのスキーマに合う
    return data


def _original(n: int, place: str, kind: str, day: str, partner: str = "") -> dict:
    return {"id": f"原本-{n:04d}", "場所": place, "区分": place.split("/")[1], "種類": kind, "日付": day,
            "相手先": partner, "補足": "", "元の名前": Path(place).name, "元の場所": f"入れ口/{Path(place).name}",
            "ハッシュ": f"{n:064x}", "版の印": "0" * 40, "大きさ": 100, "整理した日時": f"{day}T10:00:00+09:00"}


class Folder:
    def __init__(self, tmp_path: Path, with_duties: bool = True) -> None:
        self.folder = tmp_path / "やまぶき 惣菜"
        (self.folder / ".hojokin").mkdir(parents=True)
        listed = {"案件": CASE, "制度": {"名前": "中小企業省力化投資補助金", "略称": "省力化", "公募回": "第8回"},
                  "案件の回": "第9回", "資料": []}
        _write(self.folder / "記録" / "資料の本文" / CASE / "資料の一覧.json", listed)
        _write(self.folder / "記録" / "制度データ" / "省力化_第8回.json", seido(with_duties))
        for stage in ("1_申請", "2_交付申請"):
            for sub in ("申請書", "添付する書類"):
                (self.folder / "案件" / CASE / stage / sub).mkdir(parents=True, exist_ok=True)
        self.events = [
            {"案件": CASE, "名前": "採択発表", "日付": "2027-04-16", "状態": "確定", "出典": "社長の答え", "記録した日": "2027-04-20"},
            {"案件": CASE, "名前": "交付決定", "日付": "2027-06-25", "状態": "確定", "出典": "社長の答え", "記録した日": "2027-06-28"},
        ]
        self.write_events()
        self.originals = [
            _original(1, QUOTE, "見積書", "2026-10-20", VENDOR),
            _original(2, "原本/見積・契約・請求/2026-10-20_見積書_ほしみ機工.pdf", "見積書", "2026-10-20", "株式会社ほしみ機工"),
            _original(3, EARLY_ORDER, "発注書", "2027-06-10", VENDOR),
            _original(4, ORDER, "発注書", "2027-07-01", VENDOR),
        ]
        self.write_ledger()
        _write(self.folder / "記録" / "経費明細.json", {"案件": [{"案件": CASE, "行": [
            {"経費の区分": "機械装置・システム構築費", "品名": "盛り付けロボット", "金額": 7800000, "根拠": "見積書", "原本": QUOTE},
            {"経費の区分": "機械装置・システム構築費", "品名": "トップシール包装機", "金額": 4800000, "根拠": "見積書", "原本": QUOTE},
        ]}]})
        _write(self.folder / "記録" / "会社の記録.json", {"項目": [
            {"id": "事実-0001", "種類": "事実", "名前": "決算月", "値": "3月"}]})
        self.submissions = [{"案件": CASE, "段階": "1_申請"}, {"案件": CASE, "段階": "2_交付申請"}]
        self.write_submissions()

    def write_events(self) -> None:
        _write(self.folder / "記録" / "期限の台帳.json", {"出来事": self.events})

    def write_ledger(self) -> None:
        _write(self.folder / "記録" / "書類の台帳.json", {"説明": "", "原本": self.originals, "確かめ済み": []})

    def write_submissions(self) -> None:
        _write(self.folder / "記録" / "提出版.json", {"提出版": self.submissions})

    def set_today(self, day: str) -> None:
        _write(self.folder / ".hojokin" / "設定.json", {"今日の日付": day})

    def complete(self) -> None:
        """事業の完了（2028-01-31）を残し、実績報告を出した形にする。"""
        self.events.append({"案件": CASE, "名前": "補助事業の完了", "日付": "2028-01-31", "状態": "確定",
                            "出典": "社長の答え", "記録した日": "2028-02-05"})
        self.write_events()
        for sub in ("申請書", "添付する書類"):
            (self.folder / "案件" / CASE / "3_実績報告" / sub).mkdir(parents=True, exist_ok=True)
        self.submissions.append({"案件": CASE, "段階": "3_実績報告"})
        self.write_submissions()

    def build(self):
        ov = deadlines.build(self.folder)
        case = next(c for c in ov.cases if c.name == CASE)
        assert not case.problem, case.problem
        return ov, case


def all_tasks(ov) -> list:
    return [t for g in deadlines.GROUPS for t in ov.groups[g]] + ov.later + ov.undated + ov.done


def find(ov, head: str):
    found = [t for t in all_tasks(ov) if t.what.startswith(head)]
    assert len(found) == 1, (head, [t.what for t in all_tasks(ov)])
    return found[0]


def duty(case, head: str) -> str:
    found = [d for d in case.duties if d.startswith(head)]
    assert len(found) == 1, (head, case.duties)
    return found[0]


def test_duties_at_each_period(tmp_path: Path) -> None:
    f = Folder(tmp_path)

    # ---- 交付決定の後：事業期間中 ----
    f.set_today("2027-07-10")
    ov, case = f.build()
    assert case.period == "事業期間中"
    assert case.duties[0] == "今は事業期間中（交付決定 2027年6月25日（金） から）です"
    # 経費ごとの証拠の揃い具合（見積書と、交付決定の後の発注書はある。前の日付の発注書は数えずに知らせる）
    assert [(e.expense, e.partner, e.amount) for e in case.evidence] == [
        ("盛り付けロボット", VENDOR, 7800000), ("トップシール包装機", VENDOR, 4800000)]
    for e in case.evidence:
        assert e.have == ["見積書", "発注書・契約書"], e
        assert e.missing == ["納品書", "検収書", "請求書", "銀行振込の控え"], e
        assert e.early == [EARLY_ORDER], e
    task = find(ov, "経費の証拠をそろえる")
    assert task.what == "経費の証拠をそろえる（そろった経費 0/2件）" and task.kind == "証拠"
    assert task.due.last == date(2028, 11, 16)  # 補助事業の実施の期限（採択発表から19か月）
    notes = "。".join(task.notes)
    assert "足りない証拠：納品書 2件、検収書 2件、請求書 2件、銀行振込の控え 2件" in notes, notes
    assert f"事前着手のおそれ" in notes and EARLY_ORDER in notes, notes
    assert "証拠で確かめられない経費は、補助の対象にならない（要領8 p.4、要領8 p.20）" in notes, notes
    # 計画変更の事前の申請の注意。事業後の義務はまだ出さない
    change = duty(case, "計画変更・中止・廃止の事前承認（事前に申請する）：")
    assert "前もって中小機構の承認を受ける（要領8 p.36）" in change, change
    assert not any(d.startswith(("処分制限財産", "帳簿と証拠書類を残す", "事業場内最低賃金")) for d in case.duties)
    assert not any(t.what.startswith("事業実施効果報告（1年目）の数字") for t in all_tasks(ov))
    # 開いたときの文と、今の状態の画面
    text = status_view.deadline_text(ov)
    block = text[text.index(status_view.DUTY_HEAD):]
    assert f"- {CASE}：今は事業期間中（交付決定 2027年6月25日（金） から）です。経費ごとの証拠：そろった経費 0/2件" in block
    assert "計画変更・中止・廃止の事前承認" in block
    page = status_view.render_page(ov, "やまぶき 惣菜", f.folder)
    assert "<h2>事業期間中と事業後の義務</h2>" in page and "経費ごとの証拠の揃い具合" in page
    assert "<td>盛り付けロボット</td><td>株式会社つばさ台フードシステム</td><td>7,800,000円</td>" in page

    # ---- 決算月の後：事業後（1年目が 2029-03-31 に終わった後） ----
    f.complete()
    f.set_today("2029-04-05")
    ov, case = f.build()
    assert case.period == "事業後"
    assert case.duties[0] == "今は事業後（事業の完了 2028年1月31日（月） の後）です"
    assert case.evidence == [] and not any(t.what.startswith("経費の証拠") for t in all_tasks(ov))  # 実績報告を出した後
    prep = find(ov, "事業実施効果報告（1年目）の数字を用意する")
    assert prep.kind == "義務" and prep.due.first == date(2029, 4, 1) and prep.due.last == date(2029, 6, 30)
    assert prep in ov.groups[deadlines.NEAR], [t.what for t in ov.groups[deadlines.NEAR]]
    prep_notes = "。".join(prep.notes)
    assert "決算日（2029年3月31日（土））を過ぎました" in prep_notes, prep_notes
    assert "労働生産性" in prep_notes and "給与支給総額" in prep_notes, prep_notes
    disposal = duty(case, "処分制限財産の処分は前もって承認を受ける（事前に申請する）：")
    assert "終わり：資料から読み取れません（処分制限期間は、減価償却資産の耐用年数の省令で決まる" in disposal, disposal
    assert "残存簿価相当額か時価の高いほう" in disposal, disposal
    keep = duty(case, "帳簿と証拠書類を残す（残す）：")
    assert "終わり：2033年3月31日（木）" in keep, keep
    assert not any(d.startswith("計画変更") for d in case.duties)  # 事業期間中の注意は、もう出さない
    wage = find(ov, "事業場内最低賃金を確かめる")
    assert wage.what == "事業場内最低賃金を確かめる（2029年の地域別最低賃金の改定の後）"
    assert wage in ov.later and wage.due.estimate
    text = status_view.deadline_text(ov)
    assert "処分制限財産の処分は前もって承認を受ける" in text and "帳簿と証拠書類を残す" in text

    # ---- 翌年の最低賃金の改定の後 ----
    f.set_today("2029-10-05")
    ov, case = f.build()
    wage = find(ov, "事業場内最低賃金を確かめる")
    assert wage.what == "事業場内最低賃金を確かめる（2029年の地域別最低賃金の改定の後）"
    assert wage in ov.groups[deadlines.NEAR], [t.what for t in ov.groups[deadlines.NEAR]]
    assert wage.due.label() == "確かめる時期 2029年10月1日（月）〜2029年10月31日（水）（見込み）"
    assert "所在地の都道府県の公表を確かめ" in "。".join(wage.notes)
    assert "事業場内最低賃金を確かめる（2029年" in status_view.deadline_text(ov)
    # 1年目の数字の用意は、提出期間が過ぎたら出さない（効果報告の期限切れは、段階の作業が知らせる）
    assert not any(t.what.startswith("事業実施効果報告（1年目）の数字") for t in all_tasks(ov))


def test_without_duties_in_seido_data(tmp_path: Path) -> None:
    """義務の欄がない制度データ（今の正解）では、出せないことを知らせ、計画変更の注意は手続きの段階から出す。"""
    f = Folder(tmp_path, with_duties=False)
    f.set_today("2027-07-10")
    ov, case = f.build()
    assert case.period == "事業期間中"
    assert case.evidence == [] and "制度データに「義務」の欄がない" in case.evidence_note
    assert any(d.startswith("計画変更・中止・廃止の承認（事前に申請する）：交付決定後に") for d in case.duties), case.duties
    assert any("処分の制限・書類を残す期間・経費ごとの証拠は出していません" in d for d in case.duties), case.duties
    find(ov, "事業場内最低賃金を確かめる")  # 数値の要件の事業場内最低賃金から


def test_nothing_before_the_grant_decision(tmp_path: Path) -> None:
    """交付決定の前は、義務の作業も知らせも出さない（事前着手の注意は、段階の切り替えと書類の確かめが出す）。"""
    f = Folder(tmp_path)
    f.events = f.events[:1]
    f.write_events()
    f.set_today("2027-05-10")
    ov, case = f.build()
    assert case.period == "" and case.duties == [] and case.evidence == []
    assert not any(t.kind in ("証拠", "義務") for t in all_tasks(ov))
    assert status_view.DUTY_HEAD not in status_view.deadline_text(ov)
