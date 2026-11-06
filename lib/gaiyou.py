"""概要と流れ.docx を作る（SPEC F3・T3-9、DESIGN 4.5・4.6・6章、TASKS M2d）。

案件ごとに `案件/<案件>/概要と流れ.docx` を書く。作り直すときも同じファイルを置き換える（「_v2」のような別のファイルを
作らない。前の版は版の履歴に残る）。案件のフォルダや書き出す先が、別名（シンボリックリンク）などで会社のフォルダの外か
`案件/` の外を指すとき、会社の記録・制度データ・案件の資料の一覧（`記録/` やその中のフォルダも）が外を指すときは、
読まずに・書かずに断る（DESIGN 5章。確かめは lib/places.py）。

役割の分け方（DESIGN 4.6・6章）
- 数字・期限・一覧は、制度データ（`記録/制度データ/<略称>_<公募回>.json`）と会社の記録（`記録/会社の記録.json`）から、
  この道具が入れる。補助額の見込みも、この道具が計算する。
- 説明の文と、会社に当てはめた判断（要件を満たすか、加点が取れるか、補助額のどの区分に当たるか、どの特例を使うか）は
  Claude が書き、JSON で渡す。道具は、渡された名前が制度データにあるか、会社の記録の id があるかを確かめる。
  数字そのものは渡させない（制度データか会社の記録から取る）。

出典の書き方（すべての行に付ける）
- 制度データの値：「資料の名前 p.ページ」。回の違う資料は「資料の名前（第◯回）p.ページ」。ページのない資料は名前だけ。
- 会社の記録の値：「会社の記録「名前」：原本のファイル p.ページ」「…：社長の発言（日付）」など。
- 読み取れない値は、値の代わりに「読み取れませんでした（理由）」と書く。出典はない（資料に見つからなかったため）。
- 要確認・資料で食い違いの値は、頭に【要確認】【資料で食い違い】を付け、注記を添える。

Claude が渡す JSON の形
{
  "制度の概要": "平易な説明（文字か、文字の並び。並びは段落に分ける）",
  "流れの説明": "（任意）申請から効果報告までの流れの、平易な説明",
  "要件の判定": [                                     （任意。ない要件は「まだ確かめていません」）
    {"要件": "<数値の要件か、数値でない要件の名前>", "判定": "満たす" / "当てはまらない" / "満たさない見込み" / "確かめが要る",
     "理由": "…", "会社の記録": ["<会社の記録の項目の id>", …]（任意）}
    （当てはまらない：使わない特例・加点の要件や、従業員の数などで対象にならない要件。返還の表からも省く）
  ],
  "加点の判定": [                                     （任意。ない加点は「まだ確かめていません」）
    {"加点": "<加点の項目の名前>", "判定": "取れる見込み" / "今回は取れない" / "確かめが要る",
     "理由": "…", "会社の記録": [...]（任意）}
  ],
  "補助額の見込み": {                                 （任意。なければ見込みは出さない）
    "区分": "<補助額の区分の名前>", "特例": ["<その区分の特例の名前>", …]（任意。同じ特例は1回だけ。
                                                                          補助率と上限の置き換えは、それぞれ1つまで）,
    "補助の対象にする経費": "<会社の記録の事実の id。値は円の金額（22500000、「22,500千円」など）>",
    "理由": "（任意）その区分に当たる理由", "会社の記録": [...]（任意。区分の判断に使った項目）
  }
}

節と、制度データのどこから作るか（TASKS M2d で決めた形。11/6 のリハーサルの後に短くした）
応募の前に、細かい定めや交付申請より後の書類・注意まで読ませると、分かりにくい（作者のリハーサル。前の形は60ページを超えた）。
そこで、応募の準備に要るところだけを、1件1行の表で10ページ以内にまとめる（SPEC F3・T3-9）。
どの件も名前は落とさず、欄は主なもの1つ（要件は基準か内容、書類は条件・有効期限など）にしぼる。外した欄（計算式、
元の数字の決め方、確かめ方、書類の内容・形式、採択された後の手続きの書類と注意、問い合わせ文の案）は制度データに残り、
質問に答えるとき（F4）や、採択の後に段階を切り替えるとき（F12。stage_switch）に、資料のページを示して出す。
出典は、同じ資料のページを1行にまとめる（「公募要領 p.15、16」）。
- 制度の概要：Claude の文、全体の流れ（手続きの段階の名前を1行で）、補助額（区分ごとの上限・補助率）、
  特例（特例ごとに1行。区分で違う値は1つの欄に並べ、条件は幅の広い欄に置く）、審査の段階
- 自社が満たす要件：数値の要件は基準、数値でない要件は内容（当たると対象外のものは頭に印）と、Claude の判定
- 補助額の見込み：選んだ区分の上限・補助率と特例、会社の記録の経費から、min(経費 × 補助率（円未満切り捨て）, 上限＋上乗せ)
- 加点：加点の種類の数・区分ごとの上限（1つの段落）、項目ごとの内容。取れるかは Claude の判定（日付からの判定は B24）
- <最初の手続きの段階>で出す書類：申請の段階で使う書類（必須 → 条件付き → 任意の順）の、条件・有効期限・期数・発行元
  （自社でないとき）・効く審査項目。どの手続きで使うか分からない書類は、その後に別の表
- 義務と返還の条件：制度データにまだ「義務」の欄がない（DESIGN 9章。K1 で足す）ので、
  要件の「満たせないとき」と、してはいけないことから作る（応募の前に知っておくこと）
- 流れと期限：手続きの段階（順番の順。条件付きの段階には「必要なときだけ」）の期限の決め方と、決まった期日。
  期限の日付の計算は、期限の台帳（K1・M3）で行い、ここでは決め方を文にする。採択された後の書類と注意は件数だけを示す
- あわせて、読み取れなかった項目（理由）、資料どうしの食い違い、出典の資料の一覧
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lib import company, dates, places
from lib.docx_min import Document, DocxError, clean_text

FILE_NAME = "概要と流れ.docx"
RECORDS_DIR = "記録"
RECORD_FILE = "会社の記録.json"

CONFIRMED = "確認済み"
CHECK = "要確認"
CONFLICT = "資料で食い違い"
UNREADABLE = "読み取れない"
MARKS = {CHECK: "【要確認】", CONFLICT: "【資料で食い違い】"}
UNREAD_TEXT = "読み取れませんでした"
NOT_JUDGED = "まだ確かめていません"
NO_SOURCE = "（出典のある値がありません）"
SOURCE_HEAD = "出典："  # 表の名前の欄の下に置く出典の行の頭
UNKNOWN_STAGE_DOCS = "どの手続きで使うか分からない書類"
APPLY_DOCS_FALLBACK = "申請で出す書類"  # 手続きの段階が制度データにないとき
OFF_PREFIX = "当たると対象外："  # 数値でない要件のうち、当たらないことの中身の頭に付ける
# 要件と加点の表の見出し（判定で決着したものは、中身を省いた短い表に分ける）
PENDING_REQS = "満たすと決まっていない要件"
SETTLED_REQS = "満たす要件・当てはまらない要件"
PENDING_BONUS = "取れる見込みの加点・確かめが要る加点"
SETTLED_BONUS = "今回は取れない加点"

# 当てはまらない：使わない特例・加点の要件や、従業員の数などで対象にならない要件（返還の表からも省く）
REQ_JUDGES = ("満たす", "当てはまらない", "満たさない見込み", "確かめが要る")
SETTLED_JUDGES = ("満たす", "当てはまらない")
BONUS_JUDGES = ("取れる見込み", "今回は取れない", "確かめが要る")
INPUT_KEYS = ("制度の概要", "流れの説明", "要件の判定", "加点の判定", "補助額の見込み")
REQ_KEYS = ("要件", "判定", "理由", "会社の記録")
BONUS_KEYS = ("加点", "判定", "理由", "会社の記録")
ESTIMATE_KEYS = ("区分", "特例", "補助の対象にする経費", "理由", "会社の記録")
DOC_CLASSES = ("必須", "条件付き", "任意")
SPECIAL_KINDS = ("補助率の置き換え", "上限の置き換え", "上限の上乗せ")

_ROUND = re.compile(r"^第[0-9]+回$")
_YEN = re.compile(r"^([0-9]+(?:\.[0-9]+)?)(億|万|千)?円?$")
_TAIL_PAREN = re.compile(r"[（(][^）)]*[）)]$")
_UNITS = {None: 1, "千": 1000, "万": 10000, "億": 100000000}

# 余白と列の幅（twip）。余白 15mm で、A4 の本文の幅は 10,204。表はどれも compact（文字を少し小さく、行の間を詰める）。
# 出典の列は設けず、行の中で空きのある欄に「出典：…」の行を置く（named）
MARGIN = 851
W2 = [3100, 7104]                     # 名前と出典・中身
W2_WIDE = [4200, 6004]                # 名前・理由と出典（満たすと決まった要件、今回は取れない加点、してはいけないこと）
W2_NARROW = [2500, 7704]              # 項目・中身と出典（補助額の見込み、決まった期日）
W3 = [3000, 4900, 2304]               # 名前と出典・中身・自社の状況（取れるか）
W_DOC = [3700, 1100, 5404]            # 書類・区分・要点と出典
W_AMOUNT = [4000, 3200, 3004]         # 区分と出典・補助上限・補助率
W_SOURCES = [2000, 5604, 1100, 1500]  # 呼び名・資料の名前（リンク）・回・取得日


class GaiyouError(Exception):
    """書かなかったとき。problems に直す所を並べる。"""

    def __init__(self, problems: List[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


# ---- 小さな道具 ----


def _norm(text: Any) -> str:
    return unicodedata.normalize("NFC", str(text)).strip()


def _filled(value: Any) -> bool:
    """Word に入れたあとも文字が残るか。"""
    return isinstance(value, str) and bool(clean_text(value).strip())


def _is_text(value: Any) -> bool:
    if isinstance(value, str):
        return _filled(value)
    if isinstance(value, list):
        return bool(value) and all(_filled(v) for v in value)
    return False


def _paragraphs(value: Any) -> List[str]:
    if isinstance(value, list):
        return [v.strip() for v in value]
    return [str(value).strip()]


def _add(target: List[str], items: Iterable[str]) -> None:
    for item in items:
        if item and item not in target:
            target.append(item)


def is_sv(node: Any) -> bool:
    """出典つき値（値・状態の組）か。"""
    return isinstance(node, dict) and "値" in node and "状態" in node


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False


def usable(node: Any) -> bool:
    """計算に使える値か（読み取れないでなく、値がある）。"""
    return is_sv(node) and node["状態"] != UNREADABLE and node.get("値") is not None


def parse_yen(value: Any) -> Optional[int]:
    """会社の記録の金額を円の整数にする。22500000、「22,500,000円」「22,500千円」「2,250万円（税抜き）」など。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value >= 0 else None
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    text = _TAIL_PAREN.sub("", text).replace(",", "").replace(" ", "")
    m = _YEN.match(text)
    if not m:
        return None
    try:
        number = Decimal(m.group(1)) * _UNITS[m.group(2)]
    except InvalidOperation:
        return None
    if number != number.to_integral_value():
        return None
    return int(number)


