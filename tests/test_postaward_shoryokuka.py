"""省力化の採択後を、日付を進めながら通す（SPEC F12・F6、T12-1 の省力化の部分、DESIGN 4.5・4.6・9章。TASKS B31a）。

確かめること（日付は testdata/期限 の正解と同じ。採択発表日 2027-04-16、交付決定日 2027-06-25、決算は3月）：
- 交付申請：採択の後に今日を進め、採択発表日を渡すと、junbi の道具が 2_交付申請 のフォルダ・書類の一覧・期限
  （採択発表日から2か月の 2027-06-16。確定）を出す。shorui の不備チェックの物差しが、交付申請で集める書類の決まりを返し、
  有効期限の切れた見積書（2027-01-31）を期限切れとして見つける。交付決定日は、段階を変えずに残せる。
- 実績報告：事業の完了の日（2028-01-31）を渡すと 3_実績報告 へ切り替わり、期限は完了から30日（2028-03-01）と
  補助事業完了期限日（2028-11-16）の早いほう。効果報告の1年目の提出期間（2029-04-01〜06-30）も、この後の期限に出る。
- 効果報告1年目：実績報告の提出版を残し、2029年4月に進めると 4_効果報告 と 1年目 のフォルダができ、5年分の期限
  （2029〜2033年の各4月1日〜6月30日）が年ごとに出る。
- 効果報告1年目を出した後：1年目の提出版を残すと、開いたときの一覧に2年目の期限（2030-04-01〜06-30）が出る。
  同じ道具を流すと、段階を進めずに 2年目 のフォルダを作る。
- 決算の月が会社の記録になければ、効果報告の日付を出さず、そのわけ（決算の月を聞く）を示す。

材料は、リポにある省力化 第8回の制度データの正解（testdata/正解/。資料の文を写さない形）と、架空の会社の書類だけ。
道具は、Claude が Bash で動かすのと同じく、社長の Mac と同じ /usr/bin/python3 で、プラグインの写しから動かす。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import hook_runner as hr
import pytest
import version_tool as vt

CASE = "2026_省力化（一般型）第9回"
DATA = hr.REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json"
SWITCH = Path("skills") / "junbi" / "scripts" / "stage_switch.py"
KIGEN = Path("skills") / "junbi" / "scripts" / "kigen.py"
FUBI = Path("skills") / "shorui" / "scripts" / "fubi.py"
RECORD = Path("skills") / "kiroku" / "scripts" / "record.py"
VERSIONS = Path("skills") / "kiroku" / "scripts" / "versions.py"
CASE_DIR = f"案件/{CASE}"
ESTIMATE = "原本/見積・契約・請求/2026-10-20_見積書_つばさ台フードシステム.pdf"


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


class Postaward:
    """道具で用意した会社のフォルダに、省力化の案件（1_申請）と制度データの正解を置いたもの。"""

    def __init__(self, tmp_path: Path, closing: bool = True) -> None:
        self.company = vt.Company(tmp_path, name="やまぶき 惣菜")
        self.folder = self.company.folder
        for plugin in (self.company.env.plugin, self.company.plugin):
            for name in ("schema", "knowledge"):
                if not (plugin / name).exists():
                    shutil.copytree(hr.REPO_ROOT / name, plugin / name)
        listed = {"案件": CASE, "制度": {"名前": "中小企業省力化投資補助金", "略称": "省力化", "枠": "一般型",
                                        "種類": "補助金", "公募回": "第8回"},
                  "案件の回": "第9回", "資料": [{"id": "要領8", "名前": "公募要領", "公募回": "第8回"}]}
        _write_json(self.folder / "記録" / "資料の本文" / CASE / "資料の一覧.json", listed)
        _write_json(self.folder / "記録" / "制度データ" / "省力化_第8回.json",
                    json.loads(DATA.read_text(encoding="utf-8")))
        for sub in ("申請書", "添付する書類"):
            (self.folder / CASE_DIR / "1_申請" / sub).mkdir(parents=True, exist_ok=True)
        self.company.write(ESTIMATE, b"%PDF-1.4 dummy estimate")
        self.set_today("2026-11-20")
        if closing:
            self.tool(RECORD, "add-fact", "--name", "決算月", "--value", "3月", "--fixed", "--source", "質問",
                      "--question", "決算の月は何月ですか（効果報告の年度を決めるため）")

    def set_today(self, today: str) -> None:
        path = self.folder / ".hojokin" / "設定.json"
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        value["今日の日付"] = today
        _write_json(path, value)

    def run(self, script: Path, *args: str) -> subprocess.CompletedProcess:
        env = self.company.env
        cmd = [hr.real_python(), "-B", str(env.plugin / script)]
        cmd += [args[0], "--folder", str(self.folder), *args[1:]] if script in (FUBI, RECORD, VERSIONS) \
            else ["--folder", str(self.folder), *args]
        return subprocess.run(cmd, env={"PATH": env.path, "HOME": str(env.home), "TMPDIR": str(env.tmp)},
                              cwd=env.cwd, capture_output=True, timeout=120)

    def tool(self, script: Path, *args: str, code: int = 0) -> str:
        r = self.run(script, *args)
        out = r.stdout.decode("utf-8")
        assert r.returncode == code, (script, args, r.returncode, out, r.stderr.decode("utf-8"))
        return out

    def put(self, stage: str, name: str = "提出した書類.pdf") -> None:
        self.company.write(f"{CASE_DIR}/{stage}/申請書/{name}", f"%PDF-1.4 {stage}".encode("utf-8"))

    def submit(self, stage: str) -> None:
        self.put(stage)
        self.tool(VERSIONS, "submit", "--case", CASE, "--stage", stage, "--reason", "提出しました")

    def rules(self, stage: str) -> dict:
        return json.loads(self.tool(FUBI, "rules", "--case", CASE, "--stage", stage))


def section(text: str, title: str) -> list:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.lstrip("#").strip() == title)
    out = []
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        if line.strip().startswith("- "):
            out.append(line.strip())
    return out


def rule_names(rules: dict) -> list:
    return [r["名前"] for r in rules["この段階で集める書類の決まり"]]


@pytest.mark.slow
def test_postaward_shoryokuka(tmp_path: Path) -> None:
    p = Postaward(tmp_path)
    p.submit("1_申請")

    # ---- 交付申請（採択の通知の後） ----
    p.set_today("2027-04-20")
    out = p.tool(SWITCH, "--case", CASE, "--event", "採択発表日=2027-04-16")
    assert "採択後の次の段階「交付申請」へ切り替えました" in out, out
    assert (p.folder / CASE_DIR / "2_交付申請" / "添付する書類").is_dir()
    due = section(out, "交付申請の期限")
    assert due[0].startswith("- 2027年6月16日（水）（確定）（あと57日）"), due
    docs = "\n".join(section(out, "必須（5件）"))
    for name in ("見積依頼書", "見積書", "賃金引き上げ計画の表明書", "研修動画の修了証"):
        assert f"- {name}｜" in docs, (name, docs)
    assert "特に注意（交付決定の前）" in out and "事前着手" in out, out
    rules = p.rules("2_交付申請")
    assert {"見積書", "研修動画の修了証", "賃金引き上げ計画の表明書"} <= set(rule_names(rules)), rule_names(rules)
    assert "損益計算書（直近2期分）" not in rule_names(rules)  # 申請の段階の書類を混ぜない
    assert rules["交付決定の日"].startswith("まだ"), rules["交付決定の日"]
    p.company.write("記録/一時/書類の読み取り.json", json.dumps({"書類": [
        {"種類": "見積書", "原本": ESTIMATE, "発行日": "2026-10-20", "有効期限": "2027-01-31"}]}, ensure_ascii=False))
    found = json.loads(p.tool(FUBI, "check", "--case", CASE, "--stage", "2_交付申請",
                              "--input", "記録/一時/書類の読み取り.json"))
    assert [f["型"] for f in found["コードで見つけた不備の候補"]] == ["不備-01"], found
    assert "2027-01-31" in found["コードで見つけた不備の候補"][0]["内容"], found

    p.submit("2_交付申請")
    p.set_today("2027-06-28")
    out = p.tool(SWITCH, "--case", CASE, "--stage", "2_交付申請", "--event", "交付決定日=2027-06-25")
    assert "今の段階「交付申請」のままです" in out, out
    assert p.rules("2_交付申請")["交付決定の日"] == "2027-06-25"
    later = "\n".join(section(out, "この後の段階の期限（今の状態の組み立てから）"))
    assert "補助事業の実施（契約・納品・検収・支払い）：【要確認】2028年11月16日（木）（確定）" in later, later

    # ---- 実績報告（事業の完了の後） ----
    p.set_today("2028-02-05")
    out = p.tool(SWITCH, "--case", CASE, "--event", "補助事業の完了=2028-01-31")
    assert "採択後の次の段階「実績報告」へ切り替えました" in out, out
    due = section(out, "実績報告の期限")
    assert due[0].startswith("- 【要確認】2028年3月1日（水）（確定）（あと25日）"), due  # 30日と完了期限日の早いほう
    assert "補助事業の完了 2028年1月31日（月）（確定" in "\n".join(due), due
    later = "\n".join(section(out, "この後の段階の期限（今の状態の組み立てから）"))
    assert "事業実施効果報告：提出期間 2029年4月1日（日）〜2029年6月30日（土）（確定）" in later, later
    rules = p.rules("3_実績報告")
    assert {"保険への加入証明書", "取得財産等管理明細表"} <= set(rule_names(rules)), rule_names(rules)

    # ---- 効果報告1年目 ----
    p.submit("3_実績報告")
    p.set_today("2029-04-03")
    out = p.tool(SWITCH, "--case", CASE)
    assert "採択後の次の段階「事業実施効果報告（1年目）」へ切り替えました" in out, out
    assert (p.folder / CASE_DIR / "4_効果報告" / "1年目" / "添付する書類").is_dir()
    due = section(out, "事業実施効果報告（1年目）の期限")
    assert due[0] == "- 提出期間 2029年4月1日（日）〜2029年6月30日（土）（確定）（今が提出期間です（あと88日））", due
    years = [line for line in out.splitlines() if line.startswith("  - ") and "年目：" in line]
    assert [y.split("：")[0].strip("- ").strip() for y in years] == [f"{n}年目" for n in range(1, 6)], years
    for n, year in enumerate(range(2029, 2034), 1):
        assert f"{n}年目：提出期間 {year}年4月1日" in years[n - 1] and f"{year}年6月30日" in years[n - 1], years
    assert "（次に出す回）" in years[0]
    assert "賃金台帳" in rule_names(p.rules("4_効果報告/1年目"))

    # ---- 効果報告1年目を出した後：2年目の期限 ----
    p.submit("4_効果報告/1年目")
    p.set_today("2029-07-10")
    shown = p.tool(KIGEN, "--show")
    assert "事業実施効果報告（2年目）の期限" in shown, shown
    line = next(x for x in shown.splitlines() if "事業実施効果報告（2年目）の期限" in x)
    assert "提出期間 2030年4月1日（月）〜2030年6月30日（日）（確定）" in line, line
    assert "事業実施効果報告（1年目）" not in shown, shown
    out = p.tool(SWITCH, "--case", CASE)
    assert "今の段階「事業実施効果報告（2年目）」のままです" in out, out
    assert (p.folder / CASE_DIR / "4_効果報告" / "2年目" / "申請書").is_dir()
    years = [line for line in out.splitlines() if line.startswith("  - ") and "年目：" in line]
    assert years[0].endswith("（提出済み）") and years[1].endswith("（次に出す回）"), years


@pytest.mark.slow
def test_without_closing_month(tmp_path: Path) -> None:
    """決算の月が会社の記録になければ、効果報告の日付を出さず、決算の月を聞くよう示す。"""
    p = Postaward(tmp_path, closing=False)
    p.submit("1_申請")
    p.set_today("2027-04-20")
    p.tool(SWITCH, "--case", CASE, "--event", "採択発表日=2027-04-16")
    p.set_today("2028-02-05")
    out = p.tool(SWITCH, "--case", CASE, "--event", "補助事業の完了=2028-01-31")
    later = "\n".join(section(out, "この後の段階の期限（今の状態の組み立てから）"))
    assert "事業実施効果報告：日付はまだ出せません" in later and "決算の月が会社の記録にない" in later, later
