"""今日の日付の差し替えと、日本時間での表示（SPEC 共通の要件「日付の差し替え」「説明」、DESIGN 6章）。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from lib import company, dates

UTC = timezone.utc


def fixed_clock(dt: datetime):
    return lambda: dt


@pytest.fixture
def company_dir(tmp_path):
    folder = tmp_path / "試しの会社"
    (folder / ".hojokin").mkdir(parents=True)
    return folder


def write_settings(folder, value) -> None:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    company.settings_path(folder).write_text(text, encoding="utf-8")


# --- 会社のフォルダの目印 ---


def test_company_folder_needs_marker_dir(tmp_path, company_dir) -> None:
    assert company.company_folder(company_dir) == company_dir
    plain = tmp_path / "ふつうのフォルダ"
    plain.mkdir()
    assert company.company_folder(plain) is None
    # 目印と同じ名前でも、ファイルなら会社のフォルダではない
    (plain / ".hojokin").write_text("", encoding="utf-8")
    assert company.company_folder(plain) is None
    # 親のフォルダはさかのぼらない
    sub = company_dir / "案件"
    sub.mkdir()
    assert company.company_folder(sub) is None


def test_company_folder_uses_project_dir_env(tmp_path, company_dir, monkeypatch) -> None:
    elsewhere = tmp_path / "ほかの場所"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(company_dir))
    assert company.company_folder() == company_dir
    monkeypatch.delenv("CLAUDE_PROJECT_DIR")
    assert company.company_folder() is None
    monkeypatch.chdir(company_dir)
    assert company.company_folder() == company_dir


# --- 今日の日付 ---


def test_today_is_japan_date_without_substitution(company_dir) -> None:
    # 世界標準時の 11/2 16:00 は、日本時間の 11/3 1:00
    clock = fixed_clock(datetime(2026, 11, 2, 16, 0, tzinfo=UTC))
    assert dates.today(company_dir, clock) == date(2026, 11, 3)
    assert dates.today(None, clock) == date(2026, 11, 3)
    assert dates.now(company_dir, clock) == datetime(2026, 11, 3, 1, 0, tzinfo=dates.JST)


def test_today_uses_real_clock_by_default(company_dir) -> None:
    before = datetime.now(dates.JST).date()
    got = dates.today(company_dir)
    after = datetime.now(dates.JST).date()
    assert got in (before, after)


def test_substituted_today(company_dir) -> None:
    write_settings(company_dir, {"今日の日付": "2027-03-01"})
    clock = fixed_clock(datetime(2026, 11, 3, 6, 30, tzinfo=UTC))  # 日本時間 15:30
    assert dates.today(company_dir, clock) == date(2027, 3, 1)
    # 日付だけを差し替え、時刻は日本時間の今
    assert dates.now(company_dir, clock) == datetime(2027, 3, 1, 15, 30, tzinfo=dates.JST)
    # 何か月も先の段階（効果報告の5年後など）も再現できる
    write_settings(company_dir, {"今日の日付": "2032-02-29"})
    assert dates.today(company_dir, clock) == date(2032, 2, 29)


def test_substitution_only_in_company_folder(tmp_path) -> None:
    # 目印のないフォルダの設定ファイルは読まない
    plain = tmp_path / "ふつうのフォルダ"
    plain.mkdir()
    clock = fixed_clock(datetime(2026, 11, 3, 0, 0, tzinfo=UTC))
    assert dates.today(company.company_folder(plain), clock) == date(2026, 11, 3)


@pytest.mark.parametrize("settings", [{}, {"今日の日付": None}, {"ほかの設定": 1}])
def test_no_substitution_when_key_missing(company_dir, settings) -> None:
    write_settings(company_dir, settings)
    clock = fixed_clock(datetime(2026, 11, 3, 0, 0, tzinfo=UTC))
    assert dates.today(company_dir, clock) == date(2026, 11, 3)


@pytest.mark.parametrize(
    "text, words",
    [
        ('{"今日の日付": "2027/03/01"}', "2027-03-01"),
        ('{"今日の日付": "2027-02-30"}', "2027-03-01"),
        ('{"今日の日付": 20270301}', "文字"),
        ('{"今日の日付": "2027-03-01"', "JSON"),
        ('["2027-03-01"]', "{ }"),
    ],
)
def test_broken_settings_raise_clear_error(company_dir, text, words) -> None:
    """設定が壊れていたら、黙って実際の日付にせず、どこが悪いかを示して止める。"""
    write_settings(company_dir, text)
    with pytest.raises(ValueError) as e:
        dates.today(company_dir)
    assert "設定.json" in str(e.value)
    assert words in str(e.value)


# --- 日本時間での表示 ---


def test_to_jst() -> None:
    assert dates.to_jst(datetime(2026, 10, 16, 8, 0, tzinfo=UTC)) == datetime(2026, 10, 16, 17, 0, tzinfo=dates.JST)
    # 時刻帯のない日時は日本時間として扱う
    assert dates.to_jst(datetime(2026, 10, 16, 17, 0)) == datetime(2026, 10, 16, 17, 0, tzinfo=dates.JST)
    assert dates.to_jst(datetime(2026, 10, 16, 17, 0)).utcoffset() == timedelta(hours=9)


def test_format_date() -> None:
    assert dates.format_date(date(2026, 11, 3)) == "2026年11月3日（火）"
    assert dates.format_date(date(2027, 1, 10)) == "2027年1月10日（日）"


def test_format_datetime_in_japan_time() -> None:
    assert dates.format_datetime(datetime(2026, 10, 16, 17, 0, tzinfo=dates.JST)) == "2026年10月16日（金）17:00"
    # 世界標準時で受け取っても、日本時間で示す（日付をまたぐときも）
    assert dates.format_datetime(datetime(2026, 10, 16, 8, 0, tzinfo=UTC)) == "2026年10月16日（金）17:00"
    assert dates.format_datetime(datetime(2026, 12, 14, 15, 5, tzinfo=UTC)) == "2026年12月15日（火）0:05"
    assert dates.format_datetime(datetime(2026, 12, 15, 9, 0)) == "2026年12月15日（火）9:00"
