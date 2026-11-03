"""補助金の候補.docx を作る（SPEC F1・T1-6、DESIGN 4.5・4.6）。

Claude が調べた候補の一覧（JSON）を受け取り、会社のフォルダの直下の「補助金の候補.docx」に書く。
探し直したときも、同じファイルを置き換える（「_v2」のような別のファイルを作らない）。前の版は版の履歴に残る。

候補の一覧の形：
{
  "会社名": "（任意）",
  "聞き取りの要点": "（任意。文字か、文字の並び）",
  "候補": [
    {
      "名前": "中小企業省力化投資補助金（一般型）",
      "区分": "公募中" / "公募予定（発表済み）" / "例年公募がある",
      "合う理由": "…", "対象外になりそうな点": "…", "次の公募の見込み": "…（時期と根拠）",
      "予算の状況": "…（出典つき。見つからなければ「見つからなかった」）",
      "出典URL": ["https://…"],
      "締切": "（任意。日本時間）",
      "対象外の可能性が高い": false（任意）
    }
  ]
}
文字の欄は、文字か文字の並び（並びは箇条書きにする）で書く。
出典を示せない候補は出さない決まり（SPEC F1）なので、出典URL のない候補があれば、何も書かずに止める。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib import company, dates
from lib.docx_min import Document

FILE_NAME = "補助金の候補.docx"
CATEGORIES = ("公募中", "公募予定（発表済み）", "例年公募がある")
TEXT_FIELDS = ("合う理由", "対象外になりそうな点", "次の公募の見込み", "予算の状況")
REQUIRED_FIELDS = ("名前", "区分") + TEXT_FIELDS + ("出典URL",)
OPTIONAL_FIELDS = ("締切", "対象外の可能性が高い")
UNLIKELY_LABEL = "【対象外の可能性が高い】"
CATEGORY_NOTES = {
    "公募中": "今、申し込みを受け付けているもの",
    "公募予定（発表済み）": "次の公募が発表されていて、まだ受付が始まっていないもの",
    "例年公募がある": "今は公募していないが、毎年のように公募があるもの（過去の公募の時期から次を見込む）",
}


class KouhoError(Exception):
    """候補の一覧の形が正しくないとき。problems に直す所を並べる。"""

    def __init__(self, problems: List[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def _is_text(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value) and all(isinstance(v, str) and v.strip() for v in value)
    return False


def _urls(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value.strip()]
    if isinstance(value, list):
        return [v.strip() for v in value if isinstance(v, str)]
    return []


def validate(data: Any) -> List[str]:
    """直す所の一覧。空なら正しい。"""
    if not isinstance(data, dict):
        return ["候補の一覧は { } で囲んだ形にしてください"]
    problems = []
    candidates = data.get("候補")
    if not isinstance(candidates, list):
        return ["「候補」に、候補の並び [ ] を入れてください"]
    for key in ("会社名",):
        if key in data and not (isinstance(data[key], str)):
            problems.append(f"「{key}」は文字にしてください")
    if "聞き取りの要点" in data and not _is_text(data["聞き取りの要点"]):
        problems.append("「聞き取りの要点」は、文字か文字の並びにしてください")
    for i, item in enumerate(candidates, 1):
        where = f"{i}件目の候補"
        if not isinstance(item, dict):
            problems.append(f"{where}は {{ }} で囲んだ形にしてください")
            continue
        name = item.get("名前")
        if isinstance(name, str) and name.strip():
            where = f"{i}件目の候補（{name.strip()}）"
        for key in item:
            if key not in REQUIRED_FIELDS + OPTIONAL_FIELDS:
                problems.append(f"{where}に、使わない欄「{key}」があります")
        for key in REQUIRED_FIELDS:
            if key not in item:
                problems.append(f"{where}に「{key}」がありません")
        if "名前" in item and not (isinstance(name, str) and name.strip()):
            problems.append(f"{where}の「名前」が空です")
        if "区分" in item and item["区分"] not in CATEGORIES:
            problems.append(f"{where}の「区分」は、{' / '.join(CATEGORIES)} のどれかにしてください（{item['区分']}）")
        for key in TEXT_FIELDS:
            if key in item and not _is_text(item[key]):
                problems.append(
                    f"{where}の「{key}」が空です"
                    + ("（見つからなければ「見つからなかった」と書く）" if key == "予算の状況" else "")
                )
        if "出典URL" in item:
            urls = _urls(item["出典URL"])
            if not urls or not all(u.startswith(("https://", "http://")) and len(u) > 8 for u in urls):
                problems.append(f"{where}の「出典URL」は、https:// で始まる URL を1つ以上入れてください（出典を示せない候補は出さない）")
        if "締切" in item and not _is_text(item["締切"]):
            problems.append(f"{where}の「締切」が空です（なければ欄ごと外す）")
        if "対象外の可能性が高い" in item and not isinstance(item["対象外の可能性が高い"], bool):
            problems.append(f"{where}の「対象外の可能性が高い」は true か false にしてください")
    return problems


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(f"・{v.strip()}" for v in value)
    return str(value).strip()


def _url_runs(urls: List[str]) -> list:
    runs: list = []
    for i, url in enumerate(urls):
        if i:
            runs.append("\n")
        runs.append((url, url))
    return runs


def _title(item: Dict[str, Any]) -> str:
    name = item["名前"].strip()
    return f"{name} {UNLIKELY_LABEL}" if item.get("対象外の可能性が高い") else name


def build(data: Dict[str, Any], searched_on: date) -> Document:
    doc = Document()
    doc.title("補助金の候補")
    lines = [f"探した日：{dates.format_date(searched_on)}"]
    if data.get("会社名"):
        lines.append(f"会社：{data['会社名'].strip()}")
    doc.paragraph("\n".join(lines))
    if data.get("聞き取りの要点"):
        doc.heading("聞き取りの要点", 1)
        doc.paragraph(_text(data["聞き取りの要点"]))

    candidates = data["候補"]
    doc.heading("一覧", 1)
    doc.paragraph("候補を3つの区分に分けています。日時はすべて日本時間です。\n" + "\n".join(
        f"・{c}：{CATEGORY_NOTES[c]}" for c in CATEGORIES
    ))
    if not candidates:
        doc.paragraph("条件に合う候補は見つかりませんでした。")
    else:
        rows: list = [["区分", "候補", "締切・次の公募の見込み"]]
        for category in CATEGORIES:
            for item in candidates:
                if item["区分"] == category:
                    timing = _text(item["締切"]) + "\n" if item.get("締切") else ""
                    rows.append([category, _title(item), timing + _text(item["次の公募の見込み"])])
        doc.table(rows, widths=[1900, 3600, 4138])

    for category in CATEGORIES:
        members = [item for item in candidates if item["区分"] == category]
        if not members:
            continue
        doc.heading(f"{category}（{len(members)}件）", 1)
        for item in members:
            doc.heading(_title(item), 2)
            rows = [["項目", "中身"], ["区分", category]]
            if item.get("締切"):
                rows.append(["締切（日本時間）", _text(item["締切"])])
            for key in TEXT_FIELDS:
                rows.append([key, _text(item[key])])
            rows.append(["出典URL", _url_runs(_urls(item["出典URL"]))])
            doc.table(rows, widths=[2700, 6938])

    doc.paragraph("この一覧は、探し直すたびに同じファイルを直します。前の版は、頼めばいつでも見られます。")
    return doc


def write(folder: Path, data: Any, searched_on: Optional[date] = None) -> Path:
    """会社のフォルダの直下に「補助金の候補.docx」を書き、そのパスを返す。

    会社のフォルダでないとき、形が正しくないときは、何も書かずに KouhoError にする。
    """
    folder = Path(folder)
    if not company.is_company_folder(folder):
        raise KouhoError([
            "ここは会社のフォルダではありません（.hojokin/ がありません）。"
            "社長の了承を得て会社のフォルダを作ってから、もう一度試してください"
        ])
    problems = validate(data)
    if problems:
        raise KouhoError(problems)
    day = searched_on or dates.today(folder)
    path = folder / FILE_NAME
    build(data, day).save(path)
    return path
