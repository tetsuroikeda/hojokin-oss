"""申請書を確かめる道具（skills/kaku/scripts/kakunin.py）と、審査役の結果を保存する hook のテストに共通の部品
（TASKS M7。test_T9_4.py・test_check_min.py）。

- 道具は、社長の Mac と同じ /usr/bin/python3 で、Claude が Bash で動かすのと同じく引数で場所を渡して動かす。
- hook は、hooks.json のコマンド（run.sh → main.py）から、Claude Code と同じ形の入力で動かす。
- 様式は2つの形で用意する。
  - 試しの Word（make_docx）：表のセルの中に見出しと本文の段落がある、小さな Word。downloads/ がなくても流せる。
  - 公式の様式（downloads/ の その1・2）：M6 の書く道具（yoshiki.py）で書く。downloads/ がなければ飛ばす。
- 財務モデル.xlsx は、前提のシート（見出しの行に「状態」の欄）だけを持つ小さな Excel を、標準のライブラリで作る
  （テストの Python では同梱の openpyxl を読み込まない。tests/zaimu_tool.py の決まり）。
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

import hook_runner as hr

REPO_ROOT = hr.REPO_ROOT
SCRIPT = Path("skills") / "kaku" / "scripts" / "kakunin.py"
YOSHIKI = Path("skills") / "kaku" / "scripts" / "yoshiki.py"
FORM = REPO_ROOT / "downloads" / "shoryokuka_ippan" / "yoshiki_business_plan_part1_part2_ippan.docx"
SEIDO_SOURCE = REPO_ROOT / "tests" / "data" / "yoshiki" / "制度データ_様式と画面.json"
CASE = "2026_省力化（一般型）第9回"
STAGE = "1_申請"
APP_DIR = f"案件/{CASE}/{STAGE}/申請書"
WORD = f"{APP_DIR}/その1・2.docx"
SHEET = f"{APP_DIR}/入力シート.xlsx"
EVIDENCE = f"{APP_DIR}/根拠対照表.xlsx"
MODEL = "財務モデル.xlsx"
SEIDO_IN_FOLDER = "記録/制度データ/省力化_第8回.json"
OFFICIAL = f"案件/{CASE}/公式資料/事業計画書 その1・その2（参考様式）_第8回.docx"
PACKAGE = "記録/審査に渡すもの"
NOTE = f"{PACKAGE}/控え.json"
RESULTS = "記録/審査役の結果"
COMPLETION = "記録/完成の記録.json"
SHINSA = "hojokin:shinsa"

# 公式の様式（その1・2）の書き込む位置（tests/test_write_min.py と同じ）
PLAN_NAME = {"見出し": "（２）事業計画名（３０字程度）", "場所": "t1.r0.c0", "範囲": "セル"}
KEIEI = {"見出し": "１‐2経営課題", "場所": "t4.r2.c0.p0", "範囲": "見出しの後"}
HOSOKU = {"見出し": "６. 補足事項", "場所": "t4.r11.c0.p0", "範囲": "見出しの後"}
OFFICIAL_POSITIONS = {"（２）事業計画名": PLAN_NAME, "1-2 経営課題": KEIEI, "6. 補足事項": HOSOKU}

# 試しの Word の見出し（表の1列のセルの1つ目の段落）と、書き込む位置
TRIAL_HEADINGS = {"1-1 現状分析": "１‐１現状分析", "1-2 経営課題": "１‐2経営課題", "6. 補足事項": "６. 補足事項"}
TRIAL_POSITIONS = {name: {"見出し": h, "範囲": "見出しの後"} for name, h in TRIAL_HEADINGS.items()}

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
BLUE = "0070C0"


# ---------------------------------------------------------------- Word と Excel を作る


def _run(text: str, blue: bool = False) -> str:
    rpr = f'<w:rPr><w:color w:val="{BLUE}"/></w:rPr>' if blue else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _para(runs: Sequence) -> str:
    """runs は文字か、(文字, 青字か) の並び。1つの段落の中で、文字を分けて書ける（Word が文字を区切る形）。"""
    out = []
    for r in runs:
        text, blue = (r, False) if isinstance(r, str) else r
        out.append(_run(text, blue))
    return f"<w:p>{''.join(out)}</w:p>"


def make_docx(bodies: Dict[str, List], extra_paragraphs: Sequence = ()) -> bytes:
    """試しの Word。TRIAL_HEADINGS の項目ごとに表の行を1つ作り、そのセルに見出しと本文の段落を置く。

    bodies は 項目の名前 → 段落の並び（段落は文字か、runs の並び）。ない項目は、説明の青字だけの段落にする。
    extra_paragraphs は、表の後の段落（様式の項目の外）。
    """
    rows = []
    for name, heading in TRIAL_HEADINGS.items():
        paras = [_para([heading])]
        body = bodies.get(name)
        if body is None:
            paras.append(_para([("※ここに記載してください（説明の青字）", True)]))
        else:
            for p in body:
                paras.append(_para([p] if isinstance(p, str) else p))
        rows.append(f"<w:tr><w:tc>{''.join(paras)}</w:tc></w:tr>")
    after = "".join(_para([p] if isinstance(p, str) else p) for p in extra_paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document xmlns:w="{W_NS}"><w:body>{_para(["事業計画書（試しの様式）"])}'
        f"<w:tbl>{''.join(rows)}</w:tbl>{after}<w:sectPr/></w:body></w:document>"
    )
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="word/document.xml"/></Relationships>'),
        "word/document.xml": document,
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in parts.items():
            zf.writestr(name, text.encode("utf-8"))
    return out.getvalue()


def make_model_xlsx(rows: Sequence[Tuple[str, str]]) -> bytes:
    """財務モデル.xlsx の形の小さな Excel（「前提」シート。文字は共有の文字の部品に置く。openpyxl と同じ形）。

    rows は (前提の名前, 状態) の並び。状態が「仮」の行が、仮の印になる。
    """
    strings: List[str] = []

    def s(text: str) -> int:
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    def c(ref: str, text: str) -> str:
        return f'<c r="{ref}" t="s"><v>{s(text)}</v></c>' if text else ""

    sheet_rows = [f'<row r="1">{c("A1", "前提（数字の元になるもの）")}</row>',
                  f'<row r="2">{c("A2", "決まっていない前提は「状態」の欄に「仮」と書いてあります。")}</row>']
    head = ["番号", "名前", "値", "単位", "この数字は何か", "根拠", "出典", "状態"]
    sheet_rows.append('<row r="4">' + "".join(c(f"{chr(65 + i)}4", h) for i, h in enumerate(head)) + "</row>")
    for n, (name, state) in enumerate(rows, 5):
        cells = [c(f"A{n}", f"P-{n - 4:02d}"), c(f"B{n}", name), f'<c r="C{n}"><v>100</v></c>', c(f"F{n}", "聞き取り"),
                 c(f"G{n}", "社長の答え（架空）"), c(f"H{n}", state)]
        sheet_rows.append(f'<row r="{n}">{"".join(cells)}</row>')
    sheet = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{S_NS}">'
             f"<sheetData>{''.join(sheet_rows)}</sheetData></worksheet>")
    shared = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<sst xmlns="{S_NS}" count="{len(strings)}" '
              f'uniqueCount="{len(strings)}">' + "".join(f"<si><t>{escape(t)}</t></si>" for t in strings) + "</sst>")
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/></Types>'),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="xl/workbook.xml"/></Relationships>'),
        "xl/workbook.xml": (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{S_NS}" '
                            f'xmlns:r="{R_NS}"><sheets><sheet name="前提" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'sharedStrings" Target="sharedStrings.xml"/></Relationships>'),
        "xl/worksheets/sheet1.xml": sheet,
        "xl/sharedStrings.xml": shared,
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in parts.items():
            zf.writestr(name, text.encode("utf-8"))
    return out.getvalue()


def zip_parts(blob: bytes) -> Dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def all_xml_text(blob: bytes) -> str:
    """Word・Excel の zip の中の XML の文字を、すべてつないだもの（道具の読み方に頼らずに確かめるため）。"""
    import re

    out = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for name in zf.namelist():
            if name.endswith(".xml"):
                data = zf.read(name).decode("utf-8")
                out.append("".join(re.findall(r">([^<]*)<", data)))
    return "".join(out)


# ---------------------------------------------------------------- 審査役の報告


def report_json(number: str, findings: Sequence[dict] = (), fence: bool = True, **extra) -> str:
    """審査役が返す形の報告（json の囲み付き）。"""
    data = {"確かめの番号": number, "指摘": list(findings),
            "審査項目": [{"名前": "事業の実現可能性（試し）", "点数": 4, "理由": "工程と体制が具体的", "弱い所": "なし"}],
            "まとめ": "試しの報告"}
    data.update(extra)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    return f"```json\n{text}\n```" if fence else text


def finding(severity: str, content: str = "試しの指摘", where: str = "1-2 経営課題") -> dict:
    return {"重さ": severity, "観点": "試し", "場所": where, "内容": content, "直し方の案": "試しの直し方"}


# ---------------------------------------------------------------- 準備と動かし方


def out(r: subprocess.CompletedProcess) -> str:
    return r.stdout.decode("utf-8")


def ok(r: subprocess.CompletedProcess) -> str:
    assert r.returncode == 0, (r.returncode, out(r), r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    return out(r)


def code(r: subprocess.CompletedProcess, expected: int) -> str:
    assert r.returncode == expected, (r.returncode, out(r), r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    return out(r)


class Env:
    """プラグインの写しと、会社のフォルダ（目印・制度データ・案件の段階のフォルダ）。"""

    def __init__(self, tmp_path: Path, name: str = "山田 製作所") -> None:
        self.root = tmp_path
        self.plugin = tmp_path / "plugin"
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        for sub in ("lib", "skills", "hooks"):
            shutil.copytree(REPO_ROOT / sub, self.plugin / sub, ignore=ignore)
        (self.plugin / "docs").mkdir()
        shutil.copy2(REPO_ROOT / "docs" / "style-criteria.md", self.plugin / "docs" / "style-criteria.md")
        self.home = tmp_path / "home"
        self.tmp = tmp_path / "tmp"
        self.cwd = tmp_path / "どこか"
        self.data = tmp_path / "plugin-data"
        for d in (self.home, self.tmp, self.cwd, self.data):
            d.mkdir()
        self.path = hr.make_bin(tmp_path / "bin", "本物", tmp_path / "python-ran")
        self.folder = tmp_path / name
        f = self.folder
        (f / ".hojokin").mkdir(parents=True)
        (f / "記録" / "制度データ").mkdir(parents=True)
        (f / SEIDO_IN_FOLDER).write_bytes(SEIDO_SOURCE.read_bytes())
        for sub in ("申請書", "添付する書類"):
            (f / "案件" / CASE / STAGE / sub).mkdir(parents=True)

    # ---- 材料

    def seido(self) -> dict:
        return json.loads((self.folder / SEIDO_IN_FOLDER).read_text(encoding="utf-8"))

    def set_positions(self, positions: Dict[str, dict]) -> None:
        """制度データの様式の項目に、書き込む位置を置く（対応づけを済ませた形）。"""
        data = self.seido()
        for form in data["様式"]:
            for entry in form["項目"]:
                if entry["名前"] in positions:
                    entry["書き込む位置"] = positions[entry["名前"]]
        data["審査項目"] = [{"名前": "事業の実現可能性（試し）", "観点": {"値": ["工程が具体的か"], "状態": "確認済み"}}]
        (self.folder / SEIDO_IN_FOLDER).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def put(self, rel: str, data: bytes) -> Path:
        path = self.folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def trial_application(self, bodies: Dict[str, List], extra=(), sheet_values: Optional[Dict[str, str]] = None,
                          model: Optional[Sequence[Tuple[str, str]]] = None) -> None:
        """試しの Word の申請書と、入力シート（値を入れたもの）、財務モデルを置く。"""
        self.set_positions(TRIAL_POSITIONS)
        self.put(WORD, make_docx(bodies, extra))
        if sheet_values is not None:
            self.put(SHEET, self.sheet_blob(sheet_values))
        if model is not None:
            self.put(MODEL, make_model_xlsx(model))

    def sheet_blob(self, values: Dict[str, str]) -> bytes:
        """入力シート.xlsx（M6 の lib/input_sheet.py で、制度データの申請画面から作り、欄に値を書いたもの）。

        道具（yoshiki.py sheet）と同じ関数で作る。道具を何度も動かさずに済むよう、テストの中で作る。
        """
        from lib import input_sheet

        seido = self.seido()
        blob = input_sheet.build(seido)
        fields = {f.get("名前"): (s, f) for s, f in input_sheet.fields_of(seido)}
        for name, value in values.items():
            screen, field = fields[name]
            v = input_sheet.parse_number(value) if field.get("種類") == "数字" else value
            blob, _summary = input_sheet.write_value(blob, name, v, screen.get("名前"), input_sheet.limit_of(field))
        return blob

    def official_form(self, form: bytes) -> None:
        """公式の様式を、公式資料に置く（M6 の書く道具が写して使う）。"""
        f = self.folder
        (f / OFFICIAL).parent.mkdir(parents=True, exist_ok=True)
        (f / OFFICIAL).write_bytes(form)
        (f / OFFICIAL).chmod(0o444)
        listed = f / "記録" / "資料の本文" / CASE / "資料の一覧.json"
        listed.parent.mkdir(parents=True, exist_ok=True)
        listed.write_text(json.dumps({"案件": CASE, "置き場所": {"Wordその1・2": {"ファイル": OFFICIAL}}},
                                     ensure_ascii=False), encoding="utf-8")
        self.set_positions(OFFICIAL_POSITIONS)

    # ---- 道具

    def _script(self, script: Path, args: Sequence[str], stdin: bytes, folder: Optional[Path]) -> subprocess.CompletedProcess:
        argv = list(args)
        argv[1:1] = ["--folder", str(folder or self.folder)]
        return subprocess.run(
            [hr.real_python(), "-B", str(self.plugin / script), *argv],
            env={"PATH": "/usr/bin:/bin", "HOME": str(self.home), "TMPDIR": str(self.tmp)},
            cwd=self.cwd, input=stdin, capture_output=True, timeout=120,
        )

    def tool(self, *args: str, stdin: bytes = b"", folder: Optional[Path] = None) -> subprocess.CompletedProcess:
        return self._script(SCRIPT, args, stdin, folder)

    def yoshiki(self, *args: str, stdin: bytes = b"") -> subprocess.CompletedProcess:
        return self._script(YOSHIKI, args, stdin, None)

    def evidence(self, rows: Sequence[dict], replace: bool = False) -> str:
        args = ["konkyo"] + (["--replace"] if replace else [])
        return ok(self.tool(*args, stdin=json.dumps({"行": list(rows)}, ensure_ascii=False).encode("utf-8")))

    def count(self) -> Tuple[int, dict]:
        r = self.tool("count", "--json")
        assert r.returncode in (0, 3) and r.stderr == b"", (r.returncode, out(r), r.stderr.decode("utf-8"))
        return r.returncode, json.loads(out(r))

    # ---- hook

    def hook(self, event: str, payload: dict, match: str = "") -> subprocess.CompletedProcess:
        """hooks.json のコマンドで hook を動かす（match は matcher に当てる名前。道具の名前か subagent の名前）。"""
        commands = hr.hook_commands(event, match)
        assert len(commands) == 1, (event, match, commands)
        base = {"session_id": "test", "transcript_path": str(self.home / "t.jsonl"), "cwd": str(self.folder),
                "hook_event_name": event}
        r = hr.run(commands[0], {**base, **payload}, plugin=self.plugin, folder=self.folder, path=self.path,
                   home=self.home, data=self.data)
        assert r.returncode == 0, (event, r)
        assert r.stderr == b"", r.stderr.decode("utf-8")
        return r

    def subagent_stop(self, report: Optional[str], agent: str = SHINSA, mode: str = "default") -> subprocess.CompletedProcess:
        payload = {"agent_type": agent, "agent_id": "a-1", "permission_mode": mode, "stop_hook_active": False,
                   "agent_transcript_path": str(self.home / "agent.jsonl")}
        if report is not None:
            payload["last_assistant_message"] = report
        return self.hook("SubagentStop", payload, match=agent)

    def handback(self, report: str, agent: Optional[str] = SHINSA) -> subprocess.CompletedProcess:
        payload = {"tool_name": "SubagentHandback", "tool_input": {"message": report}, "permission_mode": "auto",
                   "tool_use_id": "t-1"}
        if agent is not None:
            payload.update({"agent_type": agent, "agent_id": "a-1"})
        return self.hook("PreToolUse", payload, match="SubagentHandback")

    def note(self) -> dict:
        return json.loads((self.folder / NOTE).read_text(encoding="utf-8"))

    def result(self, number: str) -> dict:
        return json.loads((self.folder / RESULTS / f"{number}.json").read_text(encoding="utf-8"))

    def completion(self) -> dict:
        return json.loads((self.folder / COMPLETION).read_text(encoding="utf-8"))

    def outside(self) -> dict:
        """会社のフォルダの外で、変わってはいけないもの。"""
        return hr.snapshot(self.plugin, self.home, self.tmp, self.cwd, self.data)


GOOD_BODIES = {
    "1-1 現状分析": ["冷凍惣菜の受注は、この2年で月400件から月650件に増えた。"],
    "1-2 経営課題": ["盛り付けと包装を4人の手作業で行っており、繁忙期は断る注文が月30件ある。"],
    "6. 補足事項": ["特になし。"],
}
GOOD_SHEET = {"事業計画名（３０文字程度）": "盛り付けの自動化で受注を断らない工場にする",
              "事業計画の概要": "盛り付け機を入れ、断っていた注文を受けられるようにする。",
              "常勤従業員数（基準年度）": "7"}
GOOD_EVIDENCE = [
    {"記述": "月400件から月650件", "種類": "数字", "書いた場所": "1-1 現状分析", "出典": "受注の台帳（架空） p.1"},
    {"記述": "4人", "種類": "数字", "書いた場所": "1-2 経営課題", "出典": "社長の答え（2026-11-04）"},
    {"記述": "月30件", "種類": "数字", "書いた場所": "1-2 経営課題", "出典": "社長の答え（2026-11-04）"},
    # B16：本文の数字（単位つき）・日付・固有名詞は、すべて根拠対照表にたどれること（T9-1）
    {"記述": "2年", "種類": "数字", "書いた場所": "1-1 現状分析", "出典": "受注の台帳（架空） p.1"},
]
