"""T1-3 jGrants API。

SPEC：記録しておいたAPIの応答で確かめ、実際の通信でも1回動かす。
合格ライン：必須の検索条件で取得でき、締切を日本時間で示す。

- 必須の検索条件（keyword・sort・order・acceptance）が、組み立てた URL にいつも4つとも入り、欠けた URL は作らない。
- 実際の通信は、tests/jgrants_record.py で1回だけ行い、送った URL と応答をそのまま
  tests/data/jgrants/記録_補助金.json に残した（2026-11-03、HTTP 200、158件）。この記録で、
  必須の4条件で送って取得できたこと、応答のすべての締切が日本時間で示されることを確かめる。
- 製品の通信の経路（道具 → jgrants.fetch → 出力）でも、tests/jgrants_record.py --tool で1回だけ本物の jGrants に
  当て、動かしたコマンド・終了コード・出力をそのまま tests/data/jgrants/道具の実行_補助金.json に残した
  （2026-11-04、終了コード0、158件）。この記録で、記録した応答を使わずに必須の4条件で取得でき、
  すべての締切が日本時間で示されたことを確かめる。
- 道具（skills/sagasu/scripts/jgrants_search.py）は、社長の Mac と同じ /usr/bin/python3（3.9）で動かす。
- 通信して確かめ直すテストは、HOJOKIN_JGRANTS_LIVE=1 のときだけ流す（相手のサイトに負担をかけないため）。
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from lib import jgrants

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "sagasu" / "scripts" / "jgrants_search.py"
RECORD = REPO_ROOT / "tests" / "data" / "jgrants" / "記録_補助金.json"
TOOL_RECORD = REPO_ROOT / "tests" / "data" / "jgrants" / "道具の実行_補助金.json"
SYSTEM_PYTHON = "/usr/bin/python3"
REQUIRED = {"keyword", "sort", "order", "acceptance"}
WEEKDAYS = "月火水木金土日"


def expected_jst(value: str) -> str:
    """テストの側で別に計算した、日本時間の表示（UTC に9時間足す）。"""
    text = value.replace("Z", "")
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in text else "%Y-%m-%dT%H:%M:%S"
    utc = datetime.strptime(text, fmt)
    jst = utc + timedelta(hours=9)
    return f"{jst.year}年{jst.month}月{jst.day}日（{WEEKDAYS[jst.weekday()]}）{jst.hour}:{jst.minute:02d}"


def query_of(url: str) -> dict:
    parsed = urllib.parse.urlparse(url)
    return {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}


def record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def run_tool(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [SYSTEM_PYTHON, "-I", "-B", str(SCRIPT), *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        env={"PATH": "/usr/bin:/bin", "HOME": str(cwd)}, timeout=60,
    )


# --- 必須の検索条件 ---

def test_url_always_has_all_required_params() -> None:
    url = jgrants.build_url(jgrants.build_query("省力化"))
    assert url.startswith(jgrants.BASE_URL + "?")
    q = query_of(url)
    assert REQUIRED <= set(q)
    assert q == {"keyword": "省力化", "sort": "acceptance_end_datetime", "order": "ASC", "acceptance": "1"}


def test_required_params_follow_arguments_and_optional_ones_are_added() -> None:
    query = jgrants.build_query(
        "設備投資", sort="created_date", order="DESC", acceptance=False,
        industry="製造業", target_number_of_employees="20名以下", use_purpose=None,
    )
    q = query_of(jgrants.build_url(query))
    assert q == {
        "keyword": "設備投資", "sort": "created_date", "order": "DESC", "acceptance": "0",
        "industry": "製造業", "target_number_of_employees": "20名以下",
    }


@pytest.mark.parametrize("missing", sorted(REQUIRED))
def test_url_with_missing_required_param_is_not_built(missing: str) -> None:
    query = jgrants.build_query("省力化")
    del query[missing]
    with pytest.raises(ValueError, match=missing):
        jgrants.build_url(query)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"keyword": "a"},
        {"keyword": "  "},
        {"keyword": "あ" * 256},
        {"keyword": "省力化", "sort": "title"},
        {"keyword": "省力化", "order": "asc"},
        {"keyword": "省力化", "prefecture": "x"},
    ],
)
def test_wrong_conditions_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        jgrants.build_query(**kwargs)


# --- 実際の通信の記録（1回だけ取ったもの） ---

def test_record_is_a_real_response_fetched_with_all_required_params() -> None:
    rec = record()
    assert rec["HTTP の状態"] == 200
    parsed = urllib.parse.urlparse(rec["送った URL"])
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == jgrants.BASE_URL
    q = query_of(rec["送った URL"])
    assert REQUIRED <= set(q)
    assert q == rec["条件"]
    # 今の道具で同じ条件を組み立てると、同じ URL になる（記録が今の道具の送り方と同じ）
    assert jgrants.build_url(jgrants.build_query(q["keyword"])) == rec["送った URL"]
    response = rec["応答"]
    assert response["metadata"]["resultset"]["count"] == len(response["result"]) > 0
    assert rec["取った日時"].endswith("+09:00")


def test_every_deadline_in_record_is_shown_in_jst() -> None:
    raw = record()["応答"]["result"]
    items = jgrants.summarize(record()["応答"])
    assert len(items) == len(raw)
    by_id = {r["id"]: r for r in raw}
    for item in items:
        source = by_id[item["id"]]
        assert source["acceptance_end_datetime"], source
        assert item["締切（日本時間）"] == expected_jst(source["acceptance_end_datetime"])
        assert item["受付開始（日本時間）"] == expected_jst(source["acceptance_start_datetime"])
        assert item["出典URL"] == f"https://www.jgrants-portal.go.jp/subsidy/{item['id']}"
    # 締切の早い順に並ぶ
    ends = [jgrants.parse_datetime(by_id[i["id"]]["acceptance_end_datetime"]) for i in items]
    assert ends == sorted(ends)


def test_known_items_in_record() -> None:
    """記録の中の決まった1件で、日付をまたぐ変換も確かめる（受付開始は世界標準時の前日 15:00）。"""
    items = {i["id"]: i for i in jgrants.summarize(record()["応答"])}
    item = items["a0W2x000005iqyXEAQ"]
    assert item["締切（日本時間）"] == "2027年5月31日（月）23:59"  # 2027-05-31T14:59:00.000Z
    assert item["受付開始（日本時間）"] == "2026年4月1日（水）0:00"  # 2026-03-31T15:00:00.000Z
    assert item["補助の上限額"] == 51900000


# --- 日時の読み方 ---

@pytest.mark.parametrize(
    "value, shown",
    [
        ("2026-11-30T15:30:00Z", "2026年12月1日（火）0:30"),
        ("2026-11-30T15:30:00.5Z", "2026年12月1日（火）0:30"),
        ("2026-11-30T15:30:00.123456Z", "2026年12月1日（火）0:30"),
        ("2026-12-01T00:30:00+09:00", "2026年12月1日（火）0:30"),
        ("2026-11-30T15:30:00", "2026年12月1日（火）0:30"),
        (None, "書かれていません"),
        ("", "書かれていません"),
    ],
)
def test_datetime_formats_are_shown_in_jst(value, shown) -> None:
    assert jgrants.format_jst(value) == shown


def test_unreadable_datetime_is_an_error() -> None:
    with pytest.raises(jgrants.JGrantsError):
        jgrants.format_jst("来月の末")


# --- 通信の部分（実際には通信しない） ---

class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_sends_one_request_with_required_params(monkeypatch) -> None:
    calls = []
    body = json.dumps(record()["応答"]).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return FakeResponse(body)

    monkeypatch.setattr(jgrants.urllib.request, "urlopen", fake_urlopen)
    url = jgrants.build_url(jgrants.build_query("補助金"))
    items = jgrants.summarize(jgrants.fetch(url))
    assert len(calls) == 1
    assert REQUIRED <= set(query_of(calls[0][0]))
    assert calls[0][1] == jgrants.TIMEOUT_SECONDS
    assert len(items) == len(record()["応答"]["result"])


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("nodename nor servname provided"),
        urllib.error.HTTPError("u", 400, "Bad Request", {}, None),
        TimeoutError("timed out"),
    ],
)
def test_fetch_failure_becomes_message_without_retry(monkeypatch, error) -> None:
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        raise error

    monkeypatch.setattr(jgrants.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(jgrants.JGrantsError, match="jGrants"):
        jgrants.fetch(jgrants.build_url(jgrants.build_query("補助金")))
    assert len(calls) == 1


def test_broken_response_is_an_error() -> None:
    with pytest.raises(jgrants.JGrantsError):
        jgrants.parse_body(b"<html>maintenance</html>")
    with pytest.raises(jgrants.JGrantsError):
        jgrants.parse_body(b'{"result": "x"}')


# --- 道具（/usr/bin/python3 で動かす） ---

def test_tool_shows_recorded_result_in_jst(tmp_path) -> None:
    r = run_tool("--keyword", "補助金", "--response-file", str(RECORD), cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "日時はすべて日本時間" in out
    assert "keyword=" in out and "sort=" in out and "order=" in out and "acceptance=1" in out
    items = jgrants.summarize(record()["応答"])
    for item in items[:30]:
        assert f"締切（日本時間）：{item['締切（日本時間）']}" in out
    assert f"ほかに{len(items) - 30}件" in out
    assert list(tmp_path.iterdir()) == []  # 何も書かない


def test_tool_json_output(tmp_path) -> None:
    r = run_tool("--keyword", "補助金", "--response-file", str(RECORD), "--json", "--limit", "500", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)
    assert REQUIRED <= set(data["条件"])
    assert data["件数"] == data["示した件数"] == len(record()["応答"]["result"])
    raw = {x["id"]: x for x in record()["応答"]["result"]}
    for item in data["候補"]:
        assert item["締切（日本時間）"] == expected_jst(raw[item["id"]]["acceptance_end_datetime"])


def test_tool_rejects_short_keyword(tmp_path) -> None:
    r = run_tool("--keyword", "a", "--response-file", str(RECORD), cwd=tmp_path)
    assert r.returncode == 2
    assert "2文字以上" in r.stdout


def test_tool_reports_unreadable_response_and_continues(tmp_path) -> None:
    broken = tmp_path / "壊れた応答.json"
    broken.write_text("<html></html>", encoding="utf-8")
    r = run_tool("--keyword", "補助金", "--response-file", str(broken), cwd=tmp_path)
    assert r.returncode == 1
    assert "jGrants で検索できませんでした" in r.stdout
    assert "候補を集め続けてください" in r.stdout


# --- 製品の道具を本物の jGrants に当てた記録（1回だけ動かしたもの） ---

JST_SHOWN = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日（([月火水木金土日])）(\d{1,2}):(\d{2})$")


def tool_record() -> dict:
    return json.loads(TOOL_RECORD.read_text(encoding="utf-8"))


def assert_jst_shown(text: str) -> None:
    match = JST_SHOWN.match(text)
    assert match, text
    year, month, day, weekday, hour, minute = match.groups()
    assert WEEKDAYS[date(int(year), int(month), int(day)).weekday()] == weekday, text  # 曜日も合う
    assert 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59, text


def test_tool_record_ran_product_tool_against_real_jgrants() -> None:
    """記録した応答を使わず、社長の Mac と同じ /usr/bin/python3 で製品の道具を動かした（jgrants.fetch を通った）。"""
    rec = tool_record()
    command = rec["コマンド"]
    assert command[:4] == [SYSTEM_PYTHON, "-I", "-B", str(SCRIPT.relative_to(REPO_ROOT))]
    assert "--response-file" not in command
    assert "--json" in command
    assert rec["終了コード"] == 0, rec["エラー出力"]
    assert rec["エラー出力"] == ""
    assert rec["動かした日時"].endswith("+09:00")


def test_tool_record_was_fetched_with_all_required_params() -> None:
    out = tool_record()["出力"]
    assert REQUIRED <= set(out["条件"])
    assert REQUIRED <= set(query_of(out["検索した URL"]))
    assert query_of(out["検索した URL"]) == out["条件"]
    assert jgrants.build_url(jgrants.build_query(out["条件"]["keyword"])) == out["検索した URL"]
    assert out["件数"] == out["示した件数"] == len(out["候補"]) > 0  # 取得できた（全件を出した）


def test_tool_record_shows_every_deadline_in_jst() -> None:
    out = tool_record()["出力"]
    for item in out["候補"]:
        assert_jst_shown(item["締切（日本時間）"])
        assert_jst_shown(item["受付開始（日本時間）"])
        assert item["出典URL"] == f"https://www.jgrants-portal.go.jp/subsidy/{item['id']}"
    # 応答そのものの記録（11/3）にもある補助金は、そこでの世界標準時の締切を9時間進めた日時と同じ
    raw = {r["id"]: r for r in record()["応答"]["result"]}
    both = [item for item in out["候補"] if item["id"] in raw]
    assert both
    for item in both:
        assert item["締切（日本時間）"] == expected_jst(raw[item["id"]]["acceptance_end_datetime"]), item["id"]


# --- 実際の通信（HOJOKIN_JGRANTS_LIVE=1 のときだけ） ---

@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("HOJOKIN_JGRANTS_LIVE") != "1",
                    reason="実際の通信は記録を取ったときの1回だけ。確かめ直すときは HOJOKIN_JGRANTS_LIVE=1 で流す")
def test_live_search(tmp_path) -> None:
    r = run_tool("--keyword", "補助金", "--json", "--limit", "5", cwd=tmp_path)
    assert r.returncode == 0, r.stdout
    data = json.loads(r.stdout)
    assert REQUIRED <= set(data["条件"])
    assert data["件数"] > 0
    for item in data["候補"]:
        assert "年" in item["締切（日本時間）"] and "（" in item["締切（日本時間）"]
