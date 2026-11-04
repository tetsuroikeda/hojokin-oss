"""模擬の申請画面（省力化・一般型 第8回）の画面の定義。

電子申請マニュアル（応募申請）第8回の画面の並び（❶〜⓬）に合わせる。
- D11a の1画面版（/shinsei）は、❶〜⓬ の段を縦に並べる。
- D11b の12画面版（/shinsei/1〜/shinsei/12）は、段を1つずつ別の画面にする。
  画面ごとのボタン（nav・screen_buttons）は、マニュアルの画面の絵に合わせる。
どちらも同じ欄の定義を使い、同じ記録に残す。

- 項目名はマニュアルの画面と同じにする（入力シートと照らすため）。
  宣誓の文・説明・注意書きは写さず、自分の言葉で短く書く。
- 文字数の上限は読み取れていないので付けない（DESIGN 14章）。
- チェック欄・ラジオボタン・選択欄は、囲むラベルで名前を付ける（DESIGN 5章）。
  担当者が入れる欄（who="person"）の名前には「確認」「誓約」「同意」「宣誓」のどれかを入れ、
  ツールが入れる欄（who="tool"）の名前には、この4語を入れない。
- 守り（hook）が押してよいボタンを決めるのは、制度データの画面の定義で、この定義ではない。

`python3 mock/screen.py` で、12画面版の画面ごとの欄とボタンの一覧を Markdown の表で出す。
`python3 mock/screen.py --one-page` で、D11a の1画面版の一覧を出す。
"""

from __future__ import annotations

import sys

# 入力値.json の名前（1画面版と12画面版で同じ記録を使う）
MOCK_NAME = "省力化投資補助金（一般型）第8回 応募申請の模擬画面"
SCREEN_NAME = MOCK_NAME + "（D11a・1画面版）"
SCREENS_NAME = MOCK_NAME + "（D11b・12画面版）"
MANUAL = "電子申請マニュアル（応募申請）第8回（downloads/shoryokuka_ippan/electronic_application_manual_ippan_08.pdf）"

# 担当者が入れる欄の名前に入れる語（DESIGN 5章の守りが見分けに使う）
PERSON_WORDS = ("確認", "誓約", "同意", "宣誓")

PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]

ORG_TYPES = [
    "1-1.中小企業者（組合関連以外）",
    "2-1.企業組合",
    "2-2.協業組合",
    "2-3.事業協同組合、事業協同小組合、協同組合連合会",
    "2-4.商工組合、商工組合連合会",
    "2-5.商店街振興組合、商店街振興組合連合会",
    "2-6.水産加工業協同組合、水産加工業協同組合連合会",
    "2-7.生活衛生同業組合、生活衛生同業小組合、生活衛生同業組合連合会",
    "2-8.酒造組合、酒造組合連合会、酒造組合中央会、酒販組合、酒販組合連合会、酒販組合中央会",
    "2-9.内航海運組合、内航海運組合連合会",
    "2-10.技術研究組合",
    "3-1.特定非営利活動法人（NPO法人）",
    "3-2.社会福祉法人",
    "3-3.歯科医業を営む医療法人",
]

# 模擬では中分類の一部だけを置く
INDUSTRIES = [
    "総合工事業", "食料品製造業", "飲料・たばこ・飼料製造業", "繊維工業", "金属製品製造業",
    "生産用機械器具製造業", "道路貨物運送業", "各種商品小売業", "飲食料品小売業", "飲食店",
    "持ち帰り・配達飲食サービス業", "洗濯・理容・美容・浴場業", "社会保険・社会福祉・介護事業",
]

YEARS = [str(y) for y in range(2020, 2031)]
MONTHS = [str(m) for m in range(1, 13)]

PDF = ".pdf"
EXCEL = ".xlsx,.xls"
PDF_IMAGE = ".pdf,.jpg,.jpeg,.png"
ANY_DOC = ".xlsx,.xls,.docx,.doc,.pdf,.jpg,.jpeg,.png"
ACCEPT_NAMES = {PDF: "PDF", EXCEL: "Excel", PDF_IMAGE: "PDF・JPEG・PNG", ANY_DOC: "Excel・Word・PDF・JPEG・PNG"}


def f(id: str, label: str, kind: str = "text", page: int = 0, who: str = "tool", required: bool = False, **extra) -> dict:
    """欄を1つ作る。kind は text・textarea・number・select・checkbox・checkboxes・radio・file・display。"""
    return {"id": id, "label": label, "kind": kind, "page": page, "who": who, "required": required, **extra}


def group(title: str, page: int, fields: list, note: str = "") -> dict:
    return {"title": title, "page": page, "fields": fields, "note": note}


def ym(id: str, label: str, page: int) -> list:
    """年と月の選択欄の組。"""
    return [
        f(id + "_year", label + "（年）", "select", page, options=YEARS),
        f(id + "_month", label + "（月）", "select", page, options=MONTHS),
    ]


def address(prefix: str, page: int, office: bool = False, page2: int = 0) -> list:
    """所在地の欄の組。page2 は、番地等から後がマニュアルの次のページに載っているときのページ。"""
    page2 = page2 or page
    fields = [
        f(prefix + "_zip", "郵便番号", "text", page, required=True),
        f(prefix + "_pref", "都道府県", "select", page, required=True, options=PREFECTURES),
        f(prefix + "_city", "市区町村", "text", page, required=True),
        f(prefix + "_town", "町域", "text", page, required=True),
        f(prefix + "_street", "番地等", "text", page2, required=True),
        f(prefix + "_building", "建物名", "text", page2),
    ]
    if office:
        fields.append(f(prefix + "_office", "事業所名", "text", page2))
    return fields


