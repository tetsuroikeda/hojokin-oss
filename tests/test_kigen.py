"""期限と、外部への依頼と待ちの道具（skills/junbi/scripts/kigen.py。SPEC F6・T6-6、DESIGN 4.5〜4.7・6章。TASKS K2）。

T6-6 そのものは振る舞いのテスト（evals/T6-6-場面1-聞く〜場面4。タグ F6）。ここでは、道具が台本のとおりの値を出し、
台帳と会社の記録に残すことを、モデルを使わずに確かめる。材料は testdata/期限/（D13）の台本と正解、制度データは
省力化 第8回の正解に第9回の仮の日付を足したもの（evals/_lib/irai_setup.py と同じ）と、evals/_lib/T6-6/ の持続化の小さなもの。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "skills" / "junbi" / "scripts" / "kigen.py"
CASE_1 = "2026_省力化（一般型）第9回"
CASE_2 = "2026_持続化（通常枠）第20回"
ANSWER = {(e["案件"], e["書類"].split("（")[0]): e
          for e in json.loads((REPO_ROOT / "testdata" / "期限" / "正解.json").read_text(encoding="utf-8"))["外部への依頼（T6-6）"]}
NOTE = "（テスト用の値。資料の文は写していない）"


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def set_today(folder: Path, day: str) -> None:
    path = folder / ".hojokin" / "設定.json"
    data = _json(path) if path.exists() else {}
    data["今日の日付"] = day
    _write(path, data)


def add_case(folder: Path, case: str, short: str, name: str, frame: str, round_: str, doc_round: str, data: dict) -> None:
    listed = {"案件": case, "制度": {"名前": name, "略称": short, "枠": frame, "種類": "補助金", "公募回": round_},
              "案件の回": round_, "資料": [{"id": "要領", "名前": "公募要領", "公募回": doc_round}]}
    _write(folder / "記録" / "資料の本文" / case / "資料の一覧.json", listed)
    _write(folder / "記録" / "制度データ" / f"{short}_{doc_round}.json", data)
    for sub in ("申請書", "添付する書類"):
        (folder / "案件" / case / "1_申請" / sub).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def folder(tmp_path) -> Path:
    folder = tmp_path / "試しの会社"
    (folder / ".hojokin").mkdir(parents=True)
    set_today(folder, "2026-11-16")
    data = _json(REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json")
    data["決まった期日"] = list(data["決まった期日"]) + [
        {"名前": "第9回 締切", "日時": {"値": {"日時": "2026-12-25T17:00+09:00"}, "出典": [{"資料": "スケジュール"}],
                                        "根拠の文": NOTE, "状態": "確認済み"}, "注記": "予定"},
        {"名前": "第9回 採択発表", "日時": {"値": {"日時": "2027-04-16"}, "出典": [{"資料": "スケジュール"}],
                                          "根拠の文": NOTE, "状態": "確認済み"}, "注記": "予定"}]
    add_case(folder, CASE_1, "省力化", "中小企業省力化投資補助金", "一般型", "第9回", "第8回", data)
    return folder


def run(folder: Path, *args: str):
    out = subprocess.run([sys.executable, "-B", str(SCRIPT), "--folder", str(folder), *args],
                         capture_output=True, text=True, encoding="utf-8")
    return out.returncode, out.stdout + out.stderr


def ledger(folder: Path) -> list:
    path = folder / "記録" / "期限の台帳.json"
    return _json(path).get("作業", []) if path.exists() else []


def facts(folder: Path) -> dict:
    path = folder / "記録" / "会社の記録.json"
    items = _json(path)["項目"] if path.exists() else []
    return {it["名前"]: it["値"] for it in items if it["種類"] == "事実"}


def test_requests_then_days_then_status(folder) -> None:
    # 場面1：候補を出す。確認書と見積書は目安の日数がない（制度データにも会社の記録にもない）
    code, out = run(folder, "--case", CASE_1, "--requests")
    assert code == 0, out
    assert "金融機関確認書（条件付き" in out and "見積書（必須。交付申請で使う）" in out
    assert "目安：まだ分かりません" in out
    # 台帳に足す（目安の日数なし）と、聞くものに並び、終了コード1
    code, out = run(folder, "--case", CASE_1, "--add", "金融機関確認書", "--add", "見積書")
    assert code == 1, out
    assert "目安の日数をまだ聞いていません" in out
    assert [(e["書類"], e["状態"], e["目安の日数"]) for e in ledger(folder)] == \
        [("金融機関確認書", "まだ", None), ("見積書", "まだ", None)]
    code, out = run(folder, "--case", CASE_1, "--requests")
    assert code == 1 and "### 目安の日数を社長に聞くもの" in out

    # A1〜A3：目安の日数と頼む人を残すと、会社の記録にも残り、始める日を逆算する
    code, out = run(folder, "--case", CASE_1, "--days", "金融機関確認書=2週間", "--days", "見積書=7日",
                    "--who", "金融機関確認書=社長", "--who", "見積書=社長", "--to", "金融機関確認書=信用金庫")
    assert code == 0, out
    bank, quote = ANSWER[("省力化（一般型）第9回", "金融機関確認書")], ANSWER[("省力化（一般型）第9回", "見積書")]
    assert bank["始める日"] == "2026-12-11" and quote["始める日"] == "2027-06-09"
    assert "始める日：2026年12月11日（金）（見込み）" in out and "始める日：2027年6月9日（水）（見込み）" in out
    assert "頼む：社長／書く：外部（信用金庫）" in out
    assert facts(folder) == {"依頼の目安の日数：金融機関確認書": "14日", "依頼の目安の日数：見積書": "7日"}
    entry = {e["書類"]: e for e in ledger(folder)}
    assert entry["金融機関確認書"]["目安の日数"] == bank["目安の日数"]["値"] == 14
    assert entry["見積書"]["目安の日数"] == quote["目安の日数"]["値"] == 7
    assert entry["金融機関確認書"]["頼む人"] == "社長" and entry["金融機関確認書"]["依頼先"] == "信用金庫"

    # S2：頼んだ（2026-11-18）。S3：届いた（整理した後の原本の場所を渡す）
    set_today(folder, "2026-11-18")
    code, out = run(folder, "--case", CASE_1, "--status", "金融機関確認書=依頼した")
    assert code == 0 and "状態：依頼した" in out
    assert {e["書類"]: e for e in ledger(folder)}["金融機関確認書"]["依頼した日"] == "2026-11-18"
    set_today(folder, "2026-11-30")
    rel = "原本/会社の資料/2026-11-27_金融機関確認書_架空の信用金庫.pdf"
    (folder / rel).parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "testdata" / "期限" / "材料" / "外部への依頼" / "信用金庫からの確認書.pdf", folder / rel)
    code, out = run(folder, "--case", CASE_1, "--received", f"金融機関確認書={rel}")
    assert code == 0, out
    done = {e["書類"]: e for e in ledger(folder)}["金融機関確認書"]
    assert (done["状態"], done["届いた日"], done["届いた書類"]) == ("届いた", "2026-11-30", rel)
    # 今の状態.html の依頼の一覧に、状態とだれがするかが出る
    page = (folder / "今の状態.html").read_text(encoding="utf-8")
    assert "<td>金融機関確認書</td><td>" in page and "<td>届いた</td><td>頼む：社長／書く：外部（信用金庫）</td>" in page

    # 場面4：2件目の見積書等は、会社の記録の7日を使い、聞き直さない（始める日 2028-02-22）
    add_case(folder, CASE_2, "持続化", "小規模事業者持続化補助金", "通常枠", "第20回", "第20回",
             _json(REPO_ROOT / "evals" / "_lib" / "T6-6" / "持続化_第20回.json"))
    code, out = run(folder, "--case", CASE_2, "--requests")
    assert code == 0, out
    second = ANSWER[("持続化（通常枠）第20回", "見積書等")]
    assert second["始める日"] == "2028-02-22"
    line = next(x for x in out.splitlines() if x.startswith("- 見積書等"))
    assert "目安：7日（会社の記録" in line and "前に社長に聞いた日数" in line and "2028年2月22日（火）" in line
    assert "事業支援計画書（様式4）" in out and "締切：2026年12月4日（金）" in out
    code, out = run(folder, "--case", CASE_2, "--add", "見積書等", "--add", "事業支援計画書（様式4）")
    assert code == 1  # 様式4 の目安は分からない（社長も知らない）
    entry = {e["書類"]: e for e in ledger(folder) if e["案件"] == CASE_2}
    assert entry["見積書等"]["目安の日数"] == 7 and "会社の記録" in entry["見積書等"]["目安の出どころ"]
    assert entry["事業支援計画書（様式4）"]["目安の日数"] is None
    assert "聞き直していません" in out


def test_external_form_in_the_forms_is_still_a_request(folder) -> None:
    """制度データの「様式」に、外の機関が出す様式4 が入っていても、人に頼む書類として依頼の候補に出る
    （11/7 の通し：読み取り役が様式4 を「様式」に入れ、締切 12/4 が依頼の候補と期限の一覧から落ちた）。"""
    data = _json(REPO_ROOT / "evals" / "_lib" / "T6-6" / "持続化_第20回.json")
    seido = json.loads(data) if isinstance(data, str) else data
    seido.setdefault("様式", []).append({"名前": "事業支援計画書（様式4）", "入力先": {"値": {"種類": "ファイル"}}, "項目": []})
    add_case(folder, CASE_2, "持続化", "小規模事業者持続化補助金", "通常枠", "第20回", "第20回",
             seido if not isinstance(data, str) else json.dumps(seido, ensure_ascii=False))
    code, out = run(folder, "--case", CASE_2, "--requests")
    assert code == 0, out
    assert "事業支援計画書（様式4）" in out and "締切：2026年12月4日（金）" in out


def test_wrong_names_and_values_write_nothing(folder) -> None:
    code, out = run(folder, "--case", CASE_1, "--add", "よく分からない書類")
    assert code == 2 and "制度データの書類に「よく分からない書類」が見当たりません" in out and "金融機関確認書" in out
    code, out = run(folder, "--case", CASE_1, "--days", "金融機関確認書=2か月")
    assert code == 2 and "日数で渡してください" in out
    code, out = run(folder, "--case", CASE_1, "--status", "金融機関確認書=たぶん頼んだ")
    assert code == 2 and "状態" in out
    code, out = run(folder, "--case", CASE_1, "--received", "金融機関確認書=原本/ない.pdf")
    assert code == 2 and "会社のフォルダにありません" in out
    code, out = run(folder, "--case", CASE_1, "--who", "金融機関確認書=外部")
    assert code == 2
    assert ledger(folder) == [] and facts(folder) == {}
    plain = folder.parent / "会社でない"
    plain.mkdir()
    code, out = run(plain, "--show")
    assert code == 2 and "会社のフォルダではありません" in out and not (plain / "記録").exists()


def test_near_days_setting_is_written_by_the_tool(folder) -> None:
    """社長が「近い締切は60日にして」と言ったときに、道具が `.hojokin/設定.json` に残す（Edit は設定で拒まれるため）。"""
    code, out = run(folder, "--near-days", "60")
    assert code == 0 and "近い締切の日数を60日にしました（前は30日" in out
    assert _json(folder / ".hojokin" / "設定.json") == {"今日の日付": "2026-11-16", "近い締切の日数": 60}
    code, out = run(folder, "--show")
    assert "近い締切は60日以内" in out and "### 近い締切（60日以内）" in out
    code, out = run(folder, "--near-days", "0")
    assert code == 2 and _json(folder / ".hojokin" / "設定.json")["近い締切の日数"] == 60
