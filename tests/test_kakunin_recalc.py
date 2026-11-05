"""審査役に渡す前に、Excel の様式（その3）の数式の値を計算し直す（TASKS B19 の直し。SPEC F8・F9、T8-8、
DESIGN 5章「Word・Excel の様式と申請書類の書式を壊さない」・8章「審査役に渡すもの」）。

- 書く道具（yoshiki.py cells）がセルを書いた後も、その3 の数式のセル（省力化指数・投資回収期間など）には、
  ファイルに前の計算の値（0 や空）が残る。prepare は、LibreOffice で計算し直した写し
  （`.hojokin/一時/計算し直した写し/`）から数式のセルの値を取り、様式の数の書式（小数の桁など）で計画書の本文に書く。
- 様式のファイルそのものは変えない（LibreOffice で保存し直すと、様式の部品が変わるため）。
- LibreOffice が動かないときは、前の値のまま渡し、計画書の本文に「数式の値は計算し直せなかった」と一言書く（止めない）。
- LibreOffice のテストと、保存した状態「書いた後」を戻すテストは時間がかかるので slow にする。
"""

from __future__ import annotations

import io
import json
import subprocess
import zipfile
from pathlib import Path

import kakunin_tool as kt
import pytest
from conftest import DOWNLOADS, REPO_ROOT
from zaimu_tool import soffice_or_skip

from lib import kakunin as kk

SONO3 = f"{kt.APP_DIR}/その3.xlsx"
COPY = f"{kk.RECALC_DIR}/その3.xlsx"
TRIAL_FORM = f"{kt.APP_DIR}/試しの様式.xlsx"
MAIN_SHEET = "【指定様式】事業計画書（その3）"
BESSHI1 = "（別紙１）省力化計算シート"
BESSHI3 = "（別紙３）投資回収期間計算シート"
FUKUGEN_SH = REPO_ROOT / "evals" / "_lib" / "fukugen.sh"


# ---------------------------------------------------------------- 数の書式


@pytest.mark.parametrize("value, code, shown", [
    (0.631578947368421, "0.00_ ", "0.63"),  # その3 の省力化指数（B8）
    (1.5949302483838, "#,##0.00_ ", "1.59"),  # その3 の投資回収期間（B39）
    (38, "0.0_ ", "38.0"),  # 別紙1 の時間
    (2773333.33, '"¥"#,##0_);[Red]\\("¥"#,##0\\)', "¥2,773,333"),
    (-1500, '"¥"#,##0_);\\("¥"#,##0\\)', "(¥1,500)"),
    (3293851.2, "[$¥-411]#,##0_);[Red]\\([$¥-411]#,##0\\)", "¥3,293,851"),
    (0.0404, "0.000%", "4.040%"),
    (5.82, "0.00", "5.82"),
    (15, '0"人"', "15人"),
    (46082, 'yyyy"年"m"月""期"', "2026年3月期"),
    (201600000, "General", "201600000"),
    (0.0404, "General", "0.0404"),
    (2.005, "0.00", "2.01"),  # 四捨五入（Excel と同じく、0.5 は大きい方へ）
    (0, "0.00_ ", "0.00"),
])
def test_numbers_are_shown_in_the_form_format(value, code, shown) -> None:
    assert kk.format_number(float(value), code) == shown


def test_text_and_errors_are_shown_as_they_are() -> None:
    assert kk.shown_value("#VALUE!", "e", "0.00") == "#VALUE!"
    assert kk.shown_value("未選択", "str", "0.00") == "未選択"
    assert kk.shown_value("", "", "0.00") == ""
    assert kk.shown_value("1", "b", "General") == "TRUE"


# ---------------------------------------------------------------- 小さな様式（数式が1つ）


def trial_form() -> bytes:
    """数式のセル（B2 ＝ A2 × 2。書式は 0.00）に、前の計算の値 0 が残った小さな Excel。"""
    s_ns = kt.S_NS
    sheet = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{s_ns}"><sheetData>'
             '<row r="1"><c r="A1" t="inlineStr"><is><t>元の数</t></is></c>'
             '<c r="B1" t="inlineStr"><is><t>2倍</t></is></c></row>'
             '<row r="2"><c r="A2"><v>3</v></c><c r="B2" s="1"><f>A2*2</f><v>0</v></c></row>'
             "</sheetData></worksheet>")
    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="{s_ns}">'
              '<numFmts count="1"><numFmt numFmtId="182" formatCode="0.00_ "/></numFmts>'
              '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
              '<borders count="1"><border/></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="182" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
              "</styleSheet>")
    main = "application/vnd.openxmlformats-officedocument.spreadsheetml"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{main}.sheet.main+xml"/>'
            f'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="{main}.worksheet+xml"/>'
            f'<Override PartName="/xl/styles.xml" ContentType="{main}.styles+xml"/></Types>'),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>'),
        "xl/workbook.xml": (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{s_ns}" '
                            f'xmlns:r="{rel}"><sheets><sheet name="試し" sheetId="1" r:id="rId1"/></sheets>'
                            '<calcPr calcId="191028"/></workbook>'),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{rel}/styles" Target="styles.xml"/></Relationships>'),
        "xl/worksheets/sheet1.xml": sheet,
        "xl/styles.xml": styles,
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in parts.items():
            zf.writestr(name, text.encode("utf-8"))
    return out.getvalue()