def yen(value: Any) -> str:
    """円の金額。1万円で割り切れるときは「1,500万円」「1億2,000万円」、そうでなければ「8,230,452円」。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return plain(value)
    if value < 10000 or value % 10000:
        return f"{value:,}円"
    oku, man = divmod(value // 10000, 10000)
    if not oku:
        return f"{man:,}万円"
    return f"{oku:,}億" + (f"{man:,}万円" if man else "円")


def iso_text(text: Any) -> str:
    """「2027-03-12T16:00+09:00」→「2027年3月12日（金）16:00」、「2027-03-12」→「2027年3月12日（金）」。"""
    if not isinstance(text, str):
        return plain(text)
    try:
        if "T" in text:
            return dates.format_datetime(datetime.fromisoformat(text))
        return dates.format_date(date.fromisoformat(text))
    except ValueError:
        return text


def due_text(value: Any) -> str:
    """決まった期日の形（日時、または年月と旬）。"""
    if isinstance(value, dict):
        if "日時" in value:
            return iso_text(value["日時"])
        if "年月" in value:
            year, _, month = str(value["年月"]).partition("-")
            try:
                head = f"{int(year)}年{int(month)}月"
            except ValueError:
                head = str(value["年月"])
            return head + str(value.get("旬") or "")
    return plain(value)


def period(value: Dict) -> str:
    return f"{value.get('数')}{value.get('単位')}"


def plain(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "はい" if value else "いいえ"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        if len(value) == 1:
            return plain(value[0])
        return "\n".join("・" + plain(v) for v in value)
    if isinstance(value, dict):
        return "、".join(f"{k}：{plain(v)}" for k, v in value.items())
    return str(value)


# ---- 中身を組み立てる ----


class Context:
    """制度データ・会社の記録と、組み立てで数えたもの。"""

    def __init__(self, seido: Dict, record: Dict[str, Dict]) -> None:
        self.seido = seido
        self.record = record
        self.round = str((seido.get("制度") or {}).get("公募回") or "")
        self.docs = {d.get("id"): d for d in seido.get("資料") or [] if isinstance(d, dict)}
        stages = [s for s in seido.get("手続きの段階") or [] if isinstance(s, dict)]
        self.stages = sorted(stages, key=lambda s: s.get("順番") if isinstance(s.get("順番"), int) else 0)
        self.stage_names = {s.get("id"): s.get("名前") for s in self.stages}
        self.marked: Dict[str, set] = {UNREADABLE: set(), CHECK: set(), CONFLICT: set()}

    # 出典

    def source_label(self, src: Dict) -> str:
        """資料の呼び名（資料の一覧の id。「要領8」など）とページ。名前との対応は、Word の終わりの「出典の資料」の表にある
        （名前のままだと、狭い出典の欄で1つの出典が2行に折れ、行が縦に長くなるため。11/6 のリハーサルの指摘）。"""
        doc = self.docs.get(src.get("資料"))
        name = str(src.get("資料"))
        doc_round = str(doc.get("公募回") or "") if doc else ""
        if doc_round and doc_round != self.round and _ROUND.match(doc_round):
            name += f"（{doc_round}）"
        page = src.get("ページ")
        if isinstance(page, int):
            end = src.get("終わりのページ")
            name += f" p.{page}" + (f"–{end}" if isinstance(end, int) and end != page else "")
        return name

    def sources(self, *nodes: Any) -> List[str]:
        """値ごとに、最初の出典だけ（2つ目からの出典は制度データに残る。Word では出典の行を1行に収めるため。11/6 の後）。"""
        out: List[str] = []
        for node in nodes:
            if is_sv(node) and node["状態"] != UNREADABLE:
                first = next((s for s in node.get("出典") or [] if isinstance(s, dict)), None)
                if first is not None:
                    _add(out, [self.source_label(first)])
        return out

    def record_label(self, item_id: str) -> str:
        """会社の記録の項目の名前（「会社の記録「従業員の数」」）。どこから覚えたか（原本のページ・社長の発言の日など）は
        会社の記録にあり、kiroku で見られる。Word では長くなるので名前だけにする（11/6 のリハーサルの後）。"""
        item = self.record.get(item_id) or {}
        name = item.get("名前") or item.get("内容") or item.get("案件") or item_id
        return f"会社の記録「{_norm(name)}」"

    def record_sources(self, ids: Optional[Sequence[str]]) -> List[str]:
        return [self.record_label(i) for i in ids or []]

    # 値

    def text(self, node: Any, fmt=None) -> str:
        """出典つき値を、社長に見せる文にする。"""
        if not is_sv(node):
            return ""
        state = node["状態"]
        if state == UNREADABLE:
            self.marked[UNREADABLE].add(id(node))
            reason = node.get("理由")
            return f"{UNREAD_TEXT}（{reason.strip()}）" if _filled(reason) else UNREAD_TEXT
        value = node.get("値")
        body = "（値が空です）" if _empty(value) else (fmt or plain)(value)
        mark = MARKS.get(state)
        if mark:
            self.marked[state].add(id(node))
            note = node.get("注記")
            body = mark + body + (f"\n※{note.strip()}" if _filled(note) else "")
        return body

    def limit_text(self, value: Any) -> str:
        """期限の決め方を文にする（決まった日付／出来事からの期間／早いほう／繰り返し）。"""
        if not isinstance(value, dict):
            return plain(value)
        kind = value.get("種類")
        if kind == "決まった日付":
            return f"{iso_text(value.get('日時'))}まで"
        if kind == "出来事からの期間":
            event = value.get("出来事")
            # 出来事は、手続きの段階の id なら段階の名前にする。資料の書き方のまま「」で囲む
            event = self.stage_names.get(event) or event
            return f"「{event}」から{period(value.get('期間') or {})}以内"
        if kind == "早いほう":
            parts = self._flatten(value)
            return "次のうち早いほう：\n" + "\n".join("・" + self.limit_text(p) for p in parts)
        if kind == "繰り返し":
            interval = value.get("間隔") or {}
            if interval.get("数") == 1 and interval.get("単位") in ("年", "か月", "日"):
                every = {"年": "毎年", "か月": "毎月", "日": "毎日"}[interval["単位"]] + "1回"
            else:
                every = f"{period(interval)}ごとに1回"
            window = value.get("提出期間") or {}
            return (f"{every}、全{value.get('回数')}回（{window.get('始まりの月')}月から"
                    f"{period(window.get('長さ') or {})}の間に出す）")
        return plain(value)

    def _flatten(self, value: Dict) -> List[Any]:
        """「早いほう」の中の「早いほう」は、1つの並びにする（早いほうの早いほうは、全部のうち早いほう）。"""
        out: List[Any] = []
        for part in value.get("期限") or []:
            if isinstance(part, dict) and part.get("種類") == "早いほう":
                out.extend(self._flatten(part))
            else:
                out.append(part)
        return out

    def lines(self, item: Dict, fields: Sequence[Tuple[str, str]], fmts: Optional[Dict[str, Any]] = None
              ) -> Tuple[List[str], List[str]]:
        """欄ごとに「見出し：値」の行と、その出典。出典つき値の並び（注意など）は1つずつ行にする。"""
        fmts = fmts or {}
        out: List[str] = []
        srcs: List[str] = []
        for key, label in fields:
            node = item.get(key)
            if node is None:
                continue
            if is_sv(node):
                out.append(f"{label}：{self.text(node, fmts.get(key))}")
                _add(srcs, self.sources(node))
            elif isinstance(node, list) and node and all(is_sv(x) for x in node):
                for x in node:
                    out.append(f"{label}：{self.text(x, fmts.get(key))}")
                    _add(srcs, self.sources(x))
            elif isinstance(node, list):
                if node:
                    out.append(f"{label}：{'、'.join(plain(x) for x in node)}")
            elif not isinstance(node, (dict, bool)):
                if _filled(str(node)):
                    out.append(f"{label}：{plain(node)}")
        return out, srcs


def merge_pages(sources: List[str]) -> List[str]:
    """同じ資料のページを1行にまとめる（「公募要領 p.15」「公募要領 p.16」→「公募要領 p.15、16」）。
    資料の順は、はじめに出た順。会社の記録の出典は、そのまま1行ずつ。"""
    order: List[str] = []
    pages: Dict[str, List[str]] = {}
    for label in sources:
        name, sep, page = label.partition(" p.")
        if not sep or label.startswith("会社の記録"):
            if label not in order:
                order.append(label)
            continue
        if name not in pages:
            pages[name] = []
            if name not in order:
                order.append(name)
        if page not in pages[name]:
            pages[name].append(page)
    return [f"{x} p.{'、'.join(pages[x])}" if x in pages else x for x in order]


def source_text(sources: List[str], value_text: str = "") -> str:
    """出典の1行（「出典：要領8 p.15、16、会社の記録「従業員の数」」）。同じ資料のページはまとめ、出典どうしは「、」でつなぐ。"""
    if sources:
        return SOURCE_HEAD + "、".join(merge_pages(sources))
    # 読み取れない値だけの行は、出典の代わりに値の欄に理由がある
    return "" if UNREAD_TEXT in value_text else NO_SOURCE


def named(name: str, sources: List[str], value_text: str = "", inline: bool = False) -> str:
    """文の下に出典の行を置いたセル。出典の列を設けず、中身の欄を広くする（狭い欄で行が縦に長くなるため。11/6 の後）。
    出典は、行の中で空きのある欄に置く（中身の長い表は名前の下、理由・要点の短い表はその下）。
    inline は、短い文の後ろに「（出典：…）」で続ける（行を増やさない）。"""
    src = source_text(sources, value_text)
    if not name:
        return src
    if not src:
        return name
    return f"{name}（{src}）" if inline else f"{name}\n{src}"


def judge_cell(ctx: Context, judge: Optional[Dict]) -> Tuple[str, List[str]]:
    if not judge:
        return NOT_JUDGED, []
    text = judge["判定"] + (f"\n{judge['理由'].strip()}" if _filled(judge.get("理由")) else "")
    return text, ctx.record_sources(judge.get("会社の記録"))


# ---- 補助額の見込み ----


def _find_amount(seido: Dict, name: str) -> Optional[Dict]:
    for entry in seido.get("補助額") or []:
        if isinstance(entry, dict) and _norm(entry.get("区分", "")) == _norm(name):
            return entry
    return None


def _find_special(entry: Dict, name: str) -> Optional[Dict]:
    for special in entry.get("特例") or []:
        if isinstance(special, dict) and _norm(special.get("名前", "")) == _norm(name):
            return special
    return None


def estimate_rows(ctx: Context, spec: Dict) -> Tuple[List[List[str]], Dict[str, Any]]:
    """補助額の見込みの表の行（項目と出典・中身）と、結果のまとめ。"""
    rows: List[List[str]] = []

    def add(item: str, text: str, srcs: List[str]) -> None:
        rows.append([item, named(text, srcs, text)])

    entry = _find_amount(ctx.seido, spec["区分"])
    cap_node = entry["上限"]
    rate_node = entry["補助率"]
    adds: List[Dict] = []
    specials = [_find_special(entry, n) for n in spec.get("特例") or []]
    for special in specials:
        if special["種類"] == "補助率の置き換え":
            rate_node = special["値"]
        elif special["種類"] == "上限の置き換え":
            cap_node = special["値"]
        else:
            adds.append(special["値"])
    cost_id = spec["補助の対象にする経費"]
    cost = parse_yen(ctx.record[cost_id]["値"])
    cost_src = ctx.record_sources([cost_id])

    region = spec["区分"].strip() + (f"\n{spec['理由'].strip()}" if _filled(spec.get("理由")) else "")
    region_src = ctx.sources(entry["上限"], entry["補助率"]) + ctx.record_sources(spec.get("会社の記録"))
    add("当たる区分", region, region_src)
    if specials:
        texts = []
        srcs: List[str] = []
        for special in specials:
            cond = special.get("条件")
            texts.append(f"{special['名前']}（{special['種類']}）" + (f"\n条件：{ctx.text(cond)}" if is_sv(cond) else ""))
            _add(srcs, ctx.sources(special["値"], cond))
        add("使う特例", "\n".join(texts), srcs)
    cap_text = ctx.text(cap_node, yen)
    for node in adds:
        cap_text += f"\n上乗せ：{ctx.text(node, yen)}"
    cap_src = ctx.sources(cap_node, *adds)
    add("補助上限", cap_text, cap_src)
    rate_text = ctx.text(rate_node)
    rate_src = ctx.sources(rate_node)
    add("補助率", rate_text, rate_src)
    add("補助の対象にする経費", yen(cost), cost_src)

    used = [cap_node, rate_node] + adds
    all_src: List[str] = []
    _add(all_src, cap_src + rate_src + cost_src)
    summary: Dict[str, Any] = {"区分": spec["区分"].strip(), "見込み": None}
    missing = [label for label, node in (("補助上限", cap_node), ("補助率", rate_node)) if not usable(node)]
    missing += ["上乗せ" for node in adds if not usable(node)]
    if missing:
        add("補助額の見込み", f"出せません（{'・'.join(missing)}が読み取れないため。資料で値が分かったら出し直します）", all_src)
        return rows, summary
    try:
        rate = Fraction(str(rate_node["値"]))
    except (ValueError, ZeroDivisionError):
        add("補助額の見込み", "出せません（補助率を数として読めないため）", all_src)
        return rows, summary
    limit = int(cap_node["値"]) + sum(int(n["値"]) for n in adds)
    product = cost * rate
    raw = product.numerator // product.denominator  # 円未満は切り捨て
    amount = min(raw, limit)
    marks: List[str] = []
    _add(marks, (MARKS.get(n["状態"], "") for n in used))
    flags = "".join(marks)
    how = f"{yen(cost)} × {rate_node['値']} ＝ {yen(raw)}"
    how += f"。上限の{yen(limit)}で頭打ち" if raw > limit else f"。上限の{yen(limit)}の内"
    add("補助額の見込み", f"{flags}{yen(amount)}\n（{how}）", all_src)
    add("自己負担の目安", f"{flags}{yen(cost - amount)}\n（補助の対象にする経費から補助額の見込みを引いたもの。"
                         "消費税と、補助の対象にならない経費は別）", all_src)
    summary["見込み"] = amount
    return rows, summary


# ---- 入力を確かめる ----


def _names(items: Any, key: str = "名前") -> List[str]:
    return [_norm(i.get(key)) for i in items or [] if isinstance(i, dict) and i.get(key) is not None]


def _check_ids(where: str, ids: Any, record: Dict[str, Dict], problems: List[str]) -> None:
    if ids is None:
        return
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        problems.append(f"{where}の「会社の記録」は、会社の記録の項目の id の並びにしてください")
        return
    for i in ids:
        if i not in record:
            problems.append(f"{where}の「会社の記録」の id「{i}」が、会社の記録（記録/会社の記録.json）にありません")


def _check_judges(key: str, target: str, allowed: Sequence[str], fields: Sequence[str], names: List[str],
                  data: Dict, record: Dict[str, Dict], problems: List[str]) -> None:
    items = data.get(key)
    if items is None:
        return
    if not isinstance(items, list):
        problems.append(f"「{key}」は、判定の並び [ ] にしてください")
        return
    seen: List[str] = []
    for n, item in enumerate(items, 1):
        where = f"「{key}」の{n}件目"
        if not isinstance(item, dict):
            problems.append(f"{where}は {{ }} で囲んだ形にしてください")
            continue
        for k in item:
            if k not in fields:
                problems.append(f"{where}に、使わない欄「{k}」があります")
        name = item.get(target)
        if not _filled(name):
            problems.append(f"{where}に「{target}」がありません")
        elif _norm(name) not in names:
            problems.append(f"{where}の{target}「{_norm(name)}」が、制度データにありません（制度データの名前のとおりに書いてください）")
        elif _norm(name) in seen:
            problems.append(f"{where}の{target}「{_norm(name)}」の判定が、2つ以上あります")
        else:
            seen.append(_norm(name))
        if item.get("判定") not in allowed:
            problems.append(f"{where}の「判定」は、{' / '.join(allowed)} のどれかにしてください")
        if not _filled(item.get("理由")):
            problems.append(f"{where}の「理由」が空です")
        _check_ids(where, item.get("会社の記録"), record, problems)


def _check_estimate(spec: Any, seido: Dict, record: Dict[str, Dict], problems: List[str]) -> None:
    where = "「補助額の見込み」"
    if not isinstance(spec, dict):
        problems.append(f"{where}は {{ }} で囲んだ形にしてください")
        return
    for k in spec:
        if k not in ESTIMATE_KEYS:
            problems.append(f"{where}に、使わない欄「{k}」があります")
    entry = None
    if not _filled(spec.get("区分")):
        problems.append(f"{where}に「区分」がありません")
    else:
        entry = _find_amount(seido, spec["区分"])
        if entry is None:
            problems.append(f"{where}の区分「{_norm(spec['区分'])}」が、制度データの補助額にありません"
                            f"（区分は {' / '.join(_names(seido.get('補助額'), '区分'))}）")
    specials = spec.get("特例")
    if specials is not None:
        if not isinstance(specials, list) or not all(isinstance(s, str) for s in specials):
            problems.append(f"{where}の「特例」は、特例の名前の並びにしてください")
        elif entry is not None:
            kinds: List[str] = []
            seen: List[str] = []
            repeated: List[str] = []
            for name in specials:
                special = _find_special(entry, name)
                if special is None:
                    problems.append(f"{where}の特例「{_norm(name)}」が、区分「{_norm(spec['区分'])}」の特例にありません")
                    continue
                # 同じ特例を2回渡すと、上乗せが2回足される。種類にかかわらず、名前（NFC にそろえ、前後の空白を除く）で断る
                key = _norm(special.get("名前", ""))
                if key in seen:
                    if key not in repeated:
                        problems.append(f"{where}で、同じ特例「{key}」を2回以上選んでいます。1回だけ書いてください")
                        repeated.append(key)
                    continue
                seen.append(key)
                kind = special.get("種類")
                if kind != "上限の上乗せ" and kind in kinds:
                    problems.append(f"{where}で、同じ種類の特例（{kind}）を2つ以上選んでいます。1つにしてください")
                kinds.append(kind)
    cost_id = spec.get("補助の対象にする経費")
    if not _filled(cost_id):
        problems.append(f"{where}に「補助の対象にする経費」（会社の記録の事実の id）がありません")
    elif cost_id not in record:
        problems.append(f"{where}の「補助の対象にする経費」の id「{cost_id}」が、会社の記録にありません")
    else:
        item = record[cost_id]
        if item.get("種類") != "事実":
            problems.append(f"{where}の「補助の対象にする経費」の id「{cost_id}」は、会社の記録の「事実」ではありません")
        elif parse_yen(item.get("値")) is None:
            problems.append(f"{where}の「補助の対象にする経費」（会社の記録「{item.get('名前')}」）の値を、"
                            f"円の金額として読めません（{item.get('値')!r}）")
    if "理由" in spec and not _filled(spec.get("理由")):
        problems.append(f"{where}の「理由」が空です（なければ欄ごと外す）")
    _check_ids(where, spec.get("会社の記録"), record, problems)


def validate(data: Any, seido: Dict, record: Dict[str, Dict]) -> List[str]:
    """Claude が渡した JSON の、直す所の一覧。空なら正しい。"""
    if not isinstance(data, dict):
        return ["渡す JSON は { } で囲んだ形にしてください"]
    problems: List[str] = []
    for key in data:
        if key not in INPUT_KEYS:
            problems.append(f"使わない欄「{key}」があります（使える欄は {' / '.join(INPUT_KEYS)}）")
    if not _is_text(data.get("制度の概要")):
        problems.append("「制度の概要」が空です（制度の概要を、平易な文で書いてください）")
    if "流れの説明" in data and not _is_text(data["流れの説明"]):
        problems.append("「流れの説明」が空です（なければ欄ごと外す）")
    req_names = _names(seido.get("数値の要件")) + _names(seido.get("数値でない要件"))
    _check_judges("要件の判定", "要件", REQ_JUDGES, REQ_KEYS, req_names, data, record, problems)
    bonus_names = _names((seido.get("加点") or {}).get("項目"))
    _check_judges("加点の判定", "加点", BONUS_JUDGES, BONUS_KEYS, bonus_names, data, record, problems)
    if "補助額の見込み" in data:
        _check_estimate(data["補助額の見込み"], seido, record, problems)
    return problems


# ---- Word を組み立てる ----


def _judges(data: Dict, key: str, target: str) -> Dict[str, Dict]:
    return {_norm(j[target]): j for j in data.get(key) or []}


def flow_line(stages: List[Dict]) -> str:
    """全体の流れを1行で（手続きの段階の名前を順に）。必要なときだけの段階は、別の行にまとめる。"""
    main = [str(s.get("名前")) for s in stages if not s.get("条件付き")]
    extra = [str(s.get("名前")) for s in stages if s.get("条件付き")]
    if not main and not extra:
        return ""
    lines = [f"全体の流れ：{' → '.join(main)}"] if main else []
    if extra:
        lines.append(f"必要なときだけの手続き：{'、'.join(extra)}")
    return "\n".join(lines)


def special_rows(ctx: Context, amounts: List[Dict]) -> List[List[str]]:
    """特例の表の行（特例と出典・中身）。区分ごとに同じ特例が繰り返されるので、特例の名前で1行にまとめる。

    区分で違う値（上限の置き換えなど）は、同じ欄に区分ごとに並べる。条件も、区分で違うときだけ区分ごとに並べる。
    """
    groups: Dict[str, Dict[str, Any]] = {}
    for entry in amounts:
        region = str(entry.get("区分"))
        for s in entry.get("特例") or []:
            if not isinstance(s, dict):
                continue
            g = groups.setdefault(_norm(s.get("名前", "")), {"名前": str(s.get("名前")).strip(), "種類": [],
                                                             "値": [], "条件": [], "出典": []})
            kind = str(s.get("種類"))
            if kind not in g["種類"]:
                g["種類"].append(kind)
            fmt = None if kind == "補助率の置き換え" else yen
            g["値"].append((region, ctx.text(s.get("値"), fmt)))
            if is_sv(s.get("条件")):
                g["条件"].append((region, ctx.text(s["条件"])))
            _add(g["出典"], ctx.sources(s.get("値"), s.get("条件")))
    regions = [str(e.get("区分")) for e in amounts]
    rows = []
    for g in groups.values():
        kinds = "・".join(g["種類"])
        values = g["値"]
        if len({t for _r, t in values}) == 1:
            lines = [f"{kinds}：{values[0][1]}"]
        else:
            # 区分ごとの値は「／」でつないで1つの段落に（区分ごとに1行にすると、縦に長くなる）
            lines = [f"{kinds}：" + "／".join(f"{r} {t}" for r, t in values)]
        used = [r for r, _t in values]
        if set(used) != set(regions):
            lines.append(f"使える区分：{'、'.join(used)}")
        conds = g["条件"]
        if conds and len({t for _r, t in conds}) == 1 and len(conds) == len(values):
            lines.append(f"条件：{conds[0][1]}")
        else:
            lines += [f"条件（{r}）：{t}" for r, t in conds]
        body = "\n".join(lines)
        rows.append([named(g["名前"], g["出典"], body), body])
    return rows


def split_tables(doc: Document, pending_title: str, pending: List[List[str]], settled_title: str,
                 settled: List[List[str]]) -> None:
    """まだ決まっていない行の表（名前と出典・中身・判定）と、判定で決着した行の短い表を、見出しとともに置く。
    まだ決まっていない行がどれも判定なしなら、判定の列（すべて「まだ確かめていません」）を外し、中身の欄を広くする。"""
    if len(pending) > 1:
        if all(row[2] == NOT_JUDGED for row in pending[1:]):
            doc.heading(f"{pending_title}（どれも、{NOT_JUDGED}）", 2)
            doc.table([row[:2] for row in pending], widths=W2, compact=True)
        else:
            doc.heading(pending_title, 2)
            doc.table(pending, widths=W3, compact=True)
    if len(settled) > 1:
        doc.heading(settled_title, 2)
        doc.table(settled, widths=W2_WIDE, compact=True)


def doc_rows(ctx: Context, members: List[Dict]) -> List[List[str]]:
    """書類の表の行（書類と出典・区分・要点）。必須 → 条件付き → 任意の順（区分の中は制度データの順）。

    要点は、条件・有効期限・期数と、発行元（自社でないとき。取りに行く・頼む書類だと分かるように）、効く審査項目。
    内容・形式・出す人は入れない（書類の名前で分かることが多く、長くなるため。制度データには残る）。
    出典は、内容も含めて付ける（書類が要ることの出典）。"""
    rows = []
    for cls in DOC_CLASSES:
        for d in members:
            if d.get("区分") != cls:
                continue
            lines, srcs = ctx.lines(d, (("条件", "条件"), ("有効期限", "有効期限"), ("期数", "期数")))
            content = d.get("内容")
            srcs = ctx.sources(content) + [s for s in srcs if s not in ctx.sources(content)]
            if is_sv(content) and content["状態"] == UNREADABLE:
                lines.insert(0, f"内容：{ctx.text(content)}")  # 出典の代わりに、読み取れない理由を出す
            issuer = d.get("発行元")
            if _filled(issuer) and issuer.strip() != "自社":
                lines.append(f"発行元：{issuer.strip()}")
            if d.get("効く審査項目"):
                lines.append(f"効く審査項目：{'、'.join(map(str, d['効く審査項目']))}")
            body = "／".join(lines)  # 要点は「／」でつなぎ、行を増やさない
            rows.append([str(d.get("名前")), cls, named(body, srcs, body, inline=True)])
    return rows


def build(ctx: Context, data: Dict, case: str, today: date, notices: List[str]) -> Tuple[Document, Dict[str, Any]]:
    seido = ctx.seido
    summary: Dict[str, Any] = {}
    doc = Document(margin_tb=MARGIN, margin_lr=MARGIN, tight=True)  # 余白 15mm、行間を詰める（10ページ以内にまとめるため）
    doc.title("概要と流れ")
    info = seido.get("制度") or {}
    frame = f"（{info['枠']}）" if info.get("枠") else ""
    head = [f"案件：{case}　作った日：{dates.format_date(today)}",
            f"制度：{info.get('名前')}{frame}（制度データは{info.get('公募回')}の資料に基づく）"]
    doc.paragraph("\n".join(head + [n.strip() for n in notices if _filled(n)]))
    doc.paragraph("応募の準備に要るところだけを短くまとめています。数字・期限・一覧は、公募要領などの資料（出典は呼び名とページ。"
                  "呼び名は終わりの「出典の資料」）と会社の記録から入れています。【要確認】は、資料と照らして確かめが要る値です。"
                  "細かい決まりと、採択された後の手続きは、要るときに案内します。")
    first = ctx.stages[0] if ctx.stages else None
    apply_docs = f"{first.get('名前')}で出す書類" if first else APPLY_DOCS_FALLBACK

    # 1. 制度の概要
    doc.heading("制度の概要", 1)
    for para in _paragraphs(data["制度の概要"]):
        doc.paragraph(para)
    flow = flow_line(ctx.stages)
    # 審査の段階は、名前を1行で（条件の文は制度データに残る）
    reviews = [s for s in seido.get("審査の段階") or [] if isinstance(s, dict)]
    if reviews:
        src = source_text(ctx.sources(*(s.get("条件") for s in reviews)))
        flow = "\n".join(x for x in (flow, f"審査の段階：{' → '.join(str(s.get('名前')) for s in reviews)}"
                                      + (f"（{src}）" if src else "")) if x)
    if flow:
        doc.paragraph(flow)
    amounts = [e for e in seido.get("補助額") or [] if isinstance(e, dict)]
    doc.heading("補助額（区分ごと）", 2)
    rows = [["区分", "補助上限", "補助率"]]
    for entry in amounts:
        cap = ctx.text(entry.get("上限"), yen)
        rate = ctx.text(entry.get("補助率"))
        rows.append([named(str(entry.get("区分")), ctx.sources(entry.get("上限"), entry.get("補助率")), cap + rate), cap, rate])
    doc.table(rows, widths=W_AMOUNT, compact=True)
    doc.heading("特例（補助上限・補助率が変わるとき）", 2)
    rows = special_rows(ctx, amounts)
    if rows:
        doc.paragraph("条件に当たると、上の表の補助上限か補助率が置き換わるか、上乗せされます。")
        doc.table([["特例", "中身"]] + rows, widths=W2, compact=True)
    else:
        doc.paragraph("特例はありません。")

    # 2. 自社が満たす要件（数値の要件は基準、数値でない要件は内容だけ。計算式などは制度データに残る）
    # 満たすと決まった要件は、中身を省いて理由だけの短い表にする（社長が読むのは、まだ決まっていない要件。11/6 の後）
    doc.heading("自社が満たす要件", 1)
    doc.paragraph("会社の記録と聞き取りから当てはめた結果です。満たす・当てはまらないと決まった要件は、中身を省いて理由だけを"
                  "書いています。「まだ確かめていません」の要件は、これから社長に確かめます。")
    judges = _judges(data, "要件の判定", "要件")
    pending = [["要件", "中身", "自社の状況"]]
    settled = [["要件", "判定と理由"]]
    count = judged = 0
    reqs = [(r, "基準", "") for r in seido.get("数値の要件") or []]
    reqs += [(r, "内容", OFF_PREFIX if r.get("種類") == "当たらないこと" else "") for r in seido.get("数値でない要件") or []]
    for req, key, prefix in reqs:
        node = req.get(key)
        srcs = ctx.sources(node)
        judge = judges.get(_norm(req.get("名前")))
        jtext, jsrc = judge_cell(ctx, judge)
        srcs += [s for s in jsrc if s not in srcs]
        if judge and judge["判定"] in SETTLED_JUDGES:
            settled.append([str(req.get("名前")), named(f"{judge['判定']}：{judge['理由'].strip()}", srcs, inline=True)])
        else:
            body = prefix + ctx.text(node) if is_sv(node) else ""
            pending.append([named(str(req.get("名前")), srcs, body), body, jtext])
        count += 1
        judged += bool(judge)
    split_tables(doc, PENDING_REQS, pending, SETTLED_REQS, settled)
    summary["要件"] = (count, judged)

    # 3. 補助額の見込み
    doc.heading("補助額の見込み", 1)
    spec = data.get("補助額の見込み")
    if spec:
        rows, est = estimate_rows(ctx, spec)
        doc.table([["項目", "中身"]] + rows, widths=W2_NARROW, compact=True)
        summary["補助額の見込み"] = est
    else:
        doc.paragraph("まだ見込みを出していません。補助額のどの区分に当たるかと、補助の対象にする経費の額が分かったら出します。")
        summary["補助額の見込み"] = None

    # 4. 加点（種類の数と区分ごとの上限は1つの段落。項目は内容だけ）
    doc.heading("加点", 1)
    bonus = seido.get("加点") or {}
    lines = []
    for key, label in (("種類の数", "加点の種類の数"), ("区分ごとの上限", "区分ごとの上限")):
        if is_sv(bonus.get(key)):
            text = ctx.text(bonus[key])
            src = merge_pages(ctx.sources(bonus[key]))
            lines.append(f"{label}：{text}" + (f"（{'、'.join(src)}）" if src else ""))
    if lines:
        doc.paragraph("\n".join(lines))
    # 今回は取れないと決まった加点は、中身を省いて理由だけの短い表にする
    judges = _judges(data, "加点の判定", "加点")
    pending = [["加点", "中身", "取れるか"]]
    settled = [["加点", "取れない理由"]]
    for item in bonus.get("項目") or []:
        node = item.get("内容")
        srcs = ctx.sources(node)
        judge = judges.get(_norm(item.get("名前")))
        jtext, jsrc = judge_cell(ctx, judge)
        srcs += [s for s in jsrc if s not in srcs]
        if judge and judge["判定"] == "今回は取れない":
            settled.append([str(item.get("名前")), named(judge["理由"].strip(), srcs, inline=True)])
        else:
            body = ctx.text(node) if is_sv(node) else ""
            pending.append([named(str(item.get("名前")), srcs, body), body, jtext])
    split_tables(doc, PENDING_BONUS, pending, SETTLED_BONUS, settled)
    summary["加点"] = len(bonus.get("項目") or [])

    # 5. 申請の段階で出す書類（2つ以上の手続きで使う書類は、それぞれの手続きに出す）
    docs = [d for d in seido.get("書類") or [] if isinstance(d, dict)]
    stage_ids = [s.get("id") for s in ctx.stages]
    doc.heading(apply_docs, 1)
    first_docs = [d for d in docs if first and first.get("id") in (d.get("手続き") or [])]
    if first_docs:
        doc.paragraph("応募のときに出す書類です（必須 → 条件付き → 任意）。発行元は、自社で作らない書類だけに書いています。")
        doc.table([["書類", "区分", "要点"]] + doc_rows(ctx, first_docs), widths=W_DOC, compact=True)
    else:
        doc.paragraph("この手続きで出す書類は、制度データにありません。")
    # どの手続きで使うか分からない書類（制度データの書類の「手続き」が、どの段階にも当たらない）は、申請の書類の後に別の表
    unknown = [d for d in docs if not set(d.get("手続き") or []) & set(stage_ids)]
    if unknown:
        doc.heading(UNKNOWN_STAGE_DOCS, 2)
        doc.table([["書類", "区分", "要点"]] + doc_rows(ctx, unknown), widths=W_DOC, compact=True)
    later_docs = [d for d in docs if d not in first_docs and d not in unknown]
    summary["必要書類"] = len(docs)
    summary["申請で出す書類"] = len(first_docs)
    summary["採択後の書類"] = len(later_docs)
    summary["分からない書類"] = len(unknown)

    # 6. 義務と返還の条件（応募の前に知っておくこと）
    doc.heading("義務と返還の条件", 1)
    doc.paragraph("採択された後も守り続けることと、守れないときに補助金を返すことになる条件です。応募する前に知っておいてください。")
    duty = 0
    # 数値の要件だけ（数値でない要件の「満たせないとき」は、応募できない・対象外などで、要件の表から分かる）。
    # 当てはまらないと判定した要件（使わない特例の要件など）は省く
    doc.heading("満たせないと返還などがある数値の要件", 2)
    rows = [["要件", "満たせないとき"]]
    req_judges = _judges(data, "要件の判定", "要件")
    skipped = 0
    for req in seido.get("数値の要件") or []:
        if not is_sv(req.get("満たせないとき")):
            continue
        if (req_judges.get(_norm(req.get("名前"))) or {}).get("判定") == "当てはまらない":
            skipped += 1
            continue
        fail = ctx.text(req["満たせないとき"])
        rows.append([named(str(req.get("名前")), ctx.sources(req["満たせないとき"]), fail), fail])
        duty += 1
    if len(rows) == 1:
        rows.append(["なし", "当てはまる数値の要件に、満たせないときの定めはありません" if skipped
                     else "満たせないときの定めのある数値の要件は、制度データにありません"])
    doc.table(rows, widths=W2, compact=True)
    if skipped:
        doc.paragraph(f"当てはまらないと判定した要件（{skipped}件）は、省いています。")
    doc.heading("してはいけないこと", 2)
    rows = [["してはいけないこと", "中身"]]
    for item in seido.get("してはいけないこと") or []:
        text = ctx.text(item.get("内容"))
        rows.append([str(item.get("名前")), named(text, ctx.sources(item.get("内容")), text, inline=True)])
        duty += 1
    doc.table(rows, widths=W2_WIDE, compact=True)
    summary["義務と返還の条件"] = duty

    # 7. 流れと期限（流れは制度の概要の「全体の流れ」の1行。期限は、決まった期日と申請の期限だけ。
    #    採択された後の手続きの期限・書類・注意は入れず、採択されたときに段階を切り替える道具が出す。11/6 の後）
    doc.heading("申請から効果報告までの流れと期限", 1)
    if data.get("流れの説明"):
        for para in _paragraphs(data["流れの説明"]):
            doc.paragraph(para)
    rows = [["期日", "日時（日本時間）"]]
    for item in seido.get("決まった期日") or []:
        text = ctx.text(item.get("日時"), due_text)
        if _filled(item.get("注記")) and UNREAD_TEXT not in text:
            text += f"（{item['注記'].strip()}）"
        rows.append([str(item.get("名前")), named(text, ctx.sources(item.get("日時")), text)])
    if first is not None and is_sv(first.get("期限")):
        limit = ctx.text(first["期限"], ctx.limit_text)
        rows.append([f"{first.get('名前')}の期限", named(limit, ctx.sources(first["期限"]), limit)])
    doc.table(rows, widths=W2_NARROW, compact=True)
    later = [s for s in ctx.stages[1:]]
    later_notes = sum(len(s.get("注意") or []) for s in later)
    summary["流れ"] = (len(ctx.stages), len(seido.get("決まった期日") or []))
    summary["採択後の注意"] = later_notes
    if later:
        doc.paragraph(f"採択された後の手続き（{len(later)}段階）の期限と、出す書類（{len(later_docs)}件）・守ること（{later_notes}件）は、"
                      "ここには入れていません。採択されたときに、手続きごとに案内します。")

    # 8. 資料で分からなかったこと（項目の名前だけ。理由と問い合わせ文の案は制度データに残り、要るときに示す）
    doc.heading("資料で分からなかったこと", 1)
    unread = [u for u in seido.get("読み取れなかった項目") or [] if isinstance(u, dict)]
    if unread:
        doc.paragraph("次のことは資料に書かれていなかったので、推測で埋めずに空けています：" + "、".join(str(u.get("項目")) for u in unread)
                      + "。応募の判断に関わるものは、資料の定めを当てはめてから案内します。")
    else:
        doc.paragraph("ありません。")

    # 9. 資料どうしの食い違い（項目の名前だけ。表の値に関わるものは、値に印と注記がある）
    doc.heading("資料どうしで書き方が違うところ", 1)
    conflicts = [c for c in seido.get("資料どうしの食い違い") or [] if isinstance(c, dict)]
    if conflicts:
        doc.paragraph("次の項目は、資料によって書き方が違います：" + "、".join(str(c.get("項目")) for c in conflicts)
                      + "。上の表の値のうち、資料で書き方が違うものには【資料で食い違い】の印と注記を付けています。"
                      "資料ごとの書き方は、聞かれたら資料のページを示して答えます。")
    else:
        doc.paragraph("見つかっていません。")

    # 10. 出典の資料
    doc.heading("出典の資料", 1)
    doc.paragraph("表の出典は、資料の呼び名とページ（資料の下に印刷された番号）です。呼び名と資料の対応は、次のとおりです。")
    # 資料の名前を、公式サイトの URL へのリンクにする（URL をそのまま書くと、1行が2〜3行に折れるため）
    rows = [["呼び名", "資料の名前（公式サイトへのリンク）", "回", "取得日"]]
    for d in seido.get("資料") or []:
        url = str(d.get("URL") or "")
        name = str(d.get("名前"))
        rows.append([str(d.get("id")), [(name, url)] if url else name, str(d.get("公募回")), str(d.get("取得日"))])
    doc.table(rows, widths=W_SOURCES, compact=True)

    summary["読み取れない値"] = len(ctx.marked[UNREADABLE])
    summary["要確認の値"] = len(ctx.marked[CHECK])
    summary["資料で食い違いの値"] = len(ctx.marked[CONFLICT])
    return doc, summary


# ---- 読み込みと書き出し ----


def _outside(what: str) -> GaiyouError:
    return GaiyouError([f"{what}が、別名（シンボリックリンク）などで会社のフォルダの外を指しています。"
                        "外のファイルは読まず、外にも書きません。別名を本物のフォルダやファイルに置き換えてから、"
                        "もう一度試してください"])


def load_record(folder: Path) -> Dict[str, Dict]:
    """会社の記録の項目を id で引けるようにする。ファイルがなければ空。会社のフォルダの外を指すときは読まずに断る。"""
    path = folder / RECORDS_DIR / RECORD_FILE
    if os.path.lexists(str(path)) and not places.is_inside(folder, path):
        raise _outside(f"会社の記録（{RECORDS_DIR}/{RECORD_FILE}）")
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise GaiyouError([f"会社の記録（{RECORDS_DIR}/{RECORD_FILE}）が JSON として読めません（{e}）"]) from e
    items = data.get("項目") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise GaiyouError([f"会社の記録（{RECORDS_DIR}/{RECORD_FILE}）に「項目」の並びがありません"])
    return {str(i["id"]): i for i in items if isinstance(i, dict) and "id" in i}


def _check_read_place(folder: Path, path: Path, what: str) -> None:
    """読む材料（資料の一覧・制度データと、その上のフォルダ）が、別名と「..」をたどった後も会社のフォルダの中にあるか
    （lib/places.py）。外なら、読まずに GaiyouError。まだない場所も、別名をたどった先で比べる。"""
    if not places.is_inside(folder, path):
        raise _outside(what)


def _check_out_place(folder: Path, path: Path, what: str) -> None:
    """path が、別名と「..」をたどった後も、会社のフォルダの `案件/` の中にあるか（lib/places.py）。外なら GaiyouError。"""
    from lib import case_folder

    try:
        rel = places.relative_inside(folder, path)
    except places.PlaceError as e:
        raise _outside(what) from e
    if rel.split("/")[0] != case_folder.CASES_DIR:
        raise GaiyouError([f"{what}が、別名（シンボリックリンク）などで {case_folder.CASES_DIR}/ の外（{rel}）を指しています。"
                           f"概要と流れ.docx は {case_folder.CASES_DIR}/<案件>/ の中にだけ書きます。"
                           "別名を本物のフォルダに置き換えてから、もう一度試してください"])


def write(folder: Path, case: Optional[str], data: Any) -> Tuple[Path, str, Dict[str, Any]]:
    """`案件/<案件>/概要と流れ.docx` を書き、（パス、案件、まとめ）を返す。書けないときは何も書かずに GaiyouError。"""
    folder = Path(folder)
    if not company.is_company_folder(folder):
        raise GaiyouError([f"ここ（{folder}）は会社のフォルダではありません（{company.MARKER_DIR}/ がありません）。"
                           "社長の了承を得て会社のフォルダを作り、公式資料を取って制度データを作ってから、もう一度試してください"])
    # 制度データを読む道具は、同梱の pypdf まで読み込むので、ここで読み込む
    from lib import case_folder, seido_data, urakadori
    from lib.official_docs import TEXT_DIR

    # 読む材料（資料の一覧・制度データ）も、別名と「..」をたどった後に会社のフォルダの中にあるときだけ読む
    # （外のフォルダの中の案件の一覧も見ない。DESIGN 5章）
    _check_read_place(folder, folder / RECORDS_DIR / TEXT_DIR, f"資料の本文（{RECORDS_DIR}/{TEXT_DIR}/）")
    _check_read_place(folder, urakadori.seido_dir(folder), f"制度データ（{RECORDS_DIR}/{urakadori.SEIDO_DIR}/）")
    try:
        case = urakadori.find_case(folder, case)
    except case_folder.CaseError as e:
        raise GaiyouError([f"案件を決められませんでした（{e}）"]) from e
    listed_path = seido_data.doc_list_path(folder, case)
    _check_read_place(folder, listed_path, f"案件の資料の一覧（{listed_path.relative_to(folder)}）")
    try:
        # 置き場所は資料の一覧から決まる（上で確かめた）。制度データのファイルそのものも確かめてから読む
        data_path = seido_data.seido_path(folder, case)
        _check_read_place(folder, data_path, f"制度データ（{data_path.relative_to(folder)}）")
        path, seido = seido_data.load_data(folder, case)
        listed = seido_data.load_doc_list(folder, case)
    except (seido_data.DataMissing, seido_data.MergeError) as e:
        raise GaiyouError([str(e)]) from e
    errors = urakadori.shape_errors(seido) if isinstance(seido, dict) else ["いちばん外側が { } の形ではありません"]
    if errors:
        rel = path.relative_to(folder)
        raise GaiyouError([f"制度データ（{rel}）の形が合いません（{len(errors)} か所）。"
                           "seido_data.py --check で確かめ、章を読ませ直してまとめ直してください"] + errors[:10])
    case_dir = folder / case_folder.CASES_DIR / case
    out = case_dir / FILE_NAME
    # 書き出す先は、別名をたどった後も `案件/` の中に限る（外や、原本/・記録/ などに書かない。DESIGN 5章）
    _check_out_place(folder, case_dir, f"案件のフォルダ（{case_folder.CASES_DIR}/{case}/）")
    if not case_dir.is_dir():
        raise GaiyouError([f"案件のフォルダ（{case_folder.CASES_DIR}/{case}/）がありません。先に公式資料を取ってください"])
    if os.path.lexists(str(out)):
        _check_out_place(folder, out, f"書き出す先（{case_folder.CASES_DIR}/{case}/{FILE_NAME}）")
    record = load_record(folder)
    problems = validate(data, seido, record)
    if problems:
        raise GaiyouError(problems)
    notices = [n for n in listed.get("案内") or [] if isinstance(n, str)]
    doc, summary = build(Context(seido, record), data, case, dates.today(folder), notices)
    # 作る間に置き換えられていないかを、書く直前にもう一度
    _check_out_place(folder, case_dir, f"案件のフォルダ（{case_folder.CASES_DIR}/{case}/）")
    if os.path.lexists(str(out)):
        _check_out_place(folder, out, f"書き出す先（{case_folder.CASES_DIR}/{case}/{FILE_NAME}）")
    try:
        doc.save(out)
    except DocxError as e:
        # 書く前に止まったので、前の「概要と流れ.docx」はそのまま残る
        raise GaiyouError([str(e)]) from e
    return out, case, summary