# ❼ 事業計画数値の表。cells は列ごとに "in"（入力）・"calc"（計算）・"none"（なし）。既定は "in"
PLAN_COLS = [("y0", "基準年度")] + [(f"y{n}", f"{n}年目計画") for n in range(1, 6)]
NO_BASE = {"y0": "none"}
ALL_CALC = {c: "calc" for c, _ in PLAN_COLS}
CALC_NO_BASE = {**ALL_CALC, "y0": "none"}
PLAN_ROWS = [
    {"key": "sales", "label": "売上高"},
    {"key": "cogs", "label": "売上原価（製造原価）"},
    {"key": "gross_profit", "label": "売上総利益", "cells": ALL_CALC},
    {"key": "sga", "label": "販売費及び一般管理費（人件費・減価償却費を含む）"},
    {"key": "operating_profit", "label": "①営業利益", "cells": ALL_CALC},
    {"key": "personnel", "label": "②人件費"},
    {"key": "depreciation", "label": "③減価償却費", "cells": ALL_CALC},
    {"key": "dep_existing", "label": "（内訳）既存設備の減価償却費"},
    {"key": "dep_new", "label": "本補助金で導入する設備の減価償却費", "cells": NO_BASE},
    {"key": "value_added", "label": "④付加価値額（①＋②＋③）", "cells": ALL_CALC},
    {"key": "va_growth", "label": "付加価値額の年平均成長率（％）", "cells": CALC_NO_BASE},
    {"key": "officers", "label": "労働者数のうち役員数（人）"},
    {"key": "employees", "label": "労働者数のうち常勤従業員数（人）"},
    {"key": "productivity", "label": "労働生産性", "cells": ALL_CALC},
    {"key": "productivity_target", "label": "労働生産性の目標値", "cells": CALC_NO_BASE},
]
SALARY_ROWS = [
    {"key": "salary_total", "label": "⑤全月分の給与等の支給を受けた従業員の給与支給総額"},
    {"key": "salary_count", "label": "⑥全月分の給与等の支給を受けた従業員数"},
    {"key": "salary_per", "label": "従業員1人当たり給与支給総額（⑤÷⑥）", "cells": ALL_CALC},
    {"key": "salary_growth", "label": "従業員1人当たり給与支給総額の年平均成長率（％）", "cells": CALC_NO_BASE},
    {"key": "salary_target", "label": "（参考）従業員1人当たり給与支給総額の目標値", "cells": CALC_NO_BASE},
]

# ❽ 経費明細表
EXPENSE_COLS = [("a", "（A）事業に要する経費（税込みの額）", "number"),
                ("b", "（B）補助対象経費（税抜きの額）", "number"),
                ("c", "（C）積算基礎（（B）の内訳）", "textarea")]
EXPENSE_ROWS = [
    {"key": "machine", "label": "機械装置・システム構築費"},
    {"key": "transport", "label": "運搬費"},
    {"key": "tech", "label": "技術導入費"},
    {"key": "ip", "label": "知的財産権等関連経費"},
    {"key": "outsourcing", "label": "外注費"},
    {"key": "expert", "label": "専門家経費"},
    {"key": "cloud", "label": "クラウドサービス利用費"},
    {"key": "total", "label": "合計", "cells": {"a": "calc", "b": "calc", "c": "none"}},
]
FUND_COLS = [("amount", "事業に要する経費（円）", "number"), ("source", "資金の調達先", "text")]
FUND_ALL_ROWS = [
    {"key": "own", "label": "自己資金", "cells": {"source": "none"}},
    {"key": "subsidy", "label": "補助金申請額（D）", "cells": {"amount": "calc", "source": "none"}},
    {"key": "loan", "label": "借入金"},
    {"key": "lease", "label": "その他（ファイナンス・リース）"},
    {"key": "total", "label": "合計額", "cells": {"amount": "calc", "source": "none"}},
]
FUND_D_ROWS = [
    {"key": "own", "label": "自己資金", "cells": {"source": "none"}},
    {"key": "loan", "label": "借入金"},
    {"key": "lease", "label": "その他（ファイナンス・リース）"},
    {"key": "total", "label": "合計額", "cells": {"amount": "calc", "source": "none"}},
]


def grid(id: str, label: str, page: int, rows: list, cols: list) -> dict:
    """表の欄。cols は (列の鍵, 列の名前) か (列の鍵, 列の名前, 種類)。"""
    cols = [c if len(c) == 3 else (c[0], c[1], "number") for c in cols]
    return f(id, label, "grid", page, rows=rows, cols=cols)


def grid_cells(g: dict) -> list:
    """表の中の入力欄を、ふつうの欄として取り出す。"""
    cells = []
    for row in g["rows"]:
        for col, col_label, kind in g["cols"]:
            if row.get("cells", {}).get(col, "in") != "in":
                continue
            cells.append(f(f"{g['id']}_{row['key']}_{col}", f"{row['label']}（{col_label}）", kind, g["page"],
                           grid=g["id"], table=g["label"]))
    return cells