@pytest.fixture
def env(tmp_path: Path) -> kt.Env:
    env = kt.Env(tmp_path)
    env.trial_application(kt.GOOD_BODIES, sheet_values=kt.GOOD_SHEET, model=[("単価_冷凍惣菜", "")])
    env.evidence(kt.GOOD_EVIDENCE)
    env.put(TRIAL_FORM, trial_form())
    return env


def _trial_section(plan: str) -> str:
    return plan.split(f"## {TRIAL_FORM}", 1)[1].split("\n## ", 1)[0]


def test_without_libreoffice_old_values_are_given_with_a_note(env: kt.Env, tmp_path: Path) -> None:
    """LibreOffice が動かないときは止めずに、前の値のまま渡し、計画書の本文に一言書く。"""
    before = (env.folder / TRIAL_FORM).read_bytes()
    seido, _rel = kk.find_seido(env.folder, None)
    done = kk.prepare(env.folder, kt.CASE, kt.STAGE, seido, REPO_ROOT, soffice=str(tmp_path / "LibreOffice はない"))
    assert done["数式の計算し直し"][TRIAL_FORM]["計算し直した"] is False
    plan = (env.folder / kt.PACKAGE / kk.PLAN_FILE).read_text(encoding="utf-8")
    section = _trial_section(plan)
    assert kk.RECALC_FAILED in section
    assert "- 3 | 0\n" in section  # 前の計算の値のまま
    assert (env.folder / TRIAL_FORM).read_bytes() == before
    assert not (env.folder / kk.RECALC_DIR / "試しの様式.xlsx").exists()
    assert env.note()["確かめの番号"] == done["確かめの番号"]


def test_forms_without_formulas_are_not_recalculated(env: kt.Env) -> None:
    """数式のない Excel（入力シート・根拠対照表・財務モデル）は、計算し直さない。"""
    (env.folder / TRIAL_FORM).unlink()
    files = kk.application_files(env.folder, kt.CASE, kt.STAGE)
    assert kk.recalc_forms(env.folder, files, soffice="/ない") == {}


@pytest.mark.slow
def test_prepare_gives_recalculated_values(env: kt.Env) -> None:
    """LibreOffice で計算し直した写しから、数式のセルの値を様式の書式で渡す。様式のファイルは変えない。"""
    soffice_or_skip()
    before = (env.folder / TRIAL_FORM).read_bytes()
    text = kt.ok(env.tool("prepare"))
    assert "計算し直した写し" in text
    plan = (env.folder / kt.PACKAGE / kk.PLAN_FILE).read_text(encoding="utf-8")
    section = _trial_section(plan)
    assert "- 3 | 6.00\n" in section
    assert kk.RECALC_FAILED not in section and "計算し直した写しから取り" in section
    assert (env.folder / TRIAL_FORM).read_bytes() == before
    assert (env.folder / kk.RECALC_DIR / "試しの様式.xlsx").is_file()
    assert not (env.folder / kk.RECALC_DIR / kk.RECALC_WORK).exists()  # 作業の場所は片付ける
    # もう一度まとめると、写しを上書きする（版の履歴に入らない .hojokin/一時/ の下）
    kt.ok(env.tool("prepare"))
    assert sorted(p.name for p in (env.folder / kk.RECALC_DIR).iterdir()) == ["試しの様式.xlsx"]


# ---------------------------------------------------------------- 保存した状態「書いた後」の その3


# 別紙1（導入前と導入後の工程と分）と別紙3（投資総額・年間稼働日数・人件費単価・増加した付加価値額）の入力の欄。
# 架空のデモの会社の値（回答表 L-01・L-03 と同じ）。導入前 38時間、導入後 14時間、削減 24時間
BEFORE_STEPS = [("盛り付け", 1080), ("計量", 420), ("包装", 300), ("ラベル貼り", 240), ("検品", 240)]
AFTER_STEPS = [("ロボットへの惣菜の補給と見守り", 360), ("計量機への材料の補給", 120), ("包装機の段取り", 120),
               ("ラベラーの段取り", 60), ("外れたパックの確かめ", 180)]
INVEST, DAYS, WAGE, ADDED = 22500000, 300, 1330, 4531200


