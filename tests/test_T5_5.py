"""T5-5 原本と写し（SPEC F5「案件で使う書類は、原本から写しを作り…」。TASKS B10）。

合格ライン：2つの案件で同じ決算書を使う。原本は1つのまま変わらない。案件ごとに写しができ、提出の決まりに合い、
元の原本が記録されている。

- 会社のフォルダは道具で用意し、2つの案件（省力化・持続化）の段階のフォルダと、案件の資料の一覧・制度データを置く。
  省力化は制度データの正解（testdata/正解/省力化_第8回.json。形式は「書類ごとに PDF・Excel・JPEG・PNG」、納税証明書は PDF）。
  持続化は、提出の形を「PDF」だけにした小さな制度データ（このテストのための架空の決まり）。
- 原本は、デモの会社の決算書（PDF）2期と、正しいセットの納税証明書の写真（JPEG）。道具（seiri.py・utsushi.py）は、
  Claude が Bash で動かすのと同じ形で動かす。
- あわせて、原本の差し替え（T5-6 の道具の部分）：取り直した納税証明書を入れると、古い原本から作った写しがある案件を
  知らせ、作り直す。古い原本は残る。
"""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt

SEIRI = Path("skills") / "shorui" / "scripts" / "seiri.py"
UTSUSHI = Path("skills") / "shorui" / "scripts" / "utsushi.py"
DOCS = hr.REPO_ROOT / "testdata" / "デモの会社" / "書類"
PHOTO = hr.REPO_ROOT / "testdata" / "書類セット" / "正しいセット" / "納税証明書_その2.jpg"
NEW_TAX = hr.REPO_ROOT / "testdata" / "書類の変化" / "取り直した納税証明書" / "納税証明書_その2_11月.pdf"
SHORYOKUKA = "2026_省力化（一般型）第9回"
JIZOKUKA = "2026_持続化（通常枠）第20回"
STAGE = "1_申請"
TODAY = "2026-11-20"