def kasan(id: str, title: str, text: str, page: int) -> dict:
    """加点のチェック欄。名前は「項目名：説明」にする。"""
    return f(id, f"{title}：{text}", "checkbox", page)


# 12画面版で、画面の上と下に置くボタン（値の並び。マニュアル p.6 と各画面の絵）。
# ❶・❿・⓫ には一時保存がなく（p.7、p.25–27）、⓬ には置かない（p.28。修正と提出だけ）
NAV_FULL = ("back", "save", "next")
NAV_NO_SAVE = ("back", "next")

SECTIONS = [
    {
        "no": "❶", "key": "s1", "title": "宣誓・手引き", "pages": "7", "nav": NAV_NO_SAVE,
        "groups": [
            group("1-1. 公募要領・手引き", 7, [
                f("guide_links", "公募要領と応募申請の手引き", "display", 7, who="display",
                  value="（模擬なので、資料へのリンクは置いていません）"),
            ]),
            group("1-2. 宣誓事項", 7, [
                f("oath_1", "宣誓事項1：公募要領を理解し、申請者自身が計画を作って申請することに同意する", "checkbox", 7, who="person", required=True),
                f("oath_2", "宣誓事項2：補助の対象となる事業者と事業に当たることを確認した", "checkbox", 7, who="person", required=True),
                f("oath_3", "宣誓事項3：不正があったときは、交付の取消しや公表などの措置に従うことを誓約する", "checkbox", 7, who="person", required=True),
                f("oath_4", "宣誓事項4：計画の達成状況の報告と、求められた調査に協力することに同意する", "checkbox", 7, who="person", required=True),
                f("oath_5", "宣誓事項5：反社会的勢力に当たらないことを宣誓する", "checkbox", 7, who="person", required=True),
            ], note="模擬の宣誓事項です（本物の文ではありません）。担当者が自分で読んでチェックを入れる欄です。"),
        ],
    },
    {
        "no": "❷", "key": "s2", "title": "基本情報", "pages": "8–9", "nav": NAV_FULL,
        "groups": [
            group("2-1. 事業者情報", 8, [
                f("biz_form", "事業形態", "display", 8, who="display", value="法人"),
                f("org_type", "組織形態", "select", 8, required=True, options=ORG_TYPES),
                f("corp_number", "法人番号", "text", 8),
                f("biz_name", "事業者名（法人名／屋号・商号）", "text", 8, required=True),
                f("biz_name_kana", "事業者名（カナ）", "text", 8, required=True),
                f("rep_title", "法人代表者役職", "text", 8, required=True),
                f("rep_last", "代表者氏名（姓）", "text", 8, required=True),
                f("rep_first", "代表者氏名（名）", "text", 8, required=True),
                f("rep_last_kana", "代表者氏名カナ（セイ）", "text", 8, required=True),
                f("rep_first_kana", "代表者氏名カナ（メイ）", "text", 8, required=True),
                f("rep_tel", "代表電話番号", "text", 8, required=True),
                f("biz_url", "事業者HPのURL", "text", 8),
                f("employees", "従業員数", "number", 8, required=True, unit="人"),
                f("capital", "資本金（出資金）", "number", 8, required=True, unit="円"),
                f("founded", "創業・設立日（西暦）", "text", 8, required=True, placeholder="YYYY/MM/DD"),
            ]),
            group("2-2. 本店所在地", 9, address("hq", 9)),
            group("2-3. 自身の該当する業種", 9, [
                f("industry_code", "業種コード", "text", 9, required=True),
                f("industry_names", "大分類・中分類・小分類・細分類", "display", 9, who="display",
                  value="（模擬では、業種コードから分類を表示しません）"),
            ]),
            group("2-4. 担当者情報", 9, [
                f("staff_title", "担当者の役職", "text", 9),
                f("staff_last", "担当者氏名（姓）", "text", 9, required=True),
                f("staff_first", "担当者氏名（名）", "text", 9, required=True),
                f("staff_last_kana", "担当者氏名カナ（セイ）", "text", 9, required=True),
                f("staff_first_kana", "担当者氏名カナ（メイ）", "text", 9, required=True),
                f("staff_email", "担当者メールアドレス", "text", 9, required=True),
                f("staff_tel", "担当者電話番号", "text", 9, required=True),
            ], note="担当者メールアドレスを入れたら「認証コード発行」を押します（⓫で使います）。"),
        ],
        "buttons": [("issue_code", "認証コード発行", 9, "2-4. 担当者情報")],
    },
    {
        "no": "❸", "key": "s3", "title": "要件", "pages": "10–11", "nav": NAV_FULL,
        "groups": [
            group("3-1. 小規模企業者・小規模事業者・再生事業者", 10, [
                f("small_business", "小規模企業者・小規模事業者：該当する", "checkbox", 10),
                f("revival", "再生事業者：該当する", "checkbox", 10),
            ]),
            group("3-2. みなし同一法人でないことの確認", 10, [
                f("not_same_corp", "みなし同一法人でないことの確認：みなし同一法人による申請でないことを宣誓する", "checkbox", 10, who="person", required=True),
            ]),
            group("3-3. みなし大企業でないことの確認", 10, [
                f("not_large", "みなし大企業でないことの確認：みなし大企業による申請でないことを宣誓する", "checkbox", 10, who="person", required=True),
            ]),
            group("3-4. 風俗営業等に関する確認", 10, [
                f("not_adult", "風俗営業等に関する確認：風俗営業等の事業でないことを宣誓する", "checkbox", 10, who="person", required=True),
            ]),
            group("3-5. 「両立支援のひろば」に関する確認", 10, [
                f("ryoritsu_url", "「両立支援のひろば」の企業データ詳細ページのURL", "text", 10),
                f("ryoritsu_oath", "両立支援のひろば：交付申請時までに行動計画を公表することを宣誓する", "checkbox", 10, who="person"),
            ], note="従業員21人以上のときの欄です。"),
            group("3-6. 国の他の助成制度との重複確認", 11, [
                f("other_subsidy", "国の他の助成制度との重複", "radio", 11, required=True, options=["はい", "いいえ"]),
            ], note="過去5年に国の他の助成制度の交付を受けたか、今申請しているかを答えます。"),
        ],
    },
    {
        "no": "❹", "key": "s4", "title": "加点項目", "pages": "12–13", "nav": NAV_FULL,
        "groups": [
            group("①事業承継又はM&Aを実施した事業者", 12, [
                kasan("kasan_succession", "事業承継又はM&A加点", "過去3年以内に事業承継やM&Aで経営資源を引き継いだ", 12)]),
            group("②事業継続力強化計画／連携事業継続力強化計画に対する加点", 12, [
                kasan("kasan_bcp", "事業継続力強化計画加点", "有効な期間の認定を受けている", 12),
                f("bcp_number", "受付番号（半角10桁）", "text", 12),
                *ym("bcp_start", "実施期間開始期", 12),
                *ym("bcp_end", "実施期間終期", 12),
            ], note="紙で認定を受けた場合、受付番号は「紙申請」と入れます。"),
            group("③成長加速マッチングサービスに登録している事業者に対する加点", 12, [
                kasan("kasan_matching", "成長加速マッチングサービス加点", "挑戦課題を登録している", 12)]),
            group("④地域別最低賃金引き上げに係る加点", 12, [
                kasan("kasan_regional_wage", "地域別最低賃金引き上げ加点", "加点の要件を満たす", 12)]),
            group("⑤事業場内最低賃金引き上げに係る加点", 12, [
                kasan("kasan_inhouse_wage", "事業場内最低賃金引き上げ加点", "加点の要件を満たす", 12)]),
            group("⑥えるぼし加点", 12, [kasan("kasan_eruboshi", "えるぼし加点", "えるぼし認定を受けている", 12)]),
            group("⑦くるみん加点", 13, [kasan("kasan_kurumin", "くるみん加点", "くるみん認定を受けている", 13)]),
            group("⑧省力化ナビ加点", 13, [kasan("kasan_navi", "省力化ナビ加点", "省力化ナビで解決策のPDFを取得している", 13)]),
            group("⑨健康経営優良法人加点", 13, [kasan("kasan_health", "健康経営優良法人加点", "健康経営優良法人に認定されている", 13)]),
            group("⑩生産性向上支援センター利用加点", 13, [
                kasan("kasan_center", "生産性向上支援センター利用加点", "支援を受けて取組計画書を作った", 13)]),
        ],
    },
    {
        "no": "❺", "key": "s5", "title": "事業計画名及び作成者情報", "pages": "14–15", "nav": NAV_FULL,
        "groups": [
            # 「程度」は目安で、上限ではない。項目名は画面のとおりにし、上限は付けない
            group("5-1. 事業計画名", 14, [f("plan_name", "事業計画名（３０文字程度）", "text", 14, required=True)]),
            group("5-2. 事業計画の概要", 14, [
                f("plan_industry", "本事業で取り組む対象分野となる業種（日本標準産業分類、中分類）", "select", 14,
                  required=True, options=INDUSTRIES),
                f("plan_summary", "事業計画の概要（１００字程度）", "textarea", 14, required=True),
                f("plan_equipment", "導入予定の機械装置・システムの名称", "textarea", 14, required=True,
                  placeholder="メーカー名：型式：名称："),
                f("no_equipment", "機器装置の導入を含まない", "checkbox", 14),
                f("uses_genai", "生成AIの導入を含む", "checkbox", 14),
                f("catalog_product", "カタログ注文型のカテゴリに当たる製品を導入する", "checkbox", 14),
            ]),
            group("5-3. 補助事業の主たる実施場所", 14, [
                *address("site", 14, office=True, page2=15),
                f("multi_sites", "事業実施場所が2か所以上ある", "checkbox", 15),
            ]),
            group("5-4. イノベーション製品応援プログラムへの参加", 15, [
                f("innovation", "イノベーション製品応援プログラムへの参加：参加する", "checkbox", 15)]),
            group("5-5. アトツギ甲子園への出場", 15, [
                f("atotsugi", "アトツギ甲子園への出場：ピッチ大会に出場したことがある", "checkbox", 15)]),
            group("5-6. 関税影響事業者の申告", 15, [
                f("tariff", "関税影響事業者の申告：関税影響事業者である", "checkbox", 15)]),
            group("5-7. 事業計画書作成支援者情報", 15, [
                f("no_supporter", "支援者なし", "checkbox", 15),
                f("supporter_org", "支援機関名", "text", 15),
                f("supporter_fee", "支援報酬（予定）額", "number", 15, unit="円"),
                f("supporter_months", "契約期間", "number", 15, unit="ヶ月"),
                f("supporter_dept", "支援担当者部署名", "text", 15),
                f("supporter_name", "支援担当者名", "text", 15),
                f("supporter_tel", "支援者連絡先電話番号", "text", 15),
                f("supporter_email", "支援者メールアドレス", "text", 15),
                f("supporter_id", "認定経営革新等支援機関ID", "text", 15),
            ], note="支援者がいないときは「支援者なし」にチェックします。支援を受けたときは各欄を入れます。"),
            group("5-8. 直近決算期の決算月", 15, [
                f("fiscal_month", "直近決算期の決算月", "select", 15, required=True, options=MONTHS, unit="月")]),
        ],
    },
    {
        "no": "❻", "key": "s6", "title": "最低賃金及び特例希望", "pages": "16", "nav": NAV_FULL,
        "groups": [
            group("6-1. 大幅賃上げに係る補助上限額引き上げの特例", 16, [
                f("special_raise", "大幅賃上げに係る補助上限額引き上げの特例：希望する", "checkbox", 16)]),
            group("6-2. 最低賃金引き上げに係る補助率引き上げの特例", 16, [
                f("special_min_wage", "最低賃金引き上げに係る補助率引き上げの特例：希望する", "checkbox", 16)]),
            group("6-3. 事業場内の最低賃金", 16, [
                *ym("min_wage_month", "直近月の事業場内の最低賃金（対象年月）", 16),
                f("min_wage", "事業場内最低賃金", "number", 16, required=True, unit="円"),
                f("regional_min_wage", "地域別最低賃金", "display", 16, who="display",
                  value="（模擬では、都道府県の地域別最低賃金を表示しません）"),
            ]),
        ],
    },
    {
        "no": "❼", "key": "s7", "title": "事業計画数値", "pages": "17", "nav": NAV_FULL,
        "groups": [
            group("7-1. 事業計画の目標", 17, [
                f("target_productivity", "①労働生産性の年平均成長率", "display", 17, who="display", calc=True),
                f("target_salary", "②1人当たり給与支給総額の年平均成長率", "display", 17, who="display", calc=True),
                f("target_min_wage", "③最低賃金の目標値", "display", 17, who="display",
                  value="（模擬では表示しません）"),
            ]),
            group("7-2. 会社全体の事業計画（単位：円）", 17, [
                f("plan_years", "計画年数", "select", 17, required=True, options=["3年", "4年", "5年"]),
                grid("plan", "労働生産性の計画値", 17, PLAN_ROWS, PLAN_COLS),
                grid("salary", "従業員1人当たり給与支給総額の計画値", 17, SALARY_ROWS, PLAN_COLS),
            ], note="計画年数にかかわらず、5年分を入れます。入れたら「計算」を押します。"),
        ],
        "buttons": [("calc_plan", "計算", 17, "7-2. 会社全体の事業計画（単位：円）")],
    },
    {
        "no": "❽", "key": "s8", "title": "経費明細｜資金調達内訳", "pages": "18–19", "nav": NAV_FULL,
        "groups": [
            group("8-1. 経費明細表", 18, [
                f("finance_lease", "ファイナンス・リースによる共同申請", "radio", 18, required=True, options=["はい", "いいえ"]),
                grid("expense", "経費明細表", 18, EXPENSE_ROWS, EXPENSE_COLS),
            ], note="（A）は税込み、（B）は税抜きで入れます。入れたら「計算」を押します。"),
            group("8-2. 補助金申請額", 19, [
                f("subsidy_amount", "補助金申請額（D）", "display", 19, who="display", calc=True, unit="円"),
            ], note="模擬では（B）の合計に補助率（小規模か最低賃金の特例なら2/3、ほかは1/2）を掛けた額を出します。上限額は見ません。"),
            group("8-3. 資金調達内訳", 19, [
                grid("fund_all", "事業全体に要する経費調達一覧", 19, FUND_ALL_ROWS, FUND_COLS),
                grid("fund_d", "補助金申請額（D）の経費内訳", 19, FUND_D_ROWS, FUND_COLS),
            ]),
        ],
        "buttons": [("calc_expense", "計算", 18, "8-1. 経費明細表")],
    },
    {
        "no": "❾", "key": "s9", "title": "書類添付", "pages": "20–24", "nav": NAV_FULL,
        "groups": [
            group("事業者の実在確認書類", 20, [
                f("doc_registry", "履歴事項全部証明書", "file", 20, required=True, accept=PDF),
                f("doc_tax", "納税証明書（その2）直近3年分", "file", 20, required=True, accept=PDF),
            ]),
            group("決算書等", 20, [
                f("doc_pl_1", "損益計算書 1期前分", "file", 20, required=True, accept=PDF),
                f("doc_pl_2", "損益計算書 2期前分", "file", 20, accept=PDF),
                f("doc_bs_1", "貸借対照表 1期前分", "file", 20, required=True, accept=PDF),
                f("doc_bs_2", "貸借対照表 2期前分", "file", 20, accept=PDF),
            ]),
            group("従業員数の確認書類", 21, [
                f("doc_overview", "法人事業概況説明書", "file", 21, required=True, accept=PDF),
                f("doc_workers", "労働者名簿", "file", 21, accept=EXCEL),
            ]),
            group("役員名簿", 21, [f("doc_officers", "役員名簿", "file", 21, required=True, accept=EXCEL)]),
            group("株主名簿", 21, [f("doc_shareholders", "株主・出資者名簿", "file", 21, required=True, accept=EXCEL)]),
            group("事業計画に係る書類", 21, [
                f("doc_plan12", "事業計画書（その1・その2）", "file", 21, required=True, accept=PDF),
                f("doc_plan3", "事業計画書（その3）", "file", 21, required=True, accept=EXCEL),
            ]),
            group("機械装置・システム構築費の積算根拠資料", 21, [
                f("doc_estimate_1", "機械装置・システム構築費の積算根拠資料（その1）", "file", 21, required=True, accept=PDF_IMAGE),
                f("doc_estimate_2", "機械装置・システム構築費の積算根拠資料（その2）", "file", 21, accept=PDF_IMAGE),
                f("doc_estimate_3", "機械装置・システム構築費の積算根拠資料（その3）", "file", 21, accept=PDF_IMAGE),
            ]),
            group("該当する場合だけ添付する書類", 22, [
                f("doc_sites", "事業実施場所リスト", "file", 22, accept=EXCEL),
                f("doc_innovation", "イノベーション製品応援プログラムの書類", "file", 22, accept=PDF),
                f("doc_inhouse_wage", "事業場内最低賃金引き上げに係る要件確認書", "file", 22, accept=EXCEL),
                f("doc_regional_wage", "地域別最低賃金引き上げに係る要件確認書", "file", 22, accept=EXCEL),
                f("doc_other_subsidy", "他の助成制度の利用実績確認書", "file", 22, accept=EXCEL),
            ], note="模擬では、ここまでの入力にかかわらず、すべての欄を出しています。"),
            group("事業承継又はM&Aを実施した事業者に対する加点を受ける場合", 23, [
                f("succession_type", "事業承継の形態", "radio", 23,
                  options=["法人から法人（代表者変更）", "法人から法人（株式譲渡）"]),
                f("doc_succession", "事業承継の書類（履歴事項全部証明書）", "file", 23, accept=PDF),
            ]),
            group("生産性向上支援センター利用加点を受ける場合", 23, [
                f("doc_center", "生産性向上取組計画書（支援申込書と合わせて1つのPDF）", "file", 23, accept=PDF),
            ]),
            group("導入予定の機器装置等の資料（任意）", 23, [
                f("doc_catalog_1", "導入予定の機器装置についてのカタログや説明資料1", "file", 23, accept=PDF_IMAGE),
                f("doc_catalog_2", "導入予定の機器装置についてのカタログや説明資料2", "file", 23, accept=PDF_IMAGE),
                f("doc_catalog_3", "導入予定の機器装置についてのカタログや説明資料3", "file", 23, accept=PDF_IMAGE),
            ]),
            group("その他資料（任意）", 24, [
                f("doc_other_1", "その他資料1", "file", 24, accept=ANY_DOC),
                f("other_comment_1", "その他資料1 コメント", "text", 24),
                f("doc_other_2", "その他資料2", "file", 24, accept=ANY_DOC),
                f("other_comment_2", "その他資料2 コメント", "text", 24),
                f("doc_other_3", "その他資料3", "file", 24, accept=ANY_DOC),
                f("other_comment_3", "その他資料3 コメント", "text", 24),
            ], note="決まった書類のほかに出すものがあるときだけ使い、内容と理由をコメントに書きます。"),
        ],
    },
    {
        "no": "❿", "key": "s10", "title": "アンケート", "pages": "25–26", "nav": NAV_NO_SAVE,
        "groups": [
            group("本補助金申請時の経営課題・関心事項（複数選択可）", 25, [
                f("survey_issues", "経営課題・関心事項", "checkboxes", 25, options=[
                    "経営戦略・経営計画", "設備投資計画", "人事・労務管理", "財務・会計", "資金調達",
                    "生産管理・品質管理", "販路開拓・マーケティング", "IT化・DX", "事業承継・後継者育成・M&A",
                    "SDGs・カーボンニュートラル"]),
            ]),
            group("本補助金申請時の関心施策（複数選択可）", 25, [
                f("survey_policies", "関心施策", "checkboxes", 25, options=[
                    "情報提供", "セミナー・シンポジウム", "展示会・商談会", "窓口相談", "専門家派遣",
                    "研修・人材育成", "補助金・助成金", "融資・債務保証", "その他の施策"]),
                f("survey_other", "その他の施策の内容", "text", 25),
            ]),
            # p.26 の問い（D11b で足した）。選択肢は一部だけ
            group("本補助金の情報の入手元（複数選択可）", 26, [
                f("survey_source", "情報の入手元", "checkboxes", 26, options=[
                    "導入する製品の販売事業者からの情報", "商工会・商工会議所", "会計士・税理士", "金融機関からの情報",
                    "インターネット検索", "SNS", "その他"]),
                f("survey_source_other", "その他の入手元の内容", "text", 26),
            ]),
            group("本事業における資金の調達方法（複数選択可）", 26, [
                f("survey_funding", "資金の調達方法", "checkboxes", 26, options=[
                    "自己資金のみ", "新たに銀行融資を活用", "都道府県等の自治体の支援策を併用", "その他の調達方法"]),
                f("survey_funding_other", "その他の調達方法の内容", "text", 26),
            ]),
            group("中小機構の各種支援情報の提供", 26, [
                f("survey_no_info", "中小機構の支援情報の提供：希望しない", "checkbox", 26),
            ], note="情報の提供を望まないときだけチェックします。"),
        ],
    },
    {
        "no": "⓫", "key": "s11", "title": "メールアドレス認証", "pages": "27", "nav": NAV_NO_SAVE,
        "groups": [
            group("メールアドレス認証", 27, [
                f("auth_email", "担当者メールアドレス", "display", 27, who="display", source="staff_email"),
                f("auth_code", "認証コード", "text", 27, required=True),
            ], note="❷の「認証コード発行」で出た番号を入れます（本物ではメールで届きます）。"),
        ],
        # 1画面版はページの中のリンク、12画面版は「基本情報画面へ」のボタン（p.27）
        "links": [("#s2", "❷ 基本情報へ戻る")],
        "screen_buttons": [("goto_2", "基本情報画面へ", 27, "メールアドレス認証")],
    },
    {
        "no": "⓬", "key": "s12", "title": "確認", "pages": "28", "nav": (),
        "groups": [],
        "buttons": [("submit", "提出", 28, "")],
    },
]

