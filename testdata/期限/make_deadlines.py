# /// script
# requires-python = ">=3.9"
# dependencies = ["reportlab>=4"]
# ///
"""期限の材料（TASKS D13）を作る。

作るもの（`材料/` の下。テストで会社のフォルダに写すのは、ここの書類だけ）：
- 通知：省力化（一般型）第9回の採択の通知と交付決定通知書、持続化 第20回の採択通知書と交付決定通知書（どれも PDF。日付入り）
- 納税証明書（その2）：第19期の決算日（2027-03-31）の前に取ったもの（第16〜18期）と、
  第19期の申告の後に取り直したもの（第17〜19期）。決算日をまたいで、直近3期が入れ替わる
- 外部への依頼で届く書類：信用金庫からの金融機関確認書（台本で、社長が入れ口に入れる）

あわせて `正解.json` を作る。通知の日付（出来事の日付）と、そこから計算した期限、使った式、出典のページを書く。
期限の決め方と出典は、制度データの正解（testdata/正解/省力化_第8回.json の「手続きの段階」と「書類」）から読む。
省力化の第9回の要領は、まだ downloads/ にない（2026-11-04）。期限の決め方は第8回の資料で計算し、第9回の要領が出たら照らし直す。
持続化 第20回は正解の JSON がまだないので、公募要領（要領20）の印刷されたページを、この中に書く。

会社の事実は testdata/デモの会社/回答表.md に合わせる（行ごとに回答表の ID を添えた）。
ID のない事柄は回答表にないもので、材料の一覧.md の「回答表にない事柄」に挙げた。
どのページにも「架空のテスト用データ」の帯を付ける（D2a の描き方を使う）。事務局の通知の見た目（ロゴ・公印・様式）と、
金融機関確認書の指定様式の配置は写さない。事務局と信用金庫は固有の名前を出さず、架空の表示にする。

動かし方：uv run --script testdata/期限/make_deadlines.py
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT_DIR = HERE / "材料"
ANSWER_FILE = HERE / "正解.json"
DOCS_DIR = REPO / "testdata" / "デモの会社" / "書類"
SEIDO_FILE = REPO / "testdata" / "正解" / "省力化_第8回.json"
sys.path.insert(0, str(DOCS_DIR))

import make_documents as d2a  # noqa: E402
from make_documents import ADDRESS, COMPANY, CORPORATE_NUMBER, LEFT, PRESIDENT, GOTHIC, Page, render  # noqa: E402

WEEKDAYS = "月火水木金土日"

# ---------------------------------------------------------------------------
# 置き場所（材料/ の中）
# ---------------------------------------------------------------------------

NOTICE_DIR = "通知"
TAX_DIR = "納税証明書"
REQUEST_DIR = "外部への依頼"

SHORYOKU_ADOPTION_FILE = f"{NOTICE_DIR}/省力化_第9回_採択の通知.pdf"
SHORYOKU_GRANT_FILE = f"{NOTICE_DIR}/省力化_第9回_交付決定通知書.pdf"
JIZOKU_ADOPTION_FILE = f"{NOTICE_DIR}/持続化_第20回_採択通知書.pdf"
JIZOKU_GRANT_FILE = f"{NOTICE_DIR}/持続化_第20回_交付決定通知書.pdf"
TAX_BEFORE_FILE = f"{TAX_DIR}/納税証明書_その2_2027年3月.pdf"
TAX_AFTER_FILE = f"{TAX_DIR}/納税証明書_その2_2027年6月.pdf"
BANK_LETTER_FILE = f"{REQUEST_DIR}/信用金庫からの確認書.pdf"

# ---------------------------------------------------------------------------
# 日付（どれも架空。回答表にない）
# ---------------------------------------------------------------------------

D = dt.date

# 省力化（一般型）第9回。第9回の締切と採択発表日は、2026-11-03 に取ったスケジュールのページでは
# 「12月下旬（予定）」「後日お知らせします」で、日付が出ていない。下の日付は仮の値
SHORYOKU = {
    "案件": "省力化（一般型）第9回",
    "制度": "中小企業省力化投資補助金（一般型）",
    "公募回": "第9回",
    "申請番号": "TEST-S09-0421",  # 架空。実際の申請番号の形は写していない
    # 応募申請の締切（仮）。12月下旬（予定）のうちの金曜日に置いた（第8回の締切も金曜日の17:00）
    "締切": D(2026, 12, 25),
    # 採択発表日（仮）。過去の回は締切から約2か月半〜4か月（第6回 105日、第8回 約3か月半）なので、約3か月半後に置いた
    "採択発表日": D(2027, 4, 16),
    "交付申請日": D(2027, 5, 28),
    # 交付決定日は、交付申請の期限（採択発表日から2か月後の日）より後にした。
    # そうすると「採択発表日から19か月後の日」が「交付決定日から17か月」より早くなり、「早いほう」の分かれが材料で見える
    "交付決定日": D(2027, 6, 25),
    "補助対象経費": 22_500_000,  # H-02（税抜）
    "補助率": "2/3",  # 小規模企業者（設定.md の参考の結論）
    "交付決定額": 15_000_000,  # 22,500,000 × 2/3。上限1,500万円と同じ
    "事業の内容": "盛り付け・計量・包装を一つのラインにつなぎ、カメラで盛り付けとラベルを確かめる設備の導入",  # H-01
}

# 持続化（一般型 通常枠）第20回。採択発表は「2027年3月頃予定」（要領20 p.3）
JIZOKU = {
    "案件": "持続化（通常枠）第20回",
    "制度": "小規模事業者持続化補助金（一般型 通常枠）",
    "公募回": "第20回",
    "申請番号": "TEST-J20-0388",  # 架空
    "枠": "通常枠（賃金引上げ特例）",  # SPEC F14
    "採択発表日": D(2027, 3, 12),
    # 交付決定は採択発表から概ね1〜2か月（要領20 p.3 の注2、p.24）。6週間後に置いた
    "交付決定日": D(2027, 4, 23),
    "補助対象経費": 3_000_000,  # I-03（税抜）
    "補助率": "2/3",  # 黒字なので2/3（設定.md の参考の結論）
    "交付決定額": 2_000_000,  # 3,000,000 × 2/3。上限200万円と同じ
    "事業の内容": "自社ブランドの冷凍惣菜をつくり、ネットショップと店頭で売る販路開拓",  # I-01、I-02
    # 公募要領に決まった日付（要領20 p.3・p.24）
    "見積書等の提出期限": D(2028, 2, 29),
    "補助事業実施期限": D(2028, 3, 31),
    "実績報告書の提出期限": D(2028, 4, 10),
    "様式4の発行の受付締切": D(2026, 12, 4),
}

# 決算と納税証明書。3月決算（A-10）。第19期は 2026-04-01〜2027-03-31
FISCAL_YEAR_END_19 = D(2027, 3, 31)
# 法人税の確定申告の期限：事業年度が終わった日の翌日から2か月以内（法人税法 第74条第1項）。
# 申告の期限の延長の特例は受けていない前提（回答表にない。F-18 は税理士に頼んでいることだけ）
FILING_DEADLINE_19 = D(2027, 5, 31)
FILED_19 = D(2027, 5, 26)  # 税理士が申告した日（架空）
TAX_BEFORE_ISSUED = D(2027, 3, 10)  # 決算日の前に取ったもの
TAX_AFTER_ISSUED = D(2027, 6, 7)  # 申告の後に取り直したもの
INCOME_19 = 4_600  # 第19期の所得金額（千円）。回答表にない（F-08 は第16〜18期だけ）

# 外部への依頼（台本_外部への依頼.md）
BANK_LETTER_DATE = D(2026, 11, 27)  # 確認書の日付
LOAN = 15_500_000  # H-12 の信用金庫からの借入
SCRIPT_DAYS = {
    "1": D(2026, 11, 16),  # 場面1：1件目の外部への依頼を一覧にする
    "2": D(2026, 11, 18),  # 場面2：信用金庫に頼んだと伝える
    "3": D(2026, 11, 30),  # 場面3：届いた確認書を入れる
    "4": D(2026, 11, 30),  # 場面4：2件目の外部への依頼を一覧にする
}
LEAD_DAYS = {"金融機関確認書": 14, "見積書": 7}  # 台本の答え（2週間くらい、1週間くらい）
# 目安の日数を聞く場面と、聞き直さない場面（T6-6 の4つ目の合格ライン）。
# 1件目の S1 で、社長が確認書と、採択の後に取り直す見積の両方を聞く。2件目の S4 で、業者の見積がまだと言う
ASK_SCENES = "場面1〜3（1件目。S1 の後、場面4の前）"
REUSE_SCENE = "場面4（2件目。S4 で社長が、業者の見積がまだと言う）"

# T6-5 の例の応募申請日（制度の日付ではない。決算日をまたぐ日付として置いた）
EXAMPLE_APPLY_BEFORE_FILING = D(2027, 5, 14)
EXAMPLE_APPLY_AFTER_FILING = D(2027, 6, 14)

# ---------------------------------------------------------------------------
# 日付の計算
# ---------------------------------------------------------------------------


def add_months(d: dt.date, months: int) -> dt.date:
    """応当日。応当日がない月は、その月の末日（民法 第143条第2項）。この材料の日付は、どれも応当日がある。"""
    index = d.month - 1 + months
    year = d.year + index // 12
    month = index % 12 + 1
    return D(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def jp(d: dt.date) -> str:
    return f"{d.year}年{d.month}月{d.day}日（{WEEKDAYS[d.weekday()]}）"


def reiwa(d: dt.date) -> str:
    return f"令和{d.year - 2018}年{d.month}月{d.day}日"


def iso(d: Optional[dt.date]) -> Optional[str]:
    return d.isoformat() if d else None


def wd(d: dt.date) -> str:
    return WEEKDAYS[d.weekday()]


def evaluate(rule: Dict, events: Dict[str, dt.date]) -> Tuple[Optional[dt.date], List[Dict]]:
    """制度データの「期限の決め方」から日付を出す。出来事の日付が分からない候補は None にする。

    返すもの：(日付, 候補の一覧)。「早いほう」で分からない候補があるときは、分かる候補の早いほう（上限）を返す。
    """
    kind = rule["種類"]
    if kind == "決まった日付":
        return dt.date.fromisoformat(rule["日時"][:10]), []
    if kind == "出来事からの期間":
        base = events.get(rule["出来事"])
        number = rule["期間"]["数"]
        unit = rule["期間"]["単位"]
        label = f"{rule['出来事']}から{number}{unit}"
        if base is None:
            return None, [{"式": label, "日付": None}]
        if unit == "か月":
            value = add_months(base, number)
        elif unit == "年":
            value = add_months(base, 12 * number)
        elif unit == "日":
            value = base + dt.timedelta(days=number)
        else:
            raise ValueError(f"知らない単位：{unit}")
        return value, [{"式": label, "起点": base.isoformat(), "日付": value.isoformat(), "曜日": wd(value)}]
    if kind == "早いほう":
        candidates = []
        known = []
        for sub in rule["期限"]:
            value, detail = evaluate(sub, events)
            candidates.extend(detail)
            if value is not None:
                known.append(value)
        return (min(known) if known else None), candidates
    raise ValueError(f"この材料では使わない種類：{kind}")


# ---------------------------------------------------------------------------
# 制度データの正解から、期限の決め方と出典を読む
# ---------------------------------------------------------------------------


def load_seido() -> Dict:
    return json.loads(SEIDO_FILE.read_text(encoding="utf-8"))


def stage(seido: Dict, stage_id: str) -> Dict:
    for item in seido["手続きの段階"]:
        if item["id"] == stage_id:
            return item
    raise KeyError(stage_id)


def document(seido: Dict, name: str) -> Dict:
    for item in seido["書類"]:
        if item["名前"] == name:
            return item
    raise KeyError(name)


def conflict(seido: Dict, name: str) -> Dict:
    for item in seido["資料どうしの食い違い"]:
        if item["項目"] == name:
            return item
    raise KeyError(name)


def pages(sources: List[Dict]) -> List[Dict]:
    """出典の一覧を写す（「根拠の文」は正解でも空けてあるので写さない）。"""
    return [dict(s) for s in sources]


def first_report_window(done: dt.date, reports: int, start_month: int, length_months: int) -> List[Dict]:
    """効果報告の提出期間。3月決算（A-10）で、完了日の属する事業年度の翌年度を1年目とし、
    1年目が終わった後の最初の4月から、毎年1回。"""
    fy_start_year = done.year if done.month >= 4 else done.year - 1
    first_year_end = D(fy_start_year + 2, 3, 31)
    windows = []
    for i in range(reports):
        start = D(first_year_end.year + i, start_month, 1)
        end = add_months(start, length_months) - dt.timedelta(days=1)
        windows.append({"回": i + 1, "始まり": start.isoformat(), "終わり": end.isoformat()})
    return windows


# ---------------------------------------------------------------------------
# 正解.json
# ---------------------------------------------------------------------------


def shoryoku_deadlines(seido: Dict) -> List[Dict]:
    s = SHORYOKU
    events = {"採択発表": s["採択発表日"], "交付決定": s["交付決定日"]}
    entries = []

    # 交付申請の期限
    kofu = stage(seido, "交付申請")
    value, candidates = evaluate(kofu["期限"]["値"], events)
    entries.append({
        "名前": "交付申請の期限",
        "手続きの段階": "交付申請",
        "式": "採択発表日から2か月後の日",
        "起点": {"出来事": "採択発表", "日付": s["採択発表日"].isoformat(), "通知": SHORYOKU_ADOPTION_FILE},
        "候補": candidates,
        "日付": value.isoformat(),
        "曜日": wd(value),
        "見込みか確定か": "確定（採択の通知を入れて、社長に確かめた後）。通知の前は、制度データの採択発表の予定から計算した見込み",
        "出典": pages(kofu["期限"]["出典"]),
        "注記": kofu["期限"].get("注記", ""),
    })

    # 補助事業の完了期限（補助事業の実施の期限）
    jisshi = stage(seido, "補助事業の実施")
    value, candidates = evaluate(jisshi["期限"]["値"], events)
    winner = min(candidates, key=lambda c: c["日付"])
    entries.append({
        "名前": "補助事業の完了期限（補助事業完了期限日）",
        "手続きの段階": "補助事業の実施",
        "式": "交付決定日から17か月と、採択発表日から19か月後の日の、早いほう",
        "起点": {"出来事": "交付決定", "日付": s["交付決定日"].isoformat(), "通知": SHORYOKU_GRANT_FILE},
        "候補": candidates,
        "早いほう": winner["式"],
        "日付": value.isoformat(),
        "曜日": wd(value),
        "見込みか確定か": "確定（交付決定通知書を入れて、社長に確かめた後）。交付決定通知書にも、この日を補助事業完了期限日として書いた（実績報告の手引き p.5 は、この日が交付決定通知書に書かれるとする）",
        "出典": pages(jisshi["期限"]["出典"]) + [{"資料": "実績報告の手引き", "ページ": 5}],
        "注記": "制度データの正解では「資料で食い違い」（交付申請の手引き6 p.9 は第6回版で、交付決定から18か月・採択発表から20か月）。第9回の要領で照らし直す",
    })

    # 実績報告の期限
    jisseki = stage(seido, "実績報告")
    value, candidates = evaluate(jisseki["期限"]["値"], events)
    entries.append({
        "名前": "実績報告の期限",
        "手続きの段階": "実績報告",
        "式": "補助事業を完了した日から起算して30日を経過した日と、補助事業完了期限日の、早いほう",
        "起点": {"出来事": "補助事業の完了", "日付": None, "通知": None},
        "候補": candidates,
        "日付": None,
        "上限": value.isoformat(),
        "上限の曜日": wd(value),
        "見込みか確定か": "完了日が分かるまでは、上限（補助事業完了期限日）だけが確定。完了日が分かったら計算し直す",
        "出典": pages(jisseki["期限"]["出典"]),
        "注記": "「起算して30日を経過した日」の数え方（完了日を1日目に数えるか）は、この材料では計算しない（完了日を決めていないため）",
    })

    # 状況報告（条件付き）
    jokyo = stage(seido, "状況報告")
    check_day = add_months(s["交付決定日"], 12)
    entries.append({
        "名前": "状況報告が要るかを確かめる日（条件付き）",
        "手続きの段階": "状況報告",
        "式": "交付決定日から1年。それまでに実績報告を出していなければ、事務局からメールが届き、状況報告が要る",
        "起点": {"出来事": "交付決定", "日付": s["交付決定日"].isoformat(), "通知": SHORYOKU_GRANT_FILE},
        "日付": check_day.isoformat(),
        "曜日": wd(check_day),
        "見込みか確定か": "確定（交付決定の日付から）。状況報告そのものの期限は資料にない（読み取れない）",
        "出典": pages(jokyo["始まる条件"]["出典"]),
        "注記": jokyo["始まる条件"].get("注記", ""),
    })

    # 効果報告（完了日で分かれる）
    koka = stage(seido, "効果報告")
    rule = koka["期限"]["値"]
    branch_a = first_report_window(D(2028, 1, 31), rule["回数"], rule["提出期間"]["始まりの月"], rule["提出期間"]["長さ"]["数"])
    branch_b = first_report_window(D(2028, 11, 16), rule["回数"], rule["提出期間"]["始まりの月"], rule["提出期間"]["長さ"]["数"])
    entries.append({
        "名前": "効果報告（毎年1回を5年）",
        "手続きの段階": "効果報告",
        "式": "補助事業を完了した日の属する事業年度（3月決算）の翌年度を1年目とし、1年目が終わった後の最初の4月から3か月の間に、毎年1回を5年",
        "起点": {"出来事": "補助事業の完了", "日付": None, "通知": None},
        "日付": None,
        "分かれ": [
            {"完了日": "2028-03-31 まで（第20期の中）", "提出期間": branch_a},
            {"完了日": "2028-04-01 から補助事業完了期限日（2028-11-16）まで（第21期の中）", "提出期間": branch_b},
        ],
        "見込みか確定か": "完了日が分かるまでは見込み。回答表 H-07（頼んでから約5か月、据え付けと調整に約1か月）から見ると、交付決定のすぐ後に頼めば 2028年1月ごろの完了で、1つ目の分かれになりそう",
        "出典": pages(koka["期限"]["出典"]) + [{"資料": "実績報告の手引き", "ページ": 7}],
        "注記": koka["期限"].get("注記", ""),
    })
    return entries


def jizoku_deadlines() -> List[Dict]:
    j = JIZOKU
    return [
        {
            "名前": "見積書等の提出期限",
            "手続きの段階": "見積書等の提出",
            "式": "決まった日付。採択発表の後、交付決定までに出す",
            "起点": {"出来事": "採択発表", "日付": j["採択発表日"].isoformat(), "通知": JIZOKU_ADOPTION_FILE},
            "日付": j["見積書等の提出期限"].isoformat(),
            "曜日": wd(j["見積書等の提出期限"]),
            "見込みか確定か": "確定（公募要領の決まった日付）",
            "出典": [{"資料": "要領20", "ページ": 3}, {"資料": "要領20", "ページ": 24}],
            "注記": "交付決定は、採択の後に見積書等を速やかに出しても、採択発表から概ね1〜2か月かかる（要領20 p.3・p.24）。この材料では、見積書等を出した後の 2027-04-23 に交付決定した",
        },
        {
            "名前": "補助事業の実施の期限",
            "手続きの段階": "補助事業の実施",
            "式": "交付決定日から、決まった日付（2028-03-31）まで",
            "起点": {"出来事": "交付決定", "日付": j["交付決定日"].isoformat(), "通知": JIZOKU_GRANT_FILE},
            "日付": j["補助事業実施期限"].isoformat(),
            "曜日": wd(j["補助事業実施期限"]),
            "見込みか確定か": "確定（公募要領の決まった日付。交付決定通知書にも書いた）",
            "出典": [{"資料": "要領20", "ページ": 7}, {"資料": "要領20", "ページ": 24}],
            "注記": "",
        },
        {
            "名前": "実績報告書の提出期限",
            "手続きの段階": "実績報告",
            "式": "補助事業の終了（支払いまで）から起算して30日を経過した日と、2028-04-10 の、早いほう",
            "起点": {"出来事": "補助事業の完了", "日付": None, "通知": None},
            "日付": None,
            "上限": j["実績報告書の提出期限"].isoformat(),
            "上限の曜日": wd(j["実績報告書の提出期限"]),
            "見込みか確定か": "終了の日が分かるまでは、上限だけが確定",
            "出典": [{"資料": "要領20", "ページ": 24}],
            "注記": "",
        },
        {
            "名前": "事業効果等状況報告",
            "手続きの段階": "効果報告",
            "式": "補助事業の終了から1年後の状況を、事務局が指定する期限までに報告する（1回）",
            "起点": {"出来事": "補助事業の完了", "日付": None, "通知": None},
            "日付": None,
            "見込みか確定か": "期限の日付は資料にない（事務局が指定する）",
            "出典": [{"資料": "要領20", "ページ": 26}],
            "注記": "",
        },
    ]


def tax_answer(seido: Dict) -> Dict:
    registry = document(seido, "履歴事項全部証明書")
    tax = document(seido, "納税証明書（その2）")
    deadline = SHORYOKU["締切"]
    earliest = add_months(deadline, -3)
    return {
        "決算の月": "3月（回答表 A-10）",
        "第19期": {
            "期間": "2026-04-01〜2027-03-31",
            "決算日": FISCAL_YEAR_END_19.isoformat(),
            "決算日の曜日": wd(FISCAL_YEAR_END_19),
            "申告の期限": FILING_DEADLINE_19.isoformat(),
            "申告の期限の曜日": wd(FILING_DEADLINE_19),
            "申告の期限の出典": "法人税法 第74条第1項（事業年度が終わった日の翌日から2か月以内）。公募要領ではなく法令。申告の期限の延長の特例は受けていない前提（回答表にない）",
            "申告した日": FILED_19.isoformat(),
            "所得金額（千円）": INCOME_19,
        },
        "納税証明書（その2）": {
            "決まり": "直近3期分（法人）",
            "出典": pages(tax["期数"]["出典"]),
            "期の入れ替わり": "第19期の決算日（2027-03-31）を過ぎると、直近3期が入れ替わる見込みになる。第19期の申告をした後（遅くとも申告の期限 2027-05-31 の後）は、直近3期は第17〜19期で、第16〜18期の証明書は使えない",
            "材料": [
                {"ファイル": TAX_BEFORE_FILE, "発行日": TAX_BEFORE_ISSUED.isoformat(), "期": "第16期〜第18期",
                 "使える申請日": "第19期の申告をした日（遅くとも 2027-05-31）まで"},
                {"ファイル": TAX_AFTER_FILE, "発行日": TAX_AFTER_ISSUED.isoformat(), "期": "第17期〜第19期",
                 "使える申請日": "第19期の申告をした後"},
            ],
            "例": [
                {"応募申請日": EXAMPLE_APPLY_BEFORE_FILING.isoformat(), "曜日": wd(EXAMPLE_APPLY_BEFORE_FILING),
                 "直近3期": "第16期〜第18期", "使う証明書": TAX_BEFORE_FILE,
                 "示すこと": "決算日を過ぎたので、第19期の申告の後は期が入れ替わる（申告の期限 2027-05-31）"},
                {"応募申請日": EXAMPLE_APPLY_AFTER_FILING.isoformat(), "曜日": wd(EXAMPLE_APPLY_AFTER_FILING),
                 "直近3期": "第17期〜第19期", "使う証明書": TAX_AFTER_FILE,
                 "示すこと": "2027年3月に取った証明書（第16〜18期）は直近3期でないので、取り直す"},
            ],
            "例の注記": "例の応募申請日は、制度の日付ではない（決算日をまたぐ日付として置いた）",
        },
        "履歴事項全部証明書": {
            "決まり": "応募申請日において、発行から3か月以内",
            "出典": pages(registry["有効期限"]["出典"]) + [{"資料": "交付申請の手引き6", "ページ": 38}],
            "例": {
                "応募申請日": deadline.isoformat(),
                "応募申請日の注記": "第9回の締切（仮）の日に申請したとき。早く申請すると、いちばん早い日も早くなる",
                "取得の期間": {"いちばん早い日": earliest.isoformat(), "いちばん遅い日": deadline.isoformat()},
                "D2a の証明書": {"ファイル": "testdata/デモの会社/書類/履歴事項全部証明書.pdf", "発行日": "2026-10-22", "期間の内か": earliest <= D(2026, 10, 22) <= deadline},
            },
            "注記": "基準日は締切ではなく応募申請日（応募手引8 p.63、交付申請の手引き6 p.38）",
        },
    }


def request_answer(seido: Dict) -> List[Dict]:
    bank = document(seido, "金融機関確認書")
    estimate = conflict(seido, "見積書（相見積もり）の条件")
    shoryoku_deadline = SHORYOKU["締切"]
    kofu_deadline = add_months(SHORYOKU["採択発表日"], 2)
    bank_start = shoryoku_deadline - dt.timedelta(days=LEAD_DAYS["金融機関確認書"])
    estimate_start = kofu_deadline - dt.timedelta(days=LEAD_DAYS["見積書"])
    reuse_start = JIZOKU["見積書等の提出期限"] - dt.timedelta(days=LEAD_DAYS["見積書"])
    return [
        {
            "案件": SHORYOKU["案件"],
            "書類": "金融機関確認書",
            "依頼先": "信用金庫（回答表 H-12）",
            "だれがするか": {"頼む": "社長（台本の答え A3）", "書く": "外部（信用金庫）"},
            "要る理由": "本事業の経費に、金融機関からの借入がある（H-12：信用金庫から 15,500千円）",
            "要る理由の出典": pages(bank["条件"]["出典"]),
            "目安の日数": {"値": LEAD_DAYS["金融機関確認書"], "出どころ": "社長に聞く（台本の答え A1「2週間くらい」）。制度データの正解にも、要領8 p.12・p.27、応募手引8 p.67 にも日数はない",
                           "聞く場面": ASK_SCENES},
            "締切": {"名前": "応募申請の締切（第9回。仮）", "日付": shoryoku_deadline.isoformat(), "曜日": wd(shoryoku_deadline)},
            "始める日": bank_start.isoformat(),
            "始める日の曜日": wd(bank_start),
            "始める日の式": "締切 − 目安の日数",
            "状態の移り変わり": [
                {"日付": SCRIPT_DAYS["1"].isoformat(), "状態": "まだ", "きっかけ": "台本の場面1"},
                {"日付": SCRIPT_DAYS["2"].isoformat(), "状態": "依頼した", "きっかけ": "台本の場面2（社長が「頼みました」と伝える）"},
                {"日付": SCRIPT_DAYS["3"].isoformat(), "状態": "届いた", "きっかけ": f"台本の場面3（材料/{BANK_LETTER_FILE} を入れ口に入れる）"},
            ],
            "届く書類の日付": BANK_LETTER_DATE.isoformat(),
        },
        {
            "案件": SHORYOKU["案件"],
            "書類": "見積書（交付申請で取り直す。見積依頼書をつけて、全経費分・最低2者分）",
            "依頼先": "機械の会社2社（回答表 H-03）",
            "だれがするか": {"頼む": "社長（台本の答え A3）", "書く": "外部（機械の会社）"},
            "要る理由": "交付申請で見積書を出す。今の見積（2026-10-20 付け）は有効期限が 2027-01-31 で（H-04）、交付申請の時期には切れている",
            "要る理由の出典": pages(estimate["値"][1]["出典"]),
            "要る理由の注記": "見積書の条件は、要領8 と交付申請の手引き6（第6回版）で書き方が違う（制度データの正解の「資料どうしの食い違い」）",
            "目安の日数": {"値": LEAD_DAYS["見積書"], "出どころ": "社長に聞く（台本の答え A2「1週間くらい」）。資料に日数はない",
                           "聞く場面": ASK_SCENES,
                           "聞く場面の注記": "S1 で社長が、採択の後に見積を取り直すことも含めて聞く。場面4の前に聞かなければ、場面4で聞いても聞かなくても T6-6 は不合格"},
            "締切": {"名前": "交付申請の期限", "日付": kofu_deadline.isoformat(), "曜日": wd(kofu_deadline)},
            "始める日": estimate_start.isoformat(),
            "始める日の曜日": wd(estimate_start),
            "始める日の式": "交付申請の期限 − 目安の日数。採択の通知の前は、交付申請の期限が見込みなので、始める日も見込み",
        },
        {
            "案件": JIZOKU["案件"],
            "書類": "見積書等（採択発表の後、交付決定までに出す）",
            "依頼先": "業者（回答表 I-04：まだ決めていない）",
            "だれがするか": {"頼む": "社長（台本の答え A3）", "書く": "外部（業者）"},
            "目安の日数": {"値": LEAD_DAYS["見積書"], "出どころ": "1件目で聞いた日数（台本の答え A2）を、会社の記録から使う。聞き直さない（T6-6）",
                           "聞かない場面": REUSE_SCENE},
            "締切": {"名前": "見積書等の提出期限", "日付": JIZOKU["見積書等の提出期限"].isoformat(), "曜日": wd(JIZOKU["見積書等の提出期限"])},
            "締切の出典": [{"資料": "要領20", "ページ": 3}, {"資料": "要領20", "ページ": 24}],
            "始める日": reuse_start.isoformat(),
            "始める日の曜日": wd(reuse_start),
            "始める日の式": "見積書等の提出期限 − 目安の日数（1件目で聞いた7日）。採択取消しにならないための、いちばん遅い始める日",
            "注記": "交付決定は見積書等を出した後（要領20 p.3・p.24）なので、実際には採択（2027-03-12）の後すぐに頼む。この材料の交付決定通知書（2027-04-23）は、見積書等を出した後のもの",
        },
        {
            "案件": JIZOKU["案件"],
            "書類": "事業支援計画書（様式4）",
            "依頼先": "地域の商工会議所（所在地は商工会議所地区。SPEC F14）",
            "目安の日数": {"値": None, "出どころ": "資料に日数がない（要領20 p.27 は「時間を要する場合がある」とだけ書く）。社長も知らない（回答表 J-03：会員でなく、相談に行ったこともない）。社長役は「分かりません」と答える"},
            "締切": {"名前": "様式4の発行の受付締切", "日付": JIZOKU["様式4の発行の受付締切"].isoformat(), "曜日": wd(JIZOKU["様式4の発行の受付締切"])},
            "締切の出典": [{"資料": "要領20", "ページ": 3}, {"資料": "要領20", "ページ": 22}],
        },
    ]


def answers(seido: Dict) -> Dict:
    s = SHORYOKU
    j = JIZOKU
    return {
        "作ったタスク": "TASKS D13（2026-11-04）",
        "使うテスト": ["T6-4", "T6-5", "T6-6", "T6-7"],
        "期限の決め方の出どころ": {
            "省力化": "testdata/正解/省力化_第8回.json の「手続きの段階」と「書類」（第8回の資料。第9回の要領はまだない。DESIGN 2章「第9回の要領が出なければ、第8回の資料を使う」）",
            "持続化": "持続化 第20回 公募要領（要領20。downloads/jizokuka_20/r6_koubover8_ip20.pdf）。ページは印刷された番号（PDF のページより1つ小さい。DESIGN 9章）",
        },
        "仮の日付": {
            "省力化 第9回の締切": {"日付": s["締切"].isoformat(), "曜日": wd(s["締切"]), "わけ": "スケジュールのページ（2026-11-03 に取得）は「12月下旬（予定）」。そのうちの金曜日に置いた"},
            "省力化 第9回の採択発表日": {"日付": s["採択発表日"].isoformat(), "曜日": wd(s["採択発表日"]), "わけ": "スケジュールのページは「後日お知らせします」。過去の回の、締切から採択発表までの間隔（約2か月半〜4か月）から置いた"},
        },
        "通知": [
            {"ファイル": SHORYOKU_ADOPTION_FILE, "案件": s["案件"], "種類": "採択の通知", "出来事": "採択発表",
             "日付": s["採択発表日"].isoformat(), "曜日": wd(s["採択発表日"]), "文書の日付": s["採択発表日"].isoformat(),
             "申請番号": s["申請番号"]},
            {"ファイル": SHORYOKU_GRANT_FILE, "案件": s["案件"], "種類": "交付決定通知書", "出来事": "交付決定",
             "日付": s["交付決定日"].isoformat(), "曜日": wd(s["交付決定日"]), "文書の日付": s["交付決定日"].isoformat(),
             "申請番号": s["申請番号"], "交付申請日": s["交付申請日"].isoformat(),
             "書いた期限": {"補助事業完了期限日": evaluate(stage(seido, "補助事業の実施")["期限"]["値"], {"採択発表": s["採択発表日"], "交付決定": s["交付決定日"]})[0].isoformat()},
             "交付決定額": s["交付決定額"]},
            {"ファイル": JIZOKU_ADOPTION_FILE, "案件": j["案件"], "種類": "採択通知書", "出来事": "採択発表",
             "日付": j["採択発表日"].isoformat(), "曜日": wd(j["採択発表日"]), "文書の日付": j["採択発表日"].isoformat(),
             "申請番号": j["申請番号"], "予定との照らし": "要領20 p.3 の「2027年3月頃予定」の内"},
            {"ファイル": JIZOKU_GRANT_FILE, "案件": j["案件"], "種類": "交付決定通知書", "出来事": "交付決定",
             "日付": j["交付決定日"].isoformat(), "曜日": wd(j["交付決定日"]), "文書の日付": j["交付決定日"].isoformat(),
             "申請番号": j["申請番号"],
             "書いた期限": {"補助事業の実施の期限": j["補助事業実施期限"].isoformat(), "実績報告書の提出期限": j["実績報告書の提出期限"].isoformat()},
             "交付決定額": j["交付決定額"]},
        ],
        "見込みのとき": {
            "省力化": "通知の前は、制度データの採択発表の予定から交付申請の期限を見込みで示す（SPEC F6、T6-4）。第9回の採択発表の予定は、2026-11-04 の時点で公表されていない。テストの制度データにどの予定を置くかは K1 で決める",
            "持続化": "採択発表の予定は「2027年3月頃」（要領20 p.3）。見積書等・実施・実績報告の期限は決まった日付なので、通知の前から確定",
        },
        "期限": {
            s["案件"]: shoryoku_deadlines(seido),
            j["案件"]: jizoku_deadlines(),
        },
        "決算日をまたぐ書類（T6-5）": tax_answer(seido),
        "外部への依頼（T6-6）": request_answer(seido),
    }


# ---------------------------------------------------------------------------
# 書類を描く
# ---------------------------------------------------------------------------


# 行の頭に来てはいけない文字（句読点と閉じかっこ）。前の行の終わりに付ける
LINE_HEAD_NG = "、。，．）」』】"


def para(pg: Page, text: str, size: float = 10) -> None:
    """D2a の para に、句読点を行の頭に出さない決まりと、段落のあとの小さな空きを足したもの。"""
    lines: List[str] = []
    for line in d2a.wrap(text, d2a.MINCHO, size, d2a.RIGHT - LEFT):
        while lines and line and line[0] in LINE_HEAD_NG:
            lines[-1] += line[0]
            line = line[1:]
        if line:
            lines.append(line)
    pg.c.setFont(d2a.MINCHO, size)
    for line in lines:
        pg.c.drawString(LEFT, pg.y, line)
        pg.y -= size + 5
    pg.gap(4)


def letter_head(pg: Page, issued: dt.date, sender: str) -> None:
    pg.right(jp(issued), 10)
    pg.gap(6)
    pg.c.setFont(GOTHIC, 12)
    pg.c.drawString(LEFT, pg.y, COMPANY)  # A-01
    pg.y -= 18
    pg.c.drawString(LEFT, pg.y, f"代表取締役　{PRESIDENT}　様")  # A-08
    pg.y -= 26
    pg.right(sender, 10)
    pg.gap(14)


SHORYOKU_SENDER = "中小企業省力化投資補助事業 事務局（架空の表示。テスト用）"
JIZOKU_SENDER = "小規模事業者持続化補助金 事務局（架空の表示。テスト用）"


def shoryoku_adoption() -> list:
    s = SHORYOKU

    def page1(pg: Page) -> None:
        letter_head(pg, s["採択発表日"], SHORYOKU_SENDER)
        pg.title("採択のお知らせ", 16)
        para(pg,
            f"{s['制度']} {s['公募回']}公募にご申請いただいた事業計画について、審査の結果、"
            "補助金交付候補者として採択されましたので、お知らせします。",
            size=10.5,
        )
        pg.gap(6)
        for key, value in (
            ("申請番号", s["申請番号"]),
            ("公募の回", f"{s['公募回']}公募"),
            ("事業者名", COMPANY),
            ("法人番号", CORPORATE_NUMBER),  # A-03
            ("採択発表日", jp(s["採択発表日"])),
            ("結果", "採択（補助金交付候補者）"),
        ):
            pg.kv(key, value, key_width=95, size=10)
        pg.gap(8)
        para(pg,"採択の後は、研修動画の視聴（確認テストを含む）と交付申請を行ってください。交付申請の期限と手続きは、公募要領と事務局の案内のとおりです。", size=10)
        para(pg,"交付決定の前に、発注・契約・支払いをしないでください。交付決定の前の経費は、補助の対象になりません。", size=10)

    return [page1]


def shoryoku_grant(completion_deadline: dt.date) -> list:
    s = SHORYOKU

    def page1(pg: Page) -> None:
        letter_head(pg, s["交付決定日"], SHORYOKU_SENDER)
        pg.title("交付決定通知書", 16)
        para(pg,
            f"{jp(s['交付申請日'])}付けで申請のあった補助金の交付について、次のとおり交付することを決定しましたので、通知します。",
            size=10.5,
        )
        pg.gap(6)
        for key, value in (
            ("申請番号", s["申請番号"]),
            ("公募の回", f"{s['制度']} {s['公募回']}公募"),
            ("交付決定日", jp(s["交付決定日"])),
            ("補助事業の内容", s["事業の内容"]),
            ("補助対象経費", f"{s['補助対象経費']:,}円（税抜）"),
            ("補助率", s["補助率"]),
            ("交付決定額", f"{s['交付決定額']:,}円"),
            ("補助事業完了期限日", jp(completion_deadline)),
        ):
            pg.kv(key, value, key_width=110, size=10)
        pg.gap(8)
        para(pg,"補助事業は、交付決定日から始められます。交付決定日より前に発注・契約したものは、補助の対象になりません。", size=10)
        para(pg,"補助事業を完了したら、完了した日から起算して30日を経過した日と、補助事業完了期限日の、いずれか早い日までに実績報告を行ってください。", size=10)
        para(pg,"経費の配分や内容を変えるときは、前もって承認を受けてください。", size=10)

    return [page1]


def jizoku_adoption() -> list:
    j = JIZOKU

    def page1(pg: Page) -> None:
        letter_head(pg, j["採択発表日"], JIZOKU_SENDER)
        pg.title("採択通知書", 16)
        para(pg,
            f"{j['制度']} {j['公募回']}公募にご申請いただいた補助事業計画について、審査の結果、採択されましたので、お知らせします。",
            size=10.5,
        )
        pg.gap(6)
        for key, value in (
            ("申請番号", j["申請番号"]),
            ("公募の回", f"{j['公募回']}公募"),
            ("申請した枠", j["枠"]),
            ("事業者名", COMPANY),
            ("採択発表日", jp(j["採択発表日"])),
            ("結果", "採択"),
        ):
            pg.kv(key, value, key_width=95, size=10)
        pg.gap(8)
        para(pg,"採択の後、経費の価格が妥当であることを示す見積書等（相見積もりを含む）を出してください。見積書等の提出期限は、公募要領のとおりです。見積書等を確かめた後に、交付決定を通知します。", size=10)
        para(pg,"交付決定の前に、発注・契約・支払いをしないでください。", size=10)

    return [page1]


def jizoku_grant() -> list:
    j = JIZOKU

    def page1(pg: Page) -> None:
        letter_head(pg, j["交付決定日"], JIZOKU_SENDER)
        pg.title("交付決定通知書", 16)
        para(pg,"ご提出いただいた見積書等を確かめ、補助金の交付を次のとおり決定しましたので、通知します。", size=10.5)
        pg.gap(6)
        for key, value in (
            ("申請番号", j["申請番号"]),
            ("公募の回", f"{j['制度']} {j['公募回']}公募"),
            ("交付決定日", jp(j["交付決定日"])),
            ("補助事業の内容", j["事業の内容"]),
            ("補助対象経費", f"{j['補助対象経費']:,}円（税抜）"),
            ("補助率", j["補助率"]),
            ("交付決定額", f"{j['交付決定額']:,}円"),
            ("補助事業の実施期間", f"{jp(j['交付決定日'])}から{jp(j['補助事業実施期限'])}まで"),
            ("実績報告書の提出期限", jp(j["実績報告書の提出期限"])),
        ):
            pg.kv(key, value, key_width=120, size=10)
        pg.gap(8)
        para(pg,"補助事業が実施期間の途中で終わったとき（支払いまで済んだとき）は、その日から起算して30日を経過した日と、実績報告書の提出期限の、いずれか早い日までに実績報告書を出してください。", size=10)
        para(pg,"補助事業の終了から1年後の状況について、事業効果等状況報告を出してください。期限は事務局からお知らせします。", size=10)

    return [page1]


def bank_letter() -> list:
    s = SHORYOKU

    def page1(pg: Page) -> None:
        pg.title("金融機関による確認書", 16)
        pg.center("（架空のテスト用データ。指定様式の配置は写していません。金融機関の印はありません）", 9)
        pg.gap(8)
        for key, value in (
            ("確認した日", jp(BANK_LETTER_DATE)),
            ("事業者名", COMPANY),
            ("代表者", f"代表取締役　{PRESIDENT}"),
            ("所在地", ADDRESS),  # B-01
            ("補助金", f"{s['制度']} {s['公募回']}公募"),
            ("事業の内容", s["事業の内容"]),
            ("事業に要する経費", f"{s['補助対象経費']:,}円（税抜）"),  # H-02
            ("借入の予定額", f"{LOAN:,}円"),  # H-12
            ("確認したこと", "上の事業計画を確かめました。借入の申し込みを受けたときは、当金庫の審査を経て融資を検討します。"),
            ("金融機関", "架空の信用金庫（テスト用）"),
        ):
            pg.kv(key, value, key_width=110, size=10)

    return [page1]


TAX_DOC_NAME = "納税証明書（その2）"


def build_tax_certificate(path: Path, issued: dt.date, incomes: list) -> None:
    """D2a の tax_certificate を、発行日と事業年度だけ差し替えて描く（D6 と同じ手）。"""
    saved = (d2a.TAX_CERTIFICATE_ISSUED, d2a.TAXABLE_INCOME)
    d2a.TAX_CERTIFICATE_ISSUED = reiwa(issued)
    d2a.TAXABLE_INCOME = incomes
    try:
        render(path, TAX_DOC_NAME, d2a.tax_certificate())
    finally:
        d2a.TAX_CERTIFICATE_ISSUED, d2a.TAXABLE_INCOME = saved


def incomes_after() -> list:
    """第17〜19期。第17期・第18期は D2a と同じ値（F-08）。第19期は回答表にない値。"""
    return list(d2a.TAXABLE_INCOME[1:]) + [("令和8年4月1日", "令和9年3月31日", INCOME_19)]


def build(out: Path, answer_file: Path) -> None:
    seido = load_seido()
    for sub in (NOTICE_DIR, TAX_DIR, REQUEST_DIR):
        (out / sub).mkdir(parents=True, exist_ok=True)
    completion = evaluate(stage(seido, "補助事業の実施")["期限"]["値"],
                          {"採択発表": SHORYOKU["採択発表日"], "交付決定": SHORYOKU["交付決定日"]})[0]
    render(out / SHORYOKU_ADOPTION_FILE, "採択のお知らせ（省力化 第9回）", shoryoku_adoption())
    render(out / SHORYOKU_GRANT_FILE, "交付決定通知書（省力化 第9回）", shoryoku_grant(completion))
    render(out / JIZOKU_ADOPTION_FILE, "採択通知書（持続化 第20回）", jizoku_adoption())
    render(out / JIZOKU_GRANT_FILE, "交付決定通知書（持続化 第20回）", jizoku_grant())
    build_tax_certificate(out / TAX_BEFORE_FILE, TAX_BEFORE_ISSUED, list(d2a.TAXABLE_INCOME))
    build_tax_certificate(out / TAX_AFTER_FILE, TAX_AFTER_ISSUED, incomes_after())
    render(out / BANK_LETTER_FILE, "金融機関による確認書", bank_letter())
    answer_file.write_text(json.dumps(answers(seido), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_story() -> None:
    """日付のつじつま。合わなければ作らない。"""
    s, j = SHORYOKU, JIZOKU
    kofu_deadline = add_months(s["採択発表日"], 2)
    if not (s["締切"] < s["採択発表日"] < s["交付申請日"] <= kofu_deadline < s["交付決定日"]):
        raise ValueError("省力化の日付の順番が合いません")
    if not (D(2027, 3, 1) <= j["採択発表日"] <= D(2027, 3, 31)):
        raise ValueError("持続化の採択発表日が、要領20 の「2027年3月頃予定」の外です")
    gap = (j["交付決定日"] - j["採択発表日"]).days
    if not (28 <= gap <= 62):
        raise ValueError("持続化の交付決定が、採択発表から概ね1〜2か月の外です")
    if not (TAX_BEFORE_ISSUED < FISCAL_YEAR_END_19 < FILED_19 <= FILING_DEADLINE_19 < TAX_AFTER_ISSUED):
        raise ValueError("納税証明書と決算・申告の日付の順番が合いません")
    if not (EXAMPLE_APPLY_BEFORE_FILING < FILED_19 and EXAMPLE_APPLY_AFTER_FILING > FILING_DEADLINE_19):
        raise ValueError("T6-5 の例の応募申請日が、申告の前後に分かれていません")
    if not (SCRIPT_DAYS["1"] <= SCRIPT_DAYS["2"] < BANK_LETTER_DATE < SCRIPT_DAYS["3"] < s["締切"]):
        raise ValueError("台本の日付と確認書の日付の順番が合いません")


def main() -> None:
    check_story()
    build(OUT_DIR, ANSWER_FILE)
    for path in sorted(OUT_DIR.rglob("*.pdf")):
        print(f"作った：{path.relative_to(HERE).as_posix()}")
    print(f"作った：{ANSWER_FILE.name}")


if __name__ == "__main__":
    main()