def run(company: vt.Company, script: Path, command: str, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": company.env.path, "HOME": str(company.env.home), "TMPDIR": str(company.env.tmp)}
    return subprocess.run(
        [hr.real_python(), "-B", str(company.env.plugin / script), command, "--folder", str(company.folder), *args],
        env=env, cwd=company.env.cwd, capture_output=True, timeout=300,
    )


def ok_json(r: subprocess.CompletedProcess):
    return json.loads(ct.ok(r))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put_case(company: vt.Company, case: str, seido: dict, short: str) -> None:
    """案件の段階のフォルダ、資料の一覧、制度データを置く（junbi の道具が作る形）。"""
    (company.folder / "案件" / case / STAGE / "添付する書類").mkdir(parents=True)
    listed = {"制度": dict(seido["制度"], 略称=short), "資料": []}
    company.write(f"記録/資料の本文/{case}/資料の一覧.json", json.dumps(listed, ensure_ascii=False))
    company.write(f"記録/制度データ/{short}_{seido['制度']['公募回']}.json", json.dumps(seido, ensure_ascii=False))


@pytest.fixture
def company(tmp_path) -> vt.Company:
    c = vt.Company(tmp_path, name="やまぶき惣菜")
    settings = c.folder / ".hojokin" / "設定.json"
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    data["今日の日付"] = TODAY
    settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    put_case(c, SHORYOKUKA, json.loads((hr.REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json").read_text(encoding="utf-8")),
             "省力化")
    jizokuka = {"制度": {"名前": "小規模事業者持続化補助金", "枠": "通常枠", "種類": "補助金", "公募回": "第20回"},
                "提出するファイルの決まり": {"形式": {"値": "PDF", "状態": "確認済み"}},
                "書類": [{"名前": "決算書", "形式": "PDF"}, {"名前": "納税証明書（その2）", "形式": "PDF"}]}
    put_case(c, JIZOKUKA, jizokuka, "持続化")
    c.write("入れ口/決算書18.pdf", (DOCS / "決算書_第18期.pdf").read_bytes())
    c.write("入れ口/決算書17.pdf", (DOCS / "決算書_第17期.pdf").read_bytes())
    c.write("入れ口/IMG_0001.jpg", PHOTO.read_bytes())
    for rel, kind, day in (("入れ口/決算書18.pdf", "決算書", "2025-04-01"), ("入れ口/決算書17.pdf", "決算書", "2024-04-01"),
                           ("入れ口/IMG_0001.jpg", "納税証明書（その2）", "2026-10-23")):
        ok_json(run(c, SEIRI, "organize", "--path", rel, "--category", "決算・税", "--kind", kind, "--date", day))
    return c


KESSAN18 = "原本/決算・税/2025-04-01_決算書.pdf"
KESSAN17 = "原本/決算・税/2024-04-01_決算書.pdf"
TAX = "原本/決算・税/2026-10-23_納税証明書（その2）.jpg"


def ledger(company: vt.Company) -> dict:
    return json.loads((company.folder / "記録" / "書類の台帳.json").read_text(encoding="utf-8"))


def pdf_pages(data: bytes) -> int:
    from lib import doc_text  # noqa: F401  同梱の pypdf
    import io

    from pypdf import PdfReader
    return len(PdfReader(io.BytesIO(data)).pages)


def test_one_original_two_cases(company) -> None:
    original = company.folder / KESSAN18
    before = original.read_bytes()

    a = ok_json(run(company, UTSUSHI, "make", "--original", KESSAN18, "--case", SHORYOKUKA, "--stage", STAGE,
                    "--document", "損益計算書（直近2期分）"))["写し"]
    b = ok_json(run(company, UTSUSHI, "make", "--original", KESSAN17, "--original", KESSAN18, "--case", JIZOKUKA,
                    "--stage", STAGE, "--document", "決算書", "--name", "決算書_第17期_第18期"))["写し"]

    # 原本は1つのまま、1バイトも変わらず、読み取り専用のまま
    assert original.read_bytes() == before
    assert stat.S_IMODE(original.stat().st_mode) == 0o444
    assert [e["場所"] for e in ledger(company)["原本"]].count(KESSAN18) == 1
    assert sorted(p.name for p in (company.folder / "原本" / "決算・税").iterdir()) == sorted(
        [Path(KESSAN18).name, Path(KESSAN17).name, Path(TAX).name])

    # 案件ごとに、段階の「添付する書類」に写しができる
    assert a["場所"] == f"案件/{SHORYOKUKA}/{STAGE}/添付する書類/2025-04-01_決算書.pdf"
    assert b["場所"] == f"案件/{JIZOKUKA}/{STAGE}/添付する書類/決算書_第17期_第18期.pdf"
    copy_a = (company.folder / a["場所"]).read_bytes()
    copy_b = (company.folder / b["場所"]).read_bytes()
    # 提出の決まりに合う：省力化の損益計算書は PDF（原本が PDF なので、そのまま写す）。持続化は PDF で、2期を1つにつなぐ
    assert copy_a == before and a["整え方"] == ["原本の形のまま写した"]
    assert copy_b.startswith(b"%PDF") and pdf_pages(copy_b) == pdf_pages(before) + pdf_pages((company.folder / KESSAN17).read_bytes())
    assert "2つの原本を1つの PDF にした" in b["整え方"]

    # 元の原本が記録されている
    entries = {e["場所"]: e for e in ledger(company)["写し"]}
    assert entries[a["場所"]]["元の原本"] == [{"id": "原本-0001", "場所": KESSAN18, "ハッシュ": sha256(before), "日付": "2025-04-01"}]
    assert [s["場所"] for s in entries[b["場所"]]["元の原本"]] == [KESSAN17, KESSAN18]
    assert entries[a["場所"]]["案件"] == SHORYOKUKA and entries[b["場所"]]["案件"] == JIZOKUKA
    assert entries[a["場所"]]["ハッシュ"] == sha256(copy_a) and entries[b["場所"]]["ハッシュ"] == sha256(copy_b)


def test_photo_becomes_pdf_when_the_rule_wants_pdf(company) -> None:
    photo = company.folder / TAX
    before = photo.read_bytes()
    out = ok_json(run(company, UTSUSHI, "make", "--original", TAX, "--case", SHORYOKUKA, "--stage", STAGE,
                      "--document", "納税証明書（その2）"))["写し"]
    assert out["場所"].endswith("/2026-10-23_納税証明書（その2）.pdf")
    data = (company.folder / out["場所"]).read_bytes()
    assert data.startswith(b"%PDF") and pdf_pages(data) == 1
    assert before in data  # 写真の中身はそのまま PDF に包んでいる（画像を変えない）
    assert photo.read_bytes() == before
    assert out["書類"] == "納税証明書（その2）"


def test_new_original_remakes_old_copies(company) -> None:
    """原本の差し替え（T5-6 の道具の部分）。影響する案件を知らせ、写しを作り直す。古い原本は残る。"""
    for case in (SHORYOKUKA, JIZOKUKA):
        ok_json(run(company, UTSUSHI, "make", "--original", TAX, "--case", case, "--stage", STAGE,
                    "--document", "納税証明書（その2）"))
    old_copy = (company.folder / f"案件/{SHORYOKUKA}/{STAGE}/添付する書類/2026-10-23_納税証明書（その2）.pdf").read_bytes()
    assert ok_json(run(company, UTSUSHI, "stale"))["数"] == 0

    company.write("入れ口/納税証明書_その2_11月.pdf", NEW_TAX.read_bytes())
    out = ok_json(run(company, SEIRI, "organize", "--path", "入れ口/納税証明書_その2_11月.pdf", "--category", "決算・税",
                      "--kind", "納税証明書（その2）", "--date", "2026-11-16"))
    new_place = "原本/決算・税/2026-11-16_納税証明書（その2）.pdf"
    assert out["新しい場所"] == new_place
    stale = out["新しくなった原本"]["作り直す写し"]
    assert sorted(s["案件"] for s in stale) == sorted([SHORYOKUKA, JIZOKUKA])
    assert all(s["古い原本"] == TAX and s["新しい原本"] == new_place for s in stale)

    for s in stale:
        remade = ok_json(run(company, UTSUSHI, "remake", "--copy", s["写し"]))["写し"]
        assert remade["場所"] == s["写し"]  # 同じ場所・同じ名前で作り直す
        assert remade["元の原本"][0]["場所"] == new_place
        assert remade["作り直した原本"] == [f"{TAX} → {new_place}"]
        assert (company.folder / s["写し"]).read_bytes() == NEW_TAX.read_bytes()
    assert old_copy != NEW_TAX.read_bytes()
    assert ok_json(run(company, UTSUSHI, "stale"))["数"] == 0
    # 古い原本は消さない
    assert (company.folder / TAX).read_bytes() == PHOTO.read_bytes()
    assert TAX in [e["場所"] for e in ledger(company)["原本"]]
    # 写しは2つのまま（増やさない）
    assert len(ledger(company)["写し"]) == 2


def test_refuses_without_changing_anything(company) -> None:
    before = {p: p.read_bytes() for p in company.folder.rglob("*") if p.is_file() and ".git" not in p.parts}
    for args in (["--original", "入れ口/ない.pdf", "--case", SHORYOKUKA, "--stage", STAGE],
                 ["--original", KESSAN18, "--case", "ない案件", "--stage", STAGE],
                 ["--original", KESSAN18, "--case", SHORYOKUKA, "--stage", "9_ない段階"]):
        r = run(company, UTSUSHI, "make", *args)
        assert r.returncode == 2, r
        assert r.stderr == b"", r.stderr.decode("utf-8")
    after = {p: p.read_bytes() for p in company.folder.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert after == before