# 12画面版の ⓬ 確認で、段ごとに置く「修正」のボタン（その画面へ移る。p.6、p.28）
FIX_PREFIX = "fix_"
FIX_LABEL = "修正"
# ⓫ の「基本情報画面へ」で移る先
GOTO_PREFIX = "goto_"

# ページの上と下に置くボタン（マニュアル p.6）
NAV_BUTTONS = [("back", "戻る", 6), ("save", "一時保存", 6), ("next", "次へ", 6)]

LOGIN_FIELDS = [
    f("account_id", "アカウントID（メールアドレス）", "text", 5, who="person"),
    f("password", "パスワード", "password", 5, who="person"),
]
LOGIN_BUTTON = ("login", "ログイン", 5)

# 提出は担当者だけが押す（SPEC 2.3）。ほかのボタンはツールが押してよい候補
PERSON_BUTTONS = {"submit"}


def section_fields(section: dict) -> list:
    """節の中の入力欄（表の中の欄を含む。表示だけの欄と表そのものは除く）。"""
    fields = []
    for g in section["groups"]:
        for field in g["fields"]:
            if field["kind"] == "grid":
                fields.extend({**cell, "group": g["title"]} for cell in grid_cells(field))
            elif field["kind"] != "display":
                fields.append({**field, "group": g["title"]})
    return [{**field, "section": section["no"] + " " + section["title"]} for field in fields]