def _besshi_values() -> list:
    values = []
    for row, (name, minutes) in enumerate(BEFORE_STEPS, 11):
        values += [{"シート": BESSHI1, "セル": f"C{row}", "値": name}, {"シート": BESSHI1, "セル": f"D{row}", "値": minutes}]
    for row, (name, minutes) in enumerate(AFTER_STEPS, 11):
        values += [{"シート": BESSHI1, "セル": f"I{row}", "値": name}, {"シート": BESSHI1, "セル": f"J{row}", "値": minutes},
                   {"シート": BESSHI1, "セル": f"K{row}", "値": "新たに追加される作業"}]
    values += [{"シート": BESSHI3, "セル": "C6", "値": INVEST}, {"シート": BESSHI3, "セル": "H6", "値": DAYS},
               {"シート": BESSHI3, "セル": "J6", "値": WAGE}, {"シート": BESSHI3, "セル": "L6", "値": ADDED}]
    return values


def _evidence_rows(values: list) -> list:
    """数を書いたセルの根拠対照表の行（財務モデルに省力化の計算がない「書いた後」でも、コードの確かめを通すため）。"""
    return [{"記述": str(v["値"]), "種類": "数字", "書いた場所": f"その3.xlsx／{v['シート']}!{v['セル']}",
             "出典": "回答表 L-01・L-03（架空の聞き取り）"} for v in values if isinstance(v["値"], int)]


def _run(script: str, folder: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["/usr/bin/python3", "-B", str(REPO_ROOT / "skills" / "kaku" / "scripts" / script), *args,
                           "--folder", str(folder)], capture_output=True, text=True, encoding="utf-8", timeout=600)


def _after(lines: list, head: str) -> str:
    """計画書の本文の、見出しの行の次の行（「- 」を除く）。"""
    n = lines.index(f"- {head}")
    return lines[n + 1][2:]


@pytest.mark.slow
def test_written_sono3_gives_the_saving_index_and_payback(tmp_path: Path) -> None:
    """「書いた後」の その3 に別紙1・別紙3 を書いて prepare すると、審査役に渡す省力化指数が 0 でなく 0.63、
    投資回収期間が空でなく 1.59 になる（財務モデルの省力化の計算と同じ）。様式のファイルは変えない。"""
    soffice_or_skip()
    if not DOWNLOADS.is_dir():
        pytest.skip("downloads/ がありません（公式資料を取ってから流す）")
    folder = tmp_path / "会社"
    folder.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "ja_JP.UTF-8"}
    done = subprocess.run(["bash", str(FUKUGEN_SH), "書いた後", str(folder)], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=300)
    assert done.returncode == 0 and "fukugen: ok" in done.stdout, done.stdout + done.stderr
    temp = folder / "記録" / "一時"
    temp.mkdir(parents=True, exist_ok=True)
    values = _besshi_values()
    (temp / "その3の値.json").write_text(json.dumps({"値": values}, ensure_ascii=False), encoding="utf-8")
    r = _run("yoshiki.py", folder, "cells", "--input", "記録/一時/その3の値.json")
    assert r.returncode == 0, r.stdout + r.stderr
    (temp / "根拠.json").write_text(json.dumps({"行": _evidence_rows(values)}, ensure_ascii=False), encoding="utf-8")
    r = _run("kakunin.py", folder, "konkyo", "--input", "記録/一時/根拠.json")
    assert r.returncode == 0, r.stdout + r.stderr
    before = (folder / SONO3).read_bytes()

    r = _run("kakunin.py", folder, "prepare")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"{SONO3} の数式のセルの値は、計算し直した写し（{COPY}）から渡しました" in r.stdout
    assert (folder / SONO3).read_bytes() == before
    assert (folder / COPY).is_file()

    plan = (folder / kt.PACKAGE / kk.PLAN_FILE).read_text(encoding="utf-8")
    section = plan.split(f"## {SONO3}", 1)[1].split("\n## ", 1)[0]
    lines = section.splitlines()
    index = _after(lines, "【１】省力化指数")
    payback = _after(lines, "【３】投資回収期間")
    # 省力化指数 ＝（38 − 14）÷ 38、投資回収期間 ＝ 投資総額 ÷（24時間 × 300日 × 1,330円 ＋ 増加した付加価値額）
    assert index == f"{(38 - 14) / 38:.2f}" == "0.63"
    assert payback.split(" | ")[0] == f"{INVEST / (24 * DAYS * WAGE + ADDED):.2f}" == "1.59"
    assert "省力化指数 | 0.63" in section  # 別紙1・別紙2 の省力化指数も
    assert "投資回収期間 | 1.59 | 年" in section  # 別紙3
    # 財務モデルに省力化の計算があれば、その表示の値と合う（組11 の「書いた後」）
    numbers = json.loads((folder / "記録" / "財務モデルの数字.json").read_text(encoding="utf-8"))["中身"]
    saving = numbers.get("省力化")
    if saving:
        assert index == f"{saving['表示']['省力化指数']:.2f}"
        assert payback.split(" | ")[0] == f"{saving['表示']['投資回収期間']:.2f}"
