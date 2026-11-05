"""T5-7 フォルダの外を変えない（SPEC F5「会社のフォルダの外（デスクトップ、ダウンロードなど）には触れない」。TASKS B9）。

合格ライン：整理の前後で、会社のフォルダの外のファイルを比べて、変化0件。

- 散らばった書類11件（testdata/書類の変化/散らばった書類/。F14）を会社のフォルダのあちこちに入れ、開いたときの hook、
  見つける・移す・確かめ済みにする道具、社長が送ったとき・応答の終わりの hook を、Claude が動かすのと同じ形で動かす。
- 会社のフォルダの外には、デスクトップ・ダウンロードに見立てたフォルダ（中の書類と同じ中身の書類を含む）、HOME、
  プラグインの写し、一時ファイルの置き場、今いるフォルダを置き、整理の前後で名前・大きさ・更新時刻・中身を比べる。
- あわせて、道具が外の書類を見つけず、外の場所を渡されたら何も変えずに断ることも見る。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt

SCRIPT = Path("skills") / "shorui" / "scripts" / "seiri.py"
SCATTERED = hr.REPO_ROOT / "testdata" / "書類の変化" / "散らばった書類"
ANSWER = json.loads((hr.REPO_ROOT / "testdata" / "書類の変化" / "正解.json").read_text(encoding="utf-8"))
TODAY = "2026-11-05"
# 正解の「種類が分かる」8件を、Claude が読み取ったことにする区分・種類・日付・相手先
KNOWN = {
    "入れ口/scan0001.pdf": ("登記・名簿", "履歴事項全部証明書", "2026-10-22", ""),
    "入れ口/IMG_2087.jpg": ("決算・税", "納税証明書（その2）", "2026-10-23", ""),
    "決算書18.pdf": ("決算・税", "決算書", "2025-04-01", ""),
    "社長/見積もり（つばさ台）.pdf": ("見積・契約・請求", "見積書", "2026-10-20", "つばさ台フードシステム"),
    "新しいフォルダ/doc04512.pdf": ("写真・カタログ", "カタログ", "2026", "つばさ台フードシステム"),
    "事務/名簿.docx": ("登記・名簿", "役員名簿", "2026-11-01", ""),
    "入れ口/10月/Book2.xlsx": ("登記・名簿", "労働者名簿", "2026-11-01", ""),
    "社長/会議のメモ.docx": ("会社の資料", "議事録", "2026-09-10", ""),
}
UNKNOWN = ("入れ口/IMG_2091.jpg", "社長/Book1.xlsx")
SAME = "メール添付/見積書_つばさ台.pdf"


def run_tool(company: vt.Company, command: str, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": company.env.path, "HOME": str(company.env.home), "TMPDIR": str(company.env.tmp)}
    return subprocess.run(
        [hr.real_python(), "-B", str(company.env.plugin / SCRIPT), command, "--folder", str(company.folder), *args],
        env=env, cwd=company.env.cwd, capture_output=True, timeout=120,
    )


def ok_json(r: subprocess.CompletedProcess):
    return json.loads(ct.ok(r))


@pytest.fixture
def company(tmp_path) -> vt.Company:
    c = vt.Company(tmp_path, name="やまぶき惣菜")
    settings = c.folder / ".hojokin" / "設定.json"
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    data["今日の日付"] = TODAY
    settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for src in sorted(SCATTERED.rglob("*")):
        if src.is_file():
            c.write(src.relative_to(SCATTERED).as_posix(), src.read_bytes())
    return c


def outside_places(company: vt.Company, tmp_path: Path) -> list:
    """会社のフォルダの外に置くもの。デスクトップ・ダウンロードに見立てたフォルダに、中の書類と同じ中身の書類も置く。"""
    desktop = tmp_path / "デスクトップ"
    downloads = tmp_path / "ダウンロード"
    (desktop / "社長").mkdir(parents=True)
    downloads.mkdir()
    (desktop / "見積書_つばさ台.pdf").write_bytes((SCATTERED / SAME).read_bytes())
    (desktop / "社長" / "会議のメモ.docx").write_bytes((SCATTERED / "社長" / "会議のメモ.docx").read_bytes())
    (downloads / "決算書.pdf").write_bytes((SCATTERED / "決算書18.pdf").read_bytes())
    (company.env.home / "Desktop").mkdir()
    (company.env.home / "Desktop" / "付箋.txt").write_text("金曜まで", encoding="utf-8")
    return [desktop, downloads, company.env.plugin, company.env.home, company.env.tmp, company.env.cwd, company.plugin]


def test_organizing_changes_nothing_outside(company, tmp_path) -> None:
    dirs = outside_places(company, tmp_path)
    before = hr.snapshot(*dirs)

    # 開いたとき：11件とも、中の書類として見つかる（外の書類は出ない）
    opened = company.start()
    text = opened["hookSpecificOutput"]["additionalContext"]
    assert "前回から増えた・変わった書類" in text
    for rel in list(KNOWN) + list(UNKNOWN) + [SAME]:
        assert f"- {rel}（増えた）" in text, rel
    assert "デスクトップ" not in text and "ダウンロード" not in text

    company.say("書類をあちこちに入れたので、整理して")
    found = ok_json(run_tool(company, "scan"))
    places = [d["場所"] for d in found["新しい書類"]] + [d["場所"] for d in found["同じ中身"]]
    assert sorted(places) == sorted(list(KNOWN) + list(UNKNOWN) + [SAME])
    assert all(d["前回から"] == "増えた" for d in found["新しい書類"])
    for rel, (category, kind, day, partner) in KNOWN.items():
        args = ["--path", rel, "--category", category, "--kind", kind, "--date", day]
        if partner:
            args += ["--partner", partner]
        r = run_tool(company, "organize", *args)
        if rel == "社長/見積もり（つばさ台）.pdf" and r.returncode == 2:
            # 同じ中身の2つのうち、メール添付のほうを先に移した形（見つける順による）
            ok_json(run_tool(company, "organize", "--path", SAME, *args[2:]))
            continue
        ok_json(r)
    for rel in UNKNOWN:
        ok_json(run_tool(company, "keep", "--path", rel, "--reason", "社長がそのままでいいと答えた"))
    assert company.stop() is None

    # 外の場所を渡されても、何も変えずに断る
    for given in (tmp_path / "デスクトップ" / "見積書_つばさ台.pdf", tmp_path / "ダウンロード" / "決算書.pdf"):
        r = run_tool(company, "organize", "--path", str(given), "--category", "決算・税", "--kind", "決算書",
                     "--date", "2025-04-01")
        assert r.returncode == 2, r
        assert "会社のフォルダの外" in r.stdout.decode("utf-8")
        r = run_tool(company, "keep", "--path", str(given))
        assert r.returncode == 2, r

    after = hr.snapshot(*dirs)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert changed == [], changed

    # 中では、8件が原本の置き場に移り、分からない2件と同じ中身の1件は残っている
    ledger = json.loads((company.folder / "記録" / "書類の台帳.json").read_text(encoding="utf-8"))
    assert len(ledger["原本"]) == 8
    assert sorted(e["場所"] for e in ledger["確かめ済み"]) == sorted(UNKNOWN)
    for rel in UNKNOWN:
        assert (company.folder / rel).is_file()


def test_tool_files_at_the_root_are_not_documents(company) -> None:
    """根にあるツールが作るファイル（今の状態.html など）は、書類として見つけず、原本にもしない。"""
    for name in ("今の状態.html", "補助金の候補.docx", "財務モデル.xlsx"):
        company.write(name, b"x")
    found = ok_json(run_tool(company, "scan"))
    names = {d["場所"] for d in found["新しい書類"]} | {d["場所"] for d in found["同じ中身"]}
    assert not names & {"今の状態.html", "補助金の候補.docx", "財務モデル.xlsx"}
    r = run_tool(company, "organize", "--path", "補助金の候補.docx", "--category", "会社の資料", "--kind", "資料",
                 "--date", "2026")
    assert r.returncode == 2 and "ツールが作るファイル" in r.stdout.decode("utf-8")