def all_fields() -> list:
    """申請の画面の入力欄をすべて、画面の順に返す。"""
    return [field for s in SECTIONS for field in section_fields(s)]


def field_map() -> dict:
    return {field["id"]: field for field in all_fields()}


def all_buttons() -> list:
    """(値, 表示名, ページ, 置き場所) の一覧。"""
    buttons = [(v, label, page, "ページの上と下") for v, label, page in NAV_BUTTONS]
    for s in SECTIONS:
        for v, label, page, where in s.get("buttons", []):
            buttons.append((v, label, page, f"{s['no']} {s['title']}" + (f"／{where}" if where else "")))
    return buttons


# ---- 12画面版（D11b） ----

SCREEN_COUNT = len(SECTIONS)


def screen_url(n: int) -> str:
    return f"/shinsei/{n}"


def screen_fields(n: int) -> list:
    """12画面版の n 番目（1〜12）の画面の入力欄。"""
    return section_fields(SECTIONS[n - 1])


def screen_buttons(n: int) -> list:
    """12画面版の n 番目の画面のボタン。(値, 表示名, ページ, 置き場所) の一覧。"""
    s = SECTIONS[n - 1]
    nav = {v: (label, page) for v, label, page in NAV_BUTTONS}
    buttons = [(v, nav[v][0], nav[v][1], "画面の上と下") for v in s["nav"]]
    if n == SCREEN_COUNT:
        buttons += [(f"{FIX_PREFIX}{k}", FIX_LABEL, 28, f"{x['no']} {x['title']}の見出しの横")
                    for k, x in enumerate(SECTIONS[:-1], start=1)]
    for v, label, page, where in s.get("buttons", []) + s.get("screen_buttons", []):
        buttons.append((v, label, page, where or "画面の下"))
    return buttons


