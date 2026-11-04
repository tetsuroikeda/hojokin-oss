"""模擬の申請画面（小規模事業者持続化補助金〈一般型 通常枠〉）の画面の定義（D11c）。

申請システム操作手引き（第19回 公募申請・商工会議所地区）の画面の並びに合わせる。
- 手引きの「申請情報入力の流れ」（p.9）の13の段を、13の画面（/shinsei/1〜/shinsei/13）にする。
  「6. 希望する特例及び加点項目」の中の賃金引上げ特例の画面（p.35–40）は、本物でも別の画面なので、
  画面7として分けた。「12. 申請内容確認」と「13. 提出」は同じ画面（p.51）なので、画面13にまとめた。
- ログインの後の「遵守事項」（p.6）、マイページ（p.7、p.52）、再開の「申請内容確認」（p.52）も置く。
- 省力化の定義（screen.py）と同じ名前の関数と定数を持ち、server.py がどちらでも同じ形で扱える。

- 項目名は手引きの画面と同じにする（入力シートと照らすため）。誓約・宣誓・同意の文、説明、注意書きは
  写さず、自分の言葉で短く書く。選択肢は、画面の絵に出ているものはそのまま、出ていないものは一部だけ置く。
- 文字数の上限は手引きに書いてある（経営計画・補助事業計画の各欄 4,000字、事業名 30文字。p.41–42）。
  上限は欄の定義（limit）に持ち、画面の maxlength と、サーバーの確かめ（超えたら次へ進ませない）に使う。
- チェック欄・ラジオボタン・選択欄は、囲むラベルで名前を付ける（DESIGN 5章）。
- 「入れる人」は SPEC 2.3 の分け方による。確認・誓約・同意（宣誓を含む）のチェック欄は担当者、それ以外はツール。
  本物の項目名に4語（確認・誓約・同意・宣誓）を含むツールの欄（「決算期の確認」など）と、
  4語を含まない担当者の欄（「上記の事項を了解しました」など）は、名前を変えずに置き、下の一覧に挙げる。
- 守り（hook）が押してよいボタンを決めるのは、制度データの画面の定義で、この定義ではない。

`python3 mock/screen_jizokuka.py` で、画面ごとの欄とボタンの一覧を Markdown の表で出す。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from screen import (  # noqa: E402
    KIND_NAMES as _BASE_KIND_NAMES,
    MONTHS,
    PERSON_WORDS,
    PREFECTURES,
    WHO_NAMES,
    f,
    grid,
    grid_cells,
    group,
    section_fields,
)

MOCK_NAME = "小規模事業者持続化補助金〈一般型 通常枠〉 公募申請の模擬画面"
SCREENS_NAME = MOCK_NAME + "（D11c）"
SYSTEM_NAME = "小規模事業者持続化補助金（一般型）"
MANUAL = "申請システム操作手引き 第19回 公募申請（会議所地区）（downloads/jizokuka_20/r6_koubomanual_ip0306.pdf）"
# 手引きのページは、印刷されたページの番号（目次と本文の「P.○」と同じ）。PDF のページは、これに1を足したもの
PDF_PAGE_OFFSET = 1

# 添付できるファイル（手引き p.3、p.55）。1つの欄に1つのファイルで、10MB まで（p.65）
ACCEPT = ".pdf,.zip,.doc,.docx,.xls,.xlsx,.png,.bmp,.jpg,.jpeg,.heic,.gif"
ACCEPT_NAMES = {ACCEPT: "PDF・zip・Word・Excel・画像（png・bmp・jpg・HEIC・gif）"}
MAX_FILE_BYTES = 10 * 1024 * 1024

# 経営計画・補助事業計画の文の欄の上限（p.41–42）と、事業名の上限（p.42）
TEXT_LIMIT = 4000
NAME_LIMIT = 30

KIND_NAMES = {**_BASE_KIND_NAMES, "date": "日付"}

YES_NO = ["はい", "いいえ"]
NG_YES = ["はい（該当する場合は申請できません）", "いいえ"]

INVOICE_OPTIONS = ["希望しない", "インボイス特例（補助上限に50万円上乗せ）"]
WAGE_OPTIONS = ["希望しない", "賃金引上げ特例（補助上限に150万円上乗せ）",
                "賃金引上げ特例（赤字事業者、補助上限に150万円上乗せ・補助率3/4）"]
WAGE_DEFICIT = WAGE_OPTIONS[2]
KASAN_WAGE = "1.賃金引上げ加点"

# 経費区分（補助事業の手引き 第19回の「補助対象経費区分」の8つ）
EXPENSE_CATEGORIES = ["①機械装置等費", "②広報費", "③ウェブサイト関連費", "④展示会等出展費",
                      "⑤旅費", "⑥新商品開発費", "⑦借料", "⑧委託・外注費"]
WEB_CATEGORY = "③ウェブサイト関連費"
EXPENSE_ROWS = 6

# 日本標準産業分類。大分類は画面の絵のとおり（A〜R）。中分類から後は、本物では前の分類を選ぶと出る。
# 模擬では、手引きの絵の例（漁業）と、デモの会社に近い食料品製造業の一部だけを置く
JSIC_MAJOR = [
    "A：農業、林業", "B：漁業", "C：鉱業、採石業、砂利採取業", "D：建設業", "E：製造業",
    "F：電気・ガス・熱供給・水道業", "G：情報通信業", "H：運輸業、郵便業", "I：卸売業、小売業",
    "J：金融業、保険業", "K：不動産業、物品賃貸業", "L：学術研究、専門・技術サービス業",
    "M：宿泊業、飲食サービス業", "N：生活関連サービス業、娯楽業", "O：教育、学習支援業", "P：医療、福祉",
    "Q：複合サービス事業", "R：サービス業（他に分類されないもの）",
]
JSIC_MIDDLE = ["03：漁業（水産養殖業を除く）", "04：水産養殖業", "09：食料品製造業",
               "10：飲料・たばこ・飼料製造業", "58：飲食料品小売業", "76：飲食店"]
JSIC_MINOR = ["030：管理、補助的経済活動を行う事業所（03漁業）", "031：海面漁業", "032：内水面漁業",
              "091：畜産食料品製造業", "099：その他の食料品製造業"]
JSIC_DETAIL = ["0321：内水面漁業", "0995：冷凍調理食品製造業", "0996：惣菜製造業",
               "0997：すし・弁当・調理パン製造業"]

# GビズIDの登録内容が出る欄（背景がグレー。p.13）。模擬では決まった文を出す
GBIZ_VALUE = "（GビズIDの登録内容が出る欄です。模擬では出しません）"


def fl(id: str, label: str, page: int, filename: str, required: bool = False) -> dict:
    """添付の欄。filename は手引きが決めているファイルの名前（「〇〇（事業者名）」）。"""
    return f(id, label, "file", page, required=required, accept=ACCEPT, accept_name=ACCEPT_NAMES[ACCEPT],
             filename=filename)


def gbiz(id: str, label: str, page: int) -> dict:
    return f(id, label, "display", page, who="display", value=GBIZ_VALUE)


def long_text(id: str, label: str, page: int, required: bool = True) -> dict:
    """経営計画・補助事業計画の文の欄（本物は書式を付けられる欄。模擬はふつうの複数行の欄）。"""
    return f(id, label, "textarea", page, required=required, limit=TEXT_LIMIT)


def activity_groups(prefix: str, title: str, page: int, count: int) -> list:
    """「具体的な取組」の組（本物は「追加」「削除」で数を変える。模擬は決まった数を並べる）。"""
    groups = []
    for k in range(1, count + 1):
        groups.append(group(f"{title}（{k}件目）", page, [
            f(f"{prefix}{k}_title", "取組内容（概要）", "text", page, required=(k == 1)),
            f(f"{prefix}{k}_detail", "具体的な取組内容（詳細）", "textarea", page, required=(k == 1), limit=TEXT_LIMIT),
        ]))
    return groups


def expense_groups() -> list:
    """経費明細（本物は「内訳金額追加」で小さな画面を開き、1件ずつ保存する。模擬は決まった数の組を並べる）。"""
    groups = []
    for k in range(1, EXPENSE_ROWS + 1):
        req = k == 1
        groups.append(group(f"経費明細（{k}件目）", 44, [
            f(f"exp{k}_category", "経費区分", "select", 44, required=req, options=EXPENSE_CATEGORIES),
            f(f"exp{k}_content", "内容", "textarea", 44, required=req),
            f(f"exp{k}_breakdown", "経費内訳（単価×数）", "text", 44, required=req, placeholder="例：10000×3"),
            f(f"exp{k}_amount", "補助対象経費（税抜）", "number", 44, required=req, unit="円"),
            f(f"exp{k}_note", "経費に係る備考", "text", 44),
            f(f"exp{k}_vendor", "購入予定先", "text", 44),
            # 本物の文のまま。確認・誓約・同意・宣誓のどれも含まないが、注意事項を読んで入れる担当者の欄
            f(f"exp{k}_ack", "上記の事項を了解しました", "checkbox", 44, who="person"),
        ], note="経費区分を選ぶと、本物では区分ごとの注意事項が出ます。読んだら担当者が「上記の事項を了解しました」に"
                "チェックを入れて保存します（模擬では注意事項の文は出しません）。" if k == 1 else ""))
    return groups


# 資金調達方法（p.46）
FUND_COLS = [("amount", "金額", "number"), ("source", "資金調達先", "text")]
FUND_ROWS = [
    {"key": "subsidy", "label": "1.持続化補助金", "cells": {"amount": "calc", "source": "none"}},
    {"key": "subsidy_own", "label": "1-1.自己資金", "cells": {"source": "none"}},
    {"key": "subsidy_loan", "label": "1-2.金融機関からの借入金"},
    {"key": "subsidy_other", "label": "1-3.その他"},
    {"key": "own", "label": "2.自己資金", "cells": {"source": "none"}},
    {"key": "loan", "label": "3.金融機関からの借入金"},
    {"key": "other", "label": "4.その他"},
    {"key": "total", "label": "合計額", "cells": {"amount": "calc", "source": "none"}},
]

# 画面の下に置くボタン（手引きの各画面の絵。左に「戻る」、右に「次へ」）。「次へ」で一時保存される（p.12、p.52）
NAV_BUTTONS = [("back", "戻る", 12), ("next", "次へ", 12)]
NAV = ("back", "next")

SECTIONS = [
    {
        "no": "画面1", "key": "s1", "title": "誓約事項", "pages": "7", "step": "1", "nav": (),
        "groups": [
            group("誓約事項", 7, [
                f("pledge_agree", "誓約事項に同意する", "checkbox", 7, who="person", required=True),
            ], note="模擬の誓約事項です（本物の文ではありません）。同じ受付締切回への申請は1件だけであること、"
                    "公募要領などを読んで申請することを誓約する、という趣旨です。担当者が自分で読んでチェックを入れます。"),
        ],
        "buttons": [("start", "申請を開始する", 7, "")],
    },
    {
        "no": "画面2", "key": "s2", "title": "申請情報入力", "pages": "10–12", "step": "2", "nav": NAV,
        "groups": [
            group("希望する特例", 10, [
                f("invoice_tokurei", "インボイス特例の希望", "radio", 10, required=True, options=INVOICE_OPTIONS),
                f("wage_tokurei", "賃金引上げ特例の希望", "radio", 10, required=True, options=WAGE_OPTIONS),
            ], note="通常枠は補助上限50万円・補助率2/3です。特例の要件は公募要領で確かめます（模擬では説明の文を写していません）。"),
            group("補助金交付申請情報", 11, [
                f("start_method", "事業開始日の決定方法", "display", 11, who="display", value="交付決定日から開始"),
                f("end_date", "事業終了日（公募・交付申請時）", "date", 11, required=True),
                f("income", "補助事業に関して生ずる収入金に関する事項（収益納付について）", "radio", 11, required=True,
                  options=["①収入金有り", "②収入金無し"]),
                f("income_detail", "該当事項", "textarea", 11, placeholder="「収入金有り」のときに入れます"),
            ]),
            group("様式4・10の発行依頼先", 12, [
                f("support_org_type", "依頼先は商工会ですか、商工会議所ですか？", "radio", 12, required=True,
                  options=["商工会", "商工会議所"]),
                f("support_org_name", "依頼する商工会および商工会議所", "text", 12, required=True),
                f("member", "会員/非会員の選択", "radio", 12, required=True, options=YES_NO),
            ], note="商工会議所地区では、入力した内容を印刷して、地域の商工会議所に様式4（事業承継加点を希望するときは様式10も）"
                    "の発行を頼みます。「会員/非会員の選択」は、その商工会議所の会員かを答えます。"),
        ],
    },
    {
        "no": "画面3", "key": "s3", "title": "基本情報入力", "pages": "13–14", "step": "3", "nav": NAV,
        "groups": [
            group("基本情報入力画面", 13, [
                f("hq_zip", "本社郵便番号", "text", 13, required=True, placeholder="ハイフンなしの7桁"),
                gbiz("hq_pref", "本社所在地/印鑑登録証明書住所(都道府県)", 13),
                gbiz("hq_city", "本社所在地/印鑑登録証明書住所(市区町村)", 13),
                gbiz("hq_street", "本社所在地/印鑑登録証明書住所(番地と建物名等)", 13),
                gbiz("corp_number", "法人番号/事業者識別番号", 13),
                f("biz_name_kana", "法人名/屋号(カナ)", "text", 13, required=True),
                gbiz("biz_name", "法人名/屋号", 13),
                gbiz("biz_form", "事業形態", 13),
                f("tax_status", "消費税の適用に関する事項", "select", 13, required=True,
                  options=["①課税事業者", "②免税事業者", "③簡易課税事業者", "④2割特例選択者"]),
                f("rep_title", "代表者役職", "text", 13, required=True),
                gbiz("rep_last", "代表者名/個人事業主氏名(姓)", 13),
                gbiz("rep_first", "代表者名/個人事業主氏名(名)", 13),
                f("rep_birth", "代表者生年月日", "date", 13, required=True),
                f("rep_age", "代表者の満年齢", "display", 13, who="display", value="（模擬では計算しません）"),
                f("rep_tel", "代表者電話番号", "text", 13, required=True, placeholder="ハイフンなしの10桁か11桁"),
                f("company_tel", "会社代表電話番号", "text", 13, required=True, placeholder="ハイフンなしの10桁か11桁"),
                f("invoice_number", "適格請求書発行事業者の登録番号", "text", 13, placeholder="T に続く半角数字13桁"),
            ], note="背景がグレーの欄（表示だけ）は、GビズIDの登録内容が出る欄です。直すときは GビズID の側で直します。"),
            group("GビズIDで修正が行えない場合", 14, [
                f("gbiz_diff", "GビズID表示内容との差異の有無", "radio", 14, required=True, options=YES_NO),
                f("gbiz_diff_detail", "GビズIDの画面で修正が行えない項目名と値", "textarea", 14),
            ]),
        ],
        "buttons": [("gbiz_refresh", "Gビズから最新情報を取得する", 14, "基本情報入力画面")],
    },
    {
        "no": "画面4", "key": "s4", "title": "応募者概要入力（様式２）", "pages": "15–23", "step": "4", "nav": NAV,
        "groups": [
            group("事業者情報", 15, [
                f("hp", "自社ホームページのＵＲＬ", "radio", 15, required=True, options=["あり", "なし"]),
                f("hp_url", "ホームページのURL", "text", 15, placeholder="「あり」のときに入れます"),
                f("main_industry", "主たる業種", "radio", 15, required=True,
                  options=["商業・サービス業（宿泊業・娯楽業を除く）", "サービス業のうち宿泊業・娯楽業", "製造業その他"]),
                f("jsic_major", "業種（日本標準産業分類 大分類）", "radio", 15, required=True, options=JSIC_MAJOR),
                f("jsic_middle", "業種（日本標準産業分類 中分類）", "radio", 15, required=True, options=JSIC_MIDDLE),
                f("jsic_minor", "業種（日本標準産業分類 小分類）", "radio", 15, required=True, options=JSIC_MINOR),
                f("jsic_detail", "業種（日本標準産業分類 細分類）", "radio", 15, required=True, options=JSIC_DETAIL),
                f("employees", "常時使用する従業員数", "number", 16, required=True, unit="人"),
                f("capital", "資本金額", "number", 16, required=True, unit="円"),
                f("founded", "設立年月日（西暦）", "date", 16, required=True),
                f("offices", "事業所数", "number", 16, required=True, placeholder="本社（店）も1事業所と数えます"),
                f("site_zip", "事業実施場所の郵便番号", "text", 16, required=True, placeholder="ハイフンなしの7桁"),
                f("site_pref", "事業実施場所の住所（都道府県）", "select", 16, required=True, options=PREFECTURES),
                f("site_city", "事業実施場所の住所（市区町村）", "text", 16, required=True),
                f("site_street", "事業実施場所の住所（番地等）", "text", 16, required=True),
                f("site_building", "事業実施場所の住所（建物名等）", "text", 16),
                # 本物の項目名のまま（「確認」を含む）。SPEC 2.3 では、確認のチェック欄ではないのでツールが入れる
                f("settled", "決算期の確認", "radio", 16, required=True, options=YES_NO),
            ], note="中分類・小分類・細分類は、本物では1つ前の分類を選ぶと選択肢が出ます。模擬では一部の選択肢だけを最初から出します。"),
            group("決算の状況（法人）", 19, [
                f("prev_period", "直前決算期間の確認", "radio", 19, required=True, options=YES_NO),
                f("sales", "直近１期（１年間）の売上高", "number", 19, required=True, unit="円"),
                f("gross_profit", "直近１期（１年間）の売上総利益", "number", 19, required=True, unit="円"),
                f("ordinary_profit", "直近１期（１年間）の経常利益", "number", 19, required=True, unit="円"),
                f("short_months", "決算期間１年未満の場合：（月数）", "select", 19,
                  options=[str(m) for m in range(1, 12)], unit="か月"),
                fl("doc_bs", "貸借対照表の写し（直近１期分）", 19, "貸借対照表（事業者名）", required=True),
                f("pl_exists", "損益計算書の確認", "radio", 21, required=True, options=YES_NO),
                fl("doc_pl", "損益計算書の写し（直近１期分）", 21, "損益計算書（事業者名）", required=True),
                fl("doc_tax_cover", "確定申告書 表紙の写し", 21, "確定申告書表紙（事業者名）"),
                fl("doc_beppyo4", "確定申告書 別表四（所得の簡易計算）の写し", 21, "確定申告書別表四（所得の簡易計算）（事業者名）"),
                fl("doc_registry", "現在事項全部証明書または履歴事項全部証明書（申請書の提出日から3か月以内の日付のもの（原本））", 20,
                   "現在事項全部証明書（事業者名）または履歴事項全部証明書（事業者名）"),
                fl("doc_sales_ledger", "売上台帳等", 20, "売上台帳（事業者名）"),
            ], note="法人の画面に合わせました（個人事業主・NPO法人だけの欄は置いていません）。本物は、決算期の確認などの答えに応じて"
                    "出る欄が変わります。模擬ではすべてを出し、決算期を迎えた法人で出る欄に「必須」を付けています。"),
            group("インボイス特例の売上高（法人）", 22, [
                f("sales_2019", "２０１９年９月３０日の属する事業年度の課税売上高", "number", 22, unit="円"),
                f("sales_2020", "２０２０年９月３０日の属する事業年度の課税売上高", "number", 22, unit="円"),
                f("sales_2021", "２０２１年９月３０日の属する事業年度の課税売上高", "number", 22, unit="円"),
            ], note="インボイス特例を希望したときだけの欄です。創業してまだ売上がない年は0円を入れます。"),
            group("連絡担当者について", 23, [
                f("staff_last_kana", "担当者(セイ)", "text", 23, required=True),
                f("staff_first_kana", "担当者(メイ)", "text", 23, required=True),
                f("staff_last", "担当者(姓)", "text", 23, required=True),
                f("staff_first", "担当者(名)", "text", 23, required=True),
                f("staff_title", "役職名", "text", 23),
                f("contact_zip", "連絡先郵便番号", "text", 23, required=True, placeholder="ハイフンなしの7桁"),
                f("contact_pref", "連絡先住所(都道府県)", "select", 23, required=True, options=PREFECTURES),
                f("contact_city", "連絡先住所(市区町村)", "text", 23, required=True),
                f("contact_street", "連絡先住所(番地等)", "text", 23, required=True),
                f("contact_building", "連絡先住所(建物名等)", "text", 23),
                f("contact_tel", "連絡先電話番号", "text", 23, required=True),
                f("mobile_tel", "携帯電話番号", "text", 23),
                f("fax", "FAX番号", "text", 23),
                f("staff_email", "担当者メールアドレス", "text", 23, required=True),
            ], note="事務局からの連絡は、代表者か連絡担当者に届きます。申請の中身を説明できる人を書きます。"),
        ],
    },
    {
        "no": "画面5", "key": "s5", "title": "確認事項入力（様式２）", "pages": "24–26", "step": "5", "nav": NAV,
        "groups": [
            group("補助事業者への確認事項", 24, [
                f("advice", "商工会・商工会議所以外からのアドバイスの有無", "radio", 24, required=True, options=YES_NO),
                f("advice_fee", "アドバイス料の有無", "radio", 24, options=["あり", "なし"]),
                f("advice_fee_amount", "アドバイス料の金額", "number", 24, unit="円"),
                f("advice_name", "アドバイス者名", "text", 24),
                f("stock_status", "保有されている株式の状況", "radio", 24, required=True, options=NG_YES),
                f("investor_type", "代表出資者の名称・出資比率・資本金", "radio", 25, required=True,
                  options=["株式会社・有限会社", "株式会社・有限会社以外の法人"]),
                f("investor_name", "出資者の名称", "text", 25),
                f("investor_capital", "出資者の資本金", "number", 25, unit="円"),
                f("investor_ratio", "申請者の資本金に占める出資比率", "number", 25, unit="％"),
                f("big_income", "課税所得額が15億円超となった年の有無", "radio", 24, required=True, options=YES_NO),
                f("income_1", "前年の課税所得", "number", 24, unit="円"),
                f("income_2", "2年前の課税所得", "number", 24, unit="円"),
                f("income_3", "3年前の課税所得", "number", 24, unit="円"),
                f("gambling", "射幸心をそそるおそれのある事業実施の確認", "radio", 24, required=True, options=NG_YES),
            ], note="「アドバイスの有無」は、この補助金の申請で、商工会・商工会議所のほかの人から助言を受けたかを答えます。"
                    "「はい」のときは、アドバイス料の有無・金額・アドバイス者名も入れます。"),
            group("これまでに実施した「小規模事業者持続化補助金」の補助事業者に該当する者か", 26, [
                f("past_ippan", "（1）小規模事業者持続化補助金（一般型）の採択・交付決定実績", "radio", 26, required=True,
                  options=YES_NO),
                f("past_corona", "（2）小規模事業者持続化補助金（コロナ特別対応型）の採択・交付決定実績", "radio", 26,
                  required=True, options=YES_NO),
                f("past_low_risk", "（3）小規模事業者持続化補助金（低感染リスク型ビジネス枠）の採択・交付決定実績", "radio", 26,
                  required=True, options=YES_NO),
                f("past_sogyo_apply", "（4）小規模事業者持続化補助金（創業型）の申請実績", "radio", 26, required=True,
                  options=NG_YES),
                f("past_sogyo", "（5）小規模事業者持続化補助金（創業型）の採択・交付決定実績", "radio", 26, required=True,
                  options=YES_NO),
                f("past_difference", "過去の補助事業の販路開拓先・方法・成果との違い", "textarea", 26),
            ], note="（1）〜（3）で「はい」のときは、本物では採択回と様式第14の提出状況も選びます（模擬では置いていません）。"),
        ],
    },
    {
        "no": "画面6", "key": "s6", "title": "希望する特例及び加点項目（様式２）", "pages": "27–34", "step": "6", "nav": NAV,
        "groups": [
            group("選択済みの特例に応じた追加項目（インボイス特例）", 27, [
                fl("doc_invoice_notice", "適格請求書発行事業者の登録通知書", 27, "インボイス登録通知書（事業者名）"),
                fl("doc_invoice_receipt", "登録申請データの「受信通知」を印刷したもの", 27, "インボイス受信通知（事業者名）"),
            ], note="インボイス特例を希望したときだけの欄です。どちらか一方を添付します。"),
            group("重点政策加点", 28, [
                f("kasan_priority", "重点政策加点", "radio", 28, required=True, options=[
                    "希望しない", "1.赤字賃上げ加点", "2.事業環境変化加点", "3-1.東日本大震災加点（福島県12市町村）",
                    "3-2.東日本大震災加点（太平洋沿岸部に所在する水産仲買業者及び水産加工業者）", "4.くるみん・えるぼし加点"]),
                f("env_change_detail", "影響を受けている内容", "textarea", 30),
                fl("doc_food_license", "食品衛生法に基づく営業許可証もしくは届出書（受領印押印済み）の写し", 30,
                   "食品衛生法証書（事業者名）"),
                fl("doc_kurumin", "「基準適合一般事業主認定通知書」の写し", 30, "基準適合一般事業主認定通知書（事業者名）"),
            ], note="「重点政策加点」と「政策加点」から1つずつ選べます。選んだ加点に応じた欄は、模擬ではいつも出します。"),
            group("政策加点", 29, [
                f("kasan_policy", "政策加点", "radio", 29, required=True, options=[
                    "希望しない", KASAN_WAGE, "2-①.地方創生型加点（地域資源型）", "2-②.地方創生型加点（地域コミュニティ型）",
                    "3.経営力向上計画加点", "4.事業承継加点", "5.過疎地域加点", "6.一般事業主行動計画策定加点",
                    "7.後継者支援加点", "8.小規模事業者卒業加点", "9.事業継続力強化計画策定加点",
                    "10.令和６年能登半島地震等に伴う加点"]),
                f("regional_plan_resource", "取組計画（地域資源型）", "textarea", 31),
                f("regional_plan_community", "取組計画（地域コミュニティ型）", "textarea", 31),
                fl("doc_keiei_ryoku", "認定書の写し", 31, "経営力向上計画認定書（事業者名）"),
            ]),
            group("事業承継の計画", 32, [
                f("succ_person", "補助事業を中心になって行う者の氏名", "text", 32),
                f("succ_same", "事業承継診断票Q１【】記載の「後継者候補」と同一の者かの確認", "select", 32,
                  options=["「後継者候補」と同一の者", "「後継者候補」と別の者"]),
                f("succ_relation", "代表者からみた「補助事業を中心になって行う者」との関係", "select", 32,
                  options=["子", "子の配偶者", "兄弟姉妹", "親族以外の役員・従業員", "その他"]),
                f("succ_when", "（1）事業承継の目標時期", "select", 32, options=["1年以内", "3年以内", "5年以内", "5年より先"]),
                f("succ_what", "（2）事業承継内容（予定）", "select", 32, options=["代表者の交代", "株式の承継", "事業の譲渡", "その他"]),
                f("succ_to", "（3）事業承継先（予定）", "select", 32, options=["親族", "役員・従業員", "社外の第三者"]),
                fl("doc_rep_birth", "「代表者の生年月日が確認できる公的書類」の写し", 32, "代表者生年月日（事業者名）"),
                fl("doc_successor", "「後継者候補の実在確認書類」の写し", 32, "後継者実在確認書類（事業者名）"),
            ], note="政策加点で「4.事業承継加点」を選んだときの欄です。選択欄の選択肢は手引きの絵から読めないので、模擬の言葉にしました。"
                    "個人事業主だけの欄（家族専従者の確認など）は置いていません。様式10の添付も要ります（画面11）。"),
            group("7.後継者支援加点", 33, [
                f("finalist_year", "ファイナリスト又は準ファイナリストに選出された年度", "text", 33, unit="年度",
                  placeholder="西暦4桁"),
            ]),
            group("8.小規模事業者卒業加点", 33, [
                fl("doc_workers", "労働基準法に基づく最新の労働者名簿（常時使用する従業員のみ）", 33, "労働者名簿（事業者名）"),
            ]),
            group("9.事業継続力強化計画策定加点", 33, [
                f("bcp_form", "事業継続力強化計画の申請形式", "radio", 33, options=["電子申請", "紙申請"]),
                f("bcp_number", "事業継続力強化計画受付番号", "text", 33, placeholder="半角数字10桁"),
                f("bcp_start_year", "事業継続力強化期間 事業期間始期（年）", "text", 33, unit="年"),
                f("bcp_start_month", "事業継続力強化期間 事業期間始期（月）", "select", 33, options=MONTHS, unit="月"),
                f("bcp_end_year", "事業継続力強化期間 事業期間終期（年）", "text", 33, unit="年"),
                f("bcp_end_month", "事業継続力強化期間 事業期間終期（月）", "select", 33, options=MONTHS, unit="月"),
            ]),
            group("10.令和６年能登半島地震等に伴う加点", 34, [
                f("noto_applying", "（1）小規模事業者持続化補助金（災害支援枠）の申請状況", "radio", 34,
                  options=["はい（該当する場合はこの加点を選べません）", "いいえ"]),
                f("noto_count", "（2）小規模事業者持続化補助金（災害支援枠）の事業実施回数", "radio", 34,
                  options=["0回", "1回", "2回（該当する場合はこの加点を選べません）"]),
                f("noto_past_type", "過去に小規模事業者持続化補助金（災害支援枠）で申請した被害種別", "radio", 34,
                  options=["地震被害", "豪雨被害"]),
                f("noto_type", "申請を行う被害種別", "radio", 34, options=["地震被害", "豪雨被害"]),
                f("noto_form", "申請を行う被害形態", "radio", 34, options=["直接被害", "間接被害"]),
                fl("doc_damage", "被害の証明書", 34, "被害の証明書（事業者名）"),
                fl("doc_sales_drop", "売上減少の証明書", 34, "売上減少の証明書（事業者名）"),
            ]),
        ],
    },
    {
        "no": "画面7", "key": "s7", "title": "賃金引上げ特例・賃金引上げ加点（様式７）", "pages": "35–40", "step": "6",
        "nav": NAV, "only_when": "wage",
        "groups": [
            group("事業場内最低賃金算出表", 35, [
                f("wage_worker", "事業場内最低賃金に該当する労働者名", "text", 35, required=True,
                  placeholder="姓と名の間に全角スペース"),
                f("wage_type", "該当する固定給", "select", 35, options=["時給制", "日給制", "月給制", "年俸制"]),
                f("wage_commission", "歩合給制", "checkbox", 35),
                f("wage_pref", "都道府県名", "select", 35, required=True, options=PREFECTURES),
                f("wage_regional", "申請時点の地域別最低賃金", "display", 35, who="display",
                  value="（模擬では表示しません）"),
            ], note="賃金引上げ特例か賃金引上げ加点を希望したときだけ出る画面です。本物は「追加」で小さな画面を開いて1人ずつ入れ、"
                    "表に並べます。模擬では1人分の欄を、固定給の種類ごとの組に分けて出します。歩合給制だけのときは、固定給を選ばずに"
                    "「歩合給制」にチェックします。"),
            group("月給制", 36, [
                f("wage_m_amount", "①直近１か月分の賃金台帳に記載された賃金額", "number", 36, unit="円/月"),
                f("wage_m_hours", "②１日の所定労働時間数", "number", 36, unit="時間"),
                f("wage_m_days", "１年の暦日数", "select", 36, options=["365日", "366日"]),
                f("wage_m_holidays", "年間休日数", "number", 36, unit="日"),
            ]),
            group("年俸制", 36, [
                f("wage_y_amount", "①年俸額", "number", 36, unit="円"),
                f("wage_y_hours", "②１年間の所定労働時間数", "number", 36, unit="時間"),
            ]),
            group("歩合給制", 37, [
                f("wage_c_amount", "１年間に支払われた歩合給の総額", "number", 37, unit="円"),
                f("wage_c_hours", "１年間の所定内・所定外含めた総労働時間数", "number", 37, unit="時間"),
            ]),
            group("時給制", 37, [
                f("wage_h_amount", "時間給または時間換算額", "number", 37, unit="円"),
            ]),
            group("日給制", 38, [
                f("wage_d_amount", "直近１か月の賃金台帳に記載された賃金額（円/日）", "number", 38, unit="円/日"),
                f("wage_d_hours", "１日の所定労働時間数", "number", 38, unit="時間"),
            ]),
            group("関連書類の添付", 39, [
                fl("doc_wage_ledger", "役員、専従者従業員を除く全従業員の労働基準法に基づく、直近１か月分の賃金台帳の写し", 39,
                   "賃金台帳（事業者名）", required=True),
                fl("doc_work_conditions", "役員、専従者従業員を除く全従業員の雇用条件（１日の所定労働時間、年間休日）が記載された書類の写し",
                   39, "雇用条件（事業者名）", required=True),
            ], note="賃金台帳は給与台帳とは別のものです。歩合給制や年俸制のときは、直近1年分が要ります。"),
            group("赤字事業者の関連書類（法人）", 40, [
                fl("doc_deficit_b1", "直近１期に税務署へ提出した、法人税申告書の別表一の写し", 40,
                   "赤字_法人税申告書別表一（事業者名）"),
                fl("doc_deficit_b4", "直近１期に税務署へ提出した、法人税申告書の別表四（所得の簡易計算）の写し", 40,
                   "赤字_法人税申告書別表四（事業者名）"),
            ], note="賃金引上げ特例（赤字事業者）を希望したときだけの欄です。"),
        ],
    },
    {
        "no": "画面8", "key": "s8", "title": "経営計画入力（様式２）", "pages": "41", "step": "7", "nav": NAV,
        "groups": [
            group("1.企業概要", 41, [
                long_text("plan_1_1", "1-1.自社の概要", 41),
                long_text("plan_1_2", "1-2.現在の売上・利益の状況", 41),
                long_text("plan_1_3", "1-3.経営課題", 41),
            ], note="各欄の上限は4,000字です。本物は書式・画像・表を入れられる欄で、画像1枚は約150字、表は約300字に数えます"
                    "（模擬はふつうの文字の欄で、改行も1字に数えます）。経営計画全体の目安は最大10,000字程度です。"),
            group("2.顧客ニーズと市場の動向", 41, [
                long_text("plan_2_1", "2-1.市場の動向", 41),
                long_text("plan_2_2", "2-2.顧客ニーズ", 41),
            ]),
            group("3.自社や自社の提供する商品・サービスの強み・弱み", 41, [
                long_text("plan_3", "3.自社や自社の提供する商品・サービスの強み・弱み", 41),
            ]),
            group("4.経営方針・目標と今後のプラン", 41, [
                long_text("plan_4_1", "4-1.経営方針・目標", 41),
                long_text("plan_4_2", "4-2.今後のプラン", 41),
            ]),
        ],
    },
    {
        "no": "画面9", "key": "s9", "title": "補助事業計画入力（様式２）", "pages": "42–43", "step": "8", "nav": NAV,
        "groups": [
            group("1.補助事業で行う事業名", 42, [
                f("project_name", "1.補助事業で行う事業名（30文字以内で記入すること）", "text", 42, required=True,
                  limit=NAME_LIMIT),
            ], note="採択されると、事業者名と事業名が公表されます。"),
            group("2.販路開拓等の取組内容", 42, [
                long_text("sales_2_1", "2-1.事業の概要", 42),
                long_text("sales_2_2", "2-2.背景・目的", 42),
            ], note="各欄の上限は4,000字です。本物は「具体的な取組」を「追加」「削除」で増やしたり減らしたりします"
                    "（模擬では3件分を並べます）。"),
            *activity_groups("sales_act", "2-3.具体的な取組", 42, 3),
            group("業務効率化（生産性向上）の取組みの有無", 43, [
                f("efficiency", "業務効率化（生産性向上）の取組みの有無", "radio", 43, required=True, options=YES_NO),
            ], note="「はい」のときは「3.業務効率化（生産性向上）の取組内容」を入れます。書いていないと、業務効率化の経費は計上できません。"),
            group("3.業務効率化（生産性向上）の取組内容", 43, [
                long_text("eff_3_1", "3-1.背景・目的", 43, required=False),
            ]),
            *[{**g, "fields": [{**x, "required": False} for x in g["fields"]]}
              for g in activity_groups("eff_act", "3-2.具体的な取組", 43, 2)],
            group("4.補助事業の効果", 43, [
                long_text("effect_4_1", "4-1.取組の効果", 43),
                long_text("effect_4_2", "4-2.効果の試算", 43),
            ], note="業務効率化の取組があるときは、生産性の向上にどうつながるかも書きます。"),
        ],
    },
    {
        "no": "画面10", "key": "s10", "title": "経費明細表・資金調達方法（様式３）", "pages": "44–48", "step": "9", "nav": NAV,
        "groups": [
            group("経費明細表・資金調達方法", 44, [
                f("tax_type", "課税区分", "select", 44, required=True, options=["税抜", "税込"]),
            ], note="免税事業者・簡易課税事業者・2割特例を選んだ事業者は「税込」を選べます。基本情報入力で課税事業者を選んだときは"
                    "「税抜」のままです。"),
            *expense_groups(),
            group("補助金交付申請額の計算", 45, [
                f("exp_sum_a", "（1）補助対象経費小計（ウェブサイト関連費を除く）(a)", "display", 45, who="display", calc=True,
                  unit="円"),
                f("subsidy_b", "（2）補助金交付申請額（ウェブサイト関連費を除く）(b)", "number", 45, required=True, unit="円"),
                f("subsidy_b_max", "（2）に入れられる額の目安（(a)×補助率、円未満切捨て）", "display", 45, who="display",
                  calc=True, unit="円"),
                f("exp_sum_c", "（3）ウェブサイト関連費に係る補助金対象経費小計(c)", "display", 45, who="display", calc=True,
                  unit="円"),
                f("exp_sub_d", "（4）ウェブサイト関連費に係る交付申請額(d)", "display", 45, who="display", calc=True, unit="円"),
                f("exp_total_e", "（5）補助対象経費合計 (e)＝(a)＋(c)", "display", 45, who="display", calc=True, unit="円"),
                f("exp_total_f", "（6）補助金交付申請額合計 (f)＝(b)＋(d)", "display", 45, who="display", calc=True, unit="円"),
                f("exp_diff_g", "（7）補助対象経費合計−補助金交付申請額合計 (g)＝(e)−(f)", "display", 45, who="display",
                  calc=True, unit="円"),
                f("web_check", "(d)の金額が(f)の金額の1/4以内（最大50万円）であるか", "display", 45, who="display",
                  calc=True),
            ], note="(2)を入れたら「自動計算」を押します。補助率は2/3（賃金引上げ特例の赤字事業者は3/4）。(4)は(c)×補助率の"
                    "円未満を切り捨て、50万円までにした額です。模擬では補助上限額は見ません。"),
            group("資金調達方法（単位：円）", 46, [
                grid("fund", "資金調達方法", 46, FUND_ROWS, FUND_COLS),
            ], note="当てはまらない金額の欄には0を入れます。1.持続化補助金は経費明細表の(6)、合計額は(5)と同じになるようにします。"
                    "1-1〜1-3は、補助金が支払われるまでの間の資金の手当てです。自己資金には資金調達先を入れません。"),
            group("事務所賃料・住宅宿泊事業者", 47, [
                f("office_rent", "事務所賃料に関する事項", "radio", 47, required=True, options=YES_NO),
                fl("doc_office_rent", "補助対象となる事務所賃料の「金額」と事務所の「床面積」が確認できる書類の写し", 48,
                   "補助対象となる事務所賃料の「金額」と事務所の「床面積」が確認できる書類（事業者名）"),
                f("floor_area", "総床面積に関する事項", "radio", 48, options=YES_NO),
                fl("doc_floor_area", "補助対象となる部分を説明した文書（任意様式）", 48, "補助対象となる部分を説明した文書（事業者名）"),
                f("minpaku", "住宅宿泊事業者に関する確認事項", "radio", 47, required=True, options=YES_NO),
                fl("doc_minpaku", "住宅宿泊事業法第３条第１項の届出書", 48, "住宅宿泊事業法第３条第１項の届出書（事業者名）"),
            ], note="「はい」のときだけの添付と問いも、模擬ではいつも出します。"),
        ],
        "buttons": [("calc_expense", "自動計算", 45, "補助金交付申請額の計算")],
    },
    {
        "no": "画面11", "key": "s11", "title": "様式添付", "pages": "49", "step": "10", "nav": NAV,
        "groups": [
            group("様式添付", 49, [
                f("form4_status", "様式４小規模事業者持続化補助金に係る事業支援計画書の作成・交付確認", "radio", 49,
                  required=True, options=YES_NO),
                f("form4_number", "発行番号", "text", 49),
                fl("doc_form4", "様式４小規模事業者持続化補助金に係る事業支援計画書", 49,
                   "様式４小規模事業者持続化補助金に係る事業支援計画書（事業者名）"),
                f("form10_status", "様式１０事業承継診断票の作成・交付確認", "radio", 49, options=YES_NO),
                fl("doc_form10", "様式１０事業承継診断票", 49, "様式１０事業承継診断票（事業者名）"),
            ], note="依頼先の商工会議所が発行した様式4（事業承継加点を希望したときは様式10も）を添付します。まだ発行されていないときは、"
                    "マイページから申請内容を印刷して商工会議所に頼みます。様式4が「いいえ」のままでは提出できません。"),
        ],
    },
    {
        "no": "画面12", "key": "s12", "title": "宣誓・同意", "pages": "50", "step": "11", "nav": ("back",),
        "groups": [
            group("誓約・同意書（様式６）", 50, [
                f("oath_pledge", "誓約・同意書の1〜5：補助の要件を満たし、申請内容に偽りがないことなどを誓約する", "checkbox", 50,
                  who="person", required=True),
                f("oath_consent", "誓約・同意書の6〜11：検査や、申請の情報の提供・利用などに同意する", "checkbox", 50,
                  who="person", required=True),
                f("oath_all", "誓約・同意書の結び：偽りがあったときの取扱いを理解して、宣誓・同意する", "checkbox", 50,
                  who="person", required=True),
            ], note="模擬の誓約・同意書です（本物の文ではありません）。本物は11の項目と結びの文を読み、まとまりごとにチェックを入れます。"
                    "表示される内容は申請内容によって変わります。担当者が自分で読んで入れる欄です。"),
            group("電子申請に係る同意事項", 50, [
                f("oath_esys", "電子申請に係る同意事項：申請の情報をほかの補助金の事務局と共有・利用することに同意する",
                  "checkbox", 50, who="person", required=True),
            ]),
        ],
        "buttons": [("to_confirm", "最終確認画面へ", 50, "")],
    },
    {
        "no": "画面13", "key": "s13", "title": "申請内容確認", "pages": "51", "step": "12・13", "nav": (),
        "groups": [
            # 本物の4つのチェック欄のうち2つは、確認・誓約・同意・宣誓のどれも含まない。その形を変えずに自分の言葉で書く
            group("提出の前のチェック", 51, [
                f("final_reviewed", "上の申請内容を確認した", "checkbox", 51, who="person", required=True),
                f("final_no_error", "入れた内容に誤りはない", "checkbox", 51, who="person", required=True),
                f("final_files", "添付した画像とファイルが正しく出ていることを確認した", "checkbox", 51, who="person",
                  required=True),
                f("final_no_change", "提出の後は、採択の発表まで直せないことを了承した", "checkbox", 51, who="person",
                  required=True),
            ], note="模擬の文です（本物の文ではありません）。担当者が申請内容を見て、自分でチェックを入れ、「提出」を押します。"),
        ],
        "buttons": [("submit", "提出", 51, "")],
    },
]

SCREEN_COUNT = len(SECTIONS)
WAGE_SCREEN = 7
# 申請内容確認（画面13）で「修正」を置く画面（入力の画面2〜11。誓約と宣誓・同意は申請内容ではないので置かない）
FIX_SCREENS = list(range(2, 12))
FIX_PREFIX = "fix_"
FIX_LABEL = "修正"
GOTO_PREFIX = "goto_"

# ログイン（p.5。GビズIDのログイン画面）
LOGIN_FIELDS = [
    f("account_id", "アカウントID（メールアドレス）", "text", 5, who="person"),
    f("password", "パスワード", "password", 5, who="person"),
]
LOGIN_BUTTON = ("login", "ログイン", 5)

# ログインの後の画面（申請の13画面の外）
JUNSHU_FIELD = f("junshu_agree", "遵守事項に同意する", "checkbox", 6, who="person")
JUNSHU_BUTTON = ("agree_start", "上記に同意して利用を開始する", 6)
MYPAGE_BUTTON = ("open_application", "公募・交付申請を開始する", 7)
SAIKAI_BUTTONS = [("resume", "申請を再開する", 52), ("back", "戻る", 52)]

# 担当者が押すボタン（SPEC 2.3。ログイン、同意・誓約・宣誓の直後に押すもの、提出）。ほかはツールが押してよい候補
PERSON_BUTTONS = {"submit", "start", "to_confirm", "agree_start", "login"}
# 値を保存するボタン（「次へ」で一時保存される。p.12、p.52）。「戻る」「修正」は保存しない
SAVING_BUTTONS = {"next", "start", "to_confirm", "calc_expense"}
# 値を保存しないで、同じ画面に戻るボタン
RECORD_ONLY_BUTTONS = {"gbiz_refresh"}
# 欄の上（見出しのすぐ下）に置くボタン。ほかの段の中のボタンは、欄の後に置く
BUTTONS_BEFORE_FIELDS = {"gbiz_refresh"}

# 4語の決まり（DESIGN 5章）と、本物の項目名が合わない欄。名前は変えずに置き、ここに挙げる（D11c）
#   ツールが入れるのに、本物の項目名に4語を含む欄。今の守りは、この欄を拒む
TOOL_FIELDS_WITH_WORDS = {
    "settled", "prev_period", "pl_exists", "gambling", "succ_same", "minpaku", "form4_status", "form10_status",
}
#   担当者が入れるのに、本物の文に4語を含まない欄
PERSON_FIELDS_WITHOUT_WORDS = {f"exp{k}_ack" for k in range(1, EXPENSE_ROWS + 1)} | {"final_no_error", "final_no_change"}


def all_fields() -> list:
    """申請の画面の入力欄をすべて、画面の順に返す。"""
    return [field for s in SECTIONS for field in section_fields(s)]


def field_map() -> dict:
    return {field["id"]: field for field in all_fields()}


def screen_url(n: int) -> str:
    return f"/shinsei/{n}"


def screen_fields(n: int) -> list:
    """n 番目（1〜13）の画面の入力欄。"""
    return section_fields(SECTIONS[n - 1])


def screen_buttons(n: int) -> list:
    """n 番目の画面のボタン。(値, 表示名, ページ, 置き場所) の一覧。"""
    s = SECTIONS[n - 1]
    nav = {v: (label, page) for v, label, page in NAV_BUTTONS}
    buttons = [(v, nav[v][0], nav[v][1], "画面の下") for v in s["nav"]]
    if n == SCREEN_COUNT:
        buttons += [(f"{FIX_PREFIX}{k}", FIX_LABEL, 51, f"{SECTIONS[k - 1]['no']} {SECTIONS[k - 1]['title']}の見出しの横")
                    for k in FIX_SCREENS]
    for v, label, page, where in s.get("buttons", []):
        buttons.append((v, label, page, where or "画面の下"))
    return buttons


def screen_button_values(n: int) -> set:
    return {v for v, _label, _page, _where in screen_buttons(n)}


def all_buttons() -> list:
    """(値, 表示名, ページ, 置き場所) の一覧（ログインの後の画面のボタンを含む）。"""
    buttons = [(LOGIN_BUTTON[0], LOGIN_BUTTON[1], LOGIN_BUTTON[2], "ログイン"),
               (JUNSHU_BUTTON[0], JUNSHU_BUTTON[1], JUNSHU_BUTTON[2], "遵守事項"),
               (MYPAGE_BUTTON[0], MYPAGE_BUTTON[1], MYPAGE_BUTTON[2], "マイページ")]
    buttons += [(v, label, page, "申請内容確認（再開）") for v, label, page in SAIKAI_BUTTONS]
    for n in range(1, SCREEN_COUNT + 1):
        buttons += screen_buttons(n)
    return buttons


def button_label(value: str) -> str:
    for v, label, _page, _where in all_buttons():
        if v == value:
            return label
    return ""


def wage_screen_applies(values: dict) -> bool:
    """賃金引上げ特例の画面（画面7）を出すか。本物では、特例か賃金引上げ加点を選んだときだけ出る（p.35）。"""
    return values.get("wage_tokurei") in WAGE_OPTIONS[1:] or values.get("kasan_policy") == KASAN_WAGE


def target_screen(n: int, button: str, values: dict = None) -> int:
    """n 番目の画面のボタンを押した後に出す画面の番号。画面7は、当たらないときは飛ばす。"""
    values = values or {}
    skip = set() if wage_screen_applies(values) else {WAGE_SCREEN}
    if button == "next":
        k = n + 1
        while k in skip:
            k += 1
        return min(k, SCREEN_COUNT)
    if button == "back":
        k = n - 1
        while k in skip:
            k -= 1
        return max(k, 1)
    if button == "start":
        return 2
    if button == "to_confirm":
        return SCREEN_COUNT
    rest = button[len(FIX_PREFIX):] if button.startswith(FIX_PREFIX) else ""
    if rest.isdigit() and int(rest) in FIX_SCREENS:
        return int(rest)
    return n


def is_empty(field: dict, values: dict, files: dict) -> bool:
    if field["kind"] == "file":
        return field["id"] not in files
    value = values.get(field["id"])
    return value in (None, "", False, [])


def missing_required(n: int, values: dict, files: dict) -> list:
    """n 番目の画面の、必須なのに空の欄の id。"""
    return [x["id"] for x in screen_fields(n) if x.get("required") and is_empty(x, values, files)]


def resume_screen(values: dict, files: dict) -> int:
    """「申請を再開する」で出す画面。本物は、入力の終わっていない画面から出す（p.52）。"""
    for n in range(2, SCREEN_COUNT):
        if n == WAGE_SCREEN and not wage_screen_applies(values):
            continue
        if missing_required(n, values, files):
            return n
    return SCREEN_COUNT


def over_limit(fields: list, values: dict) -> list:
    """上限を超えた欄。(欄, 字数) の一覧。字数は、改行を LF にそろえた後の文字の数。"""
    out = []
    for field in fields:
        limit = field.get("limit")
        value = values.get(field["id"])
        if limit and isinstance(value, str) and len(value) > limit:
            out.append((field, len(value)))
    return out


def field_cells(field: dict) -> str:
    """一覧の表の「項目 | 種類 | 入れる人 | 必須 | 上限 | ページ | 欄の id」。表の中の欄は表ごとに1行にまとめる。"""
    if field["kind"] == "grid":
        n = len(grid_cells(field))
        return f"{field['label']}（表。入力欄{n}個） | 数・文字 | ツール |  |  | {field['page']} | {field['id']}_<行>_<列>"
    kind = KIND_NAMES[field["kind"]]
    if field.get("accept"):
        kind += "（ファイル名：" + field["filename"] + "）"
    if field.get("options") and field["kind"] in ("radio", "checkboxes"):
        kind += f"（{len(field['options'])}個）"
    limit = f"{field['limit']:,}字" if field.get("limit") else ""
    return (f"{field['label']} | {kind} | {WHO_NAMES[field['who']]} | {'必須' if field['required'] else ''} "
            f"| {limit} | {field['page']} | {field['id']}")


def markdown_screens() -> str:
    """画面ごとの欄とボタンの一覧を Markdown にする（README と報告に使う）。表示だけの欄は除く。"""
    lines = ["| 画面 | URL | 手引きのページ | 手引きの流れ（p.9） | ボタン | 入力欄の数 |", "|---|---|---|---|---|---|",
             f"| ログイン | /login | p.{LOGIN_BUTTON[2]} | — | {LOGIN_BUTTON[1]} | {len(LOGIN_FIELDS)} |",
             f"| 遵守事項 | /junshu | p.{JUNSHU_BUTTON[2]} | — | {JUNSHU_BUTTON[1]} | 1 |",
             f"| マイページ | /mypage | p.{MYPAGE_BUTTON[2]}、p.52 | — | {MYPAGE_BUTTON[1]} | 0 |",
             "| 申請内容確認（再開） | /saikai | p.52 | — | " + "・".join(x[1] for x in SAIKAI_BUTTONS) + " | 0 |"]
    for n, s in enumerate(SECTIONS, start=1):
        names = "・".join(dict.fromkeys(label for _v, label, _p, _w in screen_buttons(n)))
        when = "（当たるときだけ）" if s.get("only_when") else ""
        lines.append(f"| {s['no']} {s['title']}{when} | {screen_url(n)} | p.{s['pages']} | {s['step']} | {names} "
                     f"| {len(screen_fields(n))} |")
    lines += ["", "入力欄の数は、表の中の欄を1つずつ数えたもの（下の表では、表ごとに1行にまとめる）。"]
    head = ["| 見出し | 項目 | 種類 | 入れる人 | 必須 | 上限 | ページ | 欄の id |", "|---|---|---|---|---|---|---|---|"]
    bhead = ["| ボタン | 置き場所 | 押す人 | ページ | 値 |", "|---|---|---|---|---|"]

    def who(v: str) -> str:
        return "担当者" if v in PERSON_BUTTONS else "ツール"

    lines += ["", "### ログイン（`/login`、手引き p.5）", ""] + head
    for field in LOGIN_FIELDS:
        lines.append(f"| ログイン | {field['label']} | {KIND_NAMES[field['kind']]} | {WHO_NAMES[field['who']]} |  |  "
                     f"| {field['page']} | {field['id']} |")
    lines += [""] + bhead + [f"| {LOGIN_BUTTON[1]} | 画面の下 | 担当者 | {LOGIN_BUTTON[2]} | {LOGIN_BUTTON[0]} |"]
    lines += ["", "### 遵守事項（`/junshu`、手引き p.6）", ""] + head
    lines.append(f"| 申請システム利用にあたっての遵守事項 | {field_cells(JUNSHU_FIELD)} |")
    lines += [""] + bhead + [f"| {JUNSHU_BUTTON[1]} | 画面の下 | {who(JUNSHU_BUTTON[0])} | {JUNSHU_BUTTON[2]} "
                             f"| {JUNSHU_BUTTON[0]} |"]
    lines += ["", "### マイページ（`/mypage`、手引き p.7、p.52）", "",
              "入力欄はありません。申請ステータスを出します。", ""] + bhead
    lines.append(f"| {MYPAGE_BUTTON[1]} | 公募交付申請 | {who(MYPAGE_BUTTON[0])} | {MYPAGE_BUTTON[2]} | {MYPAGE_BUTTON[0]} |")
    lines += ["", "### 申請内容確認（再開）（`/saikai`、手引き p.52）", "",
              "入力欄はありません。一時保存した内容を出します。", ""] + bhead
    for v, label, page in SAIKAI_BUTTONS:
        lines.append(f"| {label} | 画面の下 | {who(v)} | {page} | {v} |")
    for n, s in enumerate(SECTIONS, start=1):
        lines += ["", f"### {s['no']} {s['title']}（`{screen_url(n)}`、手引き p.{s['pages']}）", ""]
        rows = [f"| {g['title']} | {field_cells(field)} |"
                for g in s["groups"] for field in g["fields"] if field["kind"] != "display"]
        lines += head + rows + [""]
        if n == SCREEN_COUNT:
            lines += ["一時保存した内容を画面ごとに出し、画面ごとに「修正」を置きます。", ""]
        lines += bhead
        for v, label, page, where in screen_buttons(n):
            lines.append(f"| {label} | {where} | {who(v)} | {page} | {v} |")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.write(markdown_screens() + "\n")
