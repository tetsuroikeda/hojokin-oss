"""jGrants の公開API で補助金を検索する（SPEC F1・5.3・T1-3、DESIGN 6章）。

- 認証は要らない。検索の URL を組み立て、応答の JSON を読み、締切などの日時を日本時間で示す。
- 必須の検索条件は keyword（2〜255文字）・sort・order・acceptance の4つ。どれかが欠けた URL は作らない。
- 応答の日時は「2026-11-28T08:00:00.000Z」のような世界標準時（末尾が Z）で来る。
  Python 3.9 の fromisoformat は Z を読めないので、+00:00 に置き換えてから読む。
- 通信は urllib だけで行い、自動で何度もやり直さない（相手のサイトに負担をかけないため）。
  つながらないときは JGrantsError にして、呼んだ側が手元の作業（ほかの集め方）を続けられるようにする。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from lib import dates

BASE_URL = "https://api.jgrants-portal.go.jp/exp/v1/public/subsidies"
# 補助金ごとの詳しいページ（候補の出典 URL に使う）
DETAIL_URL = "https://www.jgrants-portal.go.jp/subsidy/{id}"

REQUIRED_PARAMS = ("keyword", "sort", "order", "acceptance")
SORT_VALUES = ("created_date", "acceptance_start_datetime", "acceptance_end_datetime")
ORDER_VALUES = ("ASC", "DESC")
KEYWORD_MIN = 2
KEYWORD_MAX = 255
# 任意の検索条件（値はそのまま API に渡す）
OPTIONAL_PARAMS = ("use_purpose", "industry", "target_number_of_employees", "target_area_search")

TIMEOUT_SECONDS = 15
USER_AGENT = "hojokin-oss (Claude Code plugin)"

_ISO_Z = re.compile(r"Z$")


class JGrantsError(Exception):
    """jGrants につながらない、または応答が読めないとき。文は社長にそのまま見せられる形にする。"""


def build_query(
    keyword: str,
    sort: str = "acceptance_end_datetime",
    order: str = "ASC",
    acceptance: bool = True,
    **optional: Optional[str],
) -> Dict[str, str]:
    """必須の4つの条件と、指定された任意の条件をそろえる。条件が正しくなければ ValueError。"""
    keyword = (keyword or "").strip()
    if not (KEYWORD_MIN <= len(keyword) <= KEYWORD_MAX):
        raise ValueError(
            f"検索の言葉は{KEYWORD_MIN}文字以上{KEYWORD_MAX}文字以下にしてください（今は{len(keyword)}文字）"
        )
    if sort not in SORT_VALUES:
        raise ValueError(f"並べ方（sort）は {' / '.join(SORT_VALUES)} のどれかにしてください（{sort}）")
    if order not in ORDER_VALUES:
        raise ValueError(f"順番（order）は ASC か DESC にしてください（{order}）")
    query = {
        "keyword": keyword,
        "sort": sort,
        "order": order,
        "acceptance": "1" if acceptance else "0",
    }
    for name, value in optional.items():
        if name not in OPTIONAL_PARAMS:
            raise ValueError(f"jGrants の検索条件にない名前です（{name}）")
        if value:
            query[name] = str(value)
    return query


def build_url(query: Dict[str, str], base_url: str = BASE_URL) -> str:
    missing = [name for name in REQUIRED_PARAMS if not query.get(name)]
    if missing:
        raise ValueError(f"必須の検索条件が欠けています（{', '.join(missing)}）")
    return base_url + "?" + urllib.parse.urlencode(query)


def fetch_raw(url: str, timeout: float = TIMEOUT_SECONDS) -> Tuple[int, bytes]:
    """1回だけ通信して、HTTP の状態と応答のバイト列を返す（fetch と、応答を記録する開発用の道具が使う）。"""
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return getattr(response, "status", 200), response.read()
    except urllib.error.HTTPError as e:
        raise JGrantsError(f"jGrants が検索を受け付けませんでした（HTTP {e.code}）") from e
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise JGrantsError(f"jGrants につながりませんでした（{reason}）") from e


def fetch(url: str, timeout: float = TIMEOUT_SECONDS) -> Dict[str, Any]:
    """1回だけ通信して、応答の JSON を返す。"""
    _status, body = fetch_raw(url, timeout)
    return parse_body(body)


def parse_body(body: bytes) -> Dict[str, Any]:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise JGrantsError("jGrants の応答を読めませんでした（JSON ではありません）") from e
    if not isinstance(data, dict) or not isinstance(data.get("result", []), list):
        raise JGrantsError("jGrants の応答の形が、思っていたものと違います（result の一覧がありません）")
    return data


def load_recorded(body: bytes) -> Dict[str, Any]:
    """記録しておいた応答を読む。応答そのものか、記録の道具が包んだ形（「応答」の欄に応答がある）のどちらでもよい。"""
    data = parse_body(body)
    wrapped = data.get("応答")
    if isinstance(wrapped, dict):
        return parse_body(json.dumps(wrapped).encode("utf-8"))
    return data


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """API の日時を、時刻帯つきの datetime にする。空なら None。時刻帯がなければ世界標準時とみなす。"""
    if not value:
        return None
    text = _ISO_Z.sub("+00:00", str(value).strip())
    # 3.9 の fromisoformat は、小数の秒が3桁か6桁のときだけ読めるので、6桁にそろえる
    match = re.match(r"^(.*T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(.*)$", text)
    if match:
        head, frac, tail = match.groups()
        text = head + ("." + (frac + "000000")[:6] if frac else "") + tail
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as e:
        raise JGrantsError(f"jGrants の日時を読めませんでした（{value}）") from e
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_jst(value: Optional[str]) -> str:
    """API の日時を、日本時間の文字にする。例：2026年11月28日（土）17:00。なければ「書かれていません」。"""
    parsed = parse_datetime(value)
    if parsed is None:
        return "書かれていません"
    return dates.format_datetime(parsed)


def summarize(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """応答の一覧を、社長に示す形（日本時間の締切と出典の URL つき）にする。締切の早い順。"""
    items = []
    for raw in data.get("result") or []:
        if not isinstance(raw, dict):
            continue
        end = parse_datetime(raw.get("acceptance_end_datetime"))
        subsidy_id = str(raw.get("id") or "")
        items.append(
            {
                "id": subsidy_id,
                "名前": raw.get("title") or raw.get("name") or "",
                "実施機関": raw.get("institution_name") or "",
                "対象地域": raw.get("target_area_search") or "",
                "対象の従業員数": raw.get("target_number_of_employees") or "",
                "補助の上限額": raw.get("subsidy_max_limit"),
                "受付開始（日本時間）": format_jst(raw.get("acceptance_start_datetime")),
                "締切（日本時間）": format_jst(raw.get("acceptance_end_datetime")),
                "出典URL": DETAIL_URL.format(id=subsidy_id) if subsidy_id else "",
                "_end": end,
            }
        )
    far = datetime.max.replace(tzinfo=timezone.utc)
    items.sort(key=lambda item: item["_end"] or far)
    for item in items:
        del item["_end"]
    return items


def format_yen(value: Any) -> str:
    if isinstance(value, (int, float)) and value > 0:
        return f"{int(value):,}円"
    return "書かれていません"


def render_text(items: List[Dict[str, Any]], url: str, limit: Optional[int] = None) -> str:
    """会話で示すための文。日時はすべて日本時間。limit を超える分は件数だけ示す（文脈を使いすぎないため）。"""
    lines = [f"jGrants の検索結果：{len(items)}件（締切の早い順。日時はすべて日本時間）", f"検索した URL：{url}", ""]
    shown = items if limit is None else items[:limit]
    for i, item in enumerate(shown, 1):
        lines.append(f"{i}. {item['名前']}")
        lines.append(f"   締切（日本時間）：{item['締切（日本時間）']}")
        lines.append(f"   受付開始（日本時間）：{item['受付開始（日本時間）']}")
        if item["実施機関"]:
            lines.append(f"   実施機関：{item['実施機関']}")
        if item["対象地域"]:
            lines.append(f"   対象地域：{item['対象地域']}")
        if item["対象の従業員数"]:
            lines.append(f"   対象の従業員数：{item['対象の従業員数']}")
        lines.append(f"   補助の上限額：{format_yen(item['補助の上限額'])}")
        if item["出典URL"]:
            lines.append(f"   出典：{item['出典URL']}")
    if len(shown) < len(items):
        lines.append(f"（ほかに{len(items) - len(shown)}件。言葉や条件を絞って探し直すか、--limit を増やす）")
    if not items:
        lines.append("条件に合う補助金は見つかりませんでした。")
    return "\n".join(lines) + "\n"