def screen_button_values(n: int) -> set:
    return {v for v, _label, _page, _where in screen_buttons(n)}


def target_screen(n: int, button: str) -> int:
    """12画面版で、n 番目の画面のボタンを押した後に出す画面の番号。"""
    if button == "next":
        return min(n + 1, SCREEN_COUNT)
    if button == "back":
        return max(n - 1, 1)
    for prefix in (FIX_PREFIX, GOTO_PREFIX):
        rest = button[len(prefix):] if button.startswith(prefix) else ""
        if rest.isdigit() and 1 <= int(rest) <= SCREEN_COUNT:
            return int(rest)
    return n


def button_label(value: str) -> str:
    for v, label, _page, _where in all_buttons():
        if v == value:
            return label
    for n in range(1, SCREEN_COUNT + 1):
        for v, label, _page, _where in screen_buttons(n):
            if v == value:
                return label
    return ""


WHO_NAMES = {"tool": "ツール", "person": "担当者", "display": "表示だけ"}
KIND_NAMES = {
    "text": "文字", "textarea": "文字（複数行）", "number": "数", "select": "選択欄", "checkbox": "チェック欄",
    "checkboxes": "チェック欄（複数）", "radio": "ラジオボタン", "file": "添付", "password": "パスワード",
}


def field_cells(field: dict) -> str:
    """一覧の表の「項目 | 種類 | 入れる人 | 必須 | ページ | 欄の id」。表の中の欄は表ごとに1行にまとめる。"""
    if field["kind"] == "grid":
        n = len(grid_cells(field))
        return f"{field['label']}（表。入力欄{n}個） | 数・文字 | ツール |  | {field['page']} | {field['id']}_<行>_<列>"
    kind = KIND_NAMES[field["kind"]]
    if field.get("accept"):
        kind += f"（{ACCEPT_NAMES[field['accept']]}）"
    if field.get("options") and field["kind"] in ("radio", "checkboxes"):
        kind += f"（{len(field['options'])}個）"
    return (f"{field['label']} | {kind} | {WHO_NAMES[field['who']]} | {'必須' if field['required'] else ''} "
            f"| {field['page']} | {field['id']}")


