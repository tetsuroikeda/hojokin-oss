"""T3-9 概要と流れの Word（SPEC F3、DESIGN 4.5・4.6・6章、TASKS M2d）。

SPEC：制度データと会社の記録から、概要と流れの Word を作る。
合格ライン：要件、義務と返還の条件、補助額の見込み、流れと期限、加点、必要書類が制度データと一致し、すべてに出典がある。

確かめ方
- 架空の制度データ（テストのためだけに作った値。公式の公募要領の文は使わない）と会社の記録を置いた会社のフォルダで、
  道具（skills/junbi/scripts/gaiyou_word.py）を、Claude が Bash で動かすのと同じく、社長の Mac と同じ /usr/bin/python3 で
  プラグインの写しから動かす。制度データと会社の記録は、先にスキーマを通ることを確かめる。
- できた Word を zip と XML で読み、見出しの後の表を節ごとに取り出して、制度データと1件ずつ突き合わせる。
  - 要件：数値の要件と数値でない要件が、同じ順で1件も欠けずに並び、値（基準・計算式・内容など）と出典が一致する
  - 義務と返還の条件：満たせないときのある数値の要件、してはいけないこと、申請より後の手続きの段階の注意が、1件ずつ一致する
  - 補助額の見込み：選んだ区分・特例の上限と補助率、会社の記録の経費から計算した額（円未満切り捨て、上限で頭打ち、
    上乗せ）と自己負担の目安が一致する。上限が読み取れない区分では、見込みを出さない
  - 流れと期限：すべての手続きの段階が順番どおりに並び、期限の決め方の文（決まった日付／出来事からの期間／早いほう／
    繰り返し）と出典が一致する。決まった期日も一致する
  - 加点：種類の数・区分ごとの上限と、すべての項目が一致する
  - 必要書類：手続きの段階ごとに、その段階で使う書類だけが、区分（必須・条件付き・任意）とともに並ぶ
  - すべてに出典：上の節のどの行にも出典があり、制度データの値の出典（資料の名前とページ。回の違う資料は回も）と、
    会社の記録の出典がそのまま出る。読み取れない値は、出典の代わりに「読み取れませんでした（理由）」を出す。
    要確認・資料で食い違いの値には印と注記が付く
- 作り直すと同じファイルが直り、ほかのファイルは増えない。同じ中身からは同じファイルになる。
- 渡した判定の名前や id が制度データ・会社の記録にないとき、会社のフォルダでないとき、制度データがないか形が合わないときは、
  何も書かない（前の概要と流れ.docx はそのまま残る）。
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = hr.REPO_ROOT
TOOL = Path("skills") / "junbi" / "scripts" / "gaiyou_word.py"
CASE = "2026_テスト補助金（一般型）第4回"
DATA_REL = Path("記録") / "制度データ" / "テスト補助金_第3回.json"
RECORD_REL = Path("記録") / "会社の記録.json"
OUT_REL = Path("案件") / CASE / "概要と流れ.docx"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NOTICE = "第4回の資料はまだ公表されていないため、直近回である第3回の資料に基づいています。"

SEIDO_SCHEMA = json.loads((REPO_ROOT / "schema" / "制度データ.schema.json").read_text(encoding="utf-8"))
RECORD_SCHEMA = json.loads((REPO_ROOT / "schema" / "会社の記録.schema.json").read_text(encoding="utf-8"))

# 資料の id と、Word の出典に出る名前（回の違う資料は回を添える）
LABELS = {"要領T": "公募要領", "手引T2": "交付申請の手引き（第2回）", "日程T": "スケジュールのページ"}
UNREAD = "読み取れませんでした"
NOT_JUDGED = "まだ確かめていません"


# ---- 架空の制度データ（テストのためだけに作った値） ----


def sv(value, doc: str, page: int = None, state: str = "確認済み", note: str = None, end: int = None) -> dict:
    src = {"資料": doc}
    if page is not None:
        src["ページ"] = page
    if end is not None:
        src["終わりのページ"] = end
    out = {"値": value, "出典": [src], "根拠の文": "（テストのための架空の根拠の文）", "状態": state}
    if note:
        out["注記"] = note
    return out


def unread(reason: str) -> dict:
    return {"値": None, "状態": "読み取れない", "理由": reason}


def after(event: str, number: int, unit: str) -> dict:
    return {"種類": "出来事からの期間", "出来事": event, "期間": {"数": number, "単位": unit}}


def seido() -> dict:
    return {
        "スキーマの版": 1,
        "制度": {"名前": "テスト用 作業改善補助金", "枠": "一般型", "種類": "補助金", "公募回": "第3回"},
        "資料": [
            {"id": "要領T", "名前": "公募要領", "公募回": "第3回", "URL": "https://example.invalid/test/koubo_03.pdf",
             "取得日": "2026-11-04", "ハッシュ": "0" * 64, "ページのずれ": 1},
            {"id": "手引T2", "名前": "交付申請の手引き", "公募回": "第2回", "URL": "https://example.invalid/test/koufu_02.pdf",
             "取得日": "2026-11-04", "ハッシュ": "1" * 64, "ページのずれ": 0},
            {"id": "日程T", "名前": "スケジュールのページ", "公募回": "第3回", "URL": "https://example.invalid/test/schedule.html",
             "取得日": "2026-11-04", "ハッシュ": "2" * 64},
        ],
        "資料どうしの食い違い": [{"項目": "二重受給の範囲", "値": [
            {"値": "国の補助金", "出典": [{"資料": "要領T", "ページ": 4}], "根拠の文": "（架空）"},
            {"値": "国と自治体の補助金", "出典": [{"資料": "手引T2", "ページ": 2}], "根拠の文": "（架空）"},
        ]}],
        "補助額": [
            {"区分": "従業員5人以下", "上限": sv(7500000, "要領T", 1), "補助率": sv("1/2", "要領T", 1),
             "特例": [{"名前": "小規模の補助率", "種類": "補助率の置き換え", "値": sv("2/3", "要領T", 1),
                      "条件": sv("小規模事業者", "要領T", 1)},
                     # 同じ種類の特例を2つ選ぶ誤りを確かめるための、もう1つの補助率の置き換え
                     {"名前": "創業の補助率", "種類": "補助率の置き換え", "値": sv("3/4", "要領T", 1),
                      "条件": sv("創業から5年以内", "要領T", 1)}]},
            {"区分": "従業員6〜20人", "上限": sv(15000000, "要領T", 1), "補助率": sv("1/2", "要領T", 1),
             "特例": [
                 {"名前": "小規模の補助率", "種類": "補助率の置き換え", "値": sv("2/3", "要領T", 1),
                  "条件": sv("小規模事業者", "要領T", 1)},
                 {"名前": "賃上げ特例", "種類": "上限の置き換え", "値": sv(20000000, "要領T", 2),
                  "条件": sv("賃上げを大きく行う", "要領T", 2)},
                 {"名前": "地域の上乗せ", "種類": "上限の上乗せ",
                  "値": sv(1000000, "日程T", state="要確認", note="裏取り：上乗せの額が根拠の文にありません")},
             ]},
            {"区分": "従業員21人以上", "上限": unread("上限が書かれていない"), "補助率": sv("1/2", "要領T", 1)},
        ],
        "補助の対象になる経費": [],
        "補助の対象にならない経費": [{"名前": "中古の機械", "種類": "対象外", "内容": sv("中古の機械の購入費", "要領T", 3)}],
        "数値の要件": [
            {"名前": "労働時間あたりの出来高", "計算式": sv("出来高 ÷ 労働時間", "要領T", 2),
             "基準": sv("年平均で3.0%以上伸ばす", "要領T", 2),
             "満たせないとき": sv("補助金の一部を返す", "要領T", 4, state="要確認", note="裏取り：返す額の決め方がない")},
            {"名前": "最低の時給", "基準": sv("地域の最低賃金＋30円以上", "要領T", 2),
             "元の数字の決め方": sv("事業場でいちばん低い時給", "要領T", 2),
             "満たせないとき": sv("その年の分を返す", "手引T2", 6)},
            {"名前": "事業計画期間", "基準": sv("3〜5年", "要領T", 2)},
            {"名前": "従業員の数の上限", "基準": unread("数が書かれていない")},
        ],
        "数値でない要件": [
            {"名前": "実施場所の特定", "種類": "満たすこと", "内容": sv("工場か店舗を特定している", "要領T", 2),
             "確かめ方": sv("登記事項証明書で確かめる", "手引T2", 4)},
            {"名前": "大企業の子会社", "種類": "当たらないこと", "内容": sv("大企業が株の半分以上を持つ", "要領T", 3, end=4),
             "満たせないとき": sv("対象外", "要領T", 3)},
        ],
        "決まった期日": [
            {"名前": "申請の締切", "日時": sv({"日時": "2027-03-12T16:00+09:00"}, "要領T", 1)},
            {"名前": "採択発表", "日時": sv({"年月": "2027-05", "旬": "上旬"}, "日程T"), "注記": "予定"},
            {"名前": "交付申請の受付開始", "日時": unread("後日お知らせとなっている")},
        ],
        "審査の段階": [{"名前": "書面審査", "条件": sv("申請者全員", "要領T", 3)}],
        "審査項目": [{"名前": "計画面", "観点": sv(["実現できるか"], "要領T", 3)}],
        "加点": {
            "種類の数": sv(2, "要領T", 3),
            "区分ごとの上限": unread("区分ごとの上限が書かれていない"),
            "項目": [
                {"名前": "認定計画の加点", "証拠の種類": ["入力"], "必要な書類": [],
                 "かかる日数": sv("認定まで約45日", "要領T", 3), "内容": sv("認定を受けた計画がある", "要領T", 3)},
                {"名前": "賃上げ表明の加点", "区分": "政策", "証拠の種類": ["添付"], "必要な書類": ["賃上げ表明書"],
                 "自動で付く条件": sv("賃上げ特例を選ぶと付く", "要領T", 3),
                 "内容": sv("賃上げを表明する", "要領T", 3, state="資料で食い違い", note="手引では別の書き方")},
            ],
        },
        "書類": [
            {"名前": "決算書", "区分": "必須", "発行元": "自社", "手続き": ["申請"],
             "内容": sv("貸借対照表と損益計算書", "要領T", 2), "期数": sv("直近2期分", "要領T", 2)},
            {"名前": "会社案内", "区分": "任意", "発行元": "自社", "手続き": ["申請"], "効く審査項目": ["計画面"],
             "内容": sv("会社の概要が分かるもの", "要領T", 3)},
            {"名前": "賃上げ表明書", "区分": "条件付き", "発行元": "自社", "手続き": ["申請"],
             "条件": sv("賃上げ特例を選ぶとき", "要領T", 3), "内容": sv("指定の様式で出す", "要領T", 3)},
            {"名前": "登記簿の写し", "区分": "必須", "発行元": "役所", "手続き": ["申請"],
             "内容": sv("履歴事項全部証明書", "要領T", 2), "有効期限": sv("発行から3か月以内", "要領T", 2)},
            {"名前": "見積書", "区分": "必須", "発行元": "外部機関", "手続き": ["申請", "交付申請"],
             "内容": sv("2社以上の見積書", "手引T2", 5)},
            {"名前": "実績報告書", "区分": "必須", "発行元": "自社", "手続き": ["実績報告"],
             "内容": sv("事業の結果をまとめる", "手引T2", 9)},
            {"名前": "古い様式の届け", "区分": "任意", "発行元": "自社", "手続き": ["廃止した手続き"],
             "内容": sv("前の回の届け", "手引T2", 11)},
        ],
        "様式": [],
        "申請画面": {"流れ": unread("画面の流れが書かれていない"), "画面": []},
        "提出するファイルの決まり": {"形式": sv("PDF", "要領T", 4)},
        "地域による違い": [],
        # 順番どおりに並べないで置く（道具が順番で並べ直すかを見る）
        "手続きの段階": [
            {"id": "交付申請", "順番": 3, "名前": "交付申請", "フォルダ": "2_交付申請",
             "始まる条件": sv("採択の発表の後", "手引T2", 3), "期限": sv(after("採択", 2, "か月"), "手引T2", 3),
             "注意": [sv("見積書を2社以上から取る", "手引T2", 5)]},
            {"id": "申請", "順番": 1, "名前": "応募申請", "フォルダ": "1_申請", "始まる条件": sv("公募が始まった後", "日程T"),
             "期限": sv({"種類": "決まった日付", "日時": "2027-03-12T16:00+09:00"}, "要領T", 1),
             "注意": [sv("GビズIDを先に取る", "要領T", 4)]},
            {"id": "採択", "順番": 2, "名前": "採択発表", "始まる条件": sv("審査が終わった後", "要領T", 3)},
            {"id": "計画変更", "順番": 4, "名前": "計画変更の承認", "条件付き": True,
             "始まる条件": sv("計画を変えるとき", "手引T2", 7), "期限": unread("期限の定めがない"),
             "注意": [sv("変える前に承認を受ける", "手引T2", 7)]},
            {"id": "実施", "順番": 5, "名前": "補助事業の実施", "始まる条件": sv("交付決定の後", "手引T2", 8),
             "期限": sv({"種類": "早いほう", "期限": [
                 after("交付決定日", 12, "か月"),
                 {"種類": "早いほう", "期限": [{"種類": "決まった日付", "日時": "2028-12-28"}, after("採択", 14, "か月")]},
             ]}, "手引T2", 8, state="要確認", note="裏取り：早いほうの組み方を確かめる")},
            {"id": "実績報告", "順番": 6, "名前": "実績報告", "フォルダ": "3_実績報告",
             "始まる条件": sv("事業が終わった後", "手引T2", 9), "期限": sv(after("事業の完了", 30, "日"), "手引T2", 9)},
            {"id": "効果報告", "順番": 7, "名前": "効果報告", "フォルダ": "4_効果報告",
             "始まる条件": sv("事業が終わった翌年度から", "手引T2", 10),
             "期限": sv({"種類": "繰り返し", "回数": 5, "間隔": {"数": 1, "単位": "年"},
                        "提出期間": {"始まりの月": 4, "長さ": {"数": 3, "単位": "か月"}}}, "手引T2", 10),
             "注意": [sv("報告しないと返還を求められることがある", "手引T2", 10)]},
        ],
        "してはいけないこと": [
            {"名前": "交付決定前の発注", "内容": sv("交付決定の前に発注しない", "要領T", 4)},
            {"名前": "二重受給", "内容": sv("同じ経費で他の補助金を受けない", "要領T", 4, state="資料で食い違い",
                                         note="手引では国と自治体の補助金")},
        ],
        "支援者の欄": None,
        "読み取れなかった項目": [{"項目": "加点の区分ごとの上限", "理由": "区分ごとの上限が書かれていない",
                                  "問い合わせ文の案": "加点の区分ごとに、いくつまで選べますか。"}],
    }


def fact(fid: str, name: str, value, source: dict) -> dict:
    return {"id": fid, "種類": "事実", "名前": name, "値": value, "変わりうる": True, "出典": source,
            "覚えた日": "2026-11-03", "最後に確かめた日": "2026-11-03", "状態": "有効"}


def record() -> dict:
    return {"スキーマの版": 1, "項目": [
        fact("f-001", "常勤の従業員数", 12, {"種類": "原本", "ファイル": "原本/登記・名簿/2026-10-01_労働者名簿.xlsx"}),
        fact("f-002", "設備投資の額（税抜き）", "22,500千円",
             {"種類": "原本", "ファイル": "原本/見積・契約・請求/2026-10-20_見積書_架空機械.pdf", "ページ": 1}),
        fact("f-003", "事業場内最低賃金", 1330, {"種類": "社長の発言", "発言": "いちばん低い時給は1,330円", "日付": "2026-11-02"}),
        fact("f-004", "加点の認定", "持っていない", {"種類": "質問", "質問": "認定を持っていますか", "答えた日": "2026-11-03"}),
        fact("f-005", "別の設備の額", "2,000万円", {"種類": "社長の発言", "発言": "2,000万円くらい", "日付": "2026-11-03"}),
        fact("f-006", "端数のある設備の額", 12345679, {"種類": "原本", "ファイル": "原本/見積・契約・請求/2026-10-21_見積書_端数.pdf"}),
        # 特例が計算に効いているかを見るための経費（特例を無視すると、見込みが変わる額）
        fact("f-007", "大型機械の額", 36000000, {"種類": "原本", "ファイル": "原本/見積・契約・請求/2026-10-22_見積書_大型機械.pdf"}),
        fact("f-008", "ライン増設の額", "4,100万円", {"種類": "社長の発言", "発言": "4,100万円の見込み", "日付": "2026-11-03"}),
        fact("f-009", "ライン全体の額", "44,000千円",
             {"種類": "原本", "ファイル": "原本/見積・契約・請求/2026-10-23_見積書_ライン.pdf", "ページ": 2}),
        fact("f-010", "包装機の額", "3,100万円（税抜き）", {"種類": "質問", "質問": "包装機はいくらですか", "答えた日": "2026-11-03"}),
        fact("f-011", "検査機の額", 27000000, {"種類": "原本", "ファイル": "原本/見積・契約・請求/2026-10-24_見積書_検査機.pdf"}),
    ]}


REC = {
    "f-001": "会社の記録「常勤の従業員数」：原本/登記・名簿/2026-10-01_労働者名簿.xlsx",
    "f-002": "会社の記録「設備投資の額（税抜き）」：原本/見積・契約・請求/2026-10-20_見積書_架空機械.pdf p.1",
    "f-003": "会社の記録「事業場内最低賃金」：社長の発言（2026-11-02）",
    "f-004": "会社の記録「加点の認定」：質問への答え（2026-11-03）",
    "f-005": "会社の記録「別の設備の額」：社長の発言（2026-11-03）",
    "f-006": "会社の記録「端数のある設備の額」：原本/見積・契約・請求/2026-10-21_見積書_端数.pdf",
    "f-007": "会社の記録「大型機械の額」：原本/見積・契約・請求/2026-10-22_見積書_大型機械.pdf",
    "f-008": "会社の記録「ライン増設の額」：社長の発言（2026-11-03）",
    "f-009": "会社の記録「ライン全体の額」：原本/見積・契約・請求/2026-10-23_見積書_ライン.pdf p.2",
    "f-010": "会社の記録「包装機の額」：質問への答え（2026-11-03）",
    "f-011": "会社の記録「検査機の額」：原本/見積・契約・請求/2026-10-24_見積書_検査機.pdf",
}

INPUT = {
    "制度の概要": ["作業を機械に置き換える投資の費用を、一部補助する架空の制度です。", "申請は電子申請で行います。"],
    "流れの説明": "申請して採択されたら交付申請をし、交付決定の後に機械を発注します。",
    "要件の判定": [
        {"要件": "最低の時給", "判定": "満たす", "理由": "いちばん低い時給は1,330円", "会社の記録": ["f-003"]},
        {"要件": "実施場所の特定", "判定": "確かめが要る", "理由": "工場の登記をまだ見ていない"},
    ],
    "加点の判定": [{"加点": "認定計画の加点", "判定": "今回は取れない", "理由": "認定まで約45日かかり、締切に間に合わない",
                    "会社の記録": ["f-004"]}],
    "補助額の見込み": {"区分": "従業員6〜20人", "特例": ["小規模の補助率"], "補助の対象にする経費": "f-002",
                       "理由": "常勤の従業員は12人", "会社の記録": ["f-001"]},
}

DOC_LIST = {
    "案件": CASE,
    "制度": {"名前": "テスト用 作業改善補助金", "略称": "テスト補助金", "枠": "一般型", "種類": "補助金", "公募回": "第4回"},
    "案件の回": "第4回",
    "直近回の資料に基づく": True,
    "案内": [NOTICE],
    "資料": seido()["資料"],
    "置き場所": {},
}


# ---- 出典の期待 ----


def label(src: dict) -> str:
    out = LABELS[src["資料"]]
    if "ページ" in src:
        out += f" p.{src['ページ']}" + (f"–{src['終わりのページ']}" if "終わりのページ" in src else "")
    return out


def srcs(*nodes) -> set:
    """制度データの値の出典（読み取れない値には出典がない）。"""
    out = set()
    for node in nodes:
        if node and node["状態"] != "読み取れない":
            out |= {label(s) for s in node["出典"]}
    return out


def cell_sources(cell: str) -> set:
    lines = [x for x in cell.split("\n") if x]
    assert len(lines) == len(set(lines)), f"出典が重なっています：{cell}"
    return set(lines)


# ---- 会社のフォルダと道具 ----


class Company:
    def __init__(self, tmp_path: Path) -> None:
        self.env = ct.Env(tmp_path)
        # 道具はプラグインの schema/ を読む（tests/company_tool.py の写しは lib/ と skills/ だけ）
        shutil.copytree(REPO_ROOT / "schema", self.env.plugin / "schema")
        self.folder = self.env.folder("架空 惣菜工房")
        (self.folder / ".hojokin").mkdir()
        (self.folder / "案件" / CASE / "公式資料").mkdir(parents=True)
        texts = self.folder / "記録" / "資料の本文" / CASE
        texts.mkdir(parents=True)
        (texts / "資料の一覧.json").write_text(json.dumps(DOC_LIST, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.folder / "記録" / "制度データ").mkdir(parents=True)
        self.put_seido(seido())
        self.put_record(record())

    def put_seido(self, data: dict) -> None:
        (self.folder / DATA_REL).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def put_record(self, data: dict) -> None:
        (self.folder / RECORD_REL).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def run(self, data, *args: str, folder: Path = None) -> subprocess.CompletedProcess:
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        env = {"PATH": self.env.path, "HOME": str(self.env.home), "TMPDIR": str(self.env.tmp)}
        return subprocess.run([hr.real_python(), "-B", str(self.env.plugin / TOOL), "--folder", str(folder or self.folder), *args],
                              input=text.encode("utf-8"), env=env, cwd=self.env.cwd, capture_output=True, timeout=120)

    @property
    def out(self) -> Path:
        return self.folder / OUT_REL

    def listing(self) -> list:
        return sorted(str(p.relative_to(self.folder)) for p in self.folder.rglob("*"))


def ok(r: subprocess.CompletedProcess) -> str:
    out = r.stdout.decode("utf-8")
    assert r.returncode == 0, (r.returncode, out, r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    return out


def refused(r: subprocess.CompletedProcess) -> str:
    out = r.stdout.decode("utf-8")
    assert r.returncode == 2, (r.returncode, out, r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    assert "作りませんでした" in out
    return out


# ---- Word を読む ----


def text_of(element) -> str:
    out = []
    for node in element.iter():
        if node.tag == W + "t":
            out.append(node.text or "")
        elif node.tag == W + "br":
            out.append("\n")
    return "".join(out)


class Word:
    """見出し1・見出し2の後の表を、その節の表として持つ。"""

    def __init__(self, path: Path) -> None:
        with zipfile.ZipFile(path) as zf:
            assert zf.testzip() is None
            for name in zf.namelist():
                if name.endswith((".xml", ".rels")):
                    ET.fromstring(zf.read(name))  # どの部品も XML として読める
            body = ET.fromstring(zf.read("word/document.xml")).find(W + "body")
        self.paragraphs = []
        self.tables = []
        h1 = h2 = None
        for child in body:
            if child.tag == W + "p":
                style = child.find(f"{W}pPr/{W}pStyle")
                style = style.get(W + "val") if style is not None else None
                text = text_of(child)
                if style == "Heading1":
                    h1, h2 = text, None
                elif style == "Heading2":
                    h2 = text
                self.paragraphs.append((style, h1, text))
            elif child.tag == W + "tbl":
                rows = [["\n".join(text_of(p) for p in tc.findall(W + "p")) for tc in tr.findall(W + "tc")]
                        for tr in child.findall(W + "tr")]
                self.tables.append((h1, h2, rows))
        self.text = "\n".join(t for _s, _h, t in self.paragraphs) + "\n" + "\n".join(
            "\n".join("\n".join(r) for r in rows) for _a, _b, rows in self.tables)

    def headings(self, level: int) -> list:
        return [t for s, _h, t in self.paragraphs if s == f"Heading{level}"]

    def table(self, h1: str, h2: str = None, first: str = None) -> list:
        """節の表の行（見出しの行を除く）。first は見出しの行のいちばん左の文字（同じ節に表が2つあるとき）。"""
        found = [rows for a, b, rows in self.tables if a == h1 and b == h2 and (first is None or rows[0][0] == first)]
        assert len(found) == 1, (h1, h2, first, [(a, b, r[0]) for a, b, r in self.tables])
        return found[0][1:]

    def section_paragraphs(self, h1: str) -> list:
        """節の中の、見出しでない段落（表の後の空の段落は除く）。"""
        return [t for s, h, t in self.paragraphs if h == h1 and s is None and t]


@pytest.fixture
def company(tmp_path) -> Company:
    return Company(tmp_path)


@pytest.fixture
def word(company) -> Word:
    out = ok(company.run(INPUT))
    assert str(OUT_REL) in out
    return Word(company.out)


# ---- 材料がスキーマを通る ----


def test_fixtures_follow_schemas() -> None:
    assert list(Draft202012Validator(SEIDO_SCHEMA).iter_errors(seido())) == []
    assert list(Draft202012Validator(RECORD_SCHEMA).iter_errors(record())) == []


# ---- 節がそろう ----


def test_sections_and_header(word: Word) -> None:
    assert word.headings(1) == [
        "制度の概要", "自社が満たす要件", "義務と返還の条件", "補助額の見込み", "申請から効果報告までの流れと期限",
        "加点", "必要書類", "資料で分からなかったこと", "資料どうしで書き方が違うところ", "出典の資料",
    ]
    head = word.paragraphs[1][2]
    assert f"案件：{CASE}" in head
    assert "制度：テスト用 作業改善補助金（一般型）" in head
    assert "第3回の資料に基づく" in head
    assert NOTICE in head  # 直近回の資料に基づくことを示す（SPEC F3）
    # 説明の文は Claude が書いたもの（渡したとおり、段落に分けて入る）
    assert word.section_paragraphs("制度の概要") == INPUT["制度の概要"]
    assert INPUT["流れの説明"] in word.section_paragraphs("申請から効果報告までの流れと期限")


# ---- 要件 ----


def test_requirements_match_seido(word: Word) -> None:
    data = seido()
    rows = word.table("自社が満たす要件")
    reqs = data["数値の要件"] + data["数値でない要件"]
    assert len(rows) == len(reqs)
    numeric = {"基準": "基準", "計算式": "計算式", "元の数字の決め方": "元の数字の決め方"}
    other = {"内容": "内容", "確かめ方": "確かめ方", "満たせないとき": "満たせないとき"}
    judges = {j["要件"]: j for j in INPUT["要件の判定"]}
    for row, req in zip(rows, reqs):
        name, body, status, source = row
        is_numeric = req in data["数値の要件"]
        kind = "（数値の要件）" if is_numeric else ("（当たると対象外）" if req["種類"] == "当たらないこと" else "（満たすこと）")
        assert name == f"{req['名前']}\n{kind}"
        fields = numeric if is_numeric else other
        expected_lines = []
        nodes = []
        for key, head in fields.items():
            if key not in req:
                continue
            node = req[key]
            nodes.append(node)
            if node["状態"] == "読み取れない":
                expected_lines.append(f"{head}：{UNREAD}（{node['理由']}）")
            else:
                expected_lines.append(f"{head}：{node['値']}")
        assert body.split("\n") == expected_lines, (name, body)
        judge = judges.get(req["名前"])
        expected_src = srcs(*nodes)
        if judge:
            assert status == f"{judge['判定']}\n{judge['理由']}"
            expected_src |= {REC[i] for i in judge.get("会社の記録", [])}
        else:
            assert status == NOT_JUDGED
        if expected_src:
            assert cell_sources(source) == expected_src, name
        else:
            assert source == "" and UNREAD in body, name  # 読み取れない値だけの行は、理由を出す


# ---- 義務と返還の条件 ----


def test_duties_and_refunds_match_seido(word: Word) -> None:
    data = seido()
    rows = word.table("義務と返還の条件", "満たせないと返還などがある数値の要件")
    reqs = [r for r in data["数値の要件"] if "満たせないとき" in r]
    assert [r[0] for r in rows] == [r["名前"] for r in reqs] == ["労働時間あたりの出来高", "最低の時給"]
    assert rows[0][1:] == ["年平均で3.0%以上伸ばす", "【要確認】補助金の一部を返す\n※裏取り：返す額の決め方がない",
                           "公募要領 p.2\n公募要領 p.4"]
    assert rows[1][1:3] == ["地域の最低賃金＋30円以上", "その年の分を返す"]
    for row, req in zip(rows, reqs):
        assert cell_sources(row[3]) == srcs(req["基準"], req["満たせないとき"])

    rows = word.table("義務と返還の条件", "してはいけないこと")
    assert len(rows) == len(data["してはいけないこと"])
    for row, item in zip(rows, data["してはいけないこと"]):
        assert row[0] == item["名前"]
        assert cell_sources(row[2]) == srcs(item["内容"])
    assert rows[0][1] == "交付決定の前に発注しない"
    assert rows[1][1] == "【資料で食い違い】同じ経費で他の補助金を受けない\n※手引では国と自治体の補助金"

    # 申請より後の手続きの段階の注意（申請の段階の注意は入らない）
    rows = word.table("義務と返還の条件", "採択後の手続きで守ること")
    stages = sorted(data["手続きの段階"], key=lambda s: s["順番"])[1:]
    notes = [(s["名前"], n) for s in stages for n in s.get("注意", [])]
    assert [(r[0], r[1]) for r in rows] == [(name, n["値"]) for name, n in notes]
    assert [cell_sources(r[2]) for r in rows] == [srcs(n) for _name, n in notes]
    assert "GビズIDを先に取る" not in "\n".join(r[1] for r in rows)


# ---- 補助額の見込み ----

# 自己負担の目安の2行目（どの見込みにも付く）
SELF_NOTE = "（補助の対象にする経費から補助額の見込みを引いたもの。消費税と、補助の対象にならない経費は別）"
# 上限の置き換え（賃上げ特例）と上乗せ（地域の上乗せ）の行
RAISE = ("賃上げ特例（上限の置き換え）\n条件：賃上げを大きく行う", {"公募要領 p.2"})
ADD_LINE = "上乗せ：【要確認】100万円\n※裏取り：上乗せの額が根拠の文にありません"
RAISE_AND_ADD = ("賃上げ特例（上限の置き換え）\n条件：賃上げを大きく行う\n地域の上乗せ（上限の上乗せ）",
                 {"公募要領 p.2", "スケジュールのページ"})

# 見込みと自己負担の目安は、2行目の計算（経費 × 補助率 ＝ 額。上限の◯の内／で頭打ち）まで1字ずつ比べる。
# 特例の件は、その特例を無視すると見込みか2行目が変わる経費にしてある（コメントの「無視すると」）。
ESTIMATES = {
    # 小規模の補助率 2/3：22,500,000 × 2/3 ＝ 15,000,000（上限 15,000,000 と同じなので「の内」）
    # 補助率の置き換えを無視すると 1/2 で 1,125万円
    "補助率の置き換え": (
        INPUT["補助額の見込み"],
        {"当たる区分": ("従業員6〜20人\n常勤の従業員は12人", {"公募要領 p.1", REC["f-001"]}),
         "使う特例": ("小規模の補助率（補助率の置き換え）\n条件：小規模事業者", {"公募要領 p.1"}),
         "補助上限": ("1,500万円", {"公募要領 p.1"}),
         "補助率": ("2/3", {"公募要領 p.1"}),
         "補助の対象にする経費": ("2,250万円", {REC["f-002"]}),
         "補助額の見込み": ("1,500万円\n（2,250万円 × 2/3 ＝ 1,500万円。上限の1,500万円の内）", {"公募要領 p.1", REC["f-002"]}),
         "自己負担の目安": (f"750万円\n{SELF_NOTE}", {"公募要領 p.1", REC["f-002"]})},
    ),
    # 上限の置き換え 2,000万円＋上乗せ 100万円（要確認）、補助率 1/2：22,500,000 × 1/2 ＝ 11,250,000。
    # 見込みは元の上限の内なので、置き換えと上乗せは2行目の「上限の2,100万円」にだけ出る（無視すると 1,500万円）
    "上限の置き換えと上乗せ（上限の内）": (
        {"区分": "従業員6〜20人", "特例": ["賃上げ特例", "地域の上乗せ"], "補助の対象にする経費": "f-002"},
        {"当たる区分": ("従業員6〜20人", {"公募要領 p.1"}),
         "使う特例": RAISE_AND_ADD,
         "補助上限": (f"2,000万円\n{ADD_LINE}", {"公募要領 p.2", "スケジュールのページ"}),
         "補助率": ("1/2", {"公募要領 p.1"}),
         "補助の対象にする経費": ("2,250万円", {REC["f-002"]}),
         "補助額の見込み": ("【要確認】1,125万円\n（2,250万円 × 1/2 ＝ 1,125万円。上限の2,100万円の内）",
                           {"公募要領 p.2", "スケジュールのページ", "公募要領 p.1", REC["f-002"]}),
         "自己負担の目安": (f"【要確認】1,125万円\n{SELF_NOTE}", {"公募要領 p.2", "スケジュールのページ", "公募要領 p.1", REC["f-002"]})},
    ),
    # 上限の置き換えが効く：36,000,000 × 1/2 ＝ 18,000,000。元の上限 1,500万円を超え、置き換えた 2,000万円の内。
    # 置き換えを無視すると 1,500万円で頭打ち
    "上限の置き換えが効く": (
        {"区分": "従業員6〜20人", "特例": ["賃上げ特例"], "補助の対象にする経費": "f-007"},
        {"当たる区分": ("従業員6〜20人", {"公募要領 p.1"}),
         "使う特例": RAISE,
         "補助上限": ("2,000万円", {"公募要領 p.2"}),
         "補助率": ("1/2", {"公募要領 p.1"}),
         "補助の対象にする経費": ("3,600万円", {REC["f-007"]}),
         "補助額の見込み": ("1,800万円\n（3,600万円 × 1/2 ＝ 1,800万円。上限の2,000万円の内）",
                           {"公募要領 p.2", "公募要領 p.1", REC["f-007"]}),
         "自己負担の目安": (f"1,800万円\n{SELF_NOTE}", {"公募要領 p.2", "公募要領 p.1", REC["f-007"]})},
    ),
    # 上乗せが効く：41,000,000 × 1/2 ＝ 20,500,000。置き換えた上限 2,000万円を超え、上乗せした 2,100万円の内。
    # 上乗せを無視すると 2,000万円で頭打ち
    "上乗せがないと頭打ち": (
        {"区分": "従業員6〜20人", "特例": ["賃上げ特例", "地域の上乗せ"], "補助の対象にする経費": "f-008"},
        {"当たる区分": ("従業員6〜20人", {"公募要領 p.1"}),
         "使う特例": RAISE_AND_ADD,
         "補助上限": (f"2,000万円\n{ADD_LINE}", {"公募要領 p.2", "スケジュールのページ"}),
         "補助率": ("1/2", {"公募要領 p.1"}),
         "補助の対象にする経費": ("4,100万円", {REC["f-008"]}),
         "補助額の見込み": ("【要確認】2,050万円\n（4,100万円 × 1/2 ＝ 2,050万円。上限の2,100万円の内）",
                           {"公募要領 p.2", "スケジュールのページ", "公募要領 p.1", REC["f-008"]}),
         "自己負担の目安": (f"【要確認】2,050万円\n{SELF_NOTE}", {"公募要領 p.2", "スケジュールのページ", "公募要領 p.1", REC["f-008"]})},
    ),
    # 置き換えて上乗せした上限で頭打ち：44,000,000 × 1/2 ＝ 22,000,000 → 2,000万円＋100万円 ＝ 2,100万円
    # （元の上限なら 1,500万円、上乗せを無視すると 2,000万円）
    "置き換えて上乗せした上限で頭打ち": (
        {"区分": "従業員6〜20人", "特例": ["賃上げ特例", "地域の上乗せ"], "補助の対象にする経費": "f-009"},
        {"当たる区分": ("従業員6〜20人", {"公募要領 p.1"}),
         "使う特例": RAISE_AND_ADD,
         "補助上限": (f"2,000万円\n{ADD_LINE}", {"公募要領 p.2", "スケジュールのページ"}),
         "補助率": ("1/2", {"公募要領 p.1"}),
         "補助の対象にする経費": ("4,400万円", {REC["f-009"]}),
         "補助額の見込み": ("【要確認】2,100万円\n（4,400万円 × 1/2 ＝ 2,200万円。上限の2,100万円で頭打ち）",
                           {"公募要領 p.2", "スケジュールのページ", "公募要領 p.1", REC["f-009"]}),
         "自己負担の目安": (f"【要確認】2,300万円\n{SELF_NOTE}", {"公募要領 p.2", "スケジュールのページ", "公募要領 p.1", REC["f-009"]})},
    ),
    # 上乗せだけ（元の上限に足す）：31,000,000 × 1/2 ＝ 15,500,000。1,500万円＋100万円 ＝ 1,600万円の内。
    # 上乗せを無視すると 1,500万円で頭打ち
    "上乗せだけ": (
        {"区分": "従業員6〜20人", "特例": ["地域の上乗せ"], "補助の対象にする経費": "f-010"},
        {"当たる区分": ("従業員6〜20人", {"公募要領 p.1"}),
         "使う特例": ("地域の上乗せ（上限の上乗せ）", {"スケジュールのページ"}),
         "補助上限": (f"1,500万円\n{ADD_LINE}", {"公募要領 p.1", "スケジュールのページ"}),
         "補助率": ("1/2", {"公募要領 p.1"}),
         "補助の対象にする経費": ("3,100万円", {REC["f-010"]}),
         "補助額の見込み": ("【要確認】1,550万円\n（3,100万円 × 1/2 ＝ 1,550万円。上限の1,600万円の内）",
                           {"公募要領 p.1", "スケジュールのページ", REC["f-010"]}),
         "自己負担の目安": (f"【要確認】1,550万円\n{SELF_NOTE}", {"公募要領 p.1", "スケジュールのページ", REC["f-010"]})},
    ),
    # 上乗せだけで頭打ち：41,000,000 × 1/2 ＝ 20,500,000 → 1,500万円＋100万円 ＝ 1,600万円。
    # 上乗せは1回だけ足す（同じ上乗せを2回渡すのは BAD_INPUTS で断る）。上乗せを無視すると 1,500万円で頭打ち
    "上乗せだけで頭打ち": (
        {"区分": "従業員6〜20人", "特例": ["地域の上乗せ"], "補助の対象にする経費": "f-008"},
        {"当たる区分": ("従業員6〜20人", {"公募要領 p.1"}),
         "使う特例": ("地域の上乗せ（上限の上乗せ）", {"スケジュールのページ"}),
         "補助上限": (f"1,500万円\n{ADD_LINE}", {"公募要領 p.1", "スケジュールのページ"}),
         "補助率": ("1/2", {"公募要領 p.1"}),
         "補助の対象にする経費": ("4,100万円", {REC["f-008"]}),
         "補助額の見込み": ("【要確認】1,600万円\n（4,100万円 × 1/2 ＝ 2,050万円。上限の1,600万円で頭打ち）",
                           {"公募要領 p.1", "スケジュールのページ", REC["f-008"]}),
         "自己負担の目安": (f"【要確認】2,500万円\n{SELF_NOTE}", {"公募要領 p.1", "スケジュールのページ", REC["f-008"]})},
    ),
    # 補助率と上限の両方の置き換え：27,000,000 × 2/3 ＝ 18,000,000。置き換えた上限 2,000万円の内。
    # 補助率の置き換えを無視すると 1,350万円、上限の置き換えを無視すると 1,500万円で頭打ち
    "補助率と上限の置き換え": (
        {"区分": "従業員6〜20人", "特例": ["小規模の補助率", "賃上げ特例"], "補助の対象にする経費": "f-011"},
        {"当たる区分": ("従業員6〜20人", {"公募要領 p.1"}),
         "使う特例": ("小規模の補助率（補助率の置き換え）\n条件：小規模事業者\n"
                     "賃上げ特例（上限の置き換え）\n条件：賃上げを大きく行う", {"公募要領 p.1", "公募要領 p.2"}),
         "補助上限": ("2,000万円", {"公募要領 p.2"}),
         "補助率": ("2/3", {"公募要領 p.1"}),
         "補助の対象にする経費": ("2,700万円", {REC["f-011"]}),
         "補助額の見込み": ("1,800万円\n（2,700万円 × 2/3 ＝ 1,800万円。上限の2,000万円の内）",
                           {"公募要領 p.2", "公募要領 p.1", REC["f-011"]}),
         "自己負担の目安": (f"900万円\n{SELF_NOTE}", {"公募要領 p.2", "公募要領 p.1", REC["f-011"]})},
    ),
    # 上限で頭打ち：20,000,000 × 1/2 ＝ 10,000,000 → 上限 7,500,000
    "上限で頭打ち": (
        {"区分": "従業員5人以下", "補助の対象にする経費": "f-005"},
        {"当たる区分": ("従業員5人以下", {"公募要領 p.1"}),
         "補助上限": ("750万円", {"公募要領 p.1"}),
         "補助率": ("1/2", {"公募要領 p.1"}),
         "補助の対象にする経費": ("2,000万円", {REC["f-005"]}),
         "補助額の見込み": ("750万円\n（2,000万円 × 1/2 ＝ 1,000万円。上限の750万円で頭打ち）", {"公募要領 p.1", REC["f-005"]}),
         "自己負担の目安": (f"1,250万円\n{SELF_NOTE}", {"公募要領 p.1", REC["f-005"]})},
    ),
    # 円未満は切り捨て：12,345,679 × 2/3 ＝ 8,230,452.66…
    "円未満の切り捨て": (
        {"区分": "従業員6〜20人", "特例": ["小規模の補助率"], "補助の対象にする経費": "f-006"},
        {"当たる区分": ("従業員6〜20人", {"公募要領 p.1"}),
         "使う特例": ("小規模の補助率（補助率の置き換え）\n条件：小規模事業者", {"公募要領 p.1"}),
         "補助上限": ("1,500万円", {"公募要領 p.1"}),
         "補助率": ("2/3", {"公募要領 p.1"}),
         "補助の対象にする経費": ("12,345,679円", {REC["f-006"]}),
         "補助額の見込み": ("8,230,452円\n（12,345,679円 × 2/3 ＝ 8,230,452円。上限の1,500万円の内）",
                           {"公募要領 p.1", REC["f-006"]}),
         "自己負担の目安": (f"4,115,227円\n{SELF_NOTE}", {"公募要領 p.1", REC["f-006"]})},
    ),
    # 上限が読み取れない区分では、見込みを出さない（推測で埋めない）
    "上限が読み取れない": (
        {"区分": "従業員21人以上", "補助の対象にする経費": "f-002"},
        {"当たる区分": ("従業員21人以上", {"公募要領 p.1"}),
         "補助上限": ("読み取れませんでした（上限が書かれていない）", set()),
         "補助率": ("1/2", {"公募要領 p.1"}),
         "補助の対象にする経費": ("2,250万円", {REC["f-002"]}),
         "補助額の見込み": ("出せません（補助上限が読み取れないため。事務局に確かめてから出し直します）",
                           {"公募要領 p.1", REC["f-002"]})},
    ),
}


@pytest.mark.parametrize("case", list(ESTIMATES))
def test_estimate_matches_seido_and_record(company: Company, case: str) -> None:
    spec, expected = ESTIMATES[case]
    data = dict(INPUT, 補助額の見込み=spec)
    out = ok(company.run(data))
    rows = Word(company.out).table("補助額の見込み")
    assert [r[0] for r in rows] == list(expected)
    for item, value, source in rows:
        want, want_src = expected[item]
        # どの行も、2行目（計算と上限、自己負担の注記）まで丸ごと比べる
        assert value == want, (item, value)
        if want_src:
            assert cell_sources(source) == want_src, item
        else:
            assert source == "" and UNREAD in value, item
    # 結果の行（担当者に見える）も、Word と同じ見込み
    want = expected["補助額の見込み"][0]
    if want.startswith("出せません"):
        line = f"- 補助額の見込み：出せませんでした（区分：{spec['区分']}。上限か補助率が読み取れない）"
    else:
        line = f"- 補助額の見込み：{want.split(chr(10))[0].replace('【要確認】', '')}（区分：{spec['区分']}）"
    assert line in out.split("\n"), out


def test_estimate_shows_calculation(word: Word) -> None:
    rows = {r[0]: r for r in word.table("補助額の見込み")}
    assert rows["補助額の見込み"][1] == "1,500万円\n（2,250万円 × 2/3 ＝ 1,500万円。上限の1,500万円の内）"


def test_no_estimate_without_input(company: Company) -> None:
    data = {k: v for k, v in INPUT.items() if k != "補助額の見込み"}
    out = ok(company.run(data))
    assert "補助額の見込み：まだ出していません" in out
    word = Word(company.out)
    assert not [t for a, _b, t in word.tables if a == "補助額の見込み"]
    assert any("まだ見込みを出していません" in p for p in word.section_paragraphs("補助額の見込み"))


# ---- 流れと期限 ----

LIMITS = {
    "申請": "2027年3月12日（金）16:00まで",
    "採択": "（期限の決まりは読み取っていません）",
    "交付申請": "「採択発表」から2か月以内",  # 出来事が段階の id なら、段階の名前にする
    "計画変更": f"{UNREAD}（期限の定めがない）",
    # 早いほうの中の早いほうは、1つの並びにする
    "実施": "【要確認】次のうち早いほう：\n・「交付決定日」から12か月以内\n・2028年12月28日（木）まで\n"
            "・「採択発表」から14か月以内\n※裏取り：早いほうの組み方を確かめる",
    "実績報告": "「事業の完了」から30日以内",
    "効果報告": "毎年1回、全5回（4月から3か月の間に出す）",
}


def test_flow_and_deadlines_match_seido(word: Word) -> None:
    data = seido()
    rows = word.table("申請から効果報告までの流れと期限", "手続きの流れ")
    stages = sorted(data["手続きの段階"], key=lambda s: s["順番"])
    assert [r[0] for r in rows] == [str(s["順番"]) for s in stages] == [str(n) for n in range(1, 8)]
    for row, stage in zip(rows, stages):
        _order, name, start, limit, source = row
        want = stage["名前"] + ("（必要なときだけ）" if stage.get("条件付き") else "")
        if stage.get("フォルダ"):
            want += f"\nフォルダ：{stage['フォルダ']}"
        assert name == want
        assert start == stage["始まる条件"]["値"]
        assert limit == LIMITS[stage["id"]], stage["id"]
        assert cell_sources(source) == srcs(stage["始まる条件"], stage.get("期限")), stage["id"]

    rows = word.table("申請から効果報告までの流れと期限", "決まった期日")
    assert rows == [
        ["申請の締切", "2027年3月12日（金）16:00", "公募要領 p.1"],
        ["採択発表", "2027年5月上旬（予定）", "スケジュールのページ"],
        ["交付申請の受付開始", f"{UNREAD}（後日お知らせとなっている）", ""],
    ]
    assert [r[0] for r in rows] == [d["名前"] for d in data["決まった期日"]]


# ---- 加点 ----


def test_bonus_points_match_seido(word: Word) -> None:
    data = seido()
    rows = word.table("加点", first="項目")
    assert rows == [["加点の種類の数", "2", "公募要領 p.3"],
                    ["区分ごとの上限", f"{UNREAD}（区分ごとの上限が書かれていない）", ""]]
    rows = word.table("加点", first="加点")
    items = data["加点"]["項目"]
    assert [r[0] for r in rows] == [i["名前"] for i in items]
    assert rows[0][1].split("\n") == ["内容：認定を受けた計画がある", "証拠の種類：入力", "かかる日数：認定まで約45日"]
    assert rows[0][2] == "今回は取れない\n認定まで約45日かかり、締切に間に合わない"
    assert cell_sources(rows[0][3]) == srcs(items[0]["内容"], items[0]["かかる日数"]) | {REC["f-004"]}
    assert rows[1][1].split("\n") == ["区分：政策", "内容：【資料で食い違い】賃上げを表明する", "※手引では別の書き方",
                                      "証拠の種類：添付", "必要な書類：賃上げ表明書", "自動で付く条件：賃上げ特例を選ぶと付く"]
    assert rows[1][2] == NOT_JUDGED
    assert cell_sources(rows[1][3]) == srcs(items[1]["内容"], items[1]["自動で付く条件"])


# ---- 必要書類 ----


def test_documents_match_seido_by_stage(word: Word) -> None:
    data = seido()
    stages = sorted(data["手続きの段階"], key=lambda s: s["順番"])
    groups = [(f"{s['名前']}で出す書類", [d for d in data["書類"] if s["id"] in d["手続き"]]) for s in stages]
    ids = {s["id"] for s in stages}
    groups.append(("どの手続きで使うか分からない書類", [d for d in data["書類"] if not set(d["手続き"]) & ids]))
    groups = [(title, docs) for title, docs in groups if docs]
    titles = [b for a, b, _rows in word.tables if a == "必要書類"]
    assert titles == [title for title, _docs in groups] == [
        "応募申請で出す書類", "交付申請で出す書類", "実績報告で出す書類", "どの手続きで使うか分からない書類"]
    order = {"必須": 0, "条件付き": 1, "任意": 2}
    for title, docs in groups:
        rows = word.table("必要書類", title)
        docs = sorted(docs, key=lambda d: order[d["区分"]])  # 区分の中は制度データの順
        assert [(r[0], r[1]) for r in rows] == [(d["名前"], d["区分"]) for d in docs], title
        for row, d in zip(rows, docs):
            body = row[2].split("\n")
            nodes = [d[k] for k in ("内容", "条件", "有効期限", "期数") if k in d]
            for key in ("内容", "条件", "有効期限", "期数"):
                if key in d:
                    assert f"{key}：{d[key]['値']}" in body, (d["名前"], key)
            assert f"発行元：{d['発行元']}" in body
            if d.get("効く審査項目"):
                assert f"効く審査項目：{'、'.join(d['効く審査項目'])}" in body
            assert cell_sources(row[3]) == srcs(*nodes), d["名前"]
    # 応募申請の書類は、必須 → 条件付き → 任意
    assert [r[0] for r in word.table("必要書類", "応募申請で出す書類")] == ["決算書", "登記簿の写し", "見積書", "賃上げ表明書", "会社案内"]


# ---- すべてに出典 ----

SECTIONS = ("自社が満たす要件", "義務と返還の条件", "補助額の見込み", "申請から効果報告までの流れと期限", "加点", "必要書類")


def test_every_row_has_source(word: Word) -> None:
    assert "（出典のある値がありません）" not in word.text
    checked = 0
    for h1, h2, rows in word.tables:
        if h1 not in SECTIONS:
            continue
        for row in rows[1:]:
            source = row[-1]
            if source:
                # 出典は、資料の名前（とページ）か、会社の記録の出典
                for line in source.split("\n"):
                    assert line in REC.values() or any(line == name or line.startswith(name + " p.")
                                                       for name in LABELS.values()), (h1, h2, row)
            else:
                # 出典のない行は、読み取れない値だけの行（理由を出す）
                assert UNREAD in "\n".join(row[:-1]), (h1, h2, row)
            checked += 1
    assert checked >= 40


def test_unreadable_items_and_conflicts_are_shown(word: Word) -> None:
    rows = word.table("資料で分からなかったこと")
    assert rows == [["加点の区分ごとの上限", "区分ごとの上限が書かれていない", "加点の区分ごとに、いくつまで選べますか。"]]
    rows = word.table("資料どうしで書き方が違うところ")
    assert rows == [["二重受給の範囲", "「国の補助金」（公募要領 p.4）\n「国と自治体の補助金」（交付申請の手引き（第2回） p.2）",
                     "公募要領 p.4\n交付申請の手引き（第2回） p.2"]]
    rows = word.table("出典の資料")
    assert [(r[0], r[1], r[2]) for r in rows] == [(d["名前"], d["公募回"], d["URL"]) for d in seido()["資料"]]


# ---- 作り直しと、書かないとき ----


def test_rewrite_replaces_same_file(company: Company) -> None:
    ok(company.run(INPUT))
    before = company.listing()
    first = company.out.read_bytes()
    ok(company.run(INPUT))
    assert company.out.read_bytes() == first  # 同じ中身からは同じファイル
    changed = dict(INPUT, 制度の概要="説明の文を直しました。")
    ok(company.run(changed))
    assert company.listing() == before  # ほかのファイルは増えない（_v2 や書きかけの一時ファイルを残さない）
    assert company.out.read_bytes() != first
    assert Word(company.out).section_paragraphs("制度の概要") == ["説明の文を直しました。"]
    assert not list(company.folder.rglob("__pycache__")) and not list(company.env.plugin.rglob("__pycache__"))


def test_text_that_xml_cannot_hold_is_cleaned(company: Company) -> None:
    data = dict(INPUT, 制度の概要="改ページの\x0cあとの文\x01です")
    ok(company.run(data))
    assert Word(company.out).section_paragraphs("制度の概要") == ["改ページの\nあとの文です"]


def _bad(**changes):
    data = copy.deepcopy(INPUT)
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return data


BAD_INPUTS = {
    "要件の名前が制度データにない": (_bad(要件の判定=[{"要件": "ない要件", "判定": "満たす", "理由": "…"}]), "ない要件"),
    "判定の言葉が違う": (_bad(要件の判定=[{"要件": "最低の時給", "判定": "たぶん", "理由": "…"}]), "判定"),
    "加点の名前が制度データにない": (_bad(加点の判定=[{"加点": "ない加点", "判定": "取れる見込み", "理由": "…"}]), "ない加点"),
    "会社の記録の id がない": (_bad(要件の判定=[{"要件": "最低の時給", "判定": "満たす", "理由": "…", "会社の記録": ["f-999"]}]), "f-999"),
    "区分が制度データにない": (_bad(補助額の見込み={"区分": "従業員100人", "補助の対象にする経費": "f-002"}), "従業員100人"),
    "特例が区分にない": (_bad(補助額の見込み={"区分": "従業員5人以下", "特例": ["賃上げ特例"], "補助の対象にする経費": "f-002"}), "賃上げ特例"),
    # 名前の違う、同じ種類の置き換え（補助率の置き換えを2つ）
    "同じ種類の特例を2つ": (_bad(補助額の見込み={"区分": "従業員5人以下", "特例": ["小規模の補助率", "創業の補助率"],
                                                 "補助の対象にする経費": "f-002"}), "同じ種類"),
    # 同じ特例を2回。上乗せを2回足すと、制度データにない上限と見込みになる
    # （4,100万円 × 1/2 ＝ 2,050万円は、上限 1,500万円＋上乗せ 100万円 ＝ 1,600万円で頭打ちのはずが、
    #   2回で 1,700万円、3回で 1,800万円になる。正しい見込みは ESTIMATES の「上乗せだけで頭打ち」）
    "同じ上乗せを2つ": (_bad(補助額の見込み={"区分": "従業員6〜20人", "特例": ["地域の上乗せ", "地域の上乗せ"],
                                             "補助の対象にする経費": "f-008"}), "同じ特例「地域の上乗せ」"),
    "同じ上乗せを3つ": (_bad(補助額の見込み={"区分": "従業員6〜20人", "特例": ["地域の上乗せ"] * 3,
                                             "補助の対象にする経費": "f-008"}), "同じ特例「地域の上乗せ」"),
    "同じ上乗せを置き換えと合わせて2つ": (_bad(補助額の見込み={"区分": "従業員6〜20人",
                                                               "特例": ["地域の上乗せ", "賃上げ特例", "地域の上乗せ"],
                                                               "補助の対象にする経費": "f-008"}), "同じ特例「地域の上乗せ」"),
    # 前後の空白（全角も）だけの違いでも、同じ特例として断る
    "同じ上乗せを空白違いで2つ": (_bad(補助額の見込み={"区分": "従業員6〜20人", "特例": ["地域の上乗せ", " 地域の上乗せ　"],
                                                       "補助の対象にする経費": "f-008"}), "同じ特例「地域の上乗せ」"),
    # NFD（濁点を分けた形）の違いだけでも、同じ特例として断る
    "同じ置き換えを NFD で2つ": (_bad(補助額の見込み={"区分": "従業員6〜20人",
                                                      "特例": ["賃上げ特例", unicodedata.normalize("NFD", "賃上げ特例")],
                                                      "補助の対象にする経費": "f-002"}), "同じ特例「賃上げ特例」"),
    "同じ置き換えを2つ": (_bad(補助額の見込み={"区分": "従業員6〜20人", "特例": ["賃上げ特例", "賃上げ特例"],
                                               "補助の対象にする経費": "f-002"}), "同じ特例「賃上げ特例」"),
    "経費が金額でない": (_bad(補助額の見込み={"区分": "従業員6〜20人", "補助の対象にする経費": "f-004"}), "円の金額"),
    "制度の概要がない": (_bad(制度の概要=None), "制度の概要"),
    "使わない欄": (_bad(補助率="2/3"), "補助率"),
    "JSON でない": ("{ 制度の概要", "JSON"),
}


@pytest.mark.parametrize("case", list(BAD_INPUTS))
def test_bad_input_writes_nothing(company: Company, case: str) -> None:
    data, word_in_message = BAD_INPUTS[case]
    before = company.listing()
    out = refused(company.run(data))
    assert word_in_message in out
    assert company.listing() == before and not company.out.exists()
    # 前に書いた概要と流れ.docx も、そのまま残る
    ok(company.run(INPUT))
    first = company.out.read_bytes()
    refused(company.run(data))
    assert company.out.read_bytes() == first


def test_refuses_outside_company_folder(company: Company) -> None:
    other = company.env.folder("ただのフォルダ")
    out = refused(company.run(INPUT, folder=other))
    assert "会社のフォルダではありません" in out
    assert list(other.iterdir()) == []


def test_refuses_without_seido_data(company: Company) -> None:
    (company.folder / DATA_REL).unlink()
    out = refused(company.run(INPUT))
    assert "制度データ" in out and not company.out.exists()


def test_refuses_broken_seido_data(company: Company) -> None:
    data = seido()
    del data["補助額"]
    company.put_seido(data)
    out = refused(company.run(INPUT))
    assert "形が合いません" in out and not company.out.exists()


# ---- 会社のフォルダの外のファイルは読まない（DESIGN 5章「会社のフォルダの外に書かない・外を読まない」） ----

SECRET = "外のファイルの中身がそのまま入る"


def test_refuses_input_file_outside_company_folder(company: Company) -> None:
    outside = company.env.folder("外のフォルダ")
    # 読めば書いてしまう中身（正しい形）と、読めば欄の名前が直す所の一覧に出る中身
    good = outside / "判定.json"
    good.write_text(json.dumps(dict(INPUT, 制度の概要=SECRET), ensure_ascii=False), encoding="utf-8")
    odd = outside / "秘密.json"
    odd.write_text(json.dumps({"秘密の欄": SECRET}, ensure_ascii=False), encoding="utf-8")
    # 会社のフォルダの中から外を指す別名も、外として断る
    link = company.folder / "記録" / "判定へのリンク.json"
    link.symlink_to(good)
    before = company.listing()
    wheres = [str(good), str(odd), str(link), "記録/判定へのリンク.json",
              "../外のフォルダ/判定.json",  # 相対の場所は会社のフォルダから解く
              str(company.folder / ".." / "外のフォルダ" / "秘密.json")]
    for where in wheres:
        # 標準入力には正しい JSON を流す（--input を無視して標準入力を読めば、書いてしまうので分かる）
        out = refused(company.run(INPUT, "--input", where))
        assert "外のファイルは読みません" in out, (where, out)
        assert SECRET not in out and "秘密の欄" not in out, (where, out)
        assert company.listing() == before and not company.out.exists(), where


def test_refuses_input_file_when_not_company_folder(company: Company) -> None:
    other = company.env.folder("ただのフォルダ")
    secret = other / "判定.json"
    secret.write_text(json.dumps({"秘密の欄": SECRET}, ensure_ascii=False), encoding="utf-8")
    out = refused(company.run(INPUT, "--input", str(secret), folder=other))
    assert "会社のフォルダではありません" in out and "読んでいません" in out
    assert SECRET not in out and "秘密の欄" not in out
    assert list(other.iterdir()) == [secret]


def test_reads_input_from_stdin_or_file_inside_company_folder(company: Company) -> None:
    ok(company.run(INPUT, "--input", "-"))
    assert Word(company.out).section_paragraphs("制度の概要") == INPUT["制度の概要"]
    inner = company.folder / "記録" / "概要の判定.json"
    inner.write_text(json.dumps(dict(INPUT, 制度の概要="中のファイルの説明です。"), ensure_ascii=False), encoding="utf-8")
    for where in (str(inner), "記録/概要の判定.json"):  # 相対の場所は、今いるフォルダでなく会社のフォルダから解く
        company.out.unlink()
        # 標準入力は JSON でない（ファイルを読まなければ断られるので分かる）
        ok(company.run("{ JSON でない", "--input", where))
        assert Word(company.out).section_paragraphs("制度の概要") == ["中のファイルの説明です。"]
