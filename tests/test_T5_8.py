"""T5-8 スキャンした書類の金額（SPEC F5、DESIGN 8.4。TASKS B11）。

合格ライン：スキャンした PDF と写真の見積書・請求書・納品書（F14）を読ませ、読み取った金額と明細を正解と突き合わせる。
一致率100%（仮）。照合で合わないまま残った読み取りは、推測せず社長に確かめている。

このファイルは2つを見る。
1. 照合の道具（lib/kingaku.py・skills/shorui/scripts/kingaku.py）：正解（testdata/スキャン/正解.json）の5通が照合を通り、
   1か所でも数を変えると外れ、読めない欄（null）は計算で埋めずに「要確認」にすること。社長が答えた値で照合し直せること。
   向きを直す・帯を切り出す画像の道具（lib/page_image.py）も見る。
2. 振る舞い（eval の T5-8）で残した出力の突き合わせ：環境変数 HOJOKIN_T5_8_KEPT に、eval が残した会社のフォルダ
   （`--keep-temp` の sealed/home/cwd を写したもの）を渡すと、`記録/金額の読み取り.json` を正解と突き合わせる。
   渡さなければ飛ばす。明細ごとの数量・単価・金額・税率と、小計・消費税・合計・税率ごとの対象額と消費税を見る。
   隠れた箇所（請求書の写真の「白だし」の単価）は、値の一致ではなく、null のまま「要確認」で残っているか
   （社長が答えたなら、出典が社長の答えか）で見る。
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt
from lib import kingaku

SEIRI = Path("skills") / "shorui" / "scripts" / "seiri.py"
KINGAKU = Path("skills") / "shorui" / "scripts" / "kingaku.py"
SCAN = hr.REPO_ROOT / "testdata" / "スキャン"
ANSWER = json.loads((SCAN / "正解.json").read_text(encoding="utf-8"))
DOCS = {d["番号"]: d for d in ANSWER["書類"]}
HIDDEN = ("MT-2610-0418", 7, "単価")  # 請求書の写真の、しみで隠れた欄（明細7 白だし 1.8L の単価）
NUMBERS = ("数量", "単価", "金額", "税率")


def reading_of(doc: dict) -> dict:
    """正解の1通を、読み取り役の返す形にする。"""
    keys = ("種類", "番号", "発行日", "有効期限", "納品日", "請求日", "支払期限", "宛名", "発行者", "登録番号", "件名",
            "税込か税抜か", "明細", "税率ごと", "小計", "消費税", "合計", "端数の処理")
    return {k: copy.deepcopy(doc.get(k)) for k in keys}


# ---- 1. 照合の道具 ----


@pytest.mark.parametrize("number", sorted(DOCS))
def test_answers_pass_the_check(number) -> None:
    result = kingaku.check(reading_of(DOCS[number]))
    assert result == {"外れ": [], "読めない": []}, result


@pytest.mark.parametrize("number", sorted(DOCS))
def test_any_changed_number_is_caught(number) -> None:
    doc = DOCS[number]
    for i, row in enumerate(doc["明細"], 1):
        for key in ("数量", "単価", "金額"):
            wrong = reading_of(doc)
            wrong["明細"][i - 1][key] = row[key] + (1 if key == "数量" else 100)
            assert kingaku.check(wrong)["外れ"], (number, i, key)
    for key in ("小計", "消費税", "合計"):
        wrong = reading_of(doc)
        wrong[key] = doc[key] + 10
        assert kingaku.check(wrong)["外れ"], (number, key)
    wrong = reading_of(doc)
    wrong["明細"][0]["税率"] = 5
    assert kingaku.check(wrong)["外れ"]


def test_unreadable_cell_is_not_filled_by_calculation() -> None:
    number, row, key = HIDDEN
    reading = reading_of(DOCS[number])
    reading["明細"][row - 1][key] = None
    result = kingaku.check(reading)
    assert result["外れ"] == []
    assert [u["欄"] for u in result["読めない"]] == [f"明細{row}.{key}"]


def test_rounding_of_tax_follows_the_document() -> None:
    reading = reading_of(DOCS["N-261015-03"])  # 8% の消費税に端数が出る（切り捨て）
    reading["税率ごと"][1]["消費税"] += 1  # 切り上げの値（合わせて、消費税と合計も1円多い書類にする）
    reading["消費税"] += 1
    reading["合計"] += 1
    assert kingaku.check(reading)["外れ"]
    reading["端数の処理"] = None  # 書いていなければ、切り捨て・四捨五入・切り上げのどれかで合えばよい
    assert kingaku.check(reading)["外れ"] == []


# ---- 道具を Claude と同じ形で動かす ----


def run(company: vt.Company, script: Path, command: str, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": company.env.path, "HOME": str(company.env.home), "TMPDIR": str(company.env.tmp)}
    return subprocess.run(
        [hr.real_python(), "-B", str(company.env.plugin / script), command, "--folder", str(company.folder), *args],
        env=env, cwd=company.env.cwd, capture_output=True, timeout=120,
    )


def ok_json(r: subprocess.CompletedProcess):
    return json.loads(ct.ok(r))


ORGANIZE = {
    "scan_20261104_0001.pdf": ("見積書", "2026-10-20", "つばさ台フードシステム", "TFS-2610-0153"),
    "scan_20261104_0003.pdf": ("納品書", "2026-10-15", "みつばね食品資材", "N-261015-03"),
    "IMG_2742.jpg": ("請求書", "2026-10-31", "みつばね食品資材", "MT-2610-0418"),
}


@pytest.fixture
def company(tmp_path) -> vt.Company:
    c = vt.Company(tmp_path, name="やまぶき惣菜")
    for name, (kind, day, partner, _number) in ORGANIZE.items():
        c.write(f"入れ口/{name}", (SCAN / "材料" / name).read_bytes())
        ok_json(run(c, SEIRI, "organize", "--path", f"入れ口/{name}", "--category", "見積・契約・請求", "--kind", kind,
                    "--date", day, "--partner", partner))
    return c


def place(name: str) -> str:
    kind, day, partner, _ = ORGANIZE[name]
    return f"原本/見積・契約・請求/{day}_{kind}_{partner}{Path(name).suffix}"


def test_check_records_and_owner_confirms(company) -> None:
    good = reading_of(DOCS["TFS-2610-0153"])
    company.write("記録/一時/読み取り.json", json.dumps(good, ensure_ascii=False))
    out = ok_json(run(company, KINGAKU, "check", "--path", place("scan_20261104_0001.pdf"), "--input",
                      "記録/一時/読み取り.json", "--model", "sonnet"))
    assert out["状態"] == "照合済み" and out["合計"] == 24750000

    number, row, key = HIDDEN
    hidden = reading_of(DOCS[number])
    hidden["明細"][row - 1][key] = None
    company.write("記録/一時/読み取り.json", json.dumps(hidden, ensure_ascii=False))
    out = ok_json(run(company, KINGAKU, "check", "--path", place("IMG_2742.jpg"), "--input", "記録/一時/読み取り.json",
                      "--model", "sonnet"))
    assert out["状態"] == "要確認" and out["読めない"][0]["欄"] == f"明細{row}.{key}"

    # 1回目で外れたら「読み直す」、2回目でも外れたら「要確認」
    wrong = reading_of(DOCS["N-261015-03"])
    wrong["明細"][1]["単価"] = 2830
    company.write("記録/一時/読み取り.json", json.dumps(wrong, ensure_ascii=False))
    out = ok_json(run(company, KINGAKU, "check", "--path", place("scan_20261104_0003.pdf"), "--input",
                      "記録/一時/読み取り.json", "--model", "sonnet"))
    assert out["状態"] == "読み直す"
    out = ok_json(run(company, KINGAKU, "check", "--path", place("scan_20261104_0003.pdf"), "--input",
                      "記録/一時/読み取り.json", "--model", "opus", "--round", "2"))
    assert out["状態"] == "要確認" and out["読んだモデル"] == ["sonnet", "opus"]

    # 社長が答えた値で照合し直す
    out = ok_json(run(company, KINGAKU, "confirm", "--path", place("IMG_2742.jpg"), "--field", f"明細{row}.{key}",
                      "--value", "1380"))
    assert out["状態"] == "照合済み"
    data = json.loads((company.folder / "記録" / "金額の読み取り.json").read_text(encoding="utf-8"))
    entry = next(d for d in data["書類"] if d["原本"] == place("IMG_2742.jpg"))
    assert entry["社長の答え"][0]["欄"] == f"明細{row}.{key}" and entry["社長の答え"][0]["値"] == "1380"
    # 照合済みの明細だけを経費に使える
    assert len(kingaku.verified_rows(company.folder, place("scan_20261104_0001.pdf"))) == 7
    with pytest.raises(kingaku.KingakuError):
        kingaku.verified_rows(company.folder, place("scan_20261104_0003.pdf"))


def test_refuses_input_outside_and_non_originals(company, tmp_path) -> None:
    outside = tmp_path / "読み取り.json"
    outside.write_text("{}", encoding="utf-8")
    r = run(company, KINGAKU, "check", "--path", place("scan_20261104_0001.pdf"), "--input", str(outside))
    assert r.returncode == 2 and "外" in r.stdout.decode("utf-8")
    company.write("記録/一時/読み取り.json", "{}")
    r = run(company, KINGAKU, "check", "--path", "入れ口/ない.pdf", "--input", "記録/一時/読み取り.json")
    assert r.returncode == 2 and "原本ではありません" in r.stdout.decode("utf-8")


def _pdf_page(path: Path):
    from lib import doc_text  # noqa: F401  同梱の pypdf
    from pypdf import PdfReader
    return PdfReader(str(path)).pages[0]


def test_page_images_rotate_and_band(company) -> None:
    # そのままなら、スキャンの PDF に埋め込まれた JPEG を、画素を変えずに取り出す
    out = ok_json(run(company, KINGAKU, "image", "--path", place("scan_20261104_0003.pdf")))
    image = company.folder / out["画像"][0]["画像"]
    assert image.suffix == ".jpg" and image.read_bytes()[:2] == b"\xff\xd8"
    # 向きを直すときは、1ページの PDF にしてページを回す（sips を使わない。eval の中でも動く）
    out = ok_json(run(company, KINGAKU, "image", "--path", place("scan_20261104_0003.pdf"), "--rotate", "180"))
    rotated = company.folder / out["画像"][0]["画像"]
    assert rotated.suffix == ".pdf" and "180度まわした" in out["画像"][0]["直したこと"]
    assert _pdf_page(rotated).rotation == 180
    # 帯を切り出すときは、ページの枠を帯に狭めて大きくする（写真は JPEG を PDF に包む）
    out = ok_json(run(company, KINGAKU, "image", "--path", place("IMG_2742.jpg"), "--band", "0.5,0.75"))
    band = _pdf_page(company.folder / out["画像"][0]["画像"])
    width, height = float(band.mediabox.width), float(band.mediabox.height)
    assert height < width  # 縦長の写真から、横長の帯になる
    assert "帯を切り出し" in out["画像"][0]["直したこと"][0]
    # 文字のある PDF は画像にせず、文字で読むよう案内する
    company.write("入れ口/見積.pdf", (hr.REPO_ROOT / "testdata" / "デモの会社" / "書類" / "見積書_ほしみ機工.pdf").read_bytes())
    ok_json(run(company, SEIRI, "organize", "--path", "入れ口/見積.pdf", "--category", "見積・契約・請求", "--kind", "見積書",
                "--date", "2026-10-20", "--partner", "ほしみ機工"))
    r = run(company, KINGAKU, "image", "--path", "原本/見積・契約・請求/2026-10-20_見積書_ほしみ機工.pdf")
    assert r.returncode == 2 and "text" in r.stdout.decode("utf-8")


# ---- 2. eval で残した出力の突き合わせ ----


KEPT = os.environ.get("HOJOKIN_T5_8_KEPT")


@pytest.mark.skipif(not KEPT, reason="eval の T5-8 で残した会社のフォルダを HOJOKIN_T5_8_KEPT に渡すと流れる")
def test_kept_readings_match_the_answer() -> None:
    data = json.loads((Path(KEPT) / "記録" / "金額の読み取り.json").read_text(encoding="utf-8"))
    by_number = {d["読み取り"].get("番号"): d for d in data["書類"]}
    assert sorted(by_number) == sorted(DOCS), sorted(by_number)
    checked = matched = 0
    misses = []
    for number, doc in DOCS.items():
        got = by_number[number]
        reading = got["読み取り"]
        assert len(reading["明細"]) == len(doc["明細"]), number
        for i, (want, have) in enumerate(zip(doc["明細"], reading["明細"]), 1):
            for key in NUMBERS:
                if (number, i, key) == HIDDEN:
                    continue
                checked += 1
                if kingaku._num(have.get(key)) == float(want[key]):
                    matched += 1
                else:
                    misses.append((number, i, key, have.get(key), want[key]))
        for key in ("小計", "消費税", "合計"):
            checked += 1
            if kingaku._num(reading.get(key)) == float(doc[key]):
                matched += 1
            else:
                misses.append((number, key, reading.get(key), doc[key]))
        if doc.get("税率ごと") and len(doc["税率ごと"]) > 1:
            want = {(t["税率"], t["対象額"], t["消費税"]) for t in doc["税率ごと"]}
            have = {(kingaku._num(t.get("税率")), kingaku._num(t.get("対象額")), kingaku._num(t.get("消費税")))
                    for t in reading.get("税率ごと") or []}
            checked += 1
            if {tuple(float(x) for x in w) for w in want} == have:
                matched += 1
            else:
                misses.append((number, "税率ごと", have, want))
    print(f"一致 {matched}/{checked}（{matched / checked:.1%}）")
    assert misses == [], misses

    # 隠れた箇所：推測で埋めず、要確認のまま残っている（社長が答えたなら、その出典がある）
    number, row, key = HIDDEN
    entry = by_number[number]
    value = entry["読み取り"]["明細"][row - 1].get(key)
    answered = [a for a in entry.get("社長の答え") or [] if a.get("欄") == f"明細{row}.{key}"]
    if answered:
        assert entry["状態"] == "照合済み"
    else:
        assert value is None, value
        assert entry["状態"] == "要確認"
    # ほかの4通は照合済み
    assert all(by_number[n]["状態"] == "照合済み" for n in DOCS if n != number)