def markdown_tables() -> str:
    """D11a の1画面版の欄とボタンの一覧を Markdown の表にする。表示だけの欄は除く。"""
    lines = ["| 段 | 項目 | 種類 | 入れる人 | 必須 | ページ | 欄の id |", "|---|---|---|---|---|---|---|"]
    for field in LOGIN_FIELDS:
        lines.append(f"| ログイン | {field['label']} | {KIND_NAMES[field['kind']]} | {WHO_NAMES[field['who']]} |  "
                     f"| {field['page']} | {field['id']} |")
    for s in SECTIONS:
        for g in s["groups"]:
            for field in g["fields"]:
                if field["kind"] != "display":
                    lines.append(f"| {s['no']} | {field_cells(field)} |")
    lines += ["", "| ボタン | 置き場所 | 押す人 | ページ | 値 |", "|---|---|---|---|---|"]
    lines.append(f"| {LOGIN_BUTTON[1]} | ログイン | 担当者 | {LOGIN_BUTTON[2]} | {LOGIN_BUTTON[0]} |")
    for v, label, page, where in all_buttons():
        who = "担当者だけ" if v in PERSON_BUTTONS else "ツール"
        lines.append(f"| {label} | {where} | {who} | {page} | {v} |")
    return "\n".join(lines)


def markdown_screens() -> str:
    """12画面版の画面ごとの欄とボタンの一覧を Markdown にする（README と報告に使う）。表示だけの欄は除く。"""
    lines = ["| 画面 | URL | マニュアルのページ | ボタン | 入力欄の数 |", "|---|---|---|---|---|",
             f"| ログイン | /login | p.{LOGIN_BUTTON[2]} | {LOGIN_BUTTON[1]} | {len(LOGIN_FIELDS)} |"]
    for n, s in enumerate(SECTIONS, start=1):
        names = "・".join(dict.fromkeys(label for _v, label, _p, _w in screen_buttons(n)))
        lines.append(f"| {s['no']} {s['title']} | {screen_url(n)} | p.{s['pages']} | {names} | {len(screen_fields(n))} |")
    lines += ["", "入力欄の数は、表の中の欄を1つずつ数えたもの（下の表では、表ごとに1行にまとめる）。"]
    lines += ["", "### ログイン（`/login`、マニュアル p.5）", "",
              "| 見出し | 項目 | 種類 | 入れる人 | 必須 | ページ | 欄の id |", "|---|---|---|---|---|---|---|"]
    for field in LOGIN_FIELDS:
        lines.append(f"| ログイン | {field['label']} | {KIND_NAMES[field['kind']]} | {WHO_NAMES[field['who']]} |  "
                     f"| {field['page']} | {field['id']} |")
    lines += ["", "| ボタン | 置き場所 | 押す人 | ページ | 値 |", "|---|---|---|---|---|",
              f"| {LOGIN_BUTTON[1]} | 画面の下 | 担当者 | {LOGIN_BUTTON[2]} | {LOGIN_BUTTON[0]} |"]
    for n, s in enumerate(SECTIONS, start=1):
        lines += ["", f"### {s['no']} {s['title']}（`{screen_url(n)}`、マニュアル p.{s['pages']}）", ""]
        rows = [f"| {g['title']} | {field_cells(field)} |"
                for g in s["groups"] for field in g["fields"] if field["kind"] != "display"]
        if rows:
            lines += ["| 見出し | 項目 | 種類 | 入れる人 | 必須 | ページ | 欄の id |", "|---|---|---|---|---|---|---|"]
            lines += rows + [""]
        else:
            lines += ["入力欄はありません。一時保存した内容を段ごとに出し、段ごとに「修正」を置きます。", ""]
        lines += ["| ボタン | 置き場所 | 押す人 | ページ | 値 |", "|---|---|---|---|---|"]
        for v, label, page, where in screen_buttons(n):
            who = "担当者だけ" if v in PERSON_BUTTONS else "ツール"
            lines.append(f"| {label} | {where} | {who} | {page} | {v} |")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.write((markdown_tables() if "--one-page" in sys.argv[1:] else markdown_screens()) + "\n")
